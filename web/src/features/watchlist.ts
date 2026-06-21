import type { AppState, WatchlistItem } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel, renderStatusPill, renderTable } from '../shared/components'
import { escapeHtml } from '../shared/html'

export function renderWatchlist(state: AppState, t: Translator): string {
  const rows = state.watchlist?.rows ?? []
  return `
    ${renderPageHeader(t('watchlistList'), t('watchlistListDesc'))}
    <div class="grid grid-cols-1 gap-4 xl:grid-cols-[0.8fr_1.2fr]">
      ${renderPanel(t('watchlistAdd'), t('watchlistAddDesc'), renderWatchlistForm(state, t))}
      ${renderPanel(t('watchlistCurrent'), t('watchlistCurrentDesc'), renderWatchlistTable(rows, t))}
    </div>
  `
}

function renderWatchlistForm(state: AppState, t: Translator): string {
  return `
    <form id="watchlistForm" class="space-y-4">
      <label class="block text-sm font-medium text-ink">${escapeHtml(t('ticker'))}<input name="ticker" placeholder="NVDA" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm uppercase" /></label>
      <label class="block text-sm font-medium text-ink">${escapeHtml(t('status'))}<select name="status" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm"><option value="active">active</option><option value="paused">paused</option><option value="archived">archived</option></select></label>
      <label class="block text-sm font-medium text-ink">${escapeHtml(t('thesis'))}<textarea name="thesis" rows="4" class="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm" placeholder="${escapeHtml(t('watchlistThesisPlaceholder'))}"></textarea></label>
      <label class="block text-sm font-medium text-ink">Tags<input name="tags" placeholder="AI,semiconductor" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm" /></label>
      <button type="submit" class="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60" ${state.watchlistSaving ? 'disabled' : ''}><i data-lucide="plus" class="h-4 w-4" aria-hidden="true"></i>${escapeHtml(state.watchlistSaving ? t('saving') : t('watchlistSave'))}</button>
      ${state.watchlistResult?.error ? `<div class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">${escapeHtml(state.watchlistResult.error)}</div>` : ''}
      ${state.watchlistResult?.item ? `<div class="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">${escapeHtml(t('watchlistSaved'))}: ${escapeHtml(state.watchlistResult.item.ticker)}</div>` : ''}
    </form>
  `
}

function renderWatchlistTable(rows: WatchlistItem[], t: Translator): string {
  return renderTable<WatchlistItem>([
    { key: 'ticker', label: t('ticker'), render: (row) => `<span class="font-semibold text-ink">${escapeHtml(row.ticker)}</span>` },
    { key: 'status', label: t('status'), render: (row) => renderStatusPill(escapeHtml(row.status ?? 'active'), row.status === 'active' ? 'good' : row.status === 'paused' ? 'warn' : 'neutral') },
    { key: 'thesis', label: t('thesis'), render: (row) => `<span class="line-clamp-2 text-muted">${escapeHtml(row.thesis ?? '')}</span>` },
    { key: 'actions', label: t('operation'), align: 'right', render: (row) => `<button type="button" data-watchlist-delete="${escapeHtml(row.ticker)}" class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line text-muted hover:border-rose-300 hover:text-rose-700" title="${escapeHtml(t('deleteTicker'))}"><i data-lucide="trash-2" class="h-4 w-4" aria-hidden="true"></i></button>` },
  ], rows, t('noRows'))
}
