from __future__ import annotations

import json
import os
import re

import anthropic

from src.card.models import CardData
from src.config.models import CardField, CardStyle, SubdeckConfig

def _extract_json(text: str) -> str:
    """Extract a JSON array from a response that may be wrapped in code fences."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        return m.group(0)
    return text


_SYSTEM = """\
You are an expert educator creating Anki flashcards for STEM subjects.
Always respond with a valid JSON array only. No extra text outside the JSON.
Use proper LaTeX notation inside formula fields (MathJax compatible).
Inline math: \\(...\\)  |  Display math: \\[...\\]
"""

# ---------------------------------------------------------------------------
# Standard Q&A cards
# ---------------------------------------------------------------------------
_QA_SCHEMA = {
    "Question": "string — the question, concept name, or problem to solve",
    "Answer": "string — the concise correct answer or definition",
    "Formula": "string — LaTeX formula if applicable, else empty string",
    "Example": "string — a worked example or use-case (optional)",
    "Difficulty": "string — one of: easy, medium, hard",
}

# ---------------------------------------------------------------------------
# Cloze deletion cards
# ---------------------------------------------------------------------------
_CLOZE_SCHEMA = {
    "Text": "string — sentence with {{c1::hidden part}} style deletions. Use {{c1::...}}, {{c2::...}} etc.",
    "Extra": "string — additional context shown on the back (optional)",
    "Difficulty": "string — easy | medium | hard",
}

# ---------------------------------------------------------------------------
# Multiple choice cards
# ---------------------------------------------------------------------------
_MC_SCHEMA = {
    "Question": "string — the question",
    "Answer": "string — the correct answer",
    "Formula": "string — LaTeX formula if relevant, else empty",
    "Choice2": "string — plausible wrong answer",
    "Choice3": "string — plausible wrong answer",
    "Choice4": "string — plausible wrong answer",
    "Difficulty": "string — easy | medium | hard",
}


def _build_prompt(
    config: SubdeckConfig,
    style: CardStyle,
    already_known: list[str],
) -> str:
    schema = {
        CardStyle.standard: _QA_SCHEMA,
        CardStyle.cloze: _CLOZE_SCHEMA,
        CardStyle.multiple_choice: _MC_SCHEMA,
    }[style]

    exclude = ""
    if already_known:
        sample = ", ".join(f'"{w}"' for w in already_known[:20])
        exclude = f"\nDo NOT repeat these already-covered concepts: {sample}."

    instructions = f"\nExtra instructions: {config.extra_instructions}" if config.extra_instructions else ""

    card_type_desc = {
        CardStyle.standard: "question-and-answer flashcards",
        CardStyle.cloze: "cloze deletion flashcards (fill-in-the-blank)",
        CardStyle.multiple_choice: "multiple choice flashcards with one correct and three plausible wrong answers",
    }[style]

    return (
        f"Generate exactly {config.daily_limit} {card_type_desc} for the topic: \"{config.topic}\"."
        f"{exclude}{instructions}\n\n"
        f"Include a mix of: definitions, formulas, properties, worked examples, and application questions.\n"
        f"Each card must be a JSON object:\n{json.dumps(schema, indent=2)}\n\n"
        f"Respond ONLY with a JSON array of {config.daily_limit} objects."
    )


class StemProvider:
    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-6") -> None:
        self._client = anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self._model = model

    def generate_cards(
        self,
        subdeck_config: SubdeckConfig,
        card_style: CardStyle,
        already_known: list[str],
    ) -> list[CardData]:
        prompt = _build_prompt(subdeck_config, card_style, already_known)

        message = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        data = json.loads(_extract_json(raw))

        if card_style == CardStyle.cloze:
            return [CardData.from_cloze_dict(item) for item in data]
        if card_style == CardStyle.multiple_choice:
            return [CardData.from_mc_dict(item) for item in data]
        return [CardData.from_ai_dict(item, subdeck_config.fields, subdeck_config.deck_type) for item in data]
