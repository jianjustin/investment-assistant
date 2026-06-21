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
tar --exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=web/node_modules --exclude=web/dist -C "$REPO_ROOT" -cf - . | tar -C "$APP" -xf -
chown -R jianjustin:jianjustin "$APP" /srv/investment-assistant

if [[ ! -f "$BASE/config/investment-assistant.json" ]]; then
  cp "$APP/config/investment-assistant.example.json" "$BASE/config/investment-assistant.json"
  chown jianjustin:jianjustin "$BASE/config/investment-assistant.json"
fi

python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$APP/requirements.txt"


if [[ -f "$BASE/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$BASE/.env"
  set +a
fi
if [[ -n "${INVESTMENT_ASSISTANT_DATABASE_URL:-}" ]]; then
  echo "Applying database migrations"
  "$VENV/bin/python" - <<'PY'
import os
from pathlib import Path
from investment_assistant.db import apply_migration, connect

app = Path(os.environ.get("HERMES_APP_DIR", "/opt/hermes-investment-assistant/app"))
with connect(os.environ["INVESTMENT_ASSISTANT_DATABASE_URL"]) as conn:
    for sql_path in sorted((app / "migrations").glob("*.sql")):
        apply_migration(conn, sql_path)
PY
fi

if command -v npm >/dev/null 2>&1 && [[ -f "$APP/web/package.json" ]]; then
  (cd "$APP/web" && if [[ -f package-lock.json ]]; then npm ci; else npm install; fi && npm run build)
  chown -R jianjustin:jianjustin "$APP/web"
fi

install -m 0644 "$APP/deploy/systemd/"*.service /etc/systemd/system/
install -m 0644 "$APP/deploy/systemd/"*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable investment-assistant-postgres.service hermes-investment-dashboard.service hermes-investment-daily.timer
