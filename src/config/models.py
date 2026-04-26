from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class MediaType(str, Enum):
    text = "text"
    image = "image"
    audio = "audio"
    latex = "latex"
    code = "code"


class DeckType(str, Enum):
    language = "language"
    stem = "stem"


class CardStyle(str, Enum):
    standard = "standard"
    reverse = "reverse"        # language: also add translation→word card
    cloze = "cloze"            # fill-in-the-blank
    multiple_choice = "multiple_choice"  # question + 4 options


class CardField(str, Enum):
    word = "Word"
    translation = "Translation"
    example = "Example"
    image = "Image"
    audio = "Audio"
    notes = "Notes"
    # STEM fields
    question = "Question"
    answer = "Answer"
    formula = "Formula"
    difficulty = "Difficulty"
    code = "Code"


class SubdeckConfig(BaseModel):
    topic: str
    daily_limit: int = Field(default=10, ge=1, le=100)
    deck_type: DeckType = DeckType.language
    card_style: CardStyle = CardStyle.standard
    fields: list[CardField] = Field(default_factory=lambda: [CardField.word, CardField.translation])
    media: list[MediaType] = Field(default_factory=list)
    extra_instructions: Optional[str] = None
    single_word: bool = False  # True → generate a definition card FOR this word; False → use as theme
    code_language: Optional[str] = None  # e.g. "c", "vhdl", "python" — used when media includes code

    @field_validator("fields")
    @classmethod
    def required_fields_present(cls, v: list[CardField], info) -> list[CardField]:
        data = info.data if hasattr(info, "data") else {}
        deck_type = data.get("deck_type", DeckType.language)
        if deck_type == DeckType.stem:
            if CardField.question not in v or CardField.answer not in v:
                raise ValueError("STEM fields must include at least 'Question' and 'Answer'")
        else:
            if CardField.word not in v or CardField.translation not in v:
                raise ValueError("Language fields must include at least 'Word' and 'Translation'")
        return v


class DeckConfig(BaseModel):
    deck: str
    language: str
    ai_provider: str = "claude"
    subdecks: dict[str, SubdeckConfig]

    @property
    def anki_deck_name(self) -> str:
        return self.deck

    def subdeck_anki_name(self, subdeck_key: str) -> str:
        return f"{self.deck}::{subdeck_key.capitalize()}"
