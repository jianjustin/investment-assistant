from pathlib import Path

# Svelte 5 frontend structure assertions (C9 — replaced vanilla-TS)


def test_svelte_entrypoint_and_app_root():
    assert Path("web/src/main.ts").exists()
    assert Path("web/src/app.svelte").exists()
    main = Path("web/src/main.ts").read_text(encoding="utf-8")
    assert "mount" in main
    assert "app.svelte" in main


def test_svelte_route_views_exist():
    # 5-layer IA: Tools/Data/Strategy/Trade/Settings (+ shared Placeholder).
    # Old Dashboard/Market/Hermes/System/Watchlist routes were retired.
    routes = ["Tools", "Data", "Strategy", "Trade", "Settings", "Placeholder"]
    for r in routes:
        path = Path(f"web/src/routes/{r}.svelte")
        assert path.exists(), str(path)


def test_svelte_shared_lib_exists():
    expected = [
        "web/src/lib/api.ts",
        "web/src/lib/sse.ts",
        "web/src/lib/theme.ts",
        "web/src/lib/format.ts",
        "web/src/lib/i18n.ts",
    ]
    for f in expected:
        assert Path(f).exists(), f


def test_svelte_components_exist():
    expected = [
        "web/src/lib/components/AppShell.svelte",
        "web/src/lib/components/SideNav.svelte",
        "web/src/lib/components/Skeleton.svelte",
        "web/src/lib/components/DataTable.svelte",
        "web/src/lib/components/Drawer.svelte",
        "web/src/lib/components/StatusPill.svelte",
    ]
    for f in expected:
        assert Path(f).exists(), f


def test_svelte_chart_wrappers_exist():
    expected = [
        "web/src/lib/charts/EChart.svelte",
        "web/src/lib/charts/LineChart.svelte",
        "web/src/lib/charts/CandleChart.svelte",
    ]
    for f in expected:
        assert Path(f).exists(), f


def test_api_client_exports_core_functions():
    api = Path("web/src/lib/api.ts").read_text(encoding="utf-8")
    for fn in ["getStatus", "getMarketSignals", "getMacroAnalysis", "getHermes",
               "getTickerTrends", "getStrategyScores", "getWatchlist",
               "runMacroLlm", "runDecisionEvidence", "pollRun"]:
        assert fn in api, f"missing: {fn}"


def test_app_svelte_has_five_zone_hash_router():
    app = Path("web/src/app.svelte").read_text(encoding="utf-8")
    for zone in ["tools", "data", "strategy", "trade", "settings"]:
        assert zone in app, f"missing zone: {zone}"
    assert "hashchange" in app


def test_design_tokens_css_exists():
    assert Path("web/src/styles/tokens.css").exists()
    tokens = Path("web/src/styles/tokens.css").read_text(encoding="utf-8")
    for var in ["--bg", "--surface", "--accent", "--up", "--down"]:
        assert var in tokens, f"missing token: {var}"


def test_dark_mode_token_override_exists():
    tokens = Path("web/src/styles/tokens.css").read_text(encoding="utf-8")
    assert "data-theme" in tokens


def test_sse_store_has_reconnect_logic():
    sse = Path("web/src/lib/sse.ts").read_text(encoding="utf-8")
    assert "EventSource" in sse
    assert "onerror" in sse
    assert "readable" in sse


def test_old_vanilla_ts_directories_are_deleted():
    for path in ["web/src/app", "web/src/features", "web/src/shared", "web/src/i18n", "web/src/styles.css"]:
        assert not Path(path).exists(), f"should be deleted: {path}"
