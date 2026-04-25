#!/bin/bash
# Run once on the VPS after cloning the repo.
# Usage: bash deploy/setup_server.sh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Anki Daily Bot — Server Setup ==="

# ── 1. System packages ──────────────────────────────────────────────────────
echo "[1/6] Installing system dependencies..."
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-dev \
  xvfb \
  libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xkb1 \
  libxkbcommon-x11-0 libegl1 libgl1 libglib2.0-0 \
  wget

# ── 2. Install Anki ─────────────────────────────────────────────────────────
echo "[2/6] Installing Anki..."
ANKI_VERSION="24.11"
ANKI_PKG="anki-${ANKI_VERSION}-linux-qt6.tar.zst"
ANKI_URL="https://github.com/ankitects/anki/releases/download/${ANKI_VERSION}/${ANKI_PKG}"

wget -q "$ANKI_URL" -O /tmp/${ANKI_PKG}
sudo apt install -y zstd
mkdir -p /tmp/anki-install
tar --use-compress-program=unzstd -xf /tmp/${ANKI_PKG} -C /tmp/anki-install --strip-components=1

sudo bash /tmp/anki-install/install.sh
rm -rf /tmp/anki-install /tmp/${ANKI_PKG}

# ── 3. Python virtualenv ─────────────────────────────────────────────────────
echo "[3/6] Creating Python virtualenv..."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

# ── 4. .env ──────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo "⚠️  Fill in your API keys in .env before starting the bot:"
  echo "   nano .env"
fi

# Ensure ANKI_CONNECT_URL points to localhost (Anki runs on the same VPS)
sed -i 's|^ANKI_CONNECT_URL=.*|ANKI_CONNECT_URL=http://localhost:8765|' .env

# ── 5. AnkiConnect ───────────────────────────────────────────────────────────
echo "[4/6] Installing AnkiConnect add-on..."
ANKI_ADDONS_DIR="/home/anki/.local/share/Anki2/addons21/AnkiConnect"
sudo -u anki mkdir -p "$ANKI_ADDONS_DIR"
sudo -u anki bash -c "cat > ${ANKI_ADDONS_DIR}/__init__.py" <<'PYEOF'
# Placeholder — AnkiConnect installs itself on first Anki launch.
# Install via Anki GUI: Tools → Add-ons → Get Add-ons → 2055492159
PYEOF

echo ""
echo "  → After first Anki launch, go to Tools → Add-ons → Get Add-ons"
echo "    and enter code: 2055492159, then restart Anki."

# ── 6. Systemd services ──────────────────────────────────────────────────────
echo "[5/6] Installing systemd services..."
CURRENT_USER=$(whoami)

sudo cp deploy/xvfb.service /etc/systemd/system/
sudo cp deploy/anki-headless.service /etc/systemd/system/
sed "s|/home/anki|/home/${CURRENT_USER}|g" deploy/anki-bot.service \
  | sed "s|User=anki|User=${CURRENT_USER}|g" \
  | sudo tee /etc/systemd/system/anki-bot.service > /dev/null

sudo systemctl daemon-reload
sudo systemctl enable xvfb anki-headless anki-bot

# ── 7. Logs dir ──────────────────────────────────────────────────────────────
echo "[6/6] Creating logs directory..."
mkdir -p logs

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Fill in API keys:          nano .env"
echo "  2. Start Xvfb + Anki:         sudo systemctl start xvfb anki-headless"
echo "  3. Sync your Anki collection: (see README — sync via AnkiWeb first)"
echo "  4. Install AnkiConnect:       Tools → Add-ons → 2055492159 → restart"
echo "  5. Start the bot:             sudo systemctl start anki-bot"
echo "  6. Check status:              sudo systemctl status anki-bot"
echo "  7. View logs:                 tail -f logs/bot.log"
