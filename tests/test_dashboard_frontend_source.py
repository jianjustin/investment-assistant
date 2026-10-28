from pathlib import Path

# Svelte 5 frontend structure assertions (C9 — replaced vanilla-TS)


def test_svelte_entrypoint_and_app_root():
    assert Path("web/src/main.ts").exists()
    assert Path("web/src/app.svelte").exists()
    main = Path("web/src/main.ts").read_text(encoding="utf-8")
    assert "mount" in main
    assert "app.svelte" in main


def test_svelte_route_views_exist():
    # v2.3 adds the Data menu after Review.
    routes = ["Today", "Instrument", "Review", "Data", "Tools", "Settings"]
    for r in routes:
        path = Path(f"web/src/routes/{r}.svelte")
        assert path.exists(), str(path)


def test_svelte_shared_lib_exists():
    expected = [
        "web/src/lib/api.ts",
        "web/src/lib/sse.ts",
        "web/src/lib/theme.ts",
        "web/src/lib/format.ts",
        "web/src/lib/router.ts",
    ]
    for f in expected:
        assert Path(f).exists(), f


def test_svelte_components_exist():
    expected = [
        "web/src/lib/components/AppShell.svelte",
        "web/src/lib/components/SideNav.svelte",
        "web/src/lib/components/Skeleton.svelte",
        "web/src/lib/components/Drawer.svelte",
        "web/src/lib/components/StatusPill.svelte",
    ]
    for f in expected:
        assert Path(f).exists(), f


def test_svelte_chart_wrappers_exist():
    expected = [
        "web/src/lib/charts/EChart.svelte",
        "web/src/lib/charts/CandleChart.svelte",
    ]
    for f in expected:
        assert Path(f).exists(), f


def test_api_client_exports_core_functions():
    api = Path("web/src/lib/api.ts").read_text(encoding="utf-8")
    for fn in ["getStatus", "getHealth", "getWatchlist", "getUSResearch",
               "syncUSResearch", "pollRun", "getFilingRecords"]:
        assert fn in api, f"missing: {fn}"


def test_app_hash_router_covers_all_zones():
    # v2.3 restores data; v2.4 adds the standalone #plan/<id> zone; v2.6 adds knowledge; v2.1 legacy zones still fall back to today.
    router = Path("web/src/lib/router.ts").read_text(encoding="utf-8")
    assert "export type Zone = 'today' | 'instrument' | 'review' | 'data' | 'knowledge' | 'tools' | 'settings' | 'plan'" in router
    assert "export const zones: Zone[] = [...workbenchZones, 'data', 'knowledge', 'tools', 'settings', 'plan']" in router
    for zone in ["technicals", "strategy", "trade"]:
        assert f"'{zone}'" not in router, f"legacy zone still routed: {zone}"
    app = Path("web/src/app.svelte").read_text(encoding="utf-8")
    assert "hashchange" in app
    assert "parseHash" in app


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


