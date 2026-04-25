from __future__ import annotations

import base64
import json
from pathlib import Path

import requests

_DEFAULT_URL = "http://localhost:8765"
_API_VERSION = 6


class AnkiConnectError(Exception):
    pass


class AnkiConnectClient:
    def __init__(self, url: str = _DEFAULT_URL) -> None:
        self._url = url

    # ------------------------------------------------------------------
    # Core transport
    # ------------------------------------------------------------------

    def _invoke(self, action: str, **params) -> object:
        payload = {"action": action, "version": _API_VERSION, "params": params}
        try:
            resp = requests.post(self._url, json=payload, timeout=10)
            resp.raise_for_status()
        except requests.ConnectionError:
            raise AnkiConnectError(
                "Cannot reach Anki. Make sure Anki is open and AnkiConnect is installed."
            )
        except requests.RequestException as exc:
            raise AnkiConnectError(f"AnkiConnect request failed: {exc}")

        body = resp.json()
        if body.get("error"):
            raise AnkiConnectError(f"AnkiConnect error: {body['error']}")
        return body["result"]

    def is_available(self) -> bool:
        try:
            self._invoke("version")
            return True
        except AnkiConnectError:
            return False

    # ------------------------------------------------------------------
    # Decks
    # ------------------------------------------------------------------

    def deck_names(self) -> list[str]:
        return self._invoke("deckNames")  # type: ignore[return-value]

    def create_deck(self, deck_name: str) -> int:
        return self._invoke("createDeck", deck=deck_name)  # type: ignore[return-value]

    def ensure_deck(self, deck_name: str) -> None:
        if deck_name not in self.deck_names():
            self.create_deck(deck_name)

    # ------------------------------------------------------------------
    # Models (note types)
    # ------------------------------------------------------------------

    def model_names(self) -> list[str]:
        return self._invoke("modelNames")  # type: ignore[return-value]

    def create_model(
        self,
        model_name: str,
        fields: list[str],
        card_templates: list[dict],
        css: str = "",
    ) -> None:
        self._invoke(
            "createModel",
            modelName=model_name,
            inOrderFields=fields,
            css=css,
            cardTemplates=card_templates,
        )

    def update_model_templates(self, model_name: str, card_templates: list[dict]) -> None:
        templates = {t["Name"]: {"Front": t["Front"], "Back": t["Back"]} for t in card_templates}
        self._invoke("updateModelTemplates", model={"name": model_name, "templates": templates})

    def ensure_model(
        self,
        model_name: str,
        fields: list[str],
        card_templates: list[dict],
        css: str = "",
    ) -> None:
        if model_name not in self.model_names():
            self.create_model(model_name, fields, card_templates, css)
        else:
            # Always push the latest template so fixes take effect immediately
            try:
                self.update_model_templates(model_name, card_templates)
            except Exception:
                pass  # Non-fatal — model exists, cards will still work

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    def find_notes(self, query: str) -> list[int]:
        return self._invoke("findNotes", query=query)  # type: ignore[return-value]

    def notes_info(self, note_ids: list[int]) -> list[dict]:
        return self._invoke("notesInfo", notes=note_ids)  # type: ignore[return-value]

    def existing_words_in_deck(self, deck_name: str) -> list[str]:
        """Return primary field values already in a deck (Word for language, Question for STEM)."""
        import re
        escaped = re.sub(r"[\x00-\x1f\x7f]", " ", deck_name).strip().replace('"', '\\"')
        note_ids = self.find_notes(f'deck:"{escaped}"')
        if not note_ids:
            return []
        values = []
        for i in range(0, len(note_ids), 100):
            batch = note_ids[i:i + 100]
            for info in self.notes_info(batch):
                fields = info.get("fields", {})
                # Try Word (language decks) then Question (STEM decks)
                value = (
                    fields.get("Word", {}).get("value", "")
                    or fields.get("Question", {}).get("value", "")
                )
                if value:
                    values.append(value)
        return values

    def add_note(self, deck_name: str, model_name: str, fields: dict[str, str], tags: list[str] | None = None) -> int:
        note = {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": fields,
            "tags": tags or [],
            "options": {"allowDuplicate": False, "duplicateScope": "deck"},
        }
        return self._invoke("addNote", note=note)  # type: ignore[return-value]

    def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None:
        self._invoke("updateNoteFields", note={"id": note_id, "fields": fields})

    def delete_notes(self, note_ids: list[int]) -> None:
        self._invoke("deleteNotes", notes=note_ids)

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    def store_media_file(self, filename: str, file_path: Path) -> str:
        data = base64.b64encode(file_path.read_bytes()).decode()
        return self._invoke("storeMediaFile", filename=filename, data=data)  # type: ignore[return-value]

    def delete_decks(self, deck_names: list[str], cards_too: bool = True) -> None:
        self._invoke("deleteDecks", decks=deck_names, cardsToo=cards_too)

    # ------------------------------------------------------------------
    # Sync
    # ------------------------------------------------------------------

    def sync(self) -> None:
        self._invoke("sync")
