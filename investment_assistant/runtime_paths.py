from pathlib import Path


RUNTIME_BASE = Path("/opt/hermes-investment-assistant")
APP_DIR = RUNTIME_BASE / "app"
CONFIG_DIR = RUNTIME_BASE / "config"
DEFAULT_CONFIG_PATH = CONFIG_DIR / "investment-assistant.json"
SERVICE_ENV_PATH = RUNTIME_BASE / ".env"

LOG_DIR = RUNTIME_BASE / "logs"
RUN_LOG_PATH = LOG_DIR / "investment-assistant-runs.jsonl"
TASK_INDEX_PATH = RUNTIME_BASE / "data" / "task-index.json"

DEFAULT_VAULT_RO = Path("/srv/vault-ro")
DEFAULT_DRAFT_DIR = Path("/srv/vault-staging/06-收集箱/AI草稿")

DATA_BASE = Path("/srv/investment-assistant")
DEFAULT_FILINGS_DIR = DATA_BASE / "filings"
