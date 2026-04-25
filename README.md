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

## Architecture (fully on VPS)

```
VPS (Hostinger — Ubuntu 22.04)
──────────────────────────────────────────────
Xvfb :99  (virtual display)
  └── Anki (headless) + AnkiConnect :8765
        ↕ AnkiWeb  (collection sync)
Telegram Bot → localhost:8765
```

Anki runs headlessly on the VPS using a virtual display (Xvfb). AnkiConnect listens on `localhost:8765`. Your collection is kept in sync with AnkiWeb — no personal computer needed.

---

## Deploying to a VPS (Hostinger / Ubuntu 22.04 LTS)

### 1. Clone the repo on the VPS

```bash
sudo apt install -y git
git clone git@github.com:JhonathanNicolas/anki-daily-bot.git
cd anki-daily-bot
```

### 2. Run the setup script

```bash
bash deploy/setup_server.sh
```

This installs: Python 3.12, Xvfb, Anki, all Python dependencies, and registers three systemd services (`xvfb`, `anki-headless`, `anki-bot`).

### 3. Fill in your API keys

```bash
nano .env
```

| Key | Where to get it |
|-----|----------------|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `TELEGRAM_BOT_TOKEN` | @BotFather on Telegram |
| `UNSPLASH_ACCESS_KEY` | unsplash.com/developers (optional) |
| `ANKI_CONNECT_URL` | leave as `http://localhost:8765` |

### 4. Start Anki headlessly and install AnkiConnect

```bash
sudo systemctl start xvfb anki-headless
```

Anki is now running in the background. Connect to it via VNC or run a one-time setup command to install AnkiConnect:

```bash
# Install AnkiConnect add-on (code 2055492160)
DISPLAY=:99 anki -b ~/.local/share/Anki2 &
sleep 10
# Then from another terminal, install the add-on via AnkiConnect bootstrap:
curl -s http://localhost:8765 || echo "AnkiConnect not yet active — install via GUI"
```

Alternatively, use a VNC viewer to connect to the VPS display `:99` and install the add-on manually:
- **Tools → Add-ons → Get Add-ons → `2055492159`** → OK → restart Anki

### 5. Sync your existing Anki collection

On your **desktop**, make sure you've synced your collection to AnkiWeb first:
- Anki desktop → **Sync** button

Then on the **VPS**, log into AnkiWeb inside the headless Anki to pull your collection:
```bash
# Via VNC or a one-time DISPLAY command
DISPLAY=:99 anki &
# Then sync via Tools → Sync (log in with your AnkiWeb account)
```

### 6. Start the bot

```bash
sudo systemctl start anki-bot
sudo systemctl status anki-bot

# Live logs
tail -f logs/bot.log
```

### 7. Updating the bot

```bash
git pull
.venv/bin/pip install -r requirements.txt  # only if dependencies changed
sudo systemctl restart anki-bot
```

### Service overview

| Service | Role |
|---------|------|
| `xvfb` | Virtual display `:99` — required by Anki's Qt UI |
| `anki-headless` | Anki desktop running headlessly + AnkiConnect |
| `anki-bot` | The Telegram bot |

All three start automatically on server reboot.

## Roadmap

### Security
- [ ] **User authentication** — whitelist of allowed Telegram user IDs; reject all other users
- [ ] **Rate limiting** — per-user request throttling to prevent API abuse

### Input sources
- [ ] **PDF support** — upload a PDF and generate cards from its content
- [ ] **Plain text / paste** — send raw text or notes and let AI extract card candidates
- [ ] **Voice messages** — transcribe Telegram voice notes and turn them into cards
- [ ] **Image / OCR** — photograph a page or whiteboard and generate cards from it
- [ ] **Web URL** — paste a URL and generate cards from the article content

### Card generation
- [ ] **Multiple AI providers** — support OpenAI GPT-4o and Google Gemini alongside Claude
- [ ] **Adaptive difficulty** — use Anki review history to avoid re-generating mastered cards
- [ ] **Bulk generation** — generate a full deck from a syllabus or topic list in one command
- [ ] **Card editing** — review and edit AI-generated cards in Telegram before syncing

### Automation
- [ ] **Scheduled daily runs** — per-deck cron schedule configured via bot commands
- [ ] **Review reminders** — Telegram notification when cards are due for review
- [ ] **Progress reports** — weekly summary of cards added, reviewed, and retention rate

### Export & integrations
- [ ] **Quizlet export** — export decks to Quizlet format
- [ ] **CSV export** — simple spreadsheet export for any deck
- [ ] **Notion / Obsidian sync** — mirror card content to a knowledge base
