#!/usr/bin/env bash
# Installation du TCG Monitor sur un serveur Ubuntu (Oracle Cloud Always Free)
# Usage : bash install_server.sh https://github.com/TON-PSEUDO/tcg-monitor.git
set -euo pipefail
REPO_URL="${1:?Usage : bash install_server.sh <adresse-du-depot-github>}"
APP_DIR="$HOME/tcg-monitor"

sudo apt-get update -y
sudo apt-get install -y python3 python3-venv git

[ -d "$APP_DIR/.git" ] || git clone "$REPO_URL" "$APP_DIR"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  read -rp "URL du webhook Discord : " WH
  read -rp "eBay Client ID (Entrée pour passer) : " EID
  read -rsp "eBay Client Secret (Entrée pour passer) : " ESEC; echo
  printf 'DISCORD_WEBHOOK_URL=%s\nEBAY_CLIENT_ID=%s\nEBAY_CLIENT_SECRET=%s\n' "$WH" "$EID" "$ESEC" > .env
  chmod 600 .env
fi

sudo tee /etc/systemd/system/tcg-monitor.service > /dev/null << UNIT
[Unit]
Description=TCG Monitor (Pokemon & One Piece)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -u monitor.py --loop 30
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

# Récupère tes modifs de config.yaml faites sur GitHub, toutes les 2 minutes
( crontab -l 2>/dev/null | grep -v tcg-monitor-pull || true
  echo "*/2 * * * * cd $APP_DIR && git pull -q # tcg-monitor-pull" ) | crontab -

sudo systemctl daemon-reload
sudo systemctl enable --now tcg-monitor
echo ""
echo "✅ TCG Monitor installé et lancé."
echo "   Voir ce qu'il fait en direct : journalctl -u tcg-monitor -f"
echo "   Le redémarrer : sudo systemctl restart tcg-monitor"
