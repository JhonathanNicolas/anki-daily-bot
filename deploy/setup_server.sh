#!/bin/bash
# Run this once on the Hostgator VPS after cloning the repo.
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Anki Daily Bot — Server Setup ==="

# 1. Python
if ! command -v python3.10 &>/dev/null; then
  echo "Installing Python 3.10..."
  sudo apt update && sudo apt install -y python3.10 python3.10-venv python3.10-dev
fi

# 2. Virtual environment
echo "Creating virtualenv..."
python3.10 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 3. .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "⚠️  Fill in your API keys in .env before starting the bot:"
  echo "   nano .env"
fi

# 4. Systemd service
SERVICE_SRC="$PROJECT_DIR/deploy/anki-bot.service"
SERVICE_DST="/etc/systemd/system/anki-bot.service"
CURRENT_USER=$(whoami)
sed "s|YOUR_USER|$CURRENT_USER|g" "$SERVICE_SRC" | sudo tee "$SERVICE_DST" > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable anki-bot

echo ""
echo "=== Setup complete ==="
echo "1. Edit .env with your API keys"
echo "2. Start the bot:   sudo systemctl start anki-bot"
echo "3. Check status:    sudo systemctl status anki-bot"
echo "4. View logs:       tail -f logs/bot.log"
echo ""
echo "Daily card generation cron (07:00 every day):"
echo "   make schedule-install"
