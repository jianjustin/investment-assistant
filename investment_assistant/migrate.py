from __future__ import annotations

import json
import os
from pathlib import Path

from investment_assistant.db import apply_pending_migrations, connect

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def run(database_url: str, migrations_dir: str | Path | None = None) -> list[str]:
    target = Path(migrations_dir or DEFAULT_MIGRATIONS_DIR)
    with connect(database_url) as conn:
        return apply_pending_migrations(conn, target)


def main() -> None:
    url = os.environ.get("INVESTMENT_ASSISTANT_DATABASE_URL")
    if not url:
        raise SystemExit("INVESTMENT_ASSISTANT_DATABASE_URL is required to run migrations")
    applied = run(url)
    print(json.dumps({"applied": applied, "count": len(applied)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
