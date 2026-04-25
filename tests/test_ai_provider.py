from unittest.mock import MagicMock, patch

import pytest

from src.card.models import CardData
from src.config.models import CardField, SubdeckConfig


@pytest.fixture
def subdeck_config() -> SubdeckConfig:
    return SubdeckConfig(
        topic="numbers in German",
        daily_limit=3,
        fields=[CardField.word, CardField.translation, CardField.example],
    )


def test_claude_provider_parses_response(subdeck_config: SubdeckConfig) -> None:
    import json

    fake_cards = [
        {"Word": "eins", "Translation": "one", "Example": "Ich habe eins Apfel."},
        {"Word": "zwei", "Translation": "two", "Example": "Zwei Hunde."},
        {"Word": "drei", "Translation": "three", "Example": "Drei Katzen."},
    ]
    fake_response_text = json.dumps(fake_cards)

    mock_content = MagicMock()
    mock_content.text = fake_response_text
    mock_message = MagicMock()
    mock_message.content = [mock_content]

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic_cls.return_value = mock_client

        from src.ai.claude_provider import ClaudeProvider

        provider = ClaudeProvider(api_key="fake-key")
        cards = provider.generate_cards(subdeck_config, language="de", already_known=[])

    assert len(cards) == 3
    assert cards[0].word == "eins"
    assert cards[0].translation == "one"
    assert cards[1].word == "zwei"


def test_claude_provider_strips_markdown_fences(subdeck_config: SubdeckConfig) -> None:
    import json

    fake_cards = [{"Word": "vier", "Translation": "four", "Example": "Vier Bäume."}]
    fake_response_text = f"```json\n{json.dumps(fake_cards)}\n```"

    mock_content = MagicMock()
    mock_content.text = fake_response_text
    mock_message = MagicMock()
    mock_message.content = [mock_content]

    with patch("anthropic.Anthropic") as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic_cls.return_value = mock_client

        from src.ai.claude_provider import ClaudeProvider

        provider = ClaudeProvider(api_key="fake-key")
        cards = provider.generate_cards(subdeck_config, language="de", already_known=[])

    assert cards[0].word == "vier"
