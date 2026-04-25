"""Daily automation runner — called by cron or systemd timer."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.ai.claude_provider import ClaudeProvider
from src.ai.stem_provider import StemProvider
from src.anki.connect_client import AnkiConnectClient
from src.anki.exporter import cleanup_media_cache, export_deck
from src.anki.sync_manager import SyncManager
from src.bot.commands import fetch_media_for_cards
from src.bot.lang import deck_to_language
from src.config.loader import load_all_deck_configs
from src.config.models import DeckType


def run_daily() -> None:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    media_cache_dir = Path(os.environ.get("MEDIA_CACHE_DIR", "media_cache"))
    anki_url = os.environ.get("ANKI_CONNECT_URL", "http://localhost:8765")

    configs = load_all_deck_configs()
    if not configs:
        print("[scheduler] No deck configs found in decks/.")
        sys.exit(0)

    client = AnkiConnectClient(url=anki_url)
    use_ankiconnect = client.is_available()
    sync_manager = SyncManager(client) if use_ankiconnect else None

    if use_ankiconnect:
        print("[scheduler] AnkiConnect detected.")
    else:
        print("[scheduler] Anki not running — will export .apkg files.")

    for deck_config in configs:
        print(f"\n=== {deck_config.deck} ({deck_config.language}) ===")
        for key, sub in deck_config.subdecks.items():
            print(f"  → {key}")
            anki_name = deck_config.subdeck_anki_name(key)
            already_known = client.existing_words_in_deck(anki_name) if use_ankiconnect else []

            if sub.deck_type == DeckType.stem:
                cards = StemProvider().generate_cards(sub, sub.card_style, already_known)
            else:
                cards = ClaudeProvider().generate_cards(sub, deck_config.language, already_known)

            fetch_media_for_cards(cards, list(sub.media), deck_config.language, media_cache_dir)

            if use_ankiconnect:
                result = sync_manager.sync_subdeck(deck_config, key, sub, cards)
                print(f"     added={result['added']} updated={result['updated']} skipped={result['skipped']}")
            else:
                apkg = export_deck(deck_config, key, sub, cards, output_dir, media_cache_dir)
                print(f"     exported: {apkg}")

        cleanup_media_cache(media_cache_dir)

    if use_ankiconnect:
        sync_manager.trigger_sync()
        print("\n[scheduler] AnkiWeb sync triggered.")


if __name__ == "__main__":
    run_daily()
