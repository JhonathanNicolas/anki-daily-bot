from pathlib import Path

import pytest
import yaml

from src.config.loader import load_deck_config
from src.config.models import CardField, DeckConfig, MediaType, SubdeckConfig


def test_load_german_deck(tmp_path: Path) -> None:
    config = {
        "deck": "German",
        "language": "de",
        "ai_provider": "claude",
        "subdecks": {
            "numbers": {
                "topic": "numbers in German",
                "daily_limit": 10,
                "fields": ["Word", "Translation", "Example", "Audio"],
                "media": ["audio"],
            }
        },
    }
    config_file = tmp_path / "german.yaml"
    config_file.write_text(yaml.dump(config))

    deck = load_deck_config(config_file)

    assert deck.deck == "German"
    assert deck.language == "de"
    assert "numbers" in deck.subdecks
    subdeck = deck.subdecks["numbers"]
    assert subdeck.daily_limit == 10
    assert CardField.example in subdeck.fields
    assert MediaType.audio in subdeck.media


def test_subdeck_anki_name() -> None:
    deck = DeckConfig(
        deck="German",
        language="de",
        subdecks={
            "numbers": SubdeckConfig(topic="numbers", fields=[CardField.word, CardField.translation])
        },
    )
    assert deck.subdeck_anki_name("numbers") == "German::Numbers"


def test_subdeck_requires_word_and_translation() -> None:
    with pytest.raises(Exception):
        SubdeckConfig(topic="numbers", fields=[CardField.example])


def test_missing_config_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_deck_config("/nonexistent/path.yaml")
