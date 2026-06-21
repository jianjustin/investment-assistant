import { Activity, createIcons, Database, FileText, RefreshCw, Server } from 'lucide'
import './styles.css'

type CommandStatus = {
  ok: boolean
  returncode?: number
  output?: string
}

type MarketSignal = {
  signal_date?: string
  market_status?: string
  score?: number
  distribution_days?: number
  vix?: number
  index_above_ma?: boolean
  notes?: string
  created_at?: string
}

type StatusPayload = {
  database?: {
    ok?: boolean
    error?: string
    latest_market_signal?: MarketSignal | null
  }
  filings?: {
    path?: string
    exists?: boolean
    file_count?: number
  }
  system?: {
    postgres_service?: CommandStatus
    dashboard_service?: CommandStatus
    timer?: CommandStatus
  }
}

type ViewState = {
  loading: boolean
  error: string | null
  data: StatusPayload | null
  refreshedAt: Date | null
}

const appElement = document.querySelector<HTMLDivElement>('#app')

if (!appElement) {
  throw new Error('Missing #app root')
}

const app = appElement

const state: ViewState = {
  loading: true,
  error: null,
  data: null,
  refreshedAt: null,
}

const statusTone: Record<string, string> = {
  green: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  yellow: 'bg-amber-100 text-amber-800 border-amber-200',
  red: 'bg-rose-100 text-rose-800 border-rose-200',
}

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function formatBool(value: unknown): string {
  if (value === true) return '是'
  if (value === false) return '否'
  return '未知'
}

function formatNumber(value: unknown, digits = 0): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'N/A'
}

function serviceLabel(service?: CommandStatus): string {
  if (!service) return '未知'
  if (service.ok) return 'active'
  return service.output?.trim() || 'inactive'
}

function serviceDot(service?: CommandStatus): string {
  if (!service) return 'bg-slate-300'
  return service.ok ? 'bg-emerald-500' : 'bg-rose-500'
}

function marketDot(signal?: MarketSignal | null): string {
  const status = signal?.market_status?.toLowerCase()
  if (status === 'green') return 'bg-emerald-500'
  if (status === 'red') return 'bg-rose-500'
  if (status === 'yellow') return 'bg-amber-500'
  return 'bg-slate-300'
}

function marketTone(signal?: MarketSignal | null): string {
  const status = signal?.market_status?.toLowerCase() ?? ''
  return statusTone[status] ?? 'bg-slate-100 text-slate-700 border-slate-200'
}

function compactTimerOutput(output?: string): string {
  const lines = (output ?? '').split('\n').map((line) => line.trim()).filter(Boolean)
  return lines.slice(0, 6).join('\n') || '暂无 timer 输出'
}

function metric(title: string, value: string, icon: string, detail = '', dotClass = 'bg-slate-300'): string {
  return `
    <section class="metric-panel min-h-[108px]">
      <div class="flex items-center justify-between gap-3">
        <div class="label">${escapeHtml(title)}</div>
        <i data-lucide="${icon}" class="h-4 w-4 text-muted" aria-hidden="true"></i>
      </div>
      <div class="mt-3 flex items-center gap-2">
        <span class="status-dot ${dotClass}" aria-hidden="true"></span>
        <div class="value truncate">${escapeHtml(value)}</div>
      </div>
      <div class="mt-2 min-h-5 truncate text-sm text-muted">${escapeHtml(detail)}</div>
    </section>
  `
}

function serviceRow(name: string, service?: CommandStatus): string {
  return `
    <div class="flex items-center justify-between gap-3 rounded-md border border-line px-3 py-2">
      <div class="flex min-w-0 items-center gap-2">
        <span class="status-dot ${serviceDot(service)}" aria-hidden="true"></span>
        <span class="truncate text-sm font-medium text-ink">${escapeHtml(name)}</span>
      </div>
      <span class="truncate text-sm text-muted">${escapeHtml(serviceLabel(service))}</span>
    </div>
  `
}

function renderStatus(data: StatusPayload): string {
  const signal = data.database?.latest_market_signal
  const dbOk = data.database?.ok === true
  const filingsOk = data.filings?.exists === true
  const postgres = data.system?.postgres_service
  const dashboard = data.system?.dashboard_service
  const timer = data.system?.timer
  const marketStatus = signal?.market_status ?? 'N/A'

  return `
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      ${metric('Database', dbOk ? 'connected' : 'error', 'database', data.database?.error ?? 'market_signals latest row', dbOk ? 'bg-emerald-500' : 'bg-rose-500')}
      ${metric('Market', marketStatus, 'activity', signal?.signal_date ?? 'no signal date', marketDot(signal))}
      ${metric('Filings', `${data.filings?.file_count ?? 0} files`, 'file-text', data.filings?.path ?? 'N/A', filingsOk ? 'bg-emerald-500' : 'bg-rose-500')}
      ${metric('Services', serviceLabel(dashboard), 'server', `Postgres: ${serviceLabel(postgres)}`, serviceDot(dashboard))}
    </div>

    <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <section class="section-panel">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="label">Latest Market Signal</div>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <span class="rounded-md border px-2.5 py-1 text-sm font-semibold ${marketTone(signal)}">${escapeHtml(marketStatus)}</span>
              <span class="text-sm text-muted">${escapeHtml(signal?.signal_date ?? 'No signal stored')}</span>
            </div>
          </div>
          <div class="grid grid-cols-3 gap-3 text-right">
            <div>
              <div class="label">Score</div>
              <div class="value">${formatNumber(signal?.score, 1)}</div>
            </div>
            <div>
              <div class="label">VIX</div>
              <div class="value">${formatNumber(signal?.vix, 2)}</div>
            </div>
            <div>
              <div class="label">Dist.</div>
              <div class="value">${formatNumber(signal?.distribution_days, 0)}</div>
            </div>
          </div>
        </div>
        <dl class="mt-5 grid grid-cols-1 gap-3 border-t border-line pt-4 sm:grid-cols-2">
          <div>
            <dt class="label">Index Above MA</dt>
            <dd class="mt-1 text-sm font-medium text-ink">${formatBool(signal?.index_above_ma)}</dd>
          </div>
          <div>
            <dt class="label">Created At</dt>
            <dd class="mt-1 text-sm font-medium text-ink">${escapeHtml(signal?.created_at ?? 'N/A')}</dd>
          </div>
        </dl>
        <div class="mt-4 rounded-md border border-line bg-panel p-3 text-sm leading-6 text-slate-700">${escapeHtml(signal?.notes ?? 'No notes')}</div>
      </section>

      <section class="section-panel">
        <div class="label">Service Runtime</div>
        <div class="mt-4 space-y-3">
          ${serviceRow('Dashboard', dashboard)}
          ${serviceRow('Postgres', postgres)}
          ${serviceRow('Daily Timer', timer)}
        </div>
        <pre class="mt-4 max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-slate-950 p-3 text-xs leading-5 text-slate-100">${escapeHtml(compactTimerOutput(timer?.output))}</pre>
      </section>
    </div>

    <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
      <section class="section-panel">
        <div class="label">Filing Storage</div>
        <dl class="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
          <div><dt class="text-muted">Exists</dt><dd class="mt-1 font-semibold text-ink">${formatBool(data.filings?.exists)}</dd></div>
          <div><dt class="text-muted">Files</dt><dd class="mt-1 font-semibold text-ink">${data.filings?.file_count ?? 0}</dd></div>
          <div><dt class="text-muted">Path</dt><dd class="mt-1 truncate font-semibold text-ink" title="${escapeHtml(data.filings?.path ?? '')}">${escapeHtml(data.filings?.path ?? 'N/A')}</dd></div>
        </dl>
      </section>

      <section class="section-panel">
        <div class="label">Raw Status Snapshot</div>
        <pre class="mt-4 max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-panel p-3 text-xs leading-5 text-slate-700">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      </section>
    </div>
  `
}

function render(): void {
  app.innerHTML = `
    <main class="mx-auto min-h-screen w-full max-w-7xl px-4 py-4 sm:px-6 lg:px-8">
      <header class="flex flex-col gap-3 border-b border-line pb-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 class="text-xl font-semibold text-ink sm:text-2xl">Hermes Investment Assistant</h1>
          <p class="mt-1 text-sm text-muted">服务看板 · 市场信号 · SEC filing 存储</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-sm text-muted">${state.refreshedAt ? `更新于 ${escapeHtml(state.refreshedAt.toLocaleString('zh-CN'))}` : '尚未更新'}</span>
          <button id="refresh" type="button" class="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink shadow-sm transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-60" ${state.loading ? 'disabled' : ''}>
            <i data-lucide="refresh-cw" class="h-4 w-4 ${state.loading ? 'animate-spin' : ''}" aria-hidden="true"></i>
            刷新
          </button>
        </div>
      </header>

      <div class="py-4">
        ${state.error ? `<div class="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">${escapeHtml(state.error)}</div>` : ''}
        ${state.loading && !state.data ? '<div class="section-panel text-sm text-muted">正在加载服务状态...</div>' : ''}
        ${state.data ? renderStatus(state.data) : ''}
      </div>
    </main>
  `

  document.querySelector<HTMLButtonElement>('#refresh')?.addEventListener('click', () => {
    void refreshStatus()
  })
  createIcons({ icons: { Activity, Database, FileText, RefreshCw, Server } })
}

async function refreshStatus(): Promise<void> {
  state.loading = true
  state.error = null
  render()

  try {
    const response = await fetch('/api/status', {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`)
    }
    state.data = (await response.json()) as StatusPayload
    state.refreshedAt = new Date()
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error)
  } finally {
    state.loading = false
    render()
  }
}

render()
void refreshStatus()
