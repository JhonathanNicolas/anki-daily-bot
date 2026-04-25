from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.ai.claude_provider import ClaudeProvider
from src.anki.connect_client import AnkiConnectClient
from src.anki.exporter import cleanup_media_cache, export_deck
from src.anki.sync_manager import SyncManager
from src.config.loader import load_all_deck_configs, load_deck_config
from src.config.models import MediaType
from src.media.audio import generate_audio
from src.media.image import fetch_image


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Anki Daily Bot — generate Anki cards with AI")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--deck", metavar="FILE", help="Path to a single deck YAML config")
    group.add_argument("--all", action="store_true", help="Process all decks in decks/")
    parser.add_argument("--subdeck", metavar="KEY", help="Only process this subdeck key")
    parser.add_argument("--dry-run", action="store_true", help="Print cards without exporting")
    parser.add_argument("--no-sync", action="store_true", help="Skip AnkiWeb sync after import")
    return parser.parse_args()


def _fetch_media(cards, subdeck_config, language: str, media_cache_dir: Path) -> None:
    for card in cards:
        if MediaType.audio in subdeck_config.media:
            try:
                card.audio_path = generate_audio(card.word, language, media_cache_dir)
            except Exception as exc:
                print(f"    [audio] Failed for '{card.word}': {exc}")
        if MediaType.image in subdeck_config.media:
            card.image_path = fetch_image(card.word, media_cache_dir)


def run(deck_config_path: str | None, subdeck_filter: str | None, dry_run: bool, no_sync: bool) -> None:
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    media_cache_dir = Path(os.environ.get("MEDIA_CACHE_DIR", "media_cache"))
    anki_url = os.environ.get("ANKI_CONNECT_URL", "http://localhost:8765")

    configs = [load_deck_config(deck_config_path)] if deck_config_path else load_all_deck_configs()
    if not configs:
        print("[main] No deck configs found.")
        sys.exit(1)

    client = AnkiConnectClient(url=anki_url)
    use_ankiconnect = client.is_available()

    if use_ankiconnect:
        print("[main] AnkiConnect detected — cards will be synced directly into Anki.")
        sync_manager = SyncManager(client)
    else:
        print("[main] Anki not running — falling back to .apkg export (import manually).")

    provider = ClaudeProvider()

    for deck_config in configs:
        print(f"\n=== Deck: {deck_config.deck} ({deck_config.language}) ===")

        subdecks = deck_config.subdecks
        if subdeck_filter:
            if subdeck_filter not in subdecks:
                print(f"  [skip] Subdeck '{subdeck_filter}' not found.")
                continue
            subdecks = {subdeck_filter: subdecks[subdeck_filter]}

        for key, subdeck_config in subdecks.items():
            print(f"\n  → Subdeck: {key} (limit: {subdeck_config.daily_limit} cards)")

            cards = provider.generate_cards(
                subdeck_config=subdeck_config,
                language=deck_config.language,
                already_known=[],
            )
            print(f"    Generated {len(cards)} cards via AI")

            if dry_run:
                for card in cards:
                    print(f"    [{card.word}] → {card.translation} | {card.example}")
                continue

            _fetch_media(cards, subdeck_config, deck_config.language, media_cache_dir)

            if use_ankiconnect:
                result = sync_manager.sync_subdeck(deck_config, key, subdeck_config, cards)
                print(
                    f"    Synced → added: {result['added']}, "
                    f"updated: {result['updated']}, skipped: {result['skipped']}"
                )
            else:
                apkg_path = export_deck(
                    deck_config=deck_config,
                    subdeck_key=key,
                    subdeck_config=subdeck_config,
                    cards=cards,
                    output_dir=output_dir,
                    media_cache_dir=media_cache_dir,
                )
                print(f"    Exported: {apkg_path}")

        cleanup_media_cache(media_cache_dir)

    if use_ankiconnect and not no_sync:
        print("\n[main] Triggering AnkiWeb sync...")
        sync_manager.trigger_sync()
        print("[main] Done.")


def main() -> None:
    args = _parse_args()
    if not args.deck and not args.all:
        args.all = True
    run(
        deck_config_path=args.deck,
        subdeck_filter=args.subdeck,
        dry_run=args.dry_run,
        no_sync=args.no_sync,
    )


if __name__ == "__main__":
    main()
