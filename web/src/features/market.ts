import type { AppState, HermesMarketInterpretationPayload, MarketSignal, RouteId } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderMetric, renderPanel, renderPageHeader, renderStatusPill, renderTable } from '../shared/components'
import { formatBool, formatNumber, marketDot, marketLabel } from '../shared/format'
import { escapeHtml } from '../shared/html'

export function renderMarket(state: AppState, t: Translator, route: RouteId = 'market-overview'): string {
  const signal = state.latestSignal ?? state.status?.database?.latest_market_signal
  const rows = state.marketSignals?.rows ?? []
  const trend = state.marketTrend
  const status = signal?.market_status?.toLowerCase()
  const tone = status === 'green' ? 'good' : status === 'yellow' ? 'warn' : status === 'red' ? 'bad' : 'neutral'

  const metrics = `
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      ${renderMetric(t('latestStatus'), marketLabel(signal, t), 'trending-up', signal?.signal_date ?? 'N/A', marketDot(signal))}
      ${renderMetric(t('sampleSize'), `${trend?.sample_size ?? rows.length}`, 'database', `${t('trendJudgement')} ${trend?.window ?? 20}`, 'bg-slate-500')}
      ${renderMetric(t('greenRatio'), `${Math.round((trend?.green_ratio ?? 0) * 100)}%`, 'activity', trendLabel(trend?.judgement, t), 'bg-emerald-500')}
      ${renderMetric(t('redRatio'), `${Math.round((trend?.red_ratio ?? 0) * 100)}%`, 'activity', trendSummary(trend?.judgement, t), 'bg-rose-500')}
    </div>
  `
  if (route === 'market-trend') {
    return `${renderPageHeader(t('marketTrend'), t('marketTrendDesc'))}${metrics}<div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.15fr_0.85fr]">${renderPanel(t('signalDashboard'), t('signalDashboardDesc'), renderSignalChart(rows))}${renderPanel(t('trendJudgement'), t('trendJudgementDesc'), renderTrend(trend, t))}</div><div class="mt-4">${renderPanel(t('hermesInterpretation'), t('hermesInterpretationDesc'), renderHermesInterpretation(state.hermesMarketInterpretation, t))}</div>`
  }
  if (route === 'market-list') {
    return `${renderPageHeader(t('marketList'), t('marketListDesc'))}${metrics}<div class="mt-4">${renderPanel(t('signalList'), t('signalListDesc'), renderSignalTable(rows, t))}</div>`
  }
  if (route === 'market-fetch') {
    return `${renderPageHeader(t('marketFetch'), t('marketFetchDesc'))}<div class="grid grid-cols-1 gap-4 xl:grid-cols-[0.9fr_1.1fr]">${renderPanel(t('manualFetch'), t('manualFetchDesc'), renderFetchForm(state, t))}${renderPanel(t('latestSignal'), t('latestSignalDesc'), renderLatest(signal, tone, t))}</div>`
  }
  return `
    ${renderPageHeader(t('marketOverview'), t('marketOverviewDesc'))}
    ${metrics}
    <div class="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.1fr_0.9fr]">
      ${renderPanel(t('signalDashboard'), t('signalDashboardDesc'), renderSignalChart(rows) + renderLatest(signal, tone, t))}
      ${renderPanel(t('trendJudgement'), t('trendJudgementDesc'), renderTrend(trend, t))}
    </div>
    <div class="mt-4">${renderPanel(t('hermesInterpretation'), t('hermesInterpretationDesc'), renderHermesInterpretation(state.hermesMarketInterpretation, t))}</div>
  `
}

function renderLatest(signal: MarketSignal | null | undefined, tone: 'neutral' | 'good' | 'warn' | 'bad', t: Translator): string {
  return `
    <div class="mt-4 rounded-lg border border-line bg-white p-4">
      <div class="flex flex-wrap items-center gap-2">
        ${renderStatusPill(marketLabel(signal, t), tone)}
        <span class="text-sm text-muted">${escapeHtml(signal?.signal_date ?? 'N/A')}</span>
      </div>
      <dl class="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <div><dt class="label">${escapeHtml(t('spyClose'))}</dt><dd class="mt-1 font-semibold text-ink">${formatNumber(signal?.spy_close, 2)}</dd></div>
        <div><dt class="label">${escapeHtml(t('spyMa200'))}</dt><dd class="mt-1 font-semibold text-ink">${formatNumber(signal?.spy_ma200, 2)}</dd></div>
        <div><dt class="label">${escapeHtml(t('vixClose'))}</dt><dd class="mt-1 font-semibold text-ink">${formatNumber(signal?.vix_close, 2)}</dd></div>
        <div><dt class="label">${escapeHtml(t('indexAboveMa'))}</dt><dd class="mt-1 font-semibold text-ink">${formatBool(signal?.spy_above_200ma, t)}</dd></div>
        <div><dt class="label">${escapeHtml(t('source'))}</dt><dd class="mt-1 font-semibold text-ink">${escapeHtml(signal?.source ?? 'N/A')}</dd></div>
        <div><dt class="label">run_id</dt><dd class="mt-1 truncate font-semibold text-ink" title="${escapeHtml(signal?.run_id ?? '')}">${escapeHtml(signal?.run_id ?? 'N/A')}</dd></div>
      </dl>
    </div>
  `
}

function renderTrend(trend: AppState['marketTrend'], t: Translator): string {
  if (!trend) return `<div class="text-sm text-muted">${escapeHtml(t('noRows'))}</div>`
  const tone = trend.judgement === 'risk_on' ? 'good' : trend.judgement === 'risk_off' ? 'bad' : 'warn'
  return `
    <div class="flex items-center justify-between gap-3">
      <div>
        <div class="text-2xl font-semibold text-ink">${escapeHtml(trendLabel(trend.judgement, t))}</div>
        <p class="mt-1 text-sm text-muted">${escapeHtml(trendSummary(trend.judgement, t))}</p>
      </div>
      ${renderStatusPill(escapeHtml(trend.latest_status), tone)}
    </div>
    <div class="mt-5 grid grid-cols-3 gap-3">
      <div class="rounded-lg border border-line bg-panel p-3"><div class="label">${escapeHtml(t('sampleSize'))}</div><div class="value">${trend.sample_size}</div></div>
      <div class="rounded-lg border border-line bg-panel p-3"><div class="label">${escapeHtml(t('green'))}</div><div class="value">${trend.status_counts.green ?? 0}</div></div>
      <div class="rounded-lg border border-line bg-panel p-3"><div class="label">${escapeHtml(t('red'))}</div><div class="value">${trend.status_counts.red ?? 0}</div></div>
    </div>
  `
}

function renderHermesInterpretation(interpretation: HermesMarketInterpretationPayload | null | undefined, t: Translator): string {
  if (!interpretation) return `<div class="rounded-md border border-line bg-panel px-3 py-4 text-sm text-muted">${escapeHtml(t('hermesNoInterpretation'))}</div>`
  const tone = interpretation.judgement === 'risk_on' ? 'good' : interpretation.judgement === 'risk_off' ? 'bad' : 'warn'
  const metrics = interpretation.metrics ?? {}
  return `
    <div class="space-y-4">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div class="flex flex-wrap items-center gap-2">
            ${renderStatusPill(trendLabel(interpretation.judgement, t), tone)}
            <span class="text-xs text-muted">${escapeHtml(t('hermesWindow'))}: ${interpretation.window} · ${escapeHtml(t('sampleSize'))}: ${interpretation.sample_size}</span>
          </div>
          <h3 class="mt-2 text-base font-semibold text-ink">${escapeHtml(interpretation.title)}</h3>
          <p class="mt-1 text-sm text-muted">${escapeHtml(interpretation.summary)}</p>
        </div>
        <div class="grid grid-cols-2 gap-2 text-sm sm:min-w-60">
          <div class="rounded-md border border-line bg-panel px-3 py-2"><div class="label">${escapeHtml(t('greenRatio'))}</div><div class="font-semibold text-ink">${Math.round((metrics.green_ratio ?? 0) * 100)}%</div></div>
          <div class="rounded-md border border-line bg-panel px-3 py-2"><div class="label">${escapeHtml(t('vixClose'))}</div><div class="font-semibold text-ink">${formatNumber(metrics.avg_vix, 1)}</div></div>
        </div>
      </div>
      ${interpretation.sections.map((section) => `
        <div>
          <div class="text-sm font-semibold text-ink">${escapeHtml(section.title)}</div>
          <ul class="mt-2 space-y-1 text-sm text-muted">
            ${section.items.map((item) => `<li class="flex gap-2"><span class="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent"></span><span>${escapeHtml(item)}</span></li>`).join('')}
          </ul>
        </div>
      `).join('')}
      <div>
        <div class="text-sm font-semibold text-ink">${escapeHtml(t('hermesActions'))}</div>
        <div class="mt-2 grid grid-cols-1 gap-2 md:grid-cols-3">
          ${interpretation.actions.map((action) => `<div class="rounded-md border border-line bg-white px-3 py-2 text-sm text-slate-700">${escapeHtml(action)}</div>`).join('')}
        </div>
      </div>
    </div>
  `
}

function trendLabel(judgement: string | undefined, t: Translator): string {
  if (judgement === 'risk_on') return t('riskOn')
  if (judgement === 'risk_off') return t('riskOff')
  return t('riskNeutral')
}

function trendSummary(judgement: string | undefined, t: Translator): string {
  if (judgement === 'risk_on') return t('riskOnSummary')
  if (judgement === 'risk_off') return t('riskOffSummary')
  return t('riskNeutralSummary')
}

function renderSignalChart(rows: MarketSignal[]): string {
  const data = rows.slice(0, 30).reverse()
  if (data.length === 0) return '<div class="h-56 rounded-lg border border-line bg-panel"></div>'
  const values = data.map((row) => Number(row.vix_close ?? 0)).filter(Number.isFinite)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = Math.max(max - min, 1)
  const points = data.map((row, index) => {
    const x = data.length === 1 ? 300 : (index / (data.length - 1)) * 600
    const y = 180 - ((Number(row.vix_close ?? min) - min) / span) * 140
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  const bands = data.map((row, index) => {
    const x = (index / data.length) * 600
    const width = 600 / data.length
    const color = row.market_status === 'green' ? '#10b981' : row.market_status === 'red' ? '#ef4444' : '#f59e0b'
    return `<rect x="${x.toFixed(1)}" y="198" width="${width.toFixed(1)}" height="10" fill="${color}" opacity="0.8" />`
  }).join('')
  return `
    <div class="rounded-lg border border-line bg-panel p-3">
      <svg viewBox="0 0 600 220" class="h-60 w-full" role="img" aria-label="Market signal trend chart">
        <line x1="0" y1="180" x2="600" y2="180" stroke="#d9e2ec" />
        <polyline fill="none" stroke="#2563eb" stroke-width="3" points="${points}" />
        ${bands}
      </svg>
    </div>
  `
}

function renderSignalTable(rows: MarketSignal[], t: Translator): string {
  return renderTable<MarketSignal>([
    { key: 'date', label: t('singleDate'), render: (row) => escapeHtml(row.signal_date ?? 'N/A') },
    { key: 'status', label: t('status'), render: (row) => renderStatusPill(marketLabel(row, t), row.market_status === 'green' ? 'good' : row.market_status === 'red' ? 'bad' : 'warn') },
    { key: 'spy', label: t('spyClose'), align: 'right', render: (row) => escapeHtml(formatNumber(row.spy_close, 2)) },
    { key: 'ma', label: t('spyMa200'), align: 'right', render: (row) => escapeHtml(formatNumber(row.spy_ma200, 2)) },
    { key: 'vix', label: t('vixClose'), align: 'right', render: (row) => escapeHtml(formatNumber(row.vix_close, 2)) },
    { key: 'created', label: t('createdAt'), render: (row) => escapeHtml(String(row.created_at ?? 'N/A')) },
  ], rows, t('noRows'))
}

function renderFetchForm(state: AppState, t: Translator): string {
  const today = new Date().toISOString().slice(0, 10)
  return `
    <form id="marketFetchForm" class="space-y-4">
      <div class="rounded-lg border border-line bg-panel p-3">
        <div class="grid grid-cols-2 gap-2 text-sm">
          <label class="inline-flex items-center gap-2"><input type="radio" name="mode" value="single" checked />${escapeHtml(t('singleDate'))}</label>
          <label class="inline-flex items-center gap-2"><input type="radio" name="mode" value="range" />${escapeHtml(t('dateRange'))}</label>
        </div>
      </div>
      <label class="block text-sm font-medium text-ink">${escapeHtml(t('singleDate'))}<input name="date" type="date" value="${today}" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm" /></label>
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label class="block text-sm font-medium text-ink">${escapeHtml(t('startDate'))}<input name="from" type="date" value="${today}" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm" /></label>
        <label class="block text-sm font-medium text-ink">${escapeHtml(t('endDate'))}<input name="to" type="date" value="${today}" class="mt-1 h-10 w-full rounded-md border border-line px-3 text-sm" /></label>
      </div>
      <button type="submit" class="inline-flex h-10 w-full items-center justify-center rounded-md bg-accent px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60" ${state.marketFetchInFlight ? 'disabled' : ''}>${escapeHtml(t('fetchMarketSignal'))}</button>
      ${renderFetchStatus(state, t)}
    </form>
  `
}

function renderFetchStatus(state: AppState, t: Translator): string {
  const result = state.marketFetchResult
  if (state.marketFetchInFlight) {
    const request = state.marketFetchRequest ? `${escapeHtml(t('fetchRequest'))}: ${escapeHtml(state.marketFetchRequest)}` : escapeHtml(t('fetchingMarketSignal'))
    return `<div class="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800"><span class="inline-flex items-center gap-2"><i data-lucide="refresh-cw" class="h-4 w-4 animate-spin" aria-hidden="true"></i>${escapeHtml(t('fetchingMarketSignal'))}</span><div class="mt-1 text-xs text-sky-700">${request}</div></div>`
  }
  if (!result) return ''
  const failed = result.error || (result.failures?.length ?? 0) > 0
  return `<div class="rounded-md border ${failed ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-emerald-200 bg-emerald-50 text-emerald-800'} px-3 py-2 text-sm">${escapeHtml(result.error ? t('fetchFailure') : t('fetchSuccess'))}: ${result.rows?.length ?? 0}</div>`
}
