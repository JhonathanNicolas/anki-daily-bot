from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

import anthropic

from src.bot.nlu import ParsedIntent
from src.config.models import CardStyle, DeckType, MediaType

Step = Literal["confirm_name", "deck_type", "description", "media", "code_language", "card_style", "done"]

_CANCEL_WORDS = {"no", "cancel", "stop", "exit", "quit", "abort", "nevermind", "never mind"}

_MEDIA_LANGUAGE = """Choose the media for cards:
• `audio` — pronunciation audio
• `image` — pictures
• `both` — audio + images
• `none` — text only"""

_MEDIA_STEM = """Choose the media for cards:
• `latex` — rendered math formulas (MathJax)
• `code` — syntax-highlighted code snippets (2 cards per note: concept→code and code→concept)
• `both` — latex formulas AND code snippets
• `none` — text only"""

_CARD_STYLE_LANGUAGE = """Choose the card style:
• `standard` — front / back
• `reverse` — also generates translation → word cards"""

_CARD_STYLE_STEM = """Choose the card style:
• `standard` — question / answer
• `cloze` — fill-in-the-blank
• `multiple_choice` — question with 4 options"""


def _guess_description(deck: str, subdeck: str, deck_type: DeckType) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    subject = f"{deck}::{subdeck}" if subdeck else deck
    type_hint = "language learning" if deck_type == DeckType.language else "STEM study"
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=80,
        messages=[{
            "role": "user",
            "content": (
                f"Write a single short sentence describing a {type_hint} Anki deck called '{subject}'. "
                f"Example: 'Deck to learn colors in German.' or 'Deck covering FFT concepts and formulas.' "
                f"Reply with only the sentence."
            ),
        }],
    )
    return msg.content[0].text.strip()


@dataclass
class DeckWizard:
    deck: str
    subdeck: str
    step: Step = "confirm_name"
    deck_type: DeckType = DeckType.language
    card_style: CardStyle = CardStyle.standard
    description: str = ""
    media: list[str] = field(default_factory=lambda: ["audio"])
    quantity: int = 10
    code_language: str = ""

    @property
    def full_path(self) -> str:
        if self.subdeck:
            return f"{self.deck}::{self.subdeck.capitalize()}"
        return self.deck


class WizardCancelled(Exception):
    pass


def wizard_start(intent: ParsedIntent) -> tuple[DeckWizard, str]:
    raw_deck = intent.deck or ""
    if "::" in raw_deck:
        parts = raw_deck.split("::", 1)
        deck, subdeck = parts[0].strip().capitalize(), parts[1].strip().lower()
    else:
        deck = raw_deck.strip().capitalize()
        subdeck = (intent.subdeck or "").strip().lower()

    wizard = DeckWizard(deck=deck, subdeck=subdeck, quantity=intent.quantity)

    if not deck:
        return wizard, "What should the deck be called? (e.g. German::Colors or DSP::FFT)"

    return wizard, (
        f"I'll create *{wizard.full_path}*.\n"
        f"Is this name correct? (yes / suggest a different name / cancel)"
    )


def wizard_step(wizard: DeckWizard, user_input: str) -> tuple[DeckWizard, str, bool]:
    """Process one user reply. Returns (wizard, reply, is_done). Raises WizardCancelled."""
    text = user_input.strip()

    if text.lower() in _CANCEL_WORDS:
        raise WizardCancelled()

    # ── Step 1: confirm name ────────────────────────────────────────────────
    if wizard.step == "confirm_name":
        if text.lower() in ("yes", "y", "ok", "correct", "yep", "sure"):
            wizard.step = "deck_type"
            return wizard, (
                "What type of deck is this?\n"
                "• `language` — vocabulary, phrases, grammar\n"
                "• `stem` — science, math, engineering, technology"
            ), False
        else:
            new_name = text.strip('"').strip("'")
            if "::" in new_name:
                parts = new_name.split("::", 1)
                wizard.deck = parts[0].strip().capitalize()
                wizard.subdeck = parts[1].strip().lower()
            elif wizard.subdeck:
                wizard.subdeck = new_name.lower()
            else:
                wizard.deck = new_name.capitalize()
            return wizard, (
                f"Updated to *{wizard.full_path}*.\n"
                f"Is this correct? (yes / suggest another name / cancel)"
            ), False

    # ── Step 2: deck type ───────────────────────────────────────────────────
    if wizard.step == "deck_type":
        choice = text.lower().strip()
        if "stem" in choice or "science" in choice or "math" in choice or "eng" in choice:
            wizard.deck_type = DeckType.stem
            wizard.media = ["latex"]  # sensible STEM default
        else:
            wizard.deck_type = DeckType.language
            wizard.media = ["audio"]  # sensible language default
        wizard.step = "description"
        return wizard, (
            f"Got it — *{wizard.deck_type.value.replace('_', ' ')}* deck.\n\n"
            f"Describe this deck in one sentence, or send `skip` to auto-generate:"
        ), False

    # ── Step 3: description ─────────────────────────────────────────────────
    if wizard.step == "description":
        if text.lower() in ("skip", "s", ""):
            generated = _guess_description(wizard.deck, wizard.subdeck, wizard.deck_type)
            wizard.description = generated
            wizard.step = "media"
            media_prompt = _MEDIA_STEM if wizard.deck_type == DeckType.stem else _MEDIA_LANGUAGE
            return wizard, (
                f"Auto-generated description:\n_{generated}_\n\n{media_prompt}"
            ), False
        else:
            wizard.description = text
            wizard.step = "media"
            media_prompt = _MEDIA_STEM if wizard.deck_type == DeckType.stem else _MEDIA_LANGUAGE
            return wizard, media_prompt, False

    # ── Step 4: media ───────────────────────────────────────────────────────
    if wizard.step == "media":
        choice = text.lower().strip()
        if wizard.deck_type == DeckType.stem:
            if "code" in choice and "latex" in choice or choice in ("both", "all"):
                wizard.media = ["latex", "code"]
            elif "code" in choice:
                wizard.media = ["code"]
            elif choice in ("latex", "math", "formula", "formulas", "yes", "y"):
                wizard.media = ["latex"]
            else:
                wizard.media = []
        else:
            if choice == "audio":
                wizard.media = ["audio"]
            elif choice == "image":
                wizard.media = ["image"]
            elif choice in ("both", "all"):
                wizard.media = ["audio", "image"]
            else:
                wizard.media = []

        if "code" in wizard.media:
            wizard.step = "code_language"
            return wizard, (
                "What programming language will this deck cover?\n"
                "Examples: `C`, `C++`, `Python`, `Verilog`, `VHDL`, `Assembly`, `Rust`..."
            ), False

        wizard.step = "card_style"
        style_prompt = _CARD_STYLE_STEM if wizard.deck_type == DeckType.stem else _CARD_STYLE_LANGUAGE
        return wizard, style_prompt, False

    # ── Step 4.5: code language ─────────────────────────────────────────────
    if wizard.step == "code_language":
        wizard.code_language = text.strip().lower()
        wizard.step = "card_style"
        style_prompt = _CARD_STYLE_STEM if wizard.deck_type == DeckType.stem else _CARD_STYLE_LANGUAGE
        return wizard, (
            f"Got it — *{wizard.code_language.upper()}* deck.\n\n{style_prompt}"
        ), False

    # ── Step 5: card style ──────────────────────────────────────────────────
    if wizard.step == "card_style":
        choice = text.lower().strip()
        if "cloze" in choice or "fill" in choice or "blank" in choice:
            wizard.card_style = CardStyle.cloze
        elif "multiple" in choice or "choice" in choice or "mc" in choice or "quiz" in choice:
            wizard.card_style = CardStyle.multiple_choice
        elif "reverse" in choice or "both way" in choice or "bidirect" in choice:
            wizard.card_style = CardStyle.reverse
        else:
            wizard.card_style = CardStyle.standard

        wizard.step = "done"
        media_label = ", ".join(wizard.media) if wizard.media else "text only"
        lang_label = f" | Language: {wizard.code_language.upper()}" if wizard.code_language else ""
        return wizard, (
            f"*{wizard.full_path}* is all set!\n"
            f"Type: {wizard.deck_type.value} | Style: {wizard.card_style.value.replace('_', ' ')} | Media: {media_label}{lang_label}\n"
            f"Description: _{wizard.description}_\n\n"
            f"Generating {wizard.quantity} cards now..."
        ), True

    return wizard, "Something went wrong in the wizard.", True
