from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from investment_assistant.config import AssistantConfig, load_config
from investment_assistant.filings.service import download_configured_filings
from investment_assistant.tasks._harness import run_task


def _core(config: AssistantConfig) -> dict[str, Any]:
    result = download_configured_filings(config.watchlist, config.filings)
    filings_meta: list[dict[str, Any]] = []
    for path in result.get("files", []):
        parts = Path(path).parts
        ticker = parts[-3] if len(parts) >= 3 else None
        form = parts[-2] if len(parts) >= 2 else None
        filings_meta.append({"ticker": ticker, "form": form, "path": str(path)})
    return {
        "downloaded_count": result.get("downloaded_count", 0),
        "filings": filings_meta,
        "errors": result.get("errors", {}),
    }


def run(config: AssistantConfig) -> dict[str, Any]:
    return run_task("filings", lambda: _core(config), config=config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily 09:00 filings task")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()
    print(json.dumps(run(load_config(args.config)), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
