from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import anthropic

_SYSTEM = """\
You are an assistant that parses user messages about an Anki flashcard bot into structured JSON.

Given a user message, return ONLY a JSON object with these fields:
- "intent": one of "generate_cards", "create_deck", "delete", "list_decks", "status", "help", "unknown"
- "deck": the full deck path mentioned (e.g. "German" or "German::Numbers"), or null
- "subdeck": a short snake_case key for the subdeck (e.g. "weather", "numbers", "food"), or null
- "topic": the word or topic for card generation, or null
- "quantity": number of cards (integer), default 10
- "media": list of media types — "audio", "image" (default: ["audio"])
- "single_word": true if the user wants a card FOR a specific word (its definition/meaning); false if the word is a theme to generate multiple cards around

Rules:
- "add word X" / "add the word X" → quantity = 1, single_word = true, topic = X
- "add N words about X" / "add cards about X" / "add N cards about X" → single_word = false, topic = X, quantity = N (default 10)
- "add X to deck Y" where X is one specific word → quantity = 1, single_word = true
- "create deck X" → intent = "create_deck"
- "delete deck X" / "delete deck with ID abc" → intent = "delete", deck = X or the ID
- For language decks include "audio" by default
- Return ONLY valid JSON, no extra text
"""

_SYSTEM_BATCH = """\
You are an assistant that parses multi-request user messages for an Anki flashcard bot.

The user has sent multiple instructions in one message. Split them into individual requests and
return ONLY a JSON array, where each element has these fields:
- "intent": one of "generate_cards", "create_deck", "delete", "list_decks", "status", "help", "unknown"
- "deck": deck path (e.g. "German" or "German::Numbers"), or null
- "subdeck": short snake_case subdeck key, or null
- "topic": the word or topic for card generation, or null
- "quantity": integer number of cards (default 10)
- "media": list of media types — "audio", "image" (default: ["audio"])
- "single_word": true if the user wants a card FOR a specific word (its definition); false if the word is a theme

Rules:
- Each distinct instruction becomes one object in the array
- "add word X" / "add the word X" → quantity = 1, single_word = true, topic = X
- "add N words about X" / "add cards about X" → single_word = false, quantity = N (default 10)
- If no quantity and topic is one specific word → quantity = 1, single_word = true
- If no quantity and topic is a general subject → quantity = 10, single_word = false
- "create deck X" → intent = "create_deck"
- Return ONLY a valid JSON array, no extra text
"""


@dataclass
class ParsedIntent:
    intent: str
    deck: str | None = None
    subdeck: str | None = None
    topic: str | None = None
    quantity: int = 10
    media: list[str] = field(default_factory=lambda: ["audio"])
    single_word: bool = False  # True = card FOR this word; False = cards themed around it


def parse_message(text: str) -> ParsedIntent:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=_SYSTEM,
        messages=[{"role": "user", "content": text}],
    )
    raw = message.content[0].text.strip()
    data = json.loads(_extract_json_object(raw))
    return ParsedIntent(
        intent=data.get("intent", "unknown"),
        deck=_clean_deck_name(data.get("deck")),
        subdeck=data.get("subdeck"),
        topic=data.get("topic"),
        quantity=int(data.get("quantity") or 10),
        media=data.get("media", ["audio"]),
        single_word=bool(data.get("single_word", False)),
    )


def parse_multi_message(text: str) -> list[ParsedIntent] | None:
    """Parse a message that may contain multiple instructions.

    Returns a list of 2+ intents if the message is clearly multi-request,
    or None to signal the caller should fall back to single-intent parsing.
    """
    if not _looks_like_batch(text):
        return None

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=_SYSTEM_BATCH,
        messages=[{"role": "user", "content": text}],
    )
    raw = message.content[0].text.strip()
    data = json.loads(_extract_json_array(raw))

    if not isinstance(data, list) or len(data) < 2:
        return None

    intents = []
    for item in data:
        intents.append(ParsedIntent(
            intent=item.get("intent", "unknown"),
            deck=_clean_deck_name(item.get("deck")),
            subdeck=item.get("subdeck"),
            topic=item.get("topic"),
            quantity=int(item.get("quantity") or 10),
            media=item.get("media", ["audio"]),
            single_word=bool(item.get("single_word", False)),
        ))
    return intents


def _looks_like_batch(text: str) -> bool:
    """Quick heuristic check before calling the LLM — avoids wasting tokens on single requests."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # Multiple non-empty lines
    if len(lines) >= 2:
        return True
    # Bullet/arrow separators in a single line
    if re.search(r"(->|•|\*|-\s)", text):
        return True
    # Multiple action verbs in one sentence
    if len(re.findall(r"\b(add|create|delete|generate|make|put)\b", text, re.I)) >= 2:
        return True
    return False


def _clean_deck_name(name: str | None) -> str | None:
    if not name:
        return name
    noise = {"deck", "the deck", "my deck", "subdeck"}
    cleaned = name.strip()
    for word in noise:
        if cleaned.lower().endswith(f" {word}"):
            cleaned = cleaned[: -(len(word) + 1)].strip()
    return cleaned or None


def _extract_json_object(text: str) -> str:
    """Extract a single JSON object {...} — used by parse_message."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def _extract_json_array(text: str) -> str:
    """Extract a JSON array [...] — used by parse_multi_message."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    return m.group(0) if m else text
