"""固定本地启动入口；配置从仓库 .env 读取，不回显凭据。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    env_path = root / ".env"
    if not env_path.is_file():
        raise SystemExit("缺少本地 .env，请先按 README 配置数据库。")
    load_dotenv(env_path)
    # 仅让本地调度开关以文件为准，保留其余显式环境配置的优先级。
    os.environ["SCHEDULER_ENABLED"] = dotenv_values(env_path).get("SCHEDULER_ENABLED") or "1"
    os.environ["HERMES_DASHBOARD_HOST"] = "127.0.0.1"
    sys.path.insert(0, str(root))

    from investment_assistant.api.server import main as run_server

    run_server()


if __name__ == "__main__":
    main()
