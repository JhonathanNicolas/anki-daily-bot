# Anki Daily Automation - Project Context & Guidelines

## 🏗️ Project Overview
This project automates the daily creation and management of Anki decks and notes (cards). It processes raw data, handles media files (images, audio), formats them into specific Anki note types, and injects them into the user's Anki collection.

## 🛠️ Tech Stack & Tools
- **Language:** Python 3.11+
- **Primary Integration:** `anki-connect` (via the `requests` library) for live interaction with the Anki desktop client.
- **Alternative Integration:** `genanki` (for building offline `.apkg` packages if Anki is closed).
- **Dependency Management:** `Poetry` (or standard `pip` + `requirements.txt`).
- **Formatting & Linting:** `Ruff` (or `Black` + `Flake8`).
- **Testing:** `pytest`.

## 📂 Repository Structure
```text
anki-daily-bot/
├── src/
│   ├── __init__.py
│   ├── main.py              # Entry point for the daily script/cron job
│   ├── anki_client.py       # HTTP wrapper for AnkiConnect API calls
│   ├── deck_manager.py      # Logic for checking/creating decks and note types
│   ├── card_builder.py      # Combines data + HTML/CSS templates into notes
│   └── media_handler.py     # Image fetching, resizing, and Anki media import
├── templates/               # HTML/CSS files for Front and Back of Anki cards
├── data/                    # Temporary storage for daily input data (JSON/CSV)
├── media_cache/             # Local staging area for downloaded images/audio
├── tests/                   # Unit and integration tests (mocking AnkiConnect)
├── .env.example             # Configuration (e.g., ANKI_CONNECT_URL=http://localhost:8765)
├── pyproject.toml           # Project dependencies and linting rules
└── CLAUDE.md                # This file
```

## 💻 Common Commands
- **Install dependencies:** `poetry install`
- **Run the daily automation:** `poetry run python src/main.py`
- **Run test suite:** `poetry run pytest`
- **Format code:** `poetry run ruff format .`

## 🤖 AI Coding Guidelines (Strict Instructions)

When writing code for this repository, please adhere to the following rules:

### 1. AnkiConnect Interaction
- **Resilience:** AnkiConnect requires the Anki desktop app to be open. Always wrap connection attempts in `try/except` blocks with clear error messages telling the user to open Anki.
- **Idempotency (Crucial):** *Never blindly add cards.* Always use the `findNotes` action to search if a card with the same exact front/key already exists before using `addNote`. Prevent duplicate bloat.
- **Note Types:** Prefer creating a custom Model (Note Type) via `createModel` with specific fields (e.g., `Word`, `Translation`, `Image`) rather than using the default "Basic" type.

### 2. Media Handling
- **Filenames:** When saving images to Anki via `storeMediaFile`, always sanitize filenames and ideally append a short hash (e.g., `daily_vocab_apple_a1b2.jpg`) to prevent naming collisions in the user's global Anki media folder.
- **Cleanup:** Clear the local `media_cache/` directory after a successful sync to Anki.

### 3. Python Style
- **Type Hinting:** Strictly use Python type hints (`-> dict`, `list[str]`, etc.) for all function signatures and class methods.
- **Data Classes:** Use `dataclasses` or `pydantic` models to represent the Card data structure before passing it to the Anki client.
- **Styling:** Keep HTML/CSS out of the Python logic. Read templates from the `templates/` directory and inject data into them.
```
***