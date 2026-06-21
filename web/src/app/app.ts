import {
  Activity,
  Braces,
  CalendarDays,
  ChevronDown,
  createIcons,
  Database,
  FileText,
  Gauge,
  HardDrive,
  Languages,
  LayoutDashboard,
  Menu,
  Plus,
  RefreshCw,
  Server,
  Trash2,
  TrendingUp,
  X,
} from 'lucide'
import { renderFilings } from '../features/filings'
import { renderHermes } from '../features/hermes'
import { renderMarket } from '../features/market'
import { renderOperations } from '../features/operations'
import { renderRaw } from '../features/raw'
import { renderServices } from '../features/services'
import { renderStrategyScores } from '../features/strategy-scores'
import { renderWatchlist } from '../features/watchlist'
import { renderTickerTrends } from '../features/ticker-trends'
import { renderWorkbench } from '../features/workbench'
import { isRouteParent, parentForRoute, routeGroups, routes } from './navigation'
import { addWatchlistItem, deleteWatchlistItem, fetchMarketSignals, reloadData, runMacroAnalystLlm, runStrategyScores, scanTickerTrends, saveHermesAgent, setRouteFromHash, state, t, toggleExpandedMenu, toggleLanguage } from './state'
import type { AppState, RouteEntry, RouteId, RouteItem, RouteParent } from './types'
import { escapeHtml } from '../shared/html'

let root: HTMLDivElement

export function bootApp(): void {
  const appElement = document.querySelector<HTMLDivElement>('#app')
  if (!appElement) {
    throw new Error('Missing #app root')
  }
  root = appElement
  window.addEventListener('hashchange', () => {
    setRouteFromHash()
    state.navOpen = false
    render()
  })
  render()
  void refresh()
}

function render(): void {
  root.innerHTML = `
    <div class="min-h-screen bg-slate-100 lg:flex">
      ${renderSidebar()}
      <div class="flex min-w-0 flex-1 flex-col lg:pl-0">
        ${renderHeader()}
        <main class="w-full px-4 py-4 sm:px-6 lg:px-8">
          <div class="mx-auto max-w-7xl">
            <div class="mb-4 text-sm text-muted sm:hidden">${escapeHtml(updatedText())}</div>
            ${state.error ? `<div class="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">${escapeHtml(t('loadFailed'))}: ${escapeHtml(state.error)}</div>` : ''}
            ${state.loading && !state.status ? `<div class="section-panel text-sm text-muted">${escapeHtml(t('loading'))}</div>` : renderActiveRoute()}
          </div>
        </main>
      </div>
    </div>
  `
  bindEvents()
  createIcons({
    icons: {
      Activity,
      Braces,
      CalendarDays,
      ChevronDown,
      Database,
      FileText,
      Gauge,
      HardDrive,
      Languages,
      LayoutDashboard,
      Menu,
      Plus,
      RefreshCw,
      Server,
      Trash2,
      TrendingUp,
      X,
    },
  })
}

function renderHeader(): string {
  return `
    <header class="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur">
      <div class="flex h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <div class="flex min-w-0 items-center gap-3">
          <button id="mobileMenuToggle" type="button" class="inline-flex h-9 w-9 items-center justify-center rounded-md border border-line text-muted hover:text-ink lg:hidden" aria-label="${escapeHtml(t('menu'))}">
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
      <nav class="flex-1 overflow-y-auto px-3 py-4" aria-label="${escapeHtml(t('menu'))}">
        ${routeGroups.map((group) => `
          <div class="mb-5">
            <div class="px-3 text-xs font-semibold uppercase tracking-normal text-muted">${escapeHtml(t(group.labelKey))}</div>
            <div class="mt-2 space-y-1">
              ${group.children.map(renderNavEntry).join('')}
            </div>
          </div>
        `).join('')}
      </nav>
      <div class="border-t border-line p-3">
        <button id="languageToggle" type="button" class="inline-flex w-full items-center justify-between rounded-md border border-line bg-panel px-3 py-2 text-sm font-medium text-ink hover:border-accent hover:text-accent">
          <span class="inline-flex items-center gap-2"><i data-lucide="languages" class="h-4 w-4" aria-hidden="true"></i>${escapeHtml(t('language'))}</span>
          <span>${escapeHtml(t('languageToggle'))}</span>
        </button>
      </div>
    </aside>
    ${state.navOpen ? '<button id="navBackdrop" class="fixed inset-0 z-30 bg-slate-950/30 lg:hidden" aria-label="Close navigation"></button>' : ''}
  `
}

function renderNavEntry(entry: RouteEntry): string {
  return isRouteParent(entry) ? renderNavParent(entry) : renderNavItem(entry)
}

function renderNavParent(parent: RouteParent): string {
  const active = parent.children.some((child) => child.id === state.activeRoute)
  const expanded = state.expandedMenus.includes(parent.id) || active
  return `
    <div>
      <button type="button" class="menu-item group ${active ? 'menu-item-active' : 'menu-item-inactive'}" data-menu-toggle="${parent.id}">
        <i data-lucide="${parent.icon}" class="h-5 w-5 shrink-0 ${active ? 'text-accent' : 'text-muted group-hover:text-accent'}" aria-hidden="true"></i>
        <span class="menu-item-text min-w-0 flex-1 text-left">
          <span class="block truncate font-medium">${escapeHtml(t(parent.labelKey))}</span>
          <span class="mt-0.5 block truncate text-xs ${active ? 'text-teal-700' : 'text-muted'}">${escapeHtml(t(parent.descriptionKey))}</span>
        </span>
        <i data-lucide="chevron-down" class="h-4 w-4 shrink-0 transition ${expanded ? 'rotate-180 text-accent' : 'text-muted'}" aria-hidden="true"></i>
      </button>
      <div class="overflow-hidden ${expanded ? 'block' : 'hidden'}">
        <ul class="mt-2 flex flex-col gap-1 pl-9">
          ${parent.children.map(renderSubNavItem).join('')}
        </ul>
      </div>
    </div>
  `
}

function renderNavItem(route: RouteItem): string {
  const active = route.id === state.activeRoute
  return `
    <a href="#/${route.id}" class="menu-item group ${active ? 'menu-item-active' : 'menu-item-inactive'}" data-route-link>
      <i data-lucide="${route.icon ?? 'circle'}" class="h-5 w-5 shrink-0 ${active ? 'text-accent' : 'text-muted group-hover:text-accent'}" aria-hidden="true"></i>
      <span class="menu-item-text min-w-0 flex-1">
        <span class="block truncate font-medium">${escapeHtml(t(route.labelKey))}</span>
        <span class="mt-0.5 block truncate text-xs ${active ? 'text-teal-700' : 'text-muted'}">${escapeHtml(t(route.descriptionKey))}</span>
      </span>
    </a>
  `
}

function renderSubNavItem(route: RouteItem): string {
  const active = route.id === state.activeRoute
  return `
    <li>
      <a href="#/${route.id}" class="menu-dropdown-item ${active ? 'menu-dropdown-item-active' : 'menu-dropdown-item-inactive'}" data-route-link>
        ${escapeHtml(t(route.labelKey))}
      </a>
    </li>
  `
}

function renderActiveRoute(): string {
  const route = routes.find((item) => item.id === state.activeRoute) ?? routes[0]
  const header = route ? '' : ''
  switch (state.activeRoute) {
    case 'hermes-overview':
    case 'hermes-agents':
    case 'hermes-ideas':
      return renderHermes(state, t, state.activeRoute)
    case 'watchlist-list':
      return renderWatchlist(state, t)
    case 'ticker-trends':
      return renderTickerTrends(state, t)
    case 'strategy-scores':
    case 'strategy-runs':
      return renderStrategyScores(state, t, state.activeRoute)
    case 'market-overview':
    case 'market-trend':
    case 'market-list':
    case 'market-fetch':
      return renderMarket(state, t, state.activeRoute)
    case 'filings':
      return renderFilings(state, t)
    case 'services':
      return renderServices(state, t)
    case 'operations':
      return renderOperations(state, t)
    case 'raw':
      return renderRaw(state, t)
    case 'workbench':
    default:
      return header + renderWorkbench(state, t)
  }
}

function bindEvents(): void {
  document.querySelector<HTMLButtonElement>('#refresh')?.addEventListener('click', () => {
    void refresh()
  })
  document.querySelector<HTMLButtonElement>('#languageToggle')?.addEventListener('click', () => {
    toggleLanguage()
    render()
  })
  document.querySelector<HTMLButtonElement>('#headerLanguageToggle')?.addEventListener('click', () => {
    toggleLanguage()
    render()
  })
  document.querySelector<HTMLButtonElement>('#mobileMenuToggle')?.addEventListener('click', () => {
    state.navOpen = true
    render()
  })
  document.querySelector<HTMLButtonElement>('#closeMobileMenu')?.addEventListener('click', closeNavigation)
  document.querySelector<HTMLButtonElement>('#navBackdrop')?.addEventListener('click', closeNavigation)
  document.querySelectorAll<HTMLButtonElement>('[data-menu-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
      const menuId = button.dataset.menuToggle
      if (menuId) {
        toggleExpandedMenu(menuId)
        render()
      }
    })
  })
  document.querySelector<HTMLFormElement>('#watchlistForm')?.addEventListener('submit', (event) => {
    event.preventDefault()
    const form = event.currentTarget as HTMLFormElement
    const formData = new FormData(form)
    state.watchlistSaving = true
    render()
    void addWatchlistItem({
      ticker: String(formData.get('ticker') ?? ''),
      status: String(formData.get('status') ?? 'active'),
      thesis: String(formData.get('thesis') ?? ''),
      tags: String(formData.get('tags') ?? '').split(',').map((item) => item.trim()).filter(Boolean),
    }).then(render)
  })
  document.querySelectorAll<HTMLButtonElement>('[data-watchlist-delete]').forEach((button) => {
    button.addEventListener('click', () => {
      const ticker = button.dataset.watchlistDelete
      if (!ticker) return
      state.watchlistSaving = true
      render()
      void deleteWatchlistItem(ticker).then(render)
    })
  })


  document.querySelector<HTMLButtonElement>('#tickerTrendScanButton')?.addEventListener('click', () => {
    state.tickerTrendScanInFlight = true
    state.tickerTrendScanResult = null
    render()
    void scanTickerTrends().then(render)
  })
  document.querySelectorAll<HTMLButtonElement>('[data-ticker-help]').forEach((button) => {
    button.addEventListener('click', () => {
      const topic = button.dataset.tickerHelp as NonNullable<AppState['tickerTrendHelpTopic']> | undefined
      if (!topic) return
      state.tickerTrendHelpTopic = state.tickerTrendHelpTopic === topic ? null : topic
      render()
    })
  })

  document.querySelector<HTMLFormElement>('#hermesAgentForm')?.addEventListener('submit', (event) => {
    event.preventDefault()
    const form = event.currentTarget as HTMLFormElement
    const formData = new FormData(form)
    state.hermesAgentSaving = true
    state.hermesAgentResult = null
    render()
    void saveHermesAgent({
      id: String(formData.get('id') ?? ''),
      name: String(formData.get('name') ?? ''),
      role: String(formData.get('role') ?? ''),
      description: String(formData.get('description') ?? ''),
      system_prompt: String(formData.get('system_prompt') ?? ''),
      data_sources: String(formData.get('data_sources') ?? '').split(',').map((item) => item.trim()).filter(Boolean),
      tools: String(formData.get('tools') ?? '').split(',').map((item) => item.trim()).filter(Boolean),
      enabled: formData.get('enabled') === 'on',
    }).then(render)
  })
  document.querySelector<HTMLButtonElement>('#macroLlmButton')?.addEventListener('click', () => {
    state.macroLlmInFlight = true
    render()
    void runMacroAnalystLlm({ window: 30 }).then(render)
  })
  document.querySelector<HTMLButtonElement>('#strategyScoreRunButton')?.addEventListener('click', () => {
    state.strategyScoreRunInFlight = true
    state.strategyScoreRunResult = null
    render()
    void runStrategyScores({ mode: 'manual' }).then(render)
  })

  document.querySelector<HTMLFormElement>('#marketFetchForm')?.addEventListener('submit', (event) => {
    event.preventDefault()
    const form = event.currentTarget as HTMLFormElement
    const formData = new FormData(form)
    const mode = String(formData.get('mode') ?? 'single')
    const date = String(formData.get('date') ?? '')
    const from = String(formData.get('from') ?? '')
    const to = String(formData.get('to') ?? '')
    const payload = mode === 'range' ? { from, to } : { date }
    state.marketFetchInFlight = true
    state.marketFetchRequest = mode === 'range' ? `${from} - ${to}` : date
    state.marketFetchResult = null
    render()
    void fetchMarketSignals(payload).then(render)
  })

}

function closeNavigation(): void {
  state.navOpen = false
  render()
}

async function refresh(): Promise<void> {
  state.loading = true
  render()
  await reloadData()
  render()
}

function updatedText(): string {
  if (!state.refreshedAt) return t('notUpdated')
  return `${t('lastUpdated')} ${state.refreshedAt.toLocaleString(state.language === 'zh' ? 'zh-CN' : 'en-US')}`
}
