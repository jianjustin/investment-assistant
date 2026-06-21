from pathlib import Path


def test_frontend_defines_admin_navigation_and_language_switch():
    source = Path("web/src/main.ts").read_text(encoding="utf-8")

    assert "type Language" in source
    assert "type NavGroup" in source
    assert "navGroups" in source
    assert "languageToggle" in source
    assert "mobileMenuToggle" in source
    assert "sidebar" in source
    assert "中文" in source
    assert "English" in source


def test_frontend_keeps_dashboard_sections_addressable():
    source = Path("web/src/main.ts").read_text(encoding="utf-8")

    for section_id in [
        "overview",
        "market-signal",
        "service-runtime",
        "filing-storage",
        "raw-status",
    ]:
        assert section_id in source
