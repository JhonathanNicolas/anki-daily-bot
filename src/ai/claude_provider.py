from __future__ import annotations

import json
import os
import re

import anthropic

from src.ai.base import AIProvider
from src.card.models import CardData
from src.config.models import CardField, SubdeckConfig

def _extract_json(text: str) -> str:
    """Extract a JSON array from a response that may be wrapped in code fences."""
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # As a last resort, find the outermost [...] array
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        return m.group(0)
    return text


_SYSTEM_PROMPT = """\
You are a language learning assistant. Your task is to generate Anki flashcard data.
Always respond with a valid JSON array. Each object in the array is one card.
Only include the fields requested. Do not add explanations outside the JSON.
"""

_CARD_SCHEMA = {
    CardField.word: "string — the word/phrase in the target language",
    CardField.translation: "string — English translation",
    CardField.example: "string — a short example sentence in the target language",
    CardField.notes: "string — optional grammar note or usage tip",
}


def _build_user_prompt(
    config: SubdeckConfig,
    language: str,
    already_known: list[str],
) -> str:
    fields_needed = {f: _CARD_SCHEMA[f] for f in config.fields if f in _CARD_SCHEMA}
    schema_str = json.dumps(fields_needed, indent=2)

    exclude_clause = ""
    if already_known:
        sample = ", ".join(f'"{w}"' for w in already_known[:20])
        exclude_clause = f"\nDo NOT include any of these already-known words: {sample}."

    instructions = ""
    if config.extra_instructions:
        instructions = f"\nExtra instructions: {config.extra_instructions}"

    return (
        f"Generate exactly {config.daily_limit} flashcards for the topic: "
        f'"{config.topic}" in {language}.'
        f"{exclude_clause}"
        f"{instructions}\n\n"
        f"Each card must be a JSON object with these fields:\n{schema_str}\n\n"
        f"Respond ONLY with a JSON array of {config.daily_limit} objects."
    )


class ClaudeProvider(AIProvider):
    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-6") -> None:
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self._model = model

    def generate_cards(
        self,
        subdeck_config: SubdeckConfig,
        language: str,
        already_known: list[str],
    ) -> list[CardData]:
        prompt = _build_user_prompt(subdeck_config, language, already_known)

        message = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        data = json.loads(_extract_json(raw))
        return [CardData.from_ai_dict(item, subdeck_config.fields, subdeck_config.deck_type) for item in data]
