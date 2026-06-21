from pathlib import Path


def test_frontend_uses_modular_admin_platform_structure():
    expected_files = [
        "web/src/app/app.ts",
        "web/src/app/navigation.ts",
        "web/src/app/state.ts",
        "web/src/app/types.ts",
        "web/src/i18n/messages.ts",
        "web/src/shared/components.ts",
        "web/src/shared/format.ts",
        "web/src/shared/html.ts",
        "web/src/features/workbench.ts",
        "web/src/features/market.ts",
        "web/src/features/filings.ts",
        "web/src/features/services.ts",
        "web/src/features/operations.ts",
        "web/src/features/raw.ts",
    ]

    for filename in expected_files:
        assert Path(filename).exists(), filename

    main_source = Path("web/src/main.ts").read_text(encoding="utf-8")
    assert "./app/app" in main_source


def test_frontend_defines_routes_tables_operations_and_default_chinese():
    navigation = Path("web/src/app/navigation.ts").read_text(encoding="utf-8")
    messages = Path("web/src/i18n/messages.ts").read_text(encoding="utf-8")
    components = Path("web/src/shared/components.ts").read_text(encoding="utf-8")
    operations = Path("web/src/features/operations.ts").read_text(encoding="utf-8")

    assert "routeGroups" in navigation
    for route_id in ["workbench", "market", "filings", "services", "operations", "raw"]:
        assert route_id in navigation

    assert "defaultLanguage = 'zh'" in messages
    assert "renderTable" in components
    assert "requires_confirmation" in operations
