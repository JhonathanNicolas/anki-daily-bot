from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.config.models import CardField, CardStyle, DeckType


@dataclass
class CardData:
    # --- Language fields ---
    word: str = ""
    translation: str = ""

    # --- STEM fields ---
    question: str = ""
    answer: str = ""
    formula: str = ""        # LaTeX/MathJax string e.g. r"\[F(\omega) = \int f(t)e^{-j\omega t}dt\]"
    difficulty: str = ""     # easy | medium | hard

    # --- Code ---
    code_snippet: str = ""   # raw code block (language stored in SubdeckConfig)

    # --- Shared ---
    example: str = ""
    notes: str = ""
    choices: list[str] = field(default_factory=list)   # multiple choice distractors
    cloze_text: str = ""     # full cloze deletion text e.g. "FFT is {{c1::O(N log N)}}"

    # --- Media paths ---
    image_path: Optional[Path] = None
    audio_path: Optional[Path] = None
    example_audio_path: Optional[Path] = None

    @property
    def front_text(self) -> str:
        """Primary text shown on the card front."""
        return self.word or self.question

    @property
    def back_text(self) -> str:
        """Primary text shown on the card back."""
        return self.translation or self.answer

    def has_image(self) -> bool:
        return self.image_path is not None and self.image_path.exists()

    def has_audio(self) -> bool:
        return self.audio_path is not None and self.audio_path.exists()

    def has_example_audio(self) -> bool:
        return self.example_audio_path is not None and self.example_audio_path.exists()

    def has_formula(self) -> bool:
        return bool(self.formula)

    def has_cloze(self) -> bool:
        return bool(self.cloze_text)

    @classmethod
    def from_ai_dict(cls, data: dict, fields: list[CardField], deck_type: DeckType = DeckType.language) -> CardData:
        if deck_type == DeckType.stem:
            return cls(
                question=data.get(CardField.question, ""),
                answer=data.get(CardField.answer, ""),
                formula=data.get(CardField.formula, "") if CardField.formula in fields else "",
                example=data.get(CardField.example, "") if CardField.example in fields else "",
                notes=data.get(CardField.notes, "") if CardField.notes in fields else "",
                difficulty=data.get(CardField.difficulty, "medium"),
            )
        return cls(
            word=data.get(CardField.word, ""),
            translation=data.get(CardField.translation, ""),
            example=data.get(CardField.example, "") if CardField.example in fields else "",
            notes=data.get(CardField.notes, "") if CardField.notes in fields else "",
            difficulty=data.get(CardField.difficulty, ""),
        )

    @classmethod
    def from_cloze_dict(cls, data: dict) -> CardData:
        return cls(
            cloze_text=data.get("Text", ""),
            notes=data.get("Extra", ""),
            difficulty=data.get("Difficulty", "medium"),
        )

    @classmethod
    def from_code_dict(cls, data: dict) -> CardData:
        return cls(
            question=data.get("Question", ""),
            answer=data.get("Answer", ""),
            code_snippet=data.get("Code", ""),
            example=data.get("Example", ""),
            difficulty=data.get("Difficulty", "medium"),
        )

    @classmethod
    def from_mc_dict(cls, data: dict) -> CardData:
        return cls(
            question=data.get("Question", ""),
            answer=data.get("Answer", ""),
            formula=data.get("Formula", ""),
            difficulty=data.get("Difficulty", "medium"),
            choices=[
                data.get("Choice2", ""),
                data.get("Choice3", ""),
                data.get("Choice4", ""),
            ],
        )
