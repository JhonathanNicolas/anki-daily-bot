from __future__ import annotations

import hashlib
import random
from pathlib import Path

from src.anki.connect_client import AnkiConnectClient
from src.card.models import CardData
from src.config.models import CardField, CardStyle, DeckConfig, DeckType, MediaType, SubdeckConfig

_CODE_CSS = """
.card { font-family: "Segoe UI", Arial, sans-serif; font-size: 16px; background: #1e1e2e; color: #cdd6f4; }
.question { font-size: 1.3rem; font-weight: 600; margin-bottom: 0.8rem; }
.answer { color: #a6e3a1; margin: 0.5rem 0 1rem; }
.code-block { background: #181825; border: 1px solid #313244; border-radius: 8px; padding: 14px;
              text-align: left; overflow-x: auto; margin: 10px 0; }
.code-block code { font-family: "Consolas", "Courier New", monospace; font-size: 13px;
                   white-space: pre; color: #cdd6f4; line-height: 1.5; }
.example { font-style: italic; color: #89b4fa; font-size: 0.9rem; margin-top: 0.5rem; }
.tag-easy { color: #a6e3a1; } .tag-medium { color: #f9e2af; } .tag-hard { color: #f38ba8; }
"""

_BASE_CSS_LIGHT = """
.card { font-family: "Segoe UI", Arial, sans-serif; font-size: 18px; text-align: center; }
.word { font-size: 2.5rem; font-weight: 700; }
.example { font-style: italic; color: #555; margin-top: 0.5rem; }
"""

_BASE_CSS_DARK = """
.card { font-family: "Segoe UI", Arial, sans-serif; font-size: 18px; background: #0f172a; color: #e2e8f0; }
"""

_BASE_FIELDS = [CardField.word, CardField.translation, CardField.example, CardField.notes]
_MEDIA_FIELD_NAMES = ["Audio", "Image"]
_STEM_FIELDS = [CardField.question, CardField.answer, CardField.formula, CardField.example, CardField.difficulty]


# ---------------------------------------------------------------------------
# Model field helpers
# ---------------------------------------------------------------------------

def _language_field_names(subdeck_config: SubdeckConfig) -> list[str]:
    names, seen = [], set()
    for f in _BASE_FIELDS:
        if f in subdeck_config.fields:
            names.append(f.value)
            seen.add(f.value)
    for m in _MEDIA_FIELD_NAMES:
        if m not in seen:
            names.append(m)
    return names


def _stem_field_names() -> list[str]:
    return ["Question", "Answer", "Formula", "Example", "Difficulty", "Image"]


def _mc_field_names() -> list[str]:
    return ["Question", "Answer", "Formula", "Choice2", "Choice3", "Choice4", "Difficulty"]


def _code_field_names() -> list[str]:
    return ["Question", "Answer", "Code", "Example", "Difficulty"]


# ---------------------------------------------------------------------------
# Card templates
# ---------------------------------------------------------------------------

def _language_templates() -> list[dict]:
    return [{"Name": "Card 1", "Front": "{{Word}}", "Back": (
        "{{FrontSide}}<hr id=answer>"
        "{{Translation}}"
        "{{#Example}}<br><i>{{Example}}</i>{{/Example}}"
        "{{#Audio}}{{Audio}}{{/Audio}}"
        "{{#Image}}<br>{{Image}}{{/Image}}"
    )}]


def _reverse_templates() -> list[dict]:
    return [
        {"Name": "Word → Translation", "Front": "{{Word}}", "Back": (
            "{{FrontSide}}<hr id=answer>{{Translation}}"
            "{{#Example}}<br><i>{{Example}}</i>{{/Example}}"
            "{{#Audio}}{{Audio}}{{/Audio}}"
            "{{#Image}}<br>{{Image}}{{/Image}}"
        )},
        {"Name": "Translation → Word", "Front": "{{Translation}}", "Back": (
            "{{FrontSide}}<hr id=answer>{{Word}}"
            "{{#Example}}<br><i>{{Example}}</i>{{/Example}}"
            "{{#Audio}}{{Audio}}{{/Audio}}"
        )},
    ]


def _stem_templates() -> list[dict]:
    return [{"Name": "Card 1", "Front": (
        "{{Question}}"
        "{{#Difficulty}}<br><small>{{Difficulty}}</small>{{/Difficulty}}"
    ), "Back": (
        "{{FrontSide}}<hr id=answer>"
        "{{Answer}}"
        "{{#Formula}}<br>\\[{{Formula}}\\]{{/Formula}}"
        "{{#Example}}<br><i>{{Example}}</i>{{/Example}}"
        "{{#Image}}<br>{{Image}}{{/Image}}"
    )}]


def _code_templates(lang: str = "") -> list[dict]:
    lang_label = f" ({lang})" if lang else ""
    code_block = (
        '{{#Code}}'
        '<div class="code-block"><code>{{Code}}</code></div>'
        '{{/Code}}'
    )
    return [
        {
            "Name": f"Concept → Code{lang_label}",
            "Front": '<div class="question">{{Question}}</div>',
            "Back": (
                "{{FrontSide}}<hr id=answer>"
                '<div class="answer">{{Answer}}</div>'
                + code_block +
                '{{#Example}}<div class="example">{{Example}}</div>{{/Example}}'
            ),
        },
        {
            "Name": f"Code → Concept{lang_label}",
            "Front": (
                f'<div class="question">What does this {lang or "code"} do?</div>'
                + code_block
            ),
            "Back": (
                "{{FrontSide}}<hr id=answer>"
                '<div class="question">{{Question}}</div>'
                '<div class="answer">{{Answer}}</div>'
                '{{#Example}}<div class="example">{{Example}}</div>{{/Example}}'
            ),
        },
    ]


def _mc_templates() -> list[dict]:
    return [{"Name": "Card 1", "Front": (
        "{{Question}}"
    ), "Back": (
        "{{FrontSide}}<hr id=answer>"
        "<b>✓ {{Answer}}</b><br>"
        "{{#Choice2}}✗ {{Choice2}}<br>{{/Choice2}}"
        "{{#Choice3}}✗ {{Choice3}}<br>{{/Choice3}}"
        "{{#Choice4}}✗ {{Choice4}}{{/Choice4}}"
    )}]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _anki_media_name(prefix: str, key: str, path: Path) -> str:
    stem = "".join(c if c.isalnum() else "_" for c in key).lower()
    word_hash = hashlib.md5(key.encode()).hexdigest()[:6]
    return f"daily_{prefix}_{stem}_{word_hash}{path.suffix}"


def _stable_id(name: str) -> int:
    return int(hashlib.md5(("anki-daily-bot-v1" + name).encode()).hexdigest(), 16) % (10**10)


def _difficulty_tags(difficulty: str) -> list[str]:
    tags = ["anki-daily-bot"]
    if difficulty in ("easy", "medium", "hard"):
        tags.append(f"difficulty::{difficulty}")
    return tags


# ---------------------------------------------------------------------------
# SyncManager
# ---------------------------------------------------------------------------

class SyncManager:
    def __init__(self, client: AnkiConnectClient) -> None:
        self._client = client

    def sync_subdeck(
        self,
        deck_config: DeckConfig,
        subdeck_key: str,
        subdeck_config: SubdeckConfig,
        cards: list[CardData],
    ) -> dict[str, int]:
        style = subdeck_config.card_style
        dtype = subdeck_config.deck_type

        if MediaType.code in subdeck_config.media:
            return self._sync_code(deck_config, subdeck_key, subdeck_config, cards)
        if style == CardStyle.cloze:
            return self._sync_cloze(deck_config, subdeck_key, cards)
        if style == CardStyle.multiple_choice:
            return self._sync_mc(deck_config, subdeck_key, subdeck_config, cards)
        if dtype == DeckType.stem:
            return self._sync_stem(deck_config, subdeck_key, subdeck_config, cards)
        if style == CardStyle.reverse:
            return self._sync_language(deck_config, subdeck_key, subdeck_config, cards, reverse=True)
        return self._sync_language(deck_config, subdeck_key, subdeck_config, cards, reverse=False)

    def trigger_sync(self) -> None:
        try:
            self._client.sync()
        except Exception as exc:
            print(f"  [sync] AnkiWeb sync failed (not logged in?): {exc}")

    # ── Language ─────────────────────────────────────────────────────────────

    def _sync_language(
        self,
        deck_config: DeckConfig,
        subdeck_key: str,
        subdeck_config: SubdeckConfig,
        cards: list[CardData],
        reverse: bool,
    ) -> dict[str, int]:
        anki_deck = deck_config.subdeck_anki_name(subdeck_key)
        model_name = f"{anki_deck} Model"
        field_names = _language_field_names(subdeck_config)
        templates = _reverse_templates() if reverse else _language_templates()

        self._client.ensure_deck(anki_deck)
        self._client.ensure_model(model_name, field_names, templates, _BASE_CSS_LIGHT)

        added = updated = skipped = 0
        for card in cards:
            fields = self._build_language_fields(card, subdeck_config, field_names)
            existing = self._find_existing(anki_deck, card.word)
            tags = _difficulty_tags(card.difficulty)
            if existing is None:
                self._client.add_note(anki_deck, model_name, fields, tags)
                added += 1
            elif self._fields_changed(existing[1], fields):
                self._client.update_note_fields(existing[0], fields)
                updated += 1
            else:
                skipped += 1

        return {"added": added, "updated": updated, "skipped": skipped}

    def _build_language_fields(
        self, card: CardData, subdeck_config: SubdeckConfig, field_names: list[str]
    ) -> dict[str, str]:
        values: dict[str, str] = {
            CardField.word.value: card.word,
            CardField.translation.value: card.translation,
            CardField.example.value: card.example,
            CardField.notes.value: card.notes,
            "Audio": "",
            "Image": "",
        }
        if MediaType.audio in subdeck_config.media and card.has_audio():
            audio_name = _anki_media_name("audio", card.word, card.audio_path)
            self._client.store_media_file(audio_name, card.audio_path)
            audio_tag = f"[sound:{audio_name}]"
            if card.has_example_audio():
                ex_name = _anki_media_name("ex", card.word, card.example_audio_path)
                self._client.store_media_file(ex_name, card.example_audio_path)
                audio_tag += f"[sound:{ex_name}]"
            values["Audio"] = audio_tag
        if MediaType.image in subdeck_config.media and card.has_image():
            img_name = _anki_media_name("img", card.word, card.image_path)
            self._client.store_media_file(img_name, card.image_path)
            values["Image"] = f'<img src="{img_name}">'
        return {name: values.get(name, "") for name in field_names}

    # ── STEM ─────────────────────────────────────────────────────────────────

    def _sync_stem(
        self,
        deck_config: DeckConfig,
        subdeck_key: str,
        subdeck_config: SubdeckConfig,
        cards: list[CardData],
    ) -> dict[str, int]:
        anki_deck = deck_config.subdeck_anki_name(subdeck_key)
        model_name = f"{anki_deck} STEM Model"
        field_names = _stem_field_names()

        self._client.ensure_deck(anki_deck)
        self._client.ensure_model(model_name, field_names, _stem_templates(), _BASE_CSS_DARK)

        added = updated = skipped = 0
        for card in cards:
            image_html = ""
            if MediaType.image in subdeck_config.media and card.has_image():
                img_name = _anki_media_name("img", card.question, card.image_path)
                self._client.store_media_file(img_name, card.image_path)
                image_html = f'<img src="{img_name}">'

            fields = {
                "Question": card.question,
                "Answer": card.answer,
                "Formula": card.formula,
                "Example": card.example,
                "Difficulty": card.difficulty,
                "Image": image_html,
            }
            existing = self._find_existing(anki_deck, card.question, field="Question")
            tags = _difficulty_tags(card.difficulty)
            if existing is None:
                self._client.add_note(anki_deck, model_name, fields, tags)
                added += 1
            elif self._fields_changed(existing[1], fields):
                self._client.update_note_fields(existing[0], fields)
                updated += 1
            else:
                skipped += 1

        return {"added": added, "updated": updated, "skipped": skipped}

    # ── Cloze ─────────────────────────────────────────────────────────────────

    def _sync_cloze(
        self,
        deck_config: DeckConfig,
        subdeck_key: str,
        cards: list[CardData],
    ) -> dict[str, int]:
        anki_deck = deck_config.subdeck_anki_name(subdeck_key)
        self._client.ensure_deck(anki_deck)
        # Anki's built-in Cloze model
        added = skipped = 0
        for card in cards:
            fields = {"Text": card.cloze_text, "Back Extra": card.notes}
            # Use first few words as dedup key
            key = card.cloze_text[:60]
            existing_ids = self._client.find_notes(
                f'deck:"{anki_deck.replace(chr(34), chr(92)+chr(34))}" note:Cloze Text:"{key[:30]}*"'
            )
            tags = _difficulty_tags(card.difficulty)
            if not existing_ids:
                self._client.add_note(anki_deck, "Cloze", fields, tags)
                added += 1
            else:
                skipped += 1

        return {"added": added, "updated": 0, "skipped": skipped}

    # ── Multiple choice ───────────────────────────────────────────────────────

    def _sync_mc(
        self,
        deck_config: DeckConfig,
        subdeck_key: str,
        subdeck_config: SubdeckConfig,
        cards: list[CardData],
    ) -> dict[str, int]:
        anki_deck = deck_config.subdeck_anki_name(subdeck_key)
        model_name = f"{anki_deck} MC Model"
        field_names = _mc_field_names()

        self._client.ensure_deck(anki_deck)
        self._client.ensure_model(model_name, field_names, _mc_templates(), _BASE_CSS_DARK)

        added = updated = skipped = 0
        for card in cards:
            # Shuffle choices so correct answer isn't always first
            all_choices = [card.answer] + card.choices
            random.shuffle(all_choices)
            fields = {
                "Question": card.question,
                "Answer": card.answer,
                "Formula": card.formula,
                "Choice2": all_choices[1] if len(all_choices) > 1 else "",
                "Choice3": all_choices[2] if len(all_choices) > 2 else "",
                "Choice4": all_choices[3] if len(all_choices) > 3 else "",
                "Difficulty": card.difficulty,
            }
            existing = self._find_existing(anki_deck, card.question, field="Question")
            tags = _difficulty_tags(card.difficulty)
            if existing is None:
                self._client.add_note(anki_deck, model_name, fields, tags)
                added += 1
            elif self._fields_changed(existing[1], fields):
                self._client.update_note_fields(existing[0], fields)
                updated += 1
            else:
                skipped += 1

        return {"added": added, "updated": updated, "skipped": skipped}

    # ── Code ─────────────────────────────────────────────────────────────────

    def _sync_code(
        self,
        deck_config: DeckConfig,
        subdeck_key: str,
        subdeck_config: SubdeckConfig,
        cards: list[CardData],
    ) -> dict[str, int]:
        anki_deck = deck_config.subdeck_anki_name(subdeck_key)
        lang = subdeck_config.code_language or ""
        model_name = f"{anki_deck} Code Model"
        field_names = _code_field_names()

        self._client.ensure_deck(anki_deck)
        self._client.ensure_model(model_name, field_names, _code_templates(lang), _CODE_CSS)

        added = updated = skipped = 0
        for card in cards:
            fields = {
                "Question": card.question,
                "Answer": card.answer,
                "Code": card.code_snippet,
                "Example": card.example,
                "Difficulty": card.difficulty,
            }
            existing = self._find_existing(anki_deck, card.question, field="Question")
            tags = _difficulty_tags(card.difficulty)
            if existing is None:
                self._client.add_note(anki_deck, model_name, fields, tags)
                added += 1
            elif self._fields_changed(existing[1], fields):
                self._client.update_note_fields(existing[0], fields)
                updated += 1
            else:
                skipped += 1

        return {"added": added, "updated": updated, "skipped": skipped}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_existing(
        self, deck_name: str, key: str, field: str = "Word"
    ) -> tuple[int, dict[str, str]] | None:
        import re
        escaped_deck = deck_name.replace('"', '\\"')
        # Strip backslashes and control chars — AI-generated content (e.g. C code)
        # can contain \0, \n, \t which are invalid in Anki's search syntax.
        safe_key = re.sub(r"[\x00-\x1f\x7f\\]", " ", key).strip()[:80]
        escaped_key = safe_key.replace('"', '\\"')
        query = f'deck:"{escaped_deck}" {field}:"{escaped_key}"'
        note_ids = self._client.find_notes(query)
        if not note_ids:
            return None
        info = self._client.notes_info(note_ids[:1])[0]
        fields = {name: data["value"] for name, data in info["fields"].items()}
        return info["noteId"], fields

    def _fields_changed(self, current: dict[str, str], new: dict[str, str]) -> bool:
        return any(current.get(k) != v for k, v in new.items())
