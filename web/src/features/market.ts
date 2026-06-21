import type { AppState } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPanel, renderPageHeader, renderStatusPill } from '../shared/components'
import { formatBool, formatNumber, marketLabel } from '../shared/format'
import { escapeHtml } from '../shared/html'

export function renderMarket(state: AppState, t: Translator): string {
  const signal = state.latestSignal ?? state.status?.database?.latest_market_signal
  const status = signal?.market_status?.toLowerCase()
  const tone = status === 'green' ? 'good' : status === 'yellow' ? 'warn' : status === 'red' ? 'bad' : 'neutral'
  const body = `
    <div class="flex flex-wrap items-center gap-2">
      ${renderStatusPill(marketLabel(signal, t), tone)}
      <span class="text-sm text-muted">${escapeHtml(signal?.signal_date ?? 'N/A')}</span>
    </div>
    <dl class="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div><dt class="label">${escapeHtml(t('score'))}</dt><dd class="value">${formatNumber(signal?.score, 1)}</dd></div>
      <div><dt class="label">${escapeHtml(t('vix'))}</dt><dd class="value">${formatNumber(signal?.vix ?? signal?.vix_close, 2)}</dd></div>
      <div><dt class="label">${escapeHtml(t('distribution'))}</dt><dd class="value">${formatNumber(signal?.distribution_days, 0)}</dd></div>
      <div><dt class="label">${escapeHtml(t('indexAboveMa'))}</dt><dd class="mt-1 text-sm font-medium text-ink">${formatBool(signal?.index_above_ma ?? signal?.spy_above_200ma, t)}</dd></div>
      <div><dt class="label">${escapeHtml(t('createdAt'))}</dt><dd class="mt-1 text-sm font-medium text-ink">${escapeHtml(signal?.created_at ?? 'N/A')}</dd></div>
      <div><dt class="label">${escapeHtml(t('source'))}</dt><dd class="mt-1 text-sm font-medium text-ink">${escapeHtml(signal?.source ?? 'N/A')}</dd></div>
    </dl>
    <pre class="mt-4 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-line bg-panel p-3 text-xs leading-5 text-slate-700">${escapeHtml(JSON.stringify(signal ?? {}, null, 2))}</pre>
  `
  return `${renderPageHeader(t('marketSignals'), t('marketSignalsDesc'))}${renderPanel(t('latestSignal'), t('latestSignalDesc'), body)}`
}
