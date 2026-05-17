# scripts/

Standalone validation scripts for quick testing without running the full pipeline.

| Script | Purpose | Run |
|--------|---------|-----|
| test_discord.py | Verify Discord webhook connectivity | `python scripts/test_discord.py` |
| test_market.py | Verify SPY/VIX market detection | `python scripts/test_market.py` |
| test_vcp.py | Verify technical signal computation | `python scripts/test_vcp.py [TICKER]` |

All scripts can be run from the project root after activating the venv.
