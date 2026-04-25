# Anki Daily Bot

AI-powered Anki flashcard generator controlled via Telegram. Generates language and STEM cards using Claude and syncs them directly into Anki via AnkiConnect.

## Requirements

- Python 3.10+
- [Anki](https://apps.ankiweb.net/) desktop app
- [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on (code: `2055492159`)
- Anthropic API key
- Telegram bot token (from [@BotFather](https://t.me/BotFather))
- Unsplash API key (optional, for image cards)

### Installing AnkiConnect

1. Open Anki
2. Go to **Tools → Add-ons → Get Add-ons**
3. Enter code **`2055492159`** → OK
4. Restart Anki

AnkiConnect exposes a local API on `http://localhost:8765`. The bot requires Anki to be running and AnkiConnect active to sync cards directly. If Anki is closed, the bot falls back to exporting `.apkg` files to `output/` for manual import.

## Setup

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd anki-daily-bot

# 2. Install dependencies
make install

# 3. Configure environment
cp .env.example .env
# Edit .env and fill in your keys
```

### .env variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key from console.anthropic.com |
| `TELEGRAM_BOT_TOKEN` | Token from @BotFather |
| `UNSPLASH_ACCESS_KEY` | Unsplash API key (optional, needed for image cards) |
| `ANKI_CONNECT_URL` | Default: `http://localhost:8765` |
| `OUTPUT_DIR` | Where `.apkg` files are saved (default: `output`) |
| `MEDIA_CACHE_DIR` | Temporary media staging dir (default: `media_cache`) |

## Running

```bash
# Start the Telegram bot (stays running)
make bot

# One-shot: generate cards for all configured decks
make run

# Dry run: print generated cards without touching Anki
make run-dry

# Run a specific deck or subdeck
.venv/bin/python -m src.main --deck decks/german.yaml --subdeck farben
```

## Telegram Usage

Just message the bot in plain language:

- `Add 10 weather words to my German deck`
- `Create a deck DSP::Filters`
- `5 Spanish food words with images`
- `Delete my German::Zahlen deck`

**Commands:**
- `/status` — check if Anki is running
- `/decks` — list all decks with IDs
- `/run` — generate & sync all decks
- `/run <deck> <subdeck>` — sync one subdeck

## Deck Configuration

Decks are defined in `decks/*.yaml`. They are auto-created/updated when you use the bot's deck creation wizard. Example:

```yaml
deck: German
language: German
ai_provider: claude
subdecks:
  farben:
    topic: Colors in German
    daily_limit: 10
    deck_type: language
    card_style: standard
    fields: [Word, Translation, Example, Audio]
    media: [audio, image]
```

### Deck types

- `language` — vocabulary cards: Word, Translation, Example
- `stem` — STEM cards: Question, Answer, Formula (LaTeX), Difficulty

### Card styles

- `standard` — front / back
- `reverse` — bidirectional (language)
- `cloze` — fill-in-the-blank
- `multiple_choice` — question with 4 options (STEM)

## Running tests

```bash
make test
```
