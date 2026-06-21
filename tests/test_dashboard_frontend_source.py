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


def test_market_signal_module_has_first_class_navigation_dashboard_and_manual_fetch():
    navigation = Path("web/src/app/navigation.ts").read_text(encoding="utf-8")
    market = Path("web/src/features/market.ts").read_text(encoding="utf-8")
    state = Path("web/src/app/state.ts").read_text(encoding="utf-8")

    assert "marketModule" in navigation
    assert "renderSignalChart" in market
    assert "renderSignalTable" in market
    assert "marketFetchForm" in market
    assert "/api/market/signals?limit=90" in state
    assert "/api/market/signals/trend?window=20" in state
    assert "/api/market/signals/fetch" in state


def test_market_signal_english_trend_copy_is_translated():
    messages = Path("web/src/i18n/messages.ts").read_text(encoding="utf-8")

    assert "Market signals are constructive" in messages
    assert "Market risk is elevated" in messages


def test_market_signal_is_parent_menu_with_second_level_routes():
    navigation = Path("web/src/app/navigation.ts").read_text(encoding="utf-8")
    app = Path("web/src/app/app.ts").read_text(encoding="utf-8")

    assert "market-signals" in navigation
    for route_id in ["market-overview", "market-trend", "market-list", "market-fetch"]:
        assert route_id in navigation
    assert "data-menu-toggle" in app
    assert "renderNavParent" in app
    assert "chevron-down" in app


def test_market_fetch_shows_in_progress_status_and_hermes_interpretation_component():
    market = Path("web/src/features/market.ts").read_text(encoding="utf-8")
    state = Path("web/src/app/state.ts").read_text(encoding="utf-8")
    types = Path("web/src/app/types.ts").read_text(encoding="utf-8")
    messages = Path("web/src/i18n/messages.ts").read_text(encoding="utf-8")

    assert "marketFetchInFlight" in state
    assert "fetchingMarketSignal" in market
    assert "renderFetchStatus" in market
    assert "HermesMarketInterpretationPayload" in types
    assert "/api/hermes/macro-analysis?window=30" in state
    assert "renderMacroAnalyst" in market
    assert "macroAnalyst" in messages


def test_hermes_module_has_first_level_menu_agents_and_ideas():
    navigation = Path("web/src/app/navigation.ts").read_text(encoding="utf-8")
    app = Path("web/src/app/app.ts").read_text(encoding="utf-8")
    state = Path("web/src/app/state.ts").read_text(encoding="utf-8")
    hermes = Path("web/src/features/hermes.ts").read_text(encoding="utf-8")
    messages = Path("web/src/i18n/messages.ts").read_text(encoding="utf-8")

    assert "hermesModule" in navigation
    for route_id in ["hermes-overview", "hermes-agents", "hermes-ideas"]:
        assert route_id in navigation
    assert "renderHermes" in app
    assert "/api/hermes" in state
    assert "/api/hermes/agents" in state
    assert "hermesAgentForm" in hermes
    assert "saveHermesAgent" in app
    assert "hermesCustomAgent" in messages


def test_frontend_reframes_market_signal_interpretation_as_macro_analyst():
    market = Path("web/src/features/market.ts").read_text(encoding="utf-8")
    state = Path("web/src/app/state.ts").read_text(encoding="utf-8")
    types = Path("web/src/app/types.ts").read_text(encoding="utf-8")
    hermes = Path("web/src/features/hermes.ts").read_text(encoding="utf-8")
    messages = Path("web/src/i18n/messages.ts").read_text(encoding="utf-8")

    assert "HermesMacroAnalysisPayload" in types
    assert "hermesMacroAnalysis" in state
    assert "/api/hermes/macro-analysis?window=30" in state
    assert "renderMacroAnalyst" in market
    assert "macroAnalyst" in messages
    assert "macro_analyst" in hermes
    assert "market_signal_interpretation" not in hermes


def test_frontend_can_run_macro_analyst_llm_interpretation_manually():
    app = Path("web/src/app/app.ts").read_text(encoding="utf-8")
    market = Path("web/src/features/market.ts").read_text(encoding="utf-8")
    state = Path("web/src/app/state.ts").read_text(encoding="utf-8")
    types = Path("web/src/app/types.ts").read_text(encoding="utf-8")
    messages = Path("web/src/i18n/messages.ts").read_text(encoding="utf-8")

    assert "runMacroAnalystLlm" in state
    assert "/api/hermes/macro-analysis/run" in state
    assert "macroLlmInFlight" in types
    assert "macroLlmResult" in types
    assert "macroLlmButton" in market
    assert "#macroLlmButton" in app
    assert "runningMacroLlm" in messages
