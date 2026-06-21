#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="/opt/hermes-investment-assistant"
APP="$BASE/app"
VENV="$BASE/.venv"

install -d -o jianjustin -g jianjustin "$BASE" "$BASE/config" "$BASE/logs" "$BASE/data"
install -d -o jianjustin -g jianjustin /srv/investment-assistant/filings
install -d /var/lib/investment-assistant/postgres

rm -rf "$APP"
mkdir -p "$APP"
tar --exclude=.git --exclude=.venv --exclude=__pycache__ -C "$REPO_ROOT" -cf - . | tar -C "$APP" -xf -
chown -R jianjustin:jianjustin "$APP" /srv/investment-assistant

if [[ ! -f "$BASE/config/investment-assistant.json" ]]; then
  cp "$APP/config/investment-assistant.example.json" "$BASE/config/investment-assistant.json"
  chown jianjustin:jianjustin "$BASE/config/investment-assistant.json"
fi

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$APP/requirements.txt"

install -m 0644 "$APP/deploy/systemd/"*.service /etc/systemd/system/
install -m 0644 "$APP/deploy/systemd/"*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable investment-assistant-postgres.service hermes-investment-dashboard.service hermes-investment-daily.timer
