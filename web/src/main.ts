import {
  Activity,
  Braces,
  Clock3,
  createIcons,
  Database,
  FileText,
  Gauge,
  HardDrive,
  Languages,
  LayoutDashboard,
  Menu,
  RefreshCw,
  Server,
  X,
} from 'lucide'
import './styles.css'

type Language = 'zh' | 'en'

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

type NavItem = {
  id: string
  labelKey: CopyKey
  descriptionKey: CopyKey
  icon: string
}

type NavGroup = {
  labelKey: CopyKey
  children: NavItem[]
}

type ViewState = {
  loading: boolean
  error: string | null
  data: StatusPayload | null
  refreshedAt: Date | null
  language: Language
  navOpen: boolean
}

const copy = {
  zh: {
    appName: 'Hermes 投资助手',
    appSubtitle: '后台系统 · 服务监控 · 市场信号 · SEC filing 存储',
    sidebarProduct: 'Hermes Admin',
    sidebarCaption: '投资助手后台',
    navDashboard: '看板',
    navData: '数据与服务',
    overview: '总览',
    overviewDesc: '数据库、市场、文件与服务状态',
    marketSignal: '市场信号',
    marketSignalDesc: '最新市场状态与关键指标',
    serviceRuntime: '服务运行',
    serviceRuntimeDesc: 'systemd 服务和定时器',
    filingStorage: 'Filing 存储',
    filingStorageDesc: 'SEC 文件目录与数量',
    rawStatus: '原始状态',
    rawStatusDesc: 'API 返回的完整 JSON',
    refresh: '刷新',
    languageToggle: 'English',
    languageLabel: '语言',
    mobileMenuToggle: '菜单',
    closeMenu: '关闭菜单',
    lastUpdated: '更新于',
    notUpdated: '尚未更新',
    loading: '正在加载服务状态...',
    connected: '已连接',
    error: '异常',
    database: '数据库',
    market: '市场',
    filings: 'Filings',
    services: '服务',
    latestMarketSignal: '最新市场信号',
    noSignalStored: '暂无信号记录',
    score: '评分',
    vix: 'VIX',
    distribution: '分布日',
    indexAboveMa: '指数高于均线',
    createdAt: '创建时间',
    noNotes: '暂无备注',
    dashboard: 'Dashboard',
    postgres: 'Postgres',
    dailyTimer: '日跑定时器',
    timerEmpty: '暂无 timer 输出',
    exists: '存在',
    files: '文件数',
    path: '路径',
    yes: '是',
    no: '否',
    unknown: '未知',
    rawSnapshot: '原始状态快照',
    latestRow: 'market_signals 最新记录',
    noSignalDate: '暂无信号日期',
    postgresLabel: 'Postgres',
    green: '绿色',
    yellow: '黄色',
    red: '红色',
  },
  en: {
    appName: 'Hermes Investment Assistant',
    appSubtitle: 'Admin system · service monitoring · market signals · SEC filing storage',
    sidebarProduct: 'Hermes Admin',
    sidebarCaption: 'Investment assistant console',
    navDashboard: 'Dashboard',
    navData: 'Data & Services',
    overview: 'Overview',
    overviewDesc: 'Database, market, filing, and service status',
    marketSignal: 'Market Signal',
    marketSignalDesc: 'Latest market state and key indicators',
    serviceRuntime: 'Service Runtime',
    serviceRuntimeDesc: 'systemd services and timers',
    filingStorage: 'Filing Storage',
    filingStorageDesc: 'SEC filing directory and count',
    rawStatus: 'Raw Status',
    rawStatusDesc: 'Complete JSON returned by the API',
    refresh: 'Refresh',
    languageToggle: '中文',
    languageLabel: 'Language',
    mobileMenuToggle: 'Menu',
    closeMenu: 'Close menu',
    lastUpdated: 'Updated at',
    notUpdated: 'Not updated yet',
    loading: 'Loading service status...',
    connected: 'connected',
    error: 'error',
    database: 'Database',
    market: 'Market',
    filings: 'Filings',
    services: 'Services',
    latestMarketSignal: 'Latest Market Signal',
    noSignalStored: 'No signal stored',
    score: 'Score',
    vix: 'VIX',
    distribution: 'Dist.',
    indexAboveMa: 'Index Above MA',
    createdAt: 'Created At',
    noNotes: 'No notes',
    dashboard: 'Dashboard',
    postgres: 'Postgres',
    dailyTimer: 'Daily Timer',
    timerEmpty: 'No timer output',
    exists: 'Exists',
    files: 'Files',
    path: 'Path',
    yes: 'Yes',
    no: 'No',
    unknown: 'Unknown',
    rawSnapshot: 'Raw Status Snapshot',
    latestRow: 'latest market_signals row',
    noSignalDate: 'no signal date',
    postgresLabel: 'Postgres',
    green: 'green',
    yellow: 'yellow',
    red: 'red',
  },
} as const

type CopyKey = keyof typeof copy.zh

const navGroups: NavGroup[] = [
  {
    labelKey: 'navDashboard',
    children: [
      { id: 'overview', labelKey: 'overview', descriptionKey: 'overviewDesc', icon: 'layout-dashboard' },
      { id: 'market-signal', labelKey: 'marketSignal', descriptionKey: 'marketSignalDesc', icon: 'activity' },
    ],
  },
  {
    labelKey: 'navData',
    children: [
      { id: 'service-runtime', labelKey: 'serviceRuntime', descriptionKey: 'serviceRuntimeDesc', icon: 'server' },
      { id: 'filing-storage', labelKey: 'filingStorage', descriptionKey: 'filingStorageDesc', icon: 'hard-drive' },
      { id: 'raw-status', labelKey: 'rawStatus', descriptionKey: 'rawStatusDesc', icon: 'braces' },
    ],
  },
]

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
  language: 'zh',
  navOpen: false,
}

const statusTone: Record<string, string> = {
  green: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  yellow: 'bg-amber-100 text-amber-800 border-amber-200',
  red: 'bg-rose-100 text-rose-800 border-rose-200',
}

function t(key: CopyKey): string {
  return copy[state.language][key]
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
  if (value === true) return t('yes')
  if (value === false) return t('no')
  return t('unknown')
}

function formatNumber(value: unknown, digits = 0): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : 'N/A'
}

function serviceLabel(service?: CommandStatus): string {
  if (!service) return t('unknown')
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

function marketLabel(signal?: MarketSignal | null): string {
  const status = signal?.market_status?.toLowerCase()
  if (status === 'green') return t('green')
  if (status === 'yellow') return t('yellow')
  if (status === 'red') return t('red')
  return signal?.market_status ?? 'N/A'
}

function compactTimerOutput(output?: string): string {
  const lines = (output ?? '').split('\n').map((line) => line.trim()).filter(Boolean)
  return lines.slice(0, 6).join('\n') || t('timerEmpty')
}

function updatedText(): string {
  if (!state.refreshedAt) return t('notUpdated')
  return `${t('lastUpdated')} ${state.refreshedAt.toLocaleString(state.language === 'zh' ? 'zh-CN' : 'en-US')}`
}

function metric(title: string, value: string, icon: string, detail = '', dotClass = 'bg-slate-300'): string {
  return `
    <section class="metric-panel min-h-[112px]">
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

function renderSidebar(): string {
  return `
    <aside id="sidebar" class="fixed inset-y-0 left-0 z-40 flex w-72 -translate-x-full flex-col border-r border-line bg-white transition-transform duration-200 lg:static lg:translate-x-0 ${state.navOpen ? 'translate-x-0' : ''}">
      <div class="flex h-16 items-center justify-between border-b border-line px-4">
        <div class="min-w-0">
          <div class="truncate text-sm font-semibold text-ink">${escapeHtml(t('sidebarProduct'))}</div>
          <div class="truncate text-xs text-muted">${escapeHtml(t('sidebarCaption'))}</div>
        </div>
        <button id="closeMobileMenu" type="button" class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-line text-muted hover:text-ink lg:hidden" aria-label="${escapeHtml(t('closeMenu'))}">
          <i data-lucide="x" class="h-4 w-4" aria-hidden="true"></i>
        </button>
      </div>
      <nav class="flex-1 overflow-y-auto px-3 py-4" aria-label="${escapeHtml(t('mobileMenuToggle'))}">
        ${navGroups.map(renderNavGroup).join('')}
      </nav>
      <div class="border-t border-line p-3">
        <button id="languageToggle" type="button" class="inline-flex w-full items-center justify-between rounded-md border border-line bg-panel px-3 py-2 text-sm font-medium text-ink hover:border-accent hover:text-accent">
          <span class="inline-flex items-center gap-2"><i data-lucide="languages" class="h-4 w-4" aria-hidden="true"></i>${escapeHtml(t('languageLabel'))}</span>
          <span>${escapeHtml(t('languageToggle'))}</span>
        </button>
      </div>
    </aside>
    ${state.navOpen ? '<button id="navBackdrop" class="fixed inset-0 z-30 bg-slate-950/30 lg:hidden" aria-label="Close navigation"></button>' : ''}
  `
}

function renderNavGroup(group: NavGroup): string {
  return `
    <div class="mb-5">
      <div class="px-3 text-xs font-semibold uppercase tracking-normal text-muted">${escapeHtml(t(group.labelKey))}</div>
      <div class="mt-2 space-y-1">
        ${group.children.map(renderNavItem).join('')}
      </div>
    </div>
  `
}

function renderNavItem(item: NavItem): string {
  return `
    <a href="#${item.id}" class="group flex items-start gap-3 rounded-md px-3 py-2 text-sm text-slate-700 hover:bg-panel hover:text-ink" data-nav-link>
      <i data-lucide="${item.icon}" class="mt-0.5 h-4 w-4 shrink-0 text-muted group-hover:text-accent" aria-hidden="true"></i>
      <span class="min-w-0">
        <span class="block truncate font-medium">${escapeHtml(t(item.labelKey))}</span>
        <span class="mt-0.5 block truncate text-xs text-muted">${escapeHtml(t(item.descriptionKey))}</span>
      </span>
    </a>
  `
}

function renderStatus(data: StatusPayload): string {
  const signal = data.database?.latest_market_signal
  const dbOk = data.database?.ok === true
  const filingsOk = data.filings?.exists === true
  const postgres = data.system?.postgres_service
  const dashboard = data.system?.dashboard_service
  const timer = data.system?.timer
  const currentMarketLabel = marketLabel(signal)

  return `
    <section id="overview" class="scroll-mt-5">
      <div class="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div class="label">${escapeHtml(t('overview'))}</div>
          <h2 class="mt-1 text-lg font-semibold text-ink">${escapeHtml(t('overviewDesc'))}</h2>
        </div>
      </div>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        ${metric(t('database'), dbOk ? t('connected') : t('error'), 'database', data.database?.error ?? t('latestRow'), dbOk ? 'bg-emerald-500' : 'bg-rose-500')}
        ${metric(t('market'), currentMarketLabel, 'activity', signal?.signal_date ?? t('noSignalDate'), marketDot(signal))}
        ${metric(t('filings'), `${data.filings?.file_count ?? 0} ${t('files')}`, 'file-text', data.filings?.path ?? 'N/A', filingsOk ? 'bg-emerald-500' : 'bg-rose-500')}
        ${metric(t('services'), serviceLabel(dashboard), 'server', `${t('postgresLabel')}: ${serviceLabel(postgres)}`, serviceDot(dashboard))}
      </div>
    </section>

    <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      <section id="market-signal" class="section-panel scroll-mt-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div class="label">${escapeHtml(t('latestMarketSignal'))}</div>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <span class="rounded-md border px-2.5 py-1 text-sm font-semibold ${marketTone(signal)}">${escapeHtml(currentMarketLabel)}</span>
              <span class="text-sm text-muted">${escapeHtml(signal?.signal_date ?? t('noSignalStored'))}</span>
            </div>
          </div>
          <div class="grid grid-cols-3 gap-3 text-right">
            <div>
              <div class="label">${escapeHtml(t('score'))}</div>
              <div class="value">${formatNumber(signal?.score, 1)}</div>
            </div>
            <div>
              <div class="label">${escapeHtml(t('vix'))}</div>
              <div class="value">${formatNumber(signal?.vix, 2)}</div>
            </div>
            <div>
              <div class="label">${escapeHtml(t('distribution'))}</div>
              <div class="value">${formatNumber(signal?.distribution_days, 0)}</div>
            </div>
          </div>
        </div>
        <dl class="mt-5 grid grid-cols-1 gap-3 border-t border-line pt-4 sm:grid-cols-2">
          <div>
            <dt class="label">${escapeHtml(t('indexAboveMa'))}</dt>
            <dd class="mt-1 text-sm font-medium text-ink">${formatBool(signal?.index_above_ma)}</dd>
          </div>
          <div>
            <dt class="label">${escapeHtml(t('createdAt'))}</dt>
            <dd class="mt-1 text-sm font-medium text-ink">${escapeHtml(signal?.created_at ?? 'N/A')}</dd>
          </div>
        </dl>
        <div class="mt-4 rounded-md border border-line bg-panel p-3 text-sm leading-6 text-slate-700">${escapeHtml(signal?.notes ?? t('noNotes'))}</div>
      </section>

      <section id="service-runtime" class="section-panel scroll-mt-5">
        <div class="label">${escapeHtml(t('serviceRuntime'))}</div>
        <p class="mt-1 text-sm text-muted">${escapeHtml(t('serviceRuntimeDesc'))}</p>
        <div class="mt-4 space-y-3">
          ${serviceRow(t('dashboard'), dashboard)}
          ${serviceRow(t('postgres'), postgres)}
          ${serviceRow(t('dailyTimer'), timer)}
        </div>
        <pre class="mt-4 max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-slate-950 p-3 text-xs leading-5 text-slate-100">${escapeHtml(compactTimerOutput(timer?.output))}</pre>
      </section>
    </div>

    <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
      <section id="filing-storage" class="section-panel scroll-mt-5">
        <div class="label">${escapeHtml(t('filingStorage'))}</div>
        <p class="mt-1 text-sm text-muted">${escapeHtml(t('filingStorageDesc'))}</p>
        <dl class="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
          <div><dt class="text-muted">${escapeHtml(t('exists'))}</dt><dd class="mt-1 font-semibold text-ink">${formatBool(data.filings?.exists)}</dd></div>
          <div><dt class="text-muted">${escapeHtml(t('files'))}</dt><dd class="mt-1 font-semibold text-ink">${data.filings?.file_count ?? 0}</dd></div>
          <div><dt class="text-muted">${escapeHtml(t('path'))}</dt><dd class="mt-1 truncate font-semibold text-ink" title="${escapeHtml(data.filings?.path ?? '')}">${escapeHtml(data.filings?.path ?? 'N/A')}</dd></div>
        </dl>
      </section>

      <section id="raw-status" class="section-panel scroll-mt-5">
        <div class="label">${escapeHtml(t('rawSnapshot'))}</div>
        <p class="mt-1 text-sm text-muted">${escapeHtml(t('rawStatusDesc'))}</p>
        <pre class="mt-4 max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-panel p-3 text-xs leading-5 text-slate-700">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      </section>
    </div>
  `
}

function render(): void {
  app.innerHTML = `
    <div class="min-h-screen bg-slate-100 lg:flex">
      ${renderSidebar()}
      <div class="flex min-w-0 flex-1 flex-col lg:pl-0">
        <header class="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
          <div class="flex h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
            <div class="flex min-w-0 items-center gap-3">
              <button id="mobileMenuToggle" type="button" class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-line text-muted hover:text-ink lg:hidden" aria-label="${escapeHtml(t('mobileMenuToggle'))}">
                <i data-lucide="menu" class="h-4 w-4" aria-hidden="true"></i>
              </button>
              <div class="min-w-0">
                <h1 class="truncate text-lg font-semibold text-ink sm:text-xl">${escapeHtml(t('appName'))}</h1>
                <p class="truncate text-sm text-muted">${escapeHtml(t('appSubtitle'))}</p>
              </div>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <span class="hidden text-sm text-muted sm:inline">${escapeHtml(updatedText())}</span>
              <button id="headerLanguageToggle" type="button" class="hidden h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink shadow-sm hover:border-accent hover:text-accent sm:inline-flex">
                <i data-lucide="languages" class="h-4 w-4" aria-hidden="true"></i>
                ${escapeHtml(t('languageToggle'))}
              </button>
              <button id="refresh" type="button" class="inline-flex h-9 items-center gap-2 rounded-md border border-line bg-white px-3 text-sm font-medium text-ink shadow-sm transition hover:border-accent hover:text-accent disabled:cursor-not-allowed disabled:opacity-60" ${state.loading ? 'disabled' : ''}>
                <i data-lucide="refresh-cw" class="h-4 w-4 ${state.loading ? 'animate-spin' : ''}" aria-hidden="true"></i>
                ${escapeHtml(t('refresh'))}
              </button>
            </div>
          </div>
        </header>

        <main class="w-full px-4 py-4 sm:px-6 lg:px-8">
          <div class="mx-auto max-w-7xl">
            <div class="mb-4 text-sm text-muted sm:hidden">${escapeHtml(updatedText())}</div>
            ${state.error ? `<div class="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">${escapeHtml(state.error)}</div>` : ''}
            ${state.loading && !state.data ? `<div class="section-panel text-sm text-muted">${escapeHtml(t('loading'))}</div>` : ''}
            ${state.data ? renderStatus(state.data) : ''}
          </div>
        </main>
      </div>
    </div>
  `

  document.querySelector<HTMLButtonElement>('#refresh')?.addEventListener('click', () => {
    void refreshStatus()
  })
  document.querySelector<HTMLButtonElement>('#languageToggle')?.addEventListener('click', toggleLanguage)
  document.querySelector<HTMLButtonElement>('#headerLanguageToggle')?.addEventListener('click', toggleLanguage)
  document.querySelector<HTMLButtonElement>('#mobileMenuToggle')?.addEventListener('click', () => {
    state.navOpen = true
    render()
  })
  document.querySelector<HTMLButtonElement>('#closeMobileMenu')?.addEventListener('click', closeNavigation)
  document.querySelector<HTMLButtonElement>('#navBackdrop')?.addEventListener('click', closeNavigation)
  document.querySelectorAll<HTMLAnchorElement>('[data-nav-link]').forEach((link) => {
    link.addEventListener('click', () => {
      state.navOpen = false
      render()
    })
  })
  createIcons({
    icons: {
      Activity,
      Braces,
      Clock3,
      Database,
      FileText,
      Gauge,
      HardDrive,
      Languages,
      LayoutDashboard,
      Menu,
      RefreshCw,
      Server,
      X,
    },
  })
}

function toggleLanguage(): void {
  state.language = state.language === 'zh' ? 'en' : 'zh'
  render()
}

function closeNavigation(): void {
  state.navOpen = false
  render()
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
