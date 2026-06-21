import {
  Activity,
  Braces,
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
import { renderFilings } from '../features/filings'
import { renderMarket } from '../features/market'
import { renderOperations } from '../features/operations'
import { renderRaw } from '../features/raw'
import { renderServices } from '../features/services'
import { renderWorkbench } from '../features/workbench'
import { routeGroups, routes } from './navigation'
import { reloadData, setRouteFromHash, state, t, toggleLanguage } from './state'
import type { RouteId, RouteItem } from './types'
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
              ${group.children.map(renderNavItem).join('')}
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

function renderNavItem(route: RouteItem): string {
  const active = route.id === state.activeRoute
  return `
    <a href="#/${route.id}" class="group flex items-start gap-3 rounded-md px-3 py-2 text-sm ${active ? 'bg-panel text-ink' : 'text-slate-700 hover:bg-panel hover:text-ink'}" data-route-link>
      <i data-lucide="${route.icon}" class="mt-0.5 h-4 w-4 shrink-0 ${active ? 'text-accent' : 'text-muted group-hover:text-accent'}" aria-hidden="true"></i>
      <span class="min-w-0">
        <span class="block truncate font-medium">${escapeHtml(t(route.labelKey))}</span>
        <span class="mt-0.5 block truncate text-xs text-muted">${escapeHtml(t(route.descriptionKey))}</span>
      </span>
    </a>
  `
}

function renderActiveRoute(): string {
  const route = routes.find((item) => item.id === state.activeRoute) ?? routes[0]
  const header = route ? '' : ''
  switch (state.activeRoute) {
    case 'market':
      return renderMarket(state, t)
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
