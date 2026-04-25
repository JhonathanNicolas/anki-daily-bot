from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import genanki

from src.card.models import CardData
from src.config.models import CardField, DeckConfig, MediaType, SubdeckConfig

_MODEL_ID_SEED = "anki-daily-bot-v1"

# Always-present fields in every model, in this order
_BASE_FIELDS = [CardField.word, CardField.translation, CardField.example, CardField.notes]
_MEDIA_FIELD_NAMES = ["Audio", "Image"]


def _stable_id(name: str) -> int:
    return int(hashlib.md5((_MODEL_ID_SEED + name).encode()).hexdigest(), 16) % (10**10)


def _model_field_names(subdeck_config: SubdeckConfig) -> list[str]:
    """Return the ordered list of field names that every Note must match exactly."""
    seen: set[str] = set()
    names: list[str] = []
    # Text fields: base fields that appear in the subdeck's field list
    for f in _BASE_FIELDS:
        if f in subdeck_config.fields:
            names.append(f.value)
            seen.add(f.value)
    # Media fields always appended at the end
    for m in _MEDIA_FIELD_NAMES:
        if m not in seen:
            names.append(m)
    return names


def _build_model(model_name: str, subdeck_config: SubdeckConfig) -> genanki.Model:
    field_names = _model_field_names(subdeck_config)
    return genanki.Model(
        model_id=_stable_id(model_name),
        name=model_name,
        fields=[{"name": n} for n in field_names],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Word}}",
                "afmt": (
                    "{{FrontSide}}<hr id=answer>"
                    "{{Translation}}"
                    "{{#Example}}<br><i>{{Example}}</i>{{/Example}}"
                    "{{#Audio}}{{Audio}}{{/Audio}}"
                    "{{#Image}}<br>{{Image}}{{/Image}}"
                ),
            }
        ],
    )


def export_deck(
    deck_config: DeckConfig,
    subdeck_key: str,
    subdeck_config: SubdeckConfig,
    cards: list[CardData],
    output_dir: Path,
    media_cache_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    anki_subdeck_name = deck_config.subdeck_anki_name(subdeck_key)
    deck = genanki.Deck(deck_id=_stable_id(anki_subdeck_name), name=anki_subdeck_name)
    model_name = f"{anki_subdeck_name} Model"
    model = _build_model(model_name, subdeck_config)
    field_names = _model_field_names(subdeck_config)
    media_files: list[str] = []

    for card in cards:
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
            values["Audio"] = f"[sound:{audio_name}]"
            media_files.append(str(card.audio_path))

        if MediaType.image in subdeck_config.media and card.has_image():
            image_name = _anki_media_name("img", card.word, card.image_path)
            values["Image"] = f'<img src="{image_name}">'
            media_files.append(str(card.image_path))

        note = genanki.Note(
            model=model,
            fields=[values.get(name, "") for name in field_names],
        )
        deck.add_note(note)

    output_path = output_dir / f"{deck_config.deck}_{subdeck_key}.apkg"
    package = genanki.Package(deck)
    package.media_files = media_files
    package.write_to_file(str(output_path))
    return output_path


def _anki_media_name(prefix: str, word: str, path: Path | None) -> str:
    stem = "".join(c if c.isalnum() else "_" for c in word).lower()
    suffix = path.suffix if path else ".bin"
    word_hash = hashlib.md5(word.encode()).hexdigest()[:6]
    return f"daily_{prefix}_{stem}_{word_hash}{suffix}"


def cleanup_media_cache(cache_dir: Path) -> None:
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
