import os

import pytest

os.chdir(os.path.join(os.path.dirname(__file__), ".."))

from src.card.builder import render_back, render_front
from src.card.models import CardData
from src.config.models import CardField


def test_render_front_contains_word() -> None:
    html = render_front("eins")
    assert "eins" in html


def test_render_back_contains_translation() -> None:
    html = render_back(translation="one", example="Ich habe eins.", notes="", image_filename="", audio_filename="")
    assert "one" in html
    assert "Ich habe eins." in html


def test_render_back_hides_empty_sections() -> None:
    html = render_back(translation="one")
    assert 'class="example empty"' in html
    assert 'class="notes empty"' in html
    assert 'class="media-image empty"' in html


def test_render_back_shows_audio_tag() -> None:
    html = render_back(translation="one", audio_filename="eins_abc123.mp3")
    assert "[sound:eins_abc123.mp3]" in html


def test_card_data_from_ai_dict() -> None:
    fields = [CardField.word, CardField.translation, CardField.example]
    data = {"Word": "eins", "Translation": "one", "Example": "Ich habe eins."}
    card = CardData.from_ai_dict(data, fields)
    assert card.word == "eins"
    assert card.translation == "one"
    assert card.example == "Ich habe eins."
    assert not card.has_audio()
    assert not card.has_image()
