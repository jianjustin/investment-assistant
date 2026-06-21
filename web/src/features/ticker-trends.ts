import type { AppState, TickerTrendSnapshot } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel, renderStatusPill, renderTable } from '../shared/components'
import { formatNumber } from '../shared/format'
import { escapeHtml } from '../shared/html'

export function renderTickerTrends(state: AppState, t: Translator): string {
  const rows = state.tickerTrends?.rows ?? []
  const counts = rows.reduce<Record<string, number>>((acc, row) => {
    const level = row.attention_level || 'unknown'
    acc[level] = (acc[level] ?? 0) + 1
    return acc
  }, {})
  const summary = `High ${counts.high ?? 0} · Medium ${counts.medium ?? 0} · Low ${counts.low ?? 0}`
  return `
    ${renderPageHeader(t('tickerTrends'), t('tickerTrendsDesc'))}
    ${renderScanPanel(state, t)}
    <div class="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div class="metric-panel"><div class="label">${escapeHtml(t('sampleSize'))}</div><div class="value mt-2">${rows.length}</div><div class="mt-2 text-sm text-muted">${escapeHtml(t('tickerTrendsCurrent'))}</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('attentionLevel'))}</div><div class="value mt-2">${escapeHtml(summary)}</div><div class="mt-2 text-sm text-muted">${escapeHtml(t('tickerTrendsDesc'))}</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('source'))}</div><div class="value mt-2">${escapeHtml(rows[0]?.source ?? 'N/A')}</div><div class="mt-2 text-sm text-muted">ticker_signal_snapshots</div></div>
    </div>
    ${renderPanel(t('tickerTrendsCurrent'), t('tickerTrendsCurrentDesc'), renderTrendTable(rows, t))}
  `
}


function renderScanPanel(state: AppState, t: Translator): string {
  const result = state.tickerTrendScanResult
  const failures = result?.failures?.length ?? 0
  const status = state.tickerTrendScanInFlight
    ? `<div class="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800"><span class="inline-flex items-center gap-2"><i data-lucide="refresh-cw" class="h-4 w-4 animate-spin" aria-hidden="true"></i>${escapeHtml(t('tickerTrendScanning'))}</span></div>`
    : result?.error
      ? `<div class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">${escapeHtml(result.error)}</div>`
      : result?.run_id
        ? `<div class="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">${escapeHtml(t('tickerTrendScanComplete'))}: ${result.count ?? 0} · ${escapeHtml(t('fetchFailure'))}: ${failures}</div>`
        : ''
  return `
    <div class="mb-4 section-panel">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div class="label">${escapeHtml(t('tickerTrendManualScan'))}</div>
          <p class="mt-1 text-sm text-muted">${escapeHtml(t('tickerTrendManualScanDesc'))}</p>
        </div>
        <button id="tickerTrendScanButton" type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60" ${state.tickerTrendScanInFlight ? 'disabled' : ''}>
          <i data-lucide="refresh-cw" class="h-4 w-4 ${state.tickerTrendScanInFlight ? 'animate-spin' : ''}" aria-hidden="true"></i>${escapeHtml(state.tickerTrendScanInFlight ? t('tickerTrendScanning') : t('tickerTrendScan'))}
        </button>
      </div>
      ${status ? `<div class="mt-3">${status}</div>` : ''}
    </div>
  `
}

function renderTrendTable(rows: TickerTrendSnapshot[], t: Translator): string {
  return renderTable<TickerTrendSnapshot>([
    { key: 'ticker', label: t('ticker'), render: (row) => `<span class="font-semibold text-ink">${escapeHtml(row.ticker)}</span><div class="mt-1 text-xs text-muted">${escapeHtml(row.signal_date ?? 'N/A')}</div>` },
    { key: 'trend_state', label: t('trendState'), render: (row) => renderStatusPill(escapeHtml(row.trend_state), trendTone(row.trend_state)) },
    { key: 'attention_level', label: t('attentionLevel'), render: (row) => renderStatusPill(escapeHtml(row.attention_level), attentionTone(row.attention_level)) },
    { key: 'price', label: t('spyClose'), align: 'right', render: (row) => `<span class="font-medium text-ink">${escapeHtml(formatNumber(row.close, 2))}</span><div class="mt-1 text-xs text-muted">MA20 ${escapeHtml(formatNumber(row.ma20, 2))} · MA50 ${escapeHtml(formatNumber(row.ma50, 2))}</div>` },
    { key: 'volume_ratio', label: t('volumeRatio'), align: 'right', render: (row) => escapeHtml(formatNumber(row.volume_ratio, 2)) },
    { key: 'rs', label: t('relativeStrengthSpy'), align: 'right', render: (row) => `<span>${escapeHtml(formatNumber(row.relative_strength_spy, 3))}</span><div class="mt-1 text-xs text-muted">QQQ ${escapeHtml(formatNumber(row.relative_strength_qqq, 3))}</div>` },
    { key: 'trigger_reason', label: t('triggerReason'), render: (row) => renderReasons(row) },
    { key: 'error', label: t('error'), render: (row) => row.error ? `<span class="text-rose-700">${escapeHtml(row.error)}</span>` : `<span class="text-muted">-</span>` },
  ], rows, t('noRows'))
}

function renderReasons(row: TickerTrendSnapshot): string {
  const reasons = row.trigger_reason ?? []
  if (reasons.length === 0) return '<span class="text-muted">-</span>'
  return `<div class="flex flex-wrap gap-1">${reasons.map((reason) => `<span class="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700">${escapeHtml(reason)}</span>`).join('')}</div>`
}

function trendTone(value: string): 'neutral' | 'good' | 'warn' | 'bad' {
  if (value === 'uptrend') return 'good'
  if (value === 'downtrend') return 'bad'
  if (value === 'volatile') return 'warn'
  return 'neutral'
}

function attentionTone(value: string): 'neutral' | 'good' | 'warn' | 'bad' {
  if (value === 'high') return 'bad'
  if (value === 'medium') return 'warn'
  if (value === 'low') return 'good'
  return 'neutral'
}
