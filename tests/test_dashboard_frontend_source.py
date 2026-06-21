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


def test_frontend_has_watchlist_management_menu_and_actions():
    navigation = Path("web/src/app/navigation.ts").read_text(encoding="utf-8")
    app = Path("web/src/app/app.ts").read_text(encoding="utf-8")
    state = Path("web/src/app/state.ts").read_text(encoding="utf-8")
    types = Path("web/src/app/types.ts").read_text(encoding="utf-8")
    messages = Path("web/src/i18n/messages.ts").read_text(encoding="utf-8")
    watchlist = Path("web/src/features/watchlist.ts").read_text(encoding="utf-8")

    assert "watchlistModule" in navigation
    assert "watchlist-list" in navigation
    assert "WatchlistPayload" in types
    assert "watchlistForm" in watchlist
    assert "data-watchlist-delete" in watchlist
    assert "/api/watchlist" in state
    assert "addWatchlistItem" in state
    assert "deleteWatchlistItem" in state
    assert "renderWatchlist" in app
    assert "标的池" in messages


def test_ticker_trends_has_clickable_metric_help_panel():
    app = Path("web/src/app/app.ts").read_text(encoding="utf-8")
    ticker_trends = Path("web/src/features/ticker-trends.ts").read_text(encoding="utf-8")
    types = Path("web/src/app/types.ts").read_text(encoding="utf-8")

    assert "tickerTrendHelpTopic" in types
    assert "[data-ticker-help]" in app
    assert "data-ticker-help" in ticker_trends
    assert "renderMetricHelpPanel" in ticker_trends
    assert "指标说明" in ticker_trends
    assert "指标逻辑" in ticker_trends
    assert "指标下枚举带来的意义" in ticker_trends


def test_frontend_has_strategy_center_scores_menu_and_table():
    navigation = Path("web/src/app/navigation.ts").read_text(encoding="utf-8")
    app = Path("web/src/app/app.ts").read_text(encoding="utf-8")
    state = Path("web/src/app/state.ts").read_text(encoding="utf-8")
    types = Path("web/src/app/types.ts").read_text(encoding="utf-8")
    messages = Path("web/src/i18n/messages.ts").read_text(encoding="utf-8")
    strategy_scores = Path("web/src/features/strategy-scores.ts").read_text(encoding="utf-8")

    assert "strategyModule" in navigation
    assert "strategy-scores" in navigation
    assert "strategy-runs" in navigation
    assert "/api/strategies/scores" in state
    assert "StrategyScoresPayload" in types
    assert "renderStrategyScores" in app
    assert "策略中心" in messages
    assert "renderStrategyScoreTable" in strategy_scores


def test_strategy_scores_have_manual_run_entrypoint_and_status():
    app = Path("web/src/app/app.ts").read_text(encoding="utf-8")
    state = Path("web/src/app/state.ts").read_text(encoding="utf-8")
    types = Path("web/src/app/types.ts").read_text(encoding="utf-8")
    messages = Path("web/src/i18n/messages.ts").read_text(encoding="utf-8")
    strategy_scores = Path("web/src/features/strategy-scores.ts").read_text(encoding="utf-8")

    assert "StrategyScoreRunResult" in types
    assert "strategyScoreRunInFlight" in state
    assert "strategyScoreRunResult" in state
    assert "/api/strategies/scores/run" in state
    assert "runStrategyScores" in state
    assert "strategyScoreRunButton" in strategy_scores
    assert "renderStrategyRunPanel" in strategy_scores
    assert "#strategyScoreRunButton" in app
    assert "runningStrategyScores" in messages


def test_strategy_scores_has_clickable_column_help_panel():
    app = Path("web/src/app/app.ts").read_text(encoding="utf-8")
    strategy_scores = Path("web/src/features/strategy-scores.ts").read_text(encoding="utf-8")
    types = Path("web/src/app/types.ts").read_text(encoding="utf-8")

    assert "StrategyScoreHelpTopic" in types
    assert "strategyScoreHelpTopic" in types
    assert "[data-strategy-help]" in app
    assert "data-strategy-help" in strategy_scores
    assert "renderStrategyScoreHelpPanel" in strategy_scores
    assert "字段说明" in strategy_scores
    assert "生成逻辑" in strategy_scores
    assert "字段值/枚举意义" in strategy_scores
    assert "下一步动作" in strategy_scores
