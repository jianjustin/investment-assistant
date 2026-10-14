"""uvicorn entry point. `python -m investment_assistant.api.server`."""
from __future__ import annotations

from investment_assistant.api import auth
from investment_assistant.api.app import create_app

app = create_app()


def main() -> None:
    from dotenv import load_dotenv
    import uvicorn

    load_dotenv()

    host = auth.resolve_bind_host()  # fail-closed：公网绑定无认证直接拒绝启动
    uvicorn.run(app, host=host, port=auth.PORT, log_level="warning")


if __name__ == "__main__":
    main()
