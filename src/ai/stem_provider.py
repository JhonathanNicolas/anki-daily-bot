from __future__ import annotations

import json
import os
import re

import anthropic

from src.card.models import CardData
from src.config.models import CardField, CardStyle, MediaType, SubdeckConfig

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
For code fields, write clean, compilable code snippets. No markdown fences — raw code only.
"""

# ---------------------------------------------------------------------------
# Code cards
# ---------------------------------------------------------------------------
_CODE_SCHEMA = {
    "Question": "string — concept name, function purpose, or 'What does this code do?'",
    "Answer": "string — clear explanation of the concept or what the code does",
    "Code": "string — a short, focused code snippet in the target language (raw code, no markdown fences)",
    "Example": "string — usage context or notes about the snippet (optional)",
    "Difficulty": "string — easy | medium | hard",
}

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


def _has_code(config: SubdeckConfig) -> bool:
    return MediaType.code in config.media


def _build_prompt(
    config: SubdeckConfig,
    style: CardStyle,
    already_known: list[str],
    source_code: str | None = None,
) -> str:
    use_code = _has_code(config)
    lang = config.code_language or "the relevant language"

    if use_code:
        schema = _CODE_SCHEMA
    else:
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

    if use_code and source_code:
        intro = (
            f"Based on the following {lang} source code, generate exactly {config.daily_limit} "
            f"flashcards. Each card should cover a specific function, concept, pattern, or idiom "
            f"found in or illustrated by this code.\n\n"
            f"--- SOURCE CODE ---\n{source_code[:4000]}\n--- END SOURCE CODE ---"
        )
    elif use_code:
        card_type_desc = "code-focused flashcards with a short code snippet per card"
        intro = (
            f"Generate exactly {config.daily_limit} {card_type_desc} for the topic: \"{config.topic}\" "
            f"in {lang}. Each card must include a focused, compilable code snippet that illustrates "
            f"the concept. Cover a mix of: syntax patterns, common idioms, functions, memory management, "
            f"data structures, and debugging scenarios relevant to {lang}."
        )
    else:
        card_type_desc = {
            CardStyle.standard: "question-and-answer flashcards",
            CardStyle.cloze: "cloze deletion flashcards (fill-in-the-blank)",
            CardStyle.multiple_choice: "multiple choice flashcards with one correct and three plausible wrong answers",
        }[style]
        intro = f"Generate exactly {config.daily_limit} {card_type_desc} for the topic: \"{config.topic}\"."

    mix_hint = (
        "Include a mix of: syntax patterns, idioms, common pitfalls, and best practices.\n"
        if use_code else
        "Include a mix of: definitions, formulas, properties, worked examples, and application questions.\n"
    )

    return (
        f"{intro}"
        f"{exclude}{instructions}\n\n"
        f"{mix_hint}"
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
        source_code: str | None = None,
    ) -> list[CardData]:
        prompt = _build_prompt(subdeck_config, card_style, already_known, source_code)

        message = self._client.messages.create(
            model=self._model,
            max_tokens=8192,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        data = json.loads(_extract_json(raw))

        if _has_code(subdeck_config):
            return [CardData.from_code_dict(item) for item in data]
        if card_style == CardStyle.cloze:
            return [CardData.from_cloze_dict(item) for item in data]
        if card_style == CardStyle.multiple_choice:
            return [CardData.from_mc_dict(item) for item in data]
        return [CardData.from_ai_dict(item, subdeck_config.fields, subdeck_config.deck_type) for item in data]
