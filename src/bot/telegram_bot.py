from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from src.bot.commands import (
    cmd_batch,
    cmd_chat,
    cmd_decks,
    cmd_delete_confirm,
    cmd_delete_request,
    cmd_from_content,
    cmd_run,
    cmd_status,
    deck_id,
)
from src.bot.nlu import parse_message, parse_multi_message
from src.media.document import (
    CODE_EXTENSIONS,
    detect_url,
    extract_from_code_file,
    extract_from_image,
    extract_from_pdf,
    extract_from_url,
    language_from_extension,
    validate_code_file,
)
from src.bot.wizard import DeckWizard, WizardCancelled, wizard_start, wizard_step

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Separate rotating logger for all messages (in + out)
_log_dir = Path("logs")
_log_dir.mkdir(exist_ok=True)
_msg_logger = logging.getLogger("messages")
_msg_logger.setLevel(logging.INFO)
_msg_handler = logging.handlers.TimedRotatingFileHandler(
    _log_dir / "messages.log", when="midnight", backupCount=30, encoding="utf-8"
)
_msg_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
_msg_logger.addHandler(_msg_handler)

# Pending delete confirmations: {user_id: {"deck": str, "token": str}}
_pending_deletes: dict[int, dict] = {}

# Partial intents waiting for a follow-up answer: {user_id: ParsedIntent}
_pending_intents: dict[int, object] = {}

# Active deck creation wizards: {user_id: DeckWizard}
_pending_wizards: dict[int, DeckWizard] = {}

# Extracted document content waiting for deck instruction: {user_id: str}
_pending_documents: dict[int, str] = {}

_HELP = """
*Anki Daily Bot* — AI-powered flashcard generator

Just tell me what you want in plain language:
• _Add 10 weather words to my German deck_
• _5 Spanish food words with images_
• _Delete my German deck_

*Commands:*
/start — Show this help
/status — Check if Anki is running
/decks — List all decks with their IDs
/run — Generate & sync all decks
/run <deck> <subdeck> — Sync one subdeck
""".strip()


def _log_message(update: Update, context_label: str) -> None:
    user = update.effective_user
    name = f"{user.first_name} {user.last_name or ''}".strip() if user else "unknown"
    username = f"@{user.username}" if user and user.username else ""
    text = (update.message.text or "").replace("\n", " ")
    _msg_logger.info("[%s %s] [%s] %s", name, username, context_label, text)


async def _reply(update: Update, text: str) -> None:
    _msg_logger.info("[BOT] %s", text.replace("\n", " "))
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_message(update, "/start")
    await _reply(update, _HELP)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_message(update, "/status")
    await _reply(update, cmd_status())


async def decks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_message(update, "/decks")
    await _reply(update, cmd_decks())


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_message(update, "/run")
    args = context.args or []
    deck = args[0] if len(args) >= 1 else None
    subdeck = args[1] if len(args) >= 2 else None

    label = f"`{deck}::{subdeck}`" if subdeck else (f"`{deck}`" if deck else "all decks")
    await _reply(update, f"Generating cards for {label}... this may take a moment.")

    try:
        result = cmd_run(deck, subdeck)
    except Exception as exc:
        logger.exception("Error in /run")
        await _reply(update, f"Error: {exc}")
        return

    await _reply(update, result)


async def _handle_content(update: Update, context: ContextTypes.DEFAULT_TYPE, content: str, instruction: str) -> None:
    """Shared handler once document content is extracted."""
    user_id = update.effective_user.id
    if not instruction:
        _pending_documents[user_id] = content
        await _reply(update, "Got it! Which deck and how many cards?\nExample: _Add 10 cards to German deck_")
        return
    await _reply(update, "Got it, working on it...")
    try:
        intent = parse_message(instruction)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, cmd_from_content, content, intent)
    except Exception as exc:
        logger.exception("Error in document handler")
        result = f"Something went wrong: {exc}"
    await _reply(update, result)


async def _handle_code_content(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    filename: str, code: str, instruction: str
) -> None:
    """Handle a code file once we have both content and a deck instruction."""
    await _reply(update, "Got it, working on it...")
    try:
        intent = parse_message(instruction)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, cmd_from_content, code, intent, filename)
    except Exception as exc:
        logger.exception("Error processing code file")
        result = f"Something went wrong: {exc}"
    await _reply(update, result)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_message(update, "photo")
    await _reply(update, "Extracting content from image...")
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        loop = asyncio.get_event_loop()
        content = await loop.run_in_executor(None, extract_from_image, bytes(file_bytes), "image/jpeg")
    except Exception as exc:
        logger.exception("Image extraction failed")
        await _reply(update, f"Could not read image: {exc}")
        return
    caption = (update.message.caption or "").strip()
    await _handle_content(update, context, content, caption)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _log_message(update, "document")
    doc = update.message.document
    filename = doc.file_name or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    caption = (update.message.caption or "").strip()

    # ── Code file ──────────────────────────────────────────────────────────
    if ext in CODE_EXTENSIONS:
        await _reply(update, f"Reading `{filename}`...")
        try:
            file = await context.bot.get_file(doc.file_id)
            file_bytes = await file.download_as_bytearray()
            content = extract_from_code_file(bytes(file_bytes))
        except Exception as exc:
            logger.exception("Code file read failed")
            await _reply(update, f"Could not read file: {exc}")
            return

        # Store the file metadata alongside content so cmd_from_content can validate
        user_id = update.effective_user.id
        _pending_documents[user_id] = f"__code_file__|{filename}|{content}"
        if caption:
            # Process immediately if caption contains deck info
            await _handle_code_content(update, context, filename, content, caption)
        else:
            lang = language_from_extension(filename)
            await _reply(update,
                f"`{filename}` ready ({lang.upper() if lang else 'code'}, {len(content.splitlines())} lines).\n"
                f"Which deck and how many cards? e.g. _Add 10 cards to Software::C deck_"
            )
        return

    # ── PDF ────────────────────────────────────────────────────────────────
    if doc.mime_type == "application/pdf" or ext == ".pdf":
        await _reply(update, "Extracting content from PDF...")
        try:
            file = await context.bot.get_file(doc.file_id)
            file_bytes = await file.download_as_bytearray()
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(None, extract_from_pdf, bytes(file_bytes))
        except Exception as exc:
            logger.exception("PDF extraction failed")
            await _reply(update, f"Could not read PDF: {exc}")
            return
        await _handle_content(update, context, content, caption)
        return

    await _reply(update, f"Unsupported file type `{ext}`. Send a PDF, image, or code file ({', '.join(sorted(CODE_EXTENSIONS))}).")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from src.bot.nlu import ParsedIntent

    text = (update.message.text or "").strip().strip('"').strip("'").strip()
    user_id = update.effective_user.id
    _log_message(update, "chat")

    # --- Active deck creation wizard ---
    wizard = _pending_wizards.get(user_id)
    if wizard:
        await _reply(update, "Got it, working on it...")
        try:
            updated_wizard, reply, is_done = wizard_step(wizard, text)
            _pending_wizards[user_id] = updated_wizard
            await _reply(update, reply)
            if is_done:
                del _pending_wizards[user_id]
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, _run_wizard_generation, updated_wizard)
                await _reply(update, result)
        except WizardCancelled:
            _pending_wizards.pop(user_id, None)
            await _reply(update, "Cancelled. Nothing was created.")
        except Exception as exc:
            logger.exception("Error in wizard step")
            _pending_wizards.pop(user_id, None)
            await _reply(update, f"Something went wrong: {exc}")
        return

    # --- Check if user is confirming a pending delete ---
    pending = _pending_deletes.get(user_id)
    if pending and text == pending["token"]:
        del _pending_deletes[user_id]
        await _reply(update, cmd_delete_confirm(pending["deck"]))
        return

    if pending and text != pending["token"]:
        del _pending_deletes[user_id]
        await _reply(update, "Delete cancelled.")
        return

    # --- Pending document waiting for deck instruction ---
    pending_content = _pending_documents.pop(user_id, None)
    if pending_content is not None:
        if pending_content.startswith("__code_file__|"):
            _, filename, code = pending_content.split("|", 2)
            await _handle_code_content(update, context, filename, code, text)
        else:
            await _reply(update, "Got it, working on it...")
            try:
                intent = parse_message(text)
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, cmd_from_content, pending_content, intent)
            except Exception as exc:
                logger.exception("Error processing pending document")
                result = f"Something went wrong: {exc}"
            await _reply(update, result)
        return

    # --- URL detected in message ---
    url = detect_url(text)
    if url:
        instruction = text.replace(url, "").strip()
        await _reply(update, "Got it, fetching content from URL...")
        try:
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(None, extract_from_url, url)
        except Exception as exc:
            logger.exception("URL extraction failed")
            await _reply(update, f"Could not fetch URL: {exc}")
            return
        await _handle_content(update, context, content, instruction)
        return

    await _reply(update, "Got it, working on it...")

    try:
        # --- Batch: multiple instructions in one message ---
        if _pending_intents.get(user_id) is None:
            intents = parse_multi_message(text)
            if intents:
                logger.info("Batch request: %d intents", len(intents))
                await _reply(update, _batch_preview(intents))
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, cmd_batch, intents)
                await _reply(update, result)
                return

        # --- Resume a partial intent if the user is answering a follow-up question ---
        partial: ParsedIntent | None = _pending_intents.pop(user_id, None)
        if partial is not None:
            if not partial.deck:
                partial.deck = text
            elif not partial.topic:
                partial.topic = text
                partial.subdeck = text.split()[0].lower()
            intent = partial
            logger.info("Resumed partial intent: %s", intent)
        else:
            intent = parse_message(text)
            logger.info("Parsed intent: %s", intent)

        if intent.intent == "create_deck":
            if not intent.deck:
                _pending_intents[user_id] = intent
                await _reply(update, "What should the deck be called? (e.g. German::Colors)")
                return
            new_wizard, msg = wizard_start(intent)
            _pending_wizards[user_id] = new_wizard
            await _reply(update, msg)
            return

        if intent.intent == "delete":
            if not intent.deck:
                await _reply(update, "Which deck do you want to delete?")
                return
            full_deck_path = intent.deck
            if intent.subdeck and "::" not in intent.deck:
                full_deck_path = f"{intent.deck}::{intent.subdeck.capitalize()}"
            token, msg = cmd_delete_request(full_deck_path)
            if token is None:
                await _reply(update, msg)
                return
            _pending_deletes[user_id] = {"deck": full_deck_path, "token": token}
            await _reply(update, msg)
            return

        if intent.intent == "generate_cards":
            if not intent.deck:
                _pending_intents[user_id] = intent
                await _reply(update, "Which deck should I add these cards to? (e.g. German, Spanish)")
                return
            if not intent.topic:
                _pending_intents[user_id] = intent
                await _reply(update, "What topic should the cards cover?")
                return

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, cmd_chat, intent)
    except Exception as exc:
        logger.exception("Error in chat handler")
        await _reply(update, f"Something went wrong: {exc}")
        return

    await _reply(update, result)


def _media_report(media_types: list, audio_ok: int, audio_fail: int, img_ok: int, img_fail: int, img_error: str = "") -> str:
    lines = []
    if audio_ok or audio_fail:
        status = f"Audio: {audio_ok} added" + (f", {audio_fail} failed" if audio_fail else "")
        lines.append(status)
    if img_ok or img_fail:
        fail_note = f", {img_fail} failed — {img_error}" if img_fail and img_error else (f", {img_fail} failed" if img_fail else "")
        lines.append(f"Images: {img_ok} added{fail_note}")
    return ("\n".join(lines) + "\n") if lines else ""


def _batch_preview(intents: list) -> str:
    lines = ["*Processing:*"]
    for i, intent in enumerate(intents, 1):
        deck = intent.deck or "?"
        if intent.intent == "generate_cards":
            topic = intent.topic or "cards"
            lines.append(f"{i}. Add {intent.quantity} cards about _{topic}_ to *{deck}*")
        elif intent.intent == "create_deck":
            lines.append(f"{i}. Create deck *{deck}*")
        elif intent.intent == "delete":
            lines.append(f"{i}. Delete deck *{deck}*")
        elif intent.intent == "list_decks":
            lines.append(f"{i}. List all decks")
        elif intent.intent == "status":
            lines.append(f"{i}. Check Anki status")
        else:
            lines.append(f"{i}. {intent.intent}")
    return "\n".join(lines)


def _run_wizard_generation(wizard: DeckWizard) -> str:
    import os
    from pathlib import Path
    from src.ai.claude_provider import ClaudeProvider
    from src.ai.stem_provider import StemProvider
    from src.anki.connect_client import AnkiConnectClient
    from src.anki.exporter import cleanup_media_cache, export_deck
    from src.anki.sync_manager import SyncManager
    from src.bot.commands import fetch_media_for_cards, save_subdeck_config
    from src.bot.lang import deck_to_language
    from src.config.models import CardField, CardStyle, DeckConfig, DeckType, MediaType, SubdeckConfig

    media_types = [MediaType(m) for m in wizard.media if m in MediaType._value2member_map_]
    deck_type = wizard.deck_type
    card_style = wizard.card_style

    # Build field list appropriate to deck type
    if deck_type == DeckType.stem:
        fields = [CardField.question, CardField.answer, CardField.formula, CardField.example, CardField.difficulty]
    else:
        fields = [CardField.word, CardField.translation, CardField.example]
        if MediaType.audio in media_types:
            fields.append(CardField.audio)

    deck_name = wizard.deck
    subdeck_key = wizard.subdeck or wizard.deck.lower()

    deck_cfg = DeckConfig(deck=deck_name, language=deck_to_language(deck_name), subdecks={})
    subdeck_cfg = SubdeckConfig(
        topic=wizard.description or f"{subdeck_key} vocabulary",
        daily_limit=wizard.quantity,
        deck_type=deck_type,
        card_style=card_style,
        fields=fields,
        media=media_types,
        code_language=wizard.code_language or None,
    )

    client = AnkiConnectClient(url=os.environ.get("ANKI_CONNECT_URL", "http://localhost:8765"))
    use_ankiconnect = client.is_available()
    sync_manager = SyncManager(client) if use_ankiconnect else None
    media_cache_dir = Path(os.environ.get("MEDIA_CACHE_DIR", "media_cache"))
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))

    anki_deck_name = deck_cfg.subdeck_anki_name(subdeck_key)
    already_known = client.existing_words_in_deck(anki_deck_name) if use_ankiconnect else []

    # Generate cards using the appropriate provider
    if deck_type == DeckType.stem:
        cards = StemProvider().generate_cards(subdeck_cfg, card_style, already_known)
    else:
        cards = ClaudeProvider().generate_cards(subdeck_cfg, deck_cfg.language, already_known)

    # Skip media fetch for code cards (no audio/images needed)
    if MediaType.code in media_types:
        audio_ok = audio_fail = img_ok = img_fail = 0
        img_error = ""

    audio_ok, audio_fail, img_ok, img_fail, img_error = fetch_media_for_cards(
        cards, media_types, deck_cfg.language, media_cache_dir, deck_type=deck_type
    )
    media_report = _media_report(media_types, audio_ok, audio_fail, img_ok, img_fail, img_error)

    if use_ankiconnect:
        result = sync_manager.sync_subdeck(deck_cfg, subdeck_key, subdeck_cfg, cards)
        cleanup_media_cache(media_cache_dir)
        sync_manager.trigger_sync()

        save_subdeck_config(
            deck_name=deck_name,
            language=deck_cfg.language,
            subdeck_key=subdeck_key,
            topic=wizard.description,
            media=[m.value for m in media_types],
            daily_limit=wizard.quantity,
            fields=[f.value for f in fields],
            deck_type=deck_type.value,
            card_style=card_style.value,
            code_language=wizard.code_language or None,
        )

        style_label = f" ({card_style.value.replace('_', ' ')})" if card_style != CardStyle.standard else ""
        return (
            f"Done! Added to *{wizard.full_path}*{style_label}\n"
            f"Added: {result['added']} | Updated: {result['updated']} | Skipped: {result['skipped']}\n"
            f"{media_report}"
            f"AnkiWeb sync triggered."
        )
    else:
        apkg = export_deck(deck_cfg, subdeck_key, subdeck_cfg, cards, output_dir, media_cache_dir)
        cleanup_media_cache(media_cache_dir)
        return f"Anki is closed. Exported to `{apkg.name}` — import it manually.\n{media_report}"


def run_bot() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")

    request = HTTPXRequest(connect_timeout=30, read_timeout=30)
    app = Application.builder().token(token).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("decks", decks))
    app.add_handler(CommandHandler("run", run))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
