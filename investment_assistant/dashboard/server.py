"""Backwards-compat entry point. Implementation moved to investment_assistant.api."""
from investment_assistant.api import static_files
from investment_assistant.api.server import Handler, main  # noqa: F401
from investment_assistant.api.router import dispatch as _dispatch
from investment_assistant.api import auth

# Re-export for tests that monkeypatch these
STATIC_DIR = static_files.STATIC_DIR


def api_response_for_path(path):
    return _dispatch("GET", path, None)


def api_post_response_for_path(path, payload):
    return _dispatch("POST", path, payload)


def api_delete_response_for_path(path):
    return _dispatch("DELETE", path, None)


def static_response_for_path(path):
    return static_files.static_response_for_path(path)


if __name__ == "__main__":
    main()
