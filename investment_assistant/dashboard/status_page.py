"""Self-contained monitoring status page (no build step required).

Served at GET /status. Polls /api/health and renders a grouped dashboard with
status dots, latency, and auto-refresh. Kept as a single inline HTML string so
it works without the Vite frontend being built.
"""
from __future__ import annotations

STATUS_PAGE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Hermes 投资助手 · 服务监控</title>
<style>
  :root {
    --bg: #0b0f14; --surface: #131a22; --surface-2: #1a232e; --border: #243140;
    --text: #e6edf3; --text-muted: #8b9aab; --accent: #2dd4bf;
    --up: #34d399; --degraded: #fbbf24; --down: #f87171; --unknown: #94a3b8;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: 14px; line-height: 1.5;
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 32px 20px 64px; }
  header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; margin-bottom: 24px; }
  h1 { font-size: 20px; margin: 0; font-weight: 600; }
  .sub { color: var(--text-muted); font-size: 13px; margin-top: 4px; }
  .banner {
    display: flex; align-items: center; gap: 14px; padding: 18px 22px; border-radius: 14px;
    background: var(--surface); border: 1px solid var(--border); margin-bottom: 28px;
  }
  .banner .big-dot { width: 16px; height: 16px; border-radius: 50%; flex: none; box-shadow: 0 0 0 4px rgba(255,255,255,0.04); }
  .banner-text { flex: 1; }
  .banner-title { font-size: 17px; font-weight: 600; }
  .banner-meta { color: var(--text-muted); font-size: 12px; margin-top: 2px; }
  .pills { display: flex; gap: 8px; flex-wrap: wrap; }
  .pill { font-size: 12px; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--border); color: var(--text-muted); }
  .pill b { color: var(--text); font-variant-numeric: tabular-nums; }
  .group { margin-bottom: 28px; }
  .group h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: var(--text-muted); margin: 0 0 12px; font-weight: 600; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
  .card {
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 14px 16px; display: flex; gap: 12px; align-items: flex-start;
  }
  .dot { width: 11px; height: 11px; border-radius: 50%; margin-top: 4px; flex: none; }
  .card-body { flex: 1; min-width: 0; }
  .card-top { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
  .card-name { font-weight: 600; }
  .latency { font-size: 12px; color: var(--text-muted); font-variant-numeric: tabular-nums; flex: none; }
  .detail { color: var(--text-muted); font-size: 12.5px; margin-top: 4px; word-break: break-word; }
  .badge { font-size: 11px; padding: 2px 8px; border-radius: 6px; font-weight: 600; }
  .s-up { background: rgba(52,211,153,.14); color: var(--up); }
  .s-degraded { background: rgba(251,191,36,.14); color: var(--degraded); }
  .s-down { background: rgba(248,113,113,.14); color: var(--down); }
  .s-unknown { background: rgba(148,163,184,.14); color: var(--unknown); }
  .bg-up { background: var(--up); } .bg-degraded { background: var(--degraded); }
  .bg-down { background: var(--down); } .bg-unknown { background: var(--unknown); }
  footer { color: var(--text-muted); font-size: 12px; margin-top: 32px; display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
  button {
    background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
    border-radius: 8px; padding: 6px 14px; font-size: 13px; cursor: pointer;
  }
  button:hover { border-color: var(--accent); }
  a { color: var(--accent); text-decoration: none; }
  .err { color: var(--down); }
  @media (max-width: 560px) { .cards { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Hermes 投资助手 · 服务监控</h1>
      <div class="sub">服务器配置 + 在线服务实时状态看板</div>
    </div>
    <button id="refresh">立即刷新</button>
  </header>

  <div class="banner" id="banner">
    <div class="big-dot bg-unknown" id="banner-dot"></div>
    <div class="banner-text">
      <div class="banner-title" id="banner-title">加载中…</div>
      <div class="banner-meta" id="banner-meta">正在采集服务状态</div>
    </div>
    <div class="pills" id="pills"></div>
  </div>

  <div id="groups"></div>

  <footer>
    <span>每 15 秒自动刷新</span>
    <span>·</span>
    <span id="updated">—</span>
    <span>·</span>
    <a href="/api/health">原始 JSON</a>
  </footer>
</div>

<script>
const LABELS = { up: "正常", degraded: "降级", down: "故障", unknown: "未知" };
const GROUPS = [
  { key: "infrastructure", title: "基础设施" },
  { key: "storage", title: "存储与调度" },
  { key: "online", title: "在线服务" },
];

function fmtLatency(ms) {
  if (ms === null || ms === undefined) return "";
  return ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : Math.round(ms) + " ms";
}

function render(data) {
  const overall = data.overall || "unknown";
  document.getElementById("banner-dot").className = "big-dot bg-" + overall;
  const titles = {
    up: "所有服务运行正常", degraded: "部分服务降级", down: "存在服务故障", unknown: "状态未知",
  };
  document.getElementById("banner-title").textContent = titles[overall] || titles.unknown;
  const s = data.summary || {};
  document.getElementById("banner-meta").textContent =
    `${data.checks.length} 项检查 · ${s.up || 0} 正常 / ${s.degraded || 0} 降级 / ${s.down || 0} 故障`;

  const pills = document.getElementById("pills");
  pills.innerHTML = "";
  [["up","正常"],["degraded","降级"],["down","故障"]].forEach(([k, label]) => {
    const el = document.createElement("span");
    el.className = "pill";
    el.innerHTML = `${label} <b>${s[k] || 0}</b>`;
    pills.appendChild(el);
  });

  const container = document.getElementById("groups");
  container.innerHTML = "";
  GROUPS.forEach(group => {
    const checks = data.checks.filter(c => c.category === group.key);
    if (!checks.length) return;
    const wrap = document.createElement("div");
    wrap.className = "group";
    const cards = checks.map(c => `
      <div class="card">
        <div class="dot bg-${c.status}"></div>
        <div class="card-body">
          <div class="card-top">
            <span class="card-name">${escapeHtml(c.name)}</span>
            <span class="latency">${fmtLatency(c.latency_ms)}</span>
          </div>
          <div class="detail">${escapeHtml(c.detail || "")}</div>
          <div style="margin-top:8px"><span class="badge s-${c.status}">${LABELS[c.status] || c.status}</span></div>
        </div>
      </div>`).join("");
    wrap.innerHTML = `<h2>${group.title}</h2><div class="cards">${cards}</div>`;
    container.appendChild(wrap);
  });

  const ts = data.generated_at ? new Date(data.generated_at).toLocaleString() : "—";
  document.getElementById("updated").textContent = "更新于 " + ts;
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;" }[c]));
}

async function load() {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    render(await res.json());
  } catch (e) {
    document.getElementById("banner-meta").innerHTML =
      '<span class="err">加载失败：' + escapeHtml(e.message) + "</span>";
  }
}

document.getElementById("refresh").addEventListener("click", load);
load();
setInterval(load, 15000);
</script>
</body>
</html>
"""
