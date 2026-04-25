from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from src.bot.telegram_bot import run_bot

if __name__ == "__main__":
    run_bot()
