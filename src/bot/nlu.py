from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import anthropic

_SYSTEM = """\
You are an assistant that parses user messages about an Anki flashcard bot into structured JSON.

Given a user message, return ONLY a JSON object with these fields:
- "intent": one of "generate_cards", "create_deck", "delete", "list_decks", "status", "help", "unknown"
- "deck": the full deck path mentioned. For top-level decks use just the name (e.g. "German"). For subdecks use Anki notation (e.g. "German::Numbers"). For delete intent, always preserve the full path exactly as the user said.
- "subdeck": a short snake_case key for the subdeck (e.g. "weather", "numbers", "food"), or null. Only used for generate_cards intent.
- "topic": a descriptive topic string for card generation (e.g. "weather vocabulary and expressions"), or null
- "quantity": number of cards requested (integer), default 10
- "media": list of media types to include — "audio" for pronunciation, "image" for pictures (default: ["audio"])

Rules:
- If the user says "my german deck" → deck = "German"
- Infer subdeck key from topic (e.g. "weather" → subdeck = "weather")
- If quantity is not mentioned, default to 10
- For language decks, always include "audio" by default
- "add the word X to deck Y" → intent = "generate_cards", topic = "the word X", quantity = 1
- "English book" or "English books deck" → deck = "English", subdeck = "books"
- "create deck X", "new deck X", "create subdeck X in Y" → intent = "create_deck" (user wants to set up a deck, not generate cards yet)
- "add X to deck Y" where X is a specific word or phrase → intent = "generate_cards", topic = X, quantity = 1
- If the user references a subdeck by an informal name (e.g. "book", "books", "the book deck") infer the subdeck key from that name
- "delete the deck with ID abc123" or "delete deck abc123" or "the ID is abc123" → intent = "delete", deck = "abc123"
- Return ONLY valid JSON, no extra text
"""


@dataclass
class ParsedIntent:
    intent: str
    deck: str | None = None
    subdeck: str | None = None
    topic: str | None = None
    quantity: int = 10
    media: list[str] = field(default_factory=lambda: ["audio"])


def parse_message(text: str) -> ParsedIntent:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=_SYSTEM,
        messages=[{"role": "user", "content": text}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    return ParsedIntent(
        intent=data.get("intent", "unknown"),
        deck=_clean_deck_name(data.get("deck")),
        subdeck=data.get("subdeck"),
        topic=data.get("topic"),
        quantity=int(data.get("quantity") or 10),
        media=data.get("media", ["audio"]),
    )


def _clean_deck_name(name: str | None) -> str | None:
    if not name:
        return name
    # Strip trailing noise words the NLU sometimes appends
    noise = {"deck", "the deck", "my deck", "subdeck"}
    cleaned = name.strip()
    for word in noise:
        if cleaned.lower().endswith(f" {word}"):
            cleaned = cleaned[: -(len(word) + 1)].strip()
    return cleaned or None
