"""
Process files from data/ directory into Anki cards without the Telegram bot.

Filename convention:
  DECK-Subdeck Name.txt  →  DECK::Subdeck Name  (Anki deck path)
  FPGA-Interview Notes.txt  →  FPGA::Interview Notes

File types (auto-detected):
  Notes:     one concept per line — Claude generates Q&A freely from the concept
  Questions: lines starting with "Q." — Claude generates the answer

Processed lines get an  #added  marker appended so re-runs skip them.

Usage:
  make data
  # or directly:
  PYTHONPATH=".venv/lib/python3.12/site-packages:$PYTHONPATH" .venv/bin/python -m src.data_processor
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import anthropic

from src.anki.connect_client import AnkiConnectClient

# ── Constants ─────────────────────────────────────────────────────────────────

_PROCESSED_MARKER = "  #added"
_BATCH_SIZE = 10          # lines per Claude API call
_DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))

_CSS = """
.card {
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 17px;
  background: #1e1e2e;
  color: #cdd6f4;
  padding: 1.2rem;
  text-align: left;
}
.question { font-size: 1.2rem; font-weight: 600; color: #89dceb; margin-bottom: 0.8rem; }
.answer   { color: #a6e3a1; line-height: 1.7; }
.example  { font-style: italic; color: #89b4fa; font-size: 0.9rem; margin-top: 0.6rem; }
"""

_FIELDS = ["Question", "Answer", "Example", "Difficulty", "Source"]

_TEMPLATES = [
    {
        "Name": "Card 1",
        "Front": '<div class="question">{{Question}}</div>',
        "Back": (
            "{{FrontSide}}<hr id=answer>"
            '<div class="answer">{{Answer}}</div>'
            '{{#Example}}<div class="example">{{Example}}</div>{{/Example}}'
        ),
    }
]

_NOTES_SYSTEM = (
    "You are creating Anki STEM flashcards from technical notes. "
    "For each numbered note, generate exactly one flashcard. "
    "Do NOT copy the note verbatim — derive a meaningful Question that tests understanding "
    "and a clear, concise Answer that explains the concept. "
    "Respond ONLY with a valid JSON array, no extra text."
)

_QUESTIONS_SYSTEM = (
    "You are creating Anki STEM flashcards from interview questions. "
    "For each numbered question, provide a concise, technically accurate Answer. "
    "Keep the Question text clean (remove 'Q.N:' prefix). "
    "Respond ONLY with a valid JSON array, no extra text."
)

_CARD_SCHEMA = (
    '{"Question": "string", "Answer": "string", '
    '"Example": "optional short example or empty string", '
    '"Difficulty": "easy | medium | hard"}'
)

# ── Filename / file parsing ────────────────────────────────────────────────────

def parse_filename(filepath: Path) -> tuple[str, str]:
    """Return (deck, subdeck) from filename. 'FPGA-Interview Notes' → ('FPGA', 'Interview Notes')."""
    stem = filepath.stem
    if "-" in stem:
        deck, subdeck = stem.split("-", 1)
        return deck.strip(), subdeck.strip()
    return stem.strip(), stem.strip()


def full_deck_name(deck: str, subdeck: str) -> str:
    return f"{deck}::{subdeck}" if deck != subdeck else deck


def detect_file_type(lines: list[str]) -> str:
    """Return 'questions' if the majority of lines look like Q. N: ..., else 'notes'."""
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return "notes"
    q_matches = sum(1 for l in non_empty if re.match(r"Q\.\s*\d*\s*:?", l.strip(), re.IGNORECASE))
    return "questions" if q_matches >= len(non_empty) / 2 else "notes"


def is_processed(line: str) -> bool:
    return _PROCESSED_MARKER in line


def clean_line(line: str) -> str:
    return line.replace(_PROCESSED_MARKER, "").strip()


# ── AI generation ─────────────────────────────────────────────────────────────

def _extract_json_array(text: str) -> list[dict]:
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    raw = m.group(0) if m else text
    return json.loads(raw)


def generate_from_notes(lines: list[str], deck: str) -> list[dict]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    numbered = "\n".join(f"{i + 1}. {l}" for i, l in enumerate(lines))
    prompt = (
        f"Create one Anki flashcard per note below for the '{deck}' deck.\n\n"
        f"Notes:\n{numbered}\n\n"
        f"Return a JSON array of exactly {len(lines)} objects:\n{_CARD_SCHEMA}\n\n"
        "Respond ONLY with the JSON array."
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=_NOTES_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_json_array(msg.content[0].text)


def generate_from_questions(lines: list[str], deck: str) -> list[dict]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    # Strip Q.N: prefix so Claude sees just the question text
    cleaned = [re.sub(r"^Q\.\s*\d*\s*:?\s*", "", l.strip(), flags=re.IGNORECASE) for l in lines]
    numbered = "\n".join(f"{i + 1}. {l}" for i, l in enumerate(cleaned))
    prompt = (
        f"Answer each interview question for the '{deck}' deck.\n\n"
        f"Questions:\n{numbered}\n\n"
        f"Return a JSON array of exactly {len(lines)} objects:\n{_CARD_SCHEMA}\n\n"
        "The Question field must be the original question (cleaned, no Q.N: prefix). "
        "The Answer must be technically accurate and concise. "
        "Respond ONLY with the JSON array."
    )
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=_QUESTIONS_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_json_array(msg.content[0].text)


# ── Anki helpers ──────────────────────────────────────────────────────────────

def _safe_question(question: str) -> str:
    """Strip control chars and truncate for use in AnkiConnect search queries."""
    return re.sub(r'[\x00-\x1f\x7f\\"]', " ", question).strip()[:80]


def note_exists(client: AnkiConnectClient, anki_deck: str, question: str) -> bool:
    escaped_deck = anki_deck.replace('"', '\\"')
    escaped_q = _safe_question(question).replace('"', '\\"')
    ids = client.find_notes(f'deck:"{escaped_deck}" Question:"{escaped_q}"')
    return bool(ids)


# ── File processing ───────────────────────────────────────────────────────────

def process_file(filepath: Path, client: AnkiConnectClient) -> None:
    deck, subdeck = parse_filename(filepath)
    anki_deck = full_deck_name(deck, subdeck)
    print(f"\n→ {filepath.name}  →  {anki_deck}")

    with filepath.open("r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    # Collect unprocessed lines with their original indices
    pending: list[tuple[int, str]] = []
    for i, line in enumerate(raw_lines):
        text = clean_line(line)
        if text and not is_processed(line):
            pending.append((i, text))

    if not pending:
        print("  All lines already processed.")
        return

    file_type = detect_file_type([t for _, t in pending])
    print(f"  Type: {file_type} | Pending: {len(pending)} lines")

    # Ensure deck + note type exist in Anki
    client.ensure_deck(anki_deck)
    model_name = f"{anki_deck} Data Model"
    client.ensure_model(model_name, _FIELDS, _TEMPLATES, _CSS)

    added = skipped = errors = 0

    def flush(indices: list[int], texts: list[str]) -> None:
        nonlocal added, skipped, errors
        print(f"  Generating {len(texts)} card(s)...")
        try:
            if file_type == "questions":
                cards = generate_from_questions(texts, anki_deck)
            else:
                cards = generate_from_notes(texts, anki_deck)
        except Exception as exc:
            print(f"  [error] AI generation failed: {exc}")
            errors += len(texts)
            return

        for idx, card in zip(indices, cards):
            question = card.get("Question", "").strip()
            answer = card.get("Answer", "").strip()
            if not question or not answer:
                errors += 1
                continue

            if note_exists(client, anki_deck, question):
                skipped += 1
            else:
                difficulty = card.get("Difficulty", "medium")
                tags = ["data-import"]
                if difficulty in ("easy", "medium", "hard"):
                    tags.append(f"difficulty::{difficulty}")
                try:
                    client.add_note(anki_deck, model_name, {
                        "Question": question,
                        "Answer": answer,
                        "Example": card.get("Example", ""),
                        "Difficulty": difficulty,
                        "Source": filepath.name,
                    }, tags)
                    added += 1
                except Exception as exc:
                    print(f"  [warn] add_note failed: {exc}")
                    errors += 1
                    continue

            # Mark line as processed regardless of add/skip
            raw_lines[idx] = raw_lines[idx].rstrip("\n") + _PROCESSED_MARKER + "\n"

        # Write back after each batch so progress is saved even on crash
        with filepath.open("w", encoding="utf-8") as f:
            f.writelines(raw_lines)

    # Batch processing
    batch_idx: list[int] = []
    batch_txt: list[str] = []
    for line_idx, text in pending:
        batch_idx.append(line_idx)
        batch_txt.append(text)
        if len(batch_txt) >= _BATCH_SIZE:
            flush(batch_idx, batch_txt)
            batch_idx, batch_txt = [], []
    if batch_txt:
        flush(batch_idx, batch_txt)

    print(f"  Result → added: {added} | skipped (duplicate): {skipped} | errors: {errors}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if not _DATA_DIR.exists():
        print(f"[error] '{_DATA_DIR}' directory not found.")
        sys.exit(1)

    files = sorted(_DATA_DIR.glob("*.txt")) + sorted(_DATA_DIR.glob("*.md"))
    if not files:
        print(f"[info] No .txt or .md files found in {_DATA_DIR}/")
        sys.exit(0)

    anki_url = os.environ.get("ANKI_CONNECT_URL", "http://localhost:8765")
    client = AnkiConnectClient(url=anki_url)

    if not client.is_available():
        print("[error] AnkiConnect not reachable. Make sure Anki is running.")
        sys.exit(1)

    print(f"[info] AnkiConnect OK | Processing {len(files)} file(s) from '{_DATA_DIR}/'")

    for filepath in files:
        try:
            process_file(filepath, client)
        except Exception as exc:
            import traceback
            print(f"[error] Failed to process {filepath.name}: {exc}")
            traceback.print_exc()

    print("\n[info] Triggering AnkiWeb sync...")
    try:
        client.sync()
        print("[done] Sync triggered.")
    except Exception as exc:
        print(f"[warn] Sync failed: {exc}")


if __name__ == "__main__":
    main()
