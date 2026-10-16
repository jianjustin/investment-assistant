import sys
from types import SimpleNamespace

from scripts import start_local


def test_local_start_uses_file_scheduler_setting_before_importing_server(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (tmp_path / ".env").write_text("SCHEDULER_ENABLED=1\n", encoding="utf-8")
    monkeypatch.setattr(start_local, "__file__", str(scripts_dir / "start_local.py"))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    monkeypatch.setenv("HERMES_DASHBOARD_HOST", "0.0.0.0")
    seen = {}

    def run_server():
        import os

        seen.update(scheduler=os.environ["SCHEDULER_ENABLED"], host=os.environ["HERMES_DASHBOARD_HOST"])

    monkeypatch.setitem(sys.modules, "investment_assistant.api.server", SimpleNamespace(main=run_server))
    start_local.main()
    assert seen == {"scheduler": "1", "host": "127.0.0.1"}


def test_local_start_respects_explicit_file_disable(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (tmp_path / ".env").write_text("SCHEDULER_ENABLED=0\n", encoding="utf-8")
    monkeypatch.setattr(start_local, "__file__", str(scripts_dir / "start_local.py"))
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCHEDULER_ENABLED", "1")
    monkeypatch.setenv("HERMES_DASHBOARD_HOST", "127.0.0.1")
    seen = []

    def run_server():
        import os

        seen.append(os.environ["SCHEDULER_ENABLED"])

    monkeypatch.setitem(sys.modules, "investment_assistant.api.server", SimpleNamespace(main=run_server))
    start_local.main()
    assert seen == ["0"]
