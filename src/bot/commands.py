from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from src.ai.claude_provider import ClaudeProvider
from src.anki.connect_client import AnkiConnectClient
from src.anki.exporter import cleanup_media_cache, export_deck
from src.anki.sync_manager import SyncManager
from src.bot.lang import clean_subdeck_key, deck_to_language
from src.bot.nlu import ParsedIntent
from src.config.loader import load_all_deck_configs
from src.card.models import CardData
from src.config.models import CardField, CardStyle, DeckConfig, DeckType, MediaType, SubdeckConfig
from src.media.audio import generate_audio
from src.media.image import ImageRateLimitError, fetch_image, fetch_image_ai


def fetch_media_for_cards(
    cards: list[CardData],
    media_types: list[MediaType],
    language: str,
    media_cache_dir: Path,
    max_workers: int = 5,
    deck_type: DeckType = DeckType.language,
) -> tuple[int, int, int, int, str]:
    """Fetch audio + example audio + images concurrently.
    Returns (audio_ok, audio_fail, img_ok, img_fail, img_error_msg)."""
    audio_ok = audio_fail = img_ok = img_fail = 0
    img_error = ""

    want_audio = MediaType.audio in media_types
    want_image = MediaType.image in media_types

    def fetch_word_audio(card: CardData) -> tuple[CardData, bool]:
        card.audio_path = generate_audio(card.word, language, media_cache_dir)
        return card, True

    def fetch_example_audio(card: CardData) -> tuple[CardData, bool]:
        if card.example:
            card.example_audio_path = generate_audio(card.example, language, media_cache_dir)
        return card, True

    def fetch_card_image(card: CardData) -> tuple[CardData, bool | str]:
        if deck_type == DeckType.stem:
            return card, True  # No images for STEM — LaTeX/formulas are the visual
        search_term = card.translation or card.word
        card.image_path = fetch_image(search_term, media_cache_dir)
        return card, True

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        # Submit all audio tasks
        audio_futures = {}
        example_futures = {}
        image_futures = {}

        if want_audio:
            for card in cards:
                audio_futures[pool.submit(fetch_word_audio, card)] = card
                if card.example:
                    example_futures[pool.submit(fetch_example_audio, card)] = card

        if want_image:
            for card in cards:
                image_futures[pool.submit(fetch_card_image, card)] = card

        for fut in as_completed(audio_futures):
            try:
                fut.result()
                audio_ok += 1
            except Exception:
                audio_fail += 1

        for fut in as_completed(example_futures):
            try:
                fut.result()
            except Exception:
                pass

        for fut in as_completed(image_futures):
            try:
                _, ok = fut.result()
                if ok and image_futures[fut].has_image():
                    img_ok += 1
                else:
                    img_fail += 1
            except ImageRateLimitError as e:
                img_error = str(e)
                img_fail += 1
                print(f"[media] {e}")
            except Exception:
                img_fail += 1

    return audio_ok, audio_fail, img_ok, img_fail, img_error


def deck_id(deck_name: str) -> str:
    """Deterministic 6-char ID for a deck name, shown in /decks and required to confirm deletion."""
    return hashlib.sha256(deck_name.encode()).hexdigest()[:6]


def _get_client() -> AnkiConnectClient:
    return AnkiConnectClient(url=os.environ.get("ANKI_CONNECT_URL", "http://localhost:8765"))


def cmd_status() -> str:
    client = _get_client()
    if not client.is_available():
        return "Anki is not running. Open Anki and make sure AnkiConnect is installed."
    decks = client.deck_names()
    bot_decks = [d for d in decks if "::" in d or d in _configured_deck_names()]
    lines = ["Anki is running."]
    if bot_decks:
        lines.append(f"Bot decks ({len(bot_decks)}): " + ", ".join(bot_decks))
    else:
        lines.append("No bot decks found yet. Run /run to generate cards.")
    return "\n".join(lines)


def cmd_decks() -> str:
    client = _get_client()
    if not client.is_available():
        return "Anki is not running."

    all_decks = client.deck_names()
    # Show top-level decks and their subdecks
    top_level = sorted({d.split("::")[0] for d in all_decks if d != "Default"})
    if not top_level:
        return "No decks found in Anki."

    lines = []
    for deck in top_level:
        did = deck_id(deck)
        lines.append(f"*{deck}* — ID: `{did}`")
        subdecks = sorted(d for d in all_decks if d.startswith(f"{deck}::"))
        for sub in subdecks:
            sub_key = sub.split("::", 1)[1]
            sub_did = deck_id(sub)
            lines.append(f"  • {sub_key} — ID: `{sub_did}`")
    return "\n".join(lines)


def _resolve_deck(all_decks: list[str], name_or_id: str) -> str | None:
    """Find a deck by name (case-insensitive, quote-tolerant) or by its 6-char ID."""
    clean = name_or_id.strip().strip('"').strip("'").strip()
    # Direct name match (case-insensitive, ignoring surrounding quotes)
    match = next(
        (d for d in all_decks if d.strip('"').strip("'").lower() == clean.lower()),
        None,
    )
    if match:
        return match
    # ID-based reverse lookup
    if len(clean) == 6:
        match = next((d for d in all_decks if deck_id(d) == clean), None)
    return match


def cmd_delete_request(deck_name: str) -> tuple[str, str] | tuple[None, str]:
    """
    Returns (token, message) if the deck exists, or (None, error_message).
    The token must be confirmed by the user to proceed with deletion.
    """
    client = _get_client()
    if not client.is_available():
        return None, "Anki is not running."

    all_decks = client.deck_names()
    match = _resolve_deck(all_decks, deck_name)
    if not match:
        return None, f"Deck *{deck_name}* not found in Anki."

    token = deck_id(match)
    is_subdeck = "::" in match
    children = [d for d in all_decks if d.startswith(f"{match}::")] if not is_subdeck else []
    children_list = "\n".join(f"  • {s}" for s in children) if children else ""

    scope = f"*{match}*"
    if children_list:
        scope += f"\n{children_list}"

    msg = (
        f"⚠️ *You are about to permanently delete:*\n"
        f"{scope}\n\n"
        f"This will remove all cards and review history. "
        f"This cannot be undone.\n\n"
        f"To confirm, reply with the deck ID:\n`{token}`"
    )
    return token, msg


def cmd_delete_confirm(deck_name: str) -> str:
    client = _get_client()
    if not client.is_available():
        return "Anki is not running."

    all_decks = client.deck_names()
    match = _resolve_deck(all_decks, deck_name)
    if not match:
        return f"Deck *{deck_name}* no longer exists."

    # Delete the deck and all its subdecks
    to_delete = [d for d in all_decks if d == match or d.startswith(f"{match}::")]
    client.delete_decks(to_delete)
    return f"Deleted *{match}* and {len(to_delete) - 1} subdeck(s). All cards and history removed."


def cmd_run(deck_filter: str | None, subdeck_filter: str | None) -> str:
    configs = load_all_deck_configs()
    if deck_filter:
        configs = [c for c in configs if c.deck.lower() == deck_filter.lower()]
    if not configs:
        return f"No deck found matching '{deck_filter}'." if deck_filter else "No deck configs found."

    client = _get_client()
    use_ankiconnect = client.is_available()
    sync_manager = SyncManager(client) if use_ankiconnect else None

    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    media_cache_dir = Path(os.environ.get("MEDIA_CACHE_DIR", "media_cache"))
    provider = ClaudeProvider()
    lines = []

    for cfg in configs:
        subdecks = cfg.subdecks
        if subdeck_filter:
            if subdeck_filter.lower() not in {k.lower(): k for k in subdecks}:
                lines.append(f"Subdeck '{subdeck_filter}' not found in {cfg.deck}.")
                continue
            key_map = {k.lower(): k for k in subdecks}
            subdecks = {key_map[subdeck_filter.lower()]: subdecks[key_map[subdeck_filter.lower()]]}

        for key, sub in subdecks.items():
            anki_name = cfg.subdeck_anki_name(key)
            already_known = client.existing_words_in_deck(anki_name) if use_ankiconnect else []
            cards = provider.generate_cards(sub, cfg.language, already_known=already_known)

            fetch_media_for_cards(cards, list(sub.media), cfg.language, media_cache_dir)

            if use_ankiconnect:
                result = sync_manager.sync_subdeck(cfg, key, sub, cards)
                lines.append(
                    f"{cfg.deck}::{key.capitalize()} — "
                    f"added {result['added']}, updated {result['updated']}, skipped {result['skipped']}"
                )
            else:
                apkg = export_deck(cfg, key, sub, cards, output_dir, media_cache_dir)
                lines.append(f"{cfg.deck}::{key.capitalize()} — exported to `{apkg.name}` (import manually)")

        cleanup_media_cache(media_cache_dir)

    if use_ankiconnect and sync_manager:
        sync_manager.trigger_sync()
        lines.append("AnkiWeb sync triggered.")

    return "\n".join(lines) if lines else "Nothing to run."


def cmd_chat(intent: ParsedIntent) -> str:
    if intent.intent == "list_decks":
        return cmd_decks()
    if intent.intent == "status":
        return cmd_status()
    if intent.intent == "help":
        return "Just tell me what you want, e.g.:\n• _Add 10 weather words to my German deck_\n• _5 Spanish food words with images_"
    if intent.intent != "generate_cards":
        return "I didn't understand that. Try something like: _Add 10 weather words to my German deck_"

    if not intent.deck or not intent.topic:
        return "I need both a deck name and a topic to generate cards."

    # If deck path already contains "::", split into parent + subdeck to avoid double-nesting
    raw_deck = intent.deck
    if "::" in raw_deck:
        parts = raw_deck.split("::", 1)
        raw_deck = parts[0]
        forced_subdeck = parts[1].lower()
    else:
        forced_subdeck = None
        # Resolve ambiguous deck name via Anki (e.g. "Farben" → "German::Farben")
        raw_deck = _resolve_deck_path(raw_deck) or raw_deck

    # Re-split in case Anki lookup returned a full path
    if "::" in raw_deck:
        parts = raw_deck.split("::", 1)
        raw_deck = parts[0]
        forced_subdeck = parts[1].lower()

    configs = load_all_deck_configs()
    deck_cfg = next((c for c in configs if c.deck.lower() == raw_deck.lower()), None)
    if deck_cfg is None:
        deck_cfg = DeckConfig(deck=raw_deck.capitalize(), language=deck_to_language(raw_deck), subdecks={})

    subdeck_key = forced_subdeck or intent.subdeck or clean_subdeck_key(intent.topic)

    # Inherit saved media/fields/type config if this subdeck was previously set up via wizard
    saved = _lookup_subdeck_config(deck_cfg.deck, subdeck_key)
    if saved:
        media_types = list(saved.media)
        fields = list(saved.fields)
        saved_deck_type = saved.deck_type
    else:
        media_types = [MediaType(m) for m in intent.media if m in MediaType._value2member_map_]
        fields = [CardField.word, CardField.translation, CardField.example]
        if MediaType.audio in media_types:
            fields.append(CardField.audio)
        saved_deck_type = DeckType.language

    if saved:
        # If user specified a sub-topic, focus on it while keeping deck context
        user_subtopic = intent.topic or ""
        already_in_topic = user_subtopic.lower() in saved.topic.lower() if user_subtopic else True
        if user_subtopic and not already_in_topic:
            topic = f"{saved.topic} — specifically focusing on: {user_subtopic}"
        else:
            topic = saved.topic
    else:
        topic = f"{intent.topic} in {deck_cfg.language.upper()}"

    subdeck_cfg = SubdeckConfig(
        topic=topic,
        daily_limit=intent.quantity,
        deck_type=saved_deck_type,
        card_style=saved.card_style if saved else CardStyle.standard,
        fields=fields,
        media=media_types,
    )

    client = _get_client()
    use_ankiconnect = client.is_available()
    sync_manager = SyncManager(client) if use_ankiconnect else None
    media_cache_dir = Path(os.environ.get("MEDIA_CACHE_DIR", "media_cache"))
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))

    anki_deck_name = deck_cfg.subdeck_anki_name(subdeck_key)
    already_known = client.existing_words_in_deck(anki_deck_name) if use_ankiconnect else []

    if saved_deck_type == DeckType.stem:
        from src.ai.stem_provider import StemProvider
        saved_style = saved.card_style if saved else CardStyle.standard
        cards = StemProvider().generate_cards(subdeck_cfg, saved_style, already_known)
    else:
        cards = ClaudeProvider().generate_cards(subdeck_cfg, deck_cfg.language, already_known=already_known)

    audio_ok, audio_fail, img_ok, img_fail, img_error = fetch_media_for_cards(
        cards, media_types, deck_cfg.language, media_cache_dir, deck_type=saved_deck_type
    )
    media_report = _media_report(media_types, audio_ok, audio_fail, img_ok, img_fail, img_error)

    if use_ankiconnect:
        result = sync_manager.sync_subdeck(deck_cfg, subdeck_key, subdeck_cfg, cards)
        cleanup_media_cache(media_cache_dir)
        sync_manager.trigger_sync()
        return (
            f"Done! Added to *{deck_cfg.deck}::{subdeck_key.capitalize()}*\n"
            f"Added: {result['added']} | Updated: {result['updated']} | Skipped: {result['skipped']}\n"
            f"{media_report}"
            f"AnkiWeb sync triggered."
        )
    else:
        apkg = export_deck(deck_cfg, subdeck_key, subdeck_cfg, cards, output_dir, media_cache_dir)
        cleanup_media_cache(media_cache_dir)
        return f"Anki is closed. Exported to `{apkg.name}` — import it manually.\n{media_report}"


def _media_report(
    media_types: list,
    audio_ok: int,
    audio_fail: int,
    img_ok: int,
    img_fail: int,
    img_error: str = "",
) -> str:
    lines = []
    if audio_ok or audio_fail:
        lines.append(f"Audio: {audio_ok} added" + (f", {audio_fail} failed" if audio_fail else ""))
    if img_ok or img_fail:
        fail_note = f", {img_fail} failed — {img_error}" if img_fail and img_error else (f", {img_fail} failed" if img_fail else "")
        lines.append(f"Images: {img_ok} added{fail_note}")
    return ("\n".join(lines) + "\n") if lines else ""


def _resolve_deck_path(name: str) -> str | None:
    """
    Given an ambiguous deck name (e.g. 'Farben'), search Anki for the canonical
    full path (e.g. 'German::Farben'). Returns None if no unique match found.
    """
    try:
        client = _get_client()
        if not client.is_available():
            return None
        all_decks = client.deck_names()
        # Exact match first
        exact = next((d for d in all_decks if d.lower() == name.lower()), None)
        if exact:
            return exact
        # Match as the last segment of a path (e.g. Farben in German::Farben)
        matches = [d for d in all_decks if d.split("::")[-1].lower() == name.lower()]
        if len(matches) == 1:
            return matches[0]
    except Exception:
        pass
    return None


def save_subdeck_config(
    deck_name: str,
    language: str,
    subdeck_key: str,
    topic: str,
    media: list[str],
    daily_limit: int,
    fields: list[str],
    deck_type: str = "language",
    card_style: str = "standard",
) -> None:
    """Persist a subdeck config into decks/<deck_name>.yaml so it can be reused later."""
    decks_dir = Path("decks")
    decks_dir.mkdir(exist_ok=True)
    yaml_path = decks_dir / f"{deck_name.lower()}.yaml"

    if yaml_path.exists():
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {"deck": deck_name, "language": language, "ai_provider": "claude", "subdecks": {}}

    data.setdefault("subdecks", {})[subdeck_key] = {
        "topic": topic,
        "daily_limit": daily_limit,
        "fields": fields,
        "media": media,
        "deck_type": deck_type,
        "card_style": card_style,
    }

    with yaml_path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _lookup_subdeck_config(deck_name: str, subdeck_key: str) -> SubdeckConfig | None:
    """Return saved SubdeckConfig for a deck+subdeck if it exists in YAML."""
    configs = load_all_deck_configs()
    deck_cfg = next((c for c in configs if c.deck.lower() == deck_name.lower()), None)
    if deck_cfg is None:
        return None
    return deck_cfg.subdecks.get(subdeck_key.lower()) or deck_cfg.subdecks.get(subdeck_key)


def _configured_deck_names() -> set[str]:
    try:
        return {c.deck for c in load_all_deck_configs()}
    except Exception:
        return set()


def cmd_batch(intents: list[ParsedIntent], max_workers: int = 4) -> str:
    """Execute multiple intents concurrently and return one aggregated reply."""
    results: dict[int, str] = {}

    def _sanitize(intent: ParsedIntent) -> ParsedIntent:
        """Strip newlines/extra whitespace that batch NLU sometimes embeds."""
        if intent.deck:
            intent.deck = intent.deck.strip().replace("\n", " ")
        if intent.subdeck:
            intent.subdeck = intent.subdeck.strip().replace("\n", " ")
        if intent.topic:
            intent.topic = intent.topic.strip().replace("\n", " ")
        return intent

    def _run(idx: int, intent: ParsedIntent) -> tuple[int, str]:
        try:
            intent = _sanitize(intent)
            if intent.intent == "create_deck":
                label = intent.deck or "new deck"
                return idx, f"⚠️ *{label}*: deck creation requires the setup wizard — send it as a separate message."
            return idx, cmd_chat(intent)
        except Exception as exc:
            return idx, f"Error: {exc}"

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run, i, intent): i for i, intent in enumerate(intents)}
        for fut in as_completed(futures):
            idx, result = fut.result()
            results[idx] = result

    lines = []
    for i, intent in enumerate(intents):
        label = f"*{intent.deck}*" if intent.deck else f"request {i + 1}"
        lines.append(f"{label}\n{results.get(i, 'No result')}")

    return "\n\n".join(lines)
