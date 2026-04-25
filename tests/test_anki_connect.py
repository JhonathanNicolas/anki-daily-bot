from unittest.mock import MagicMock, patch

import pytest

from src.anki.connect_client import AnkiConnectClient, AnkiConnectError


@pytest.fixture
def client() -> AnkiConnectClient:
    return AnkiConnectClient(url="http://localhost:8765")


def _mock_response(result=None, error=None):
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = {"result": result, "error": error}
    return mock


def test_is_available_true(client):
    with patch("requests.post", return_value=_mock_response(result=6)):
        assert client.is_available() is True


def test_is_available_false_when_connection_error(client):
    import requests as req
    with patch("requests.post", side_effect=req.ConnectionError):
        assert client.is_available() is False


def test_invoke_raises_on_anki_error(client):
    with patch("requests.post", return_value=_mock_response(error="deck not found")):
        with pytest.raises(AnkiConnectError, match="deck not found"):
            client.deck_names()


def test_ensure_deck_creates_if_missing(client):
    with patch.object(client, "deck_names", return_value=["Default"]):
        with patch.object(client, "create_deck") as mock_create:
            client.ensure_deck("German::Numbers")
            mock_create.assert_called_once_with("German::Numbers")


def test_ensure_deck_skips_if_exists(client):
    with patch.object(client, "deck_names", return_value=["German::Numbers"]):
        with patch.object(client, "create_deck") as mock_create:
            client.ensure_deck("German::Numbers")
            mock_create.assert_not_called()


def test_find_notes_returns_ids(client):
    with patch("requests.post", return_value=_mock_response(result=[123, 456])):
        ids = client.find_notes('deck:"German::Numbers" Word:"eins"')
    assert ids == [123, 456]


def test_store_media_file(client, tmp_path):
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"fake-mp3-data")
    with patch("requests.post", return_value=_mock_response(result="test.mp3")) as mock_post:
        client.store_media_file("test.mp3", audio)
        call_payload = mock_post.call_args[1]["json"]
        assert call_payload["action"] == "storeMediaFile"
        assert call_payload["params"]["filename"] == "test.mp3"
        assert "data" in call_payload["params"]
