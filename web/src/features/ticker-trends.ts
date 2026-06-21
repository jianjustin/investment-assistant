import type { AppState, TickerTrendHelpTopic, TickerTrendSnapshot } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel, renderStatusPill, renderTable } from '../shared/components'
import { formatNumber } from '../shared/format'
import { escapeHtml } from '../shared/html'

type MetricHelpCopy = {
  title: string
  indicator: string
  logic: string
  enumMeaning: Array<{ label: string; meaning: string }>
  nextAction: string
}

const metricHelpCopy: Record<AppState['language'], Record<TickerTrendHelpTopic, MetricHelpCopy>> = {
  zh: {
    trend_state: {
      title: '趋势状态',
      indicator: '描述标的当前价格结构，帮助判断它处于上升、筑底、下跌、剧烈波动还是数据不足状态。',
      logic: '基于 close、MA20、MA50、MA200、成交量比率和相对强弱做规则判断；上升趋势要求价格站上中期均线并维持相对强度，下跌趋势优先识别价格跌破关键均线，volatile 用于波动或信号冲突。',
      enumMeaning: [
        { label: 'uptrend', meaning: '趋势偏强，可进入候选机会跟踪，但仍需结合宏观状态和个股基本面。' },
        { label: 'base', meaning: '横盘或筑底，适合观察突破、缩量整理和财报催化。' },
        { label: 'downtrend', meaning: '趋势偏弱，优先避免新增风险敞口，已有持仓需要复核止损或仓位。' },
        { label: 'volatile', meaning: '波动显著或规则冲突，不适合只看单日结论，需等待确认。' },
        { label: 'unknown', meaning: '数据不足或拉取异常，先处理数据质量。' },
      ],
      nextAction: '优先查看 high/medium 标的的触发原因，再决定是否交给宏观分析师或个股研究流程。',
    },
    attention_level: {
      title: '关注级别',
      indicator: '把趋势状态、相对强弱、成交量异动和错误状态压缩成操作优先级。',
      logic: 'high 通常代表趋势或风险信号需要立即复核；medium 代表值得观察但未到强动作点；low 代表当前无需优先处理。',
      enumMeaning: [
        { label: 'high', meaning: '优先处理。可能是强趋势延续、风险恶化、成交量异常或数据错误。' },
        { label: 'medium', meaning: '进入观察清单。适合等待第二个确认信号或补充基本面信息。' },
        { label: 'low', meaning: '维持常规监控。没有明显动作需求。' },
      ],
      nextAction: '每天先扫 high，再扫 medium；low 只在组合复盘或周度检查时看。',
    },
    trigger_reason: {
      title: '触发原因',
      indicator: '列出系统把某个标的提升关注级别或标记趋势状态的直接原因。',
      logic: '由趋势规则、均线位置、相对强弱、成交量比率和错误状态共同生成，可作为后续人工复核入口。',
      enumMeaning: [
        { label: 'price_above_ma / price_below_ma', meaning: '价格相对均线结构变化，是趋势判断的基础信号。' },
        { label: 'volume_expansion', meaning: '成交量放大，说明市场参与度变化，需要判断是突破还是派发。' },
        { label: 'relative_strength', meaning: '相对 SPY/QQQ 更强或更弱，反映标的是否跑赢大盘。' },
        { label: 'error / insufficient_data', meaning: '数据质量问题，先修复或回补后再做决策。' },
      ],
      nextAction: '把触发原因当成问题清单，不直接当买卖结论。',
    },
    volume_ratio: {
      title: '成交量比率',
      indicator: '当前成交量相对近期平均成交量的倍数，用于识别放量或缩量。',
      logic: '通常以当前 volume 除以近期均量得到；数值越高，说明当天成交更活跃，但方向需要结合价格和趋势。',
      enumMeaning: [
        { label: '> 1.5', meaning: '明显放量。若价格突破，可能是趋势确认；若下跌，可能是风险释放或派发。' },
        { label: '0.8 - 1.5', meaning: '常规成交区间，单独解释力有限。' },
        { label: '< 0.8', meaning: '缩量。适合观察整理，但突破可信度较弱。' },
      ],
      nextAction: '放量信号必须和价格位置一起看，避免把噪音误判成趋势。',
    },
    relative_strength: {
      title: '相对 SPY / QQQ',
      indicator: '标的相对大盘和成长股基准的强弱，帮助判断涨跌是否来自个股 alpha。',
      logic: '用标的表现和 SPY、QQQ 表现做相对比较；大于基准代表跑赢，小于基准代表跑输。',
      enumMeaning: [
        { label: '> 1', meaning: '相对跑赢。若趋势状态同步向上，可提高研究优先级。' },
        { label: '≈ 1', meaning: '基本跟随市场。需要更多个股证据。' },
        { label: '< 1', meaning: '相对跑输。即使绝对价格上涨，也要警惕弱于市场。' },
      ],
      nextAction: '成长股优先和 QQQ 比，防御或大盘权重股优先和 SPY 比。',
    },
  },
  en: {
    trend_state: {
      title: 'Trend State',
      indicator: 'Describes the ticker price structure: uptrend, base, downtrend, volatile, or unknown.',
      logic: 'Rule-based judgement from close, MA20, MA50, MA200, volume ratio, and relative strength.',
      enumMeaning: [
        { label: 'uptrend', meaning: 'Constructive trend; monitor as a candidate, then confirm with macro state and fundamentals.' },
        { label: 'base', meaning: 'Sideways or basing; watch for breakout, volume contraction, and catalysts.' },
        { label: 'downtrend', meaning: 'Weak trend; avoid adding exposure before review.' },
        { label: 'volatile', meaning: 'Conflicting or unstable signal; wait for confirmation.' },
        { label: 'unknown', meaning: 'Insufficient data or fetch error; fix data quality first.' },
      ],
      nextAction: 'Review high/medium tickers first, then route them to macro or single-name research.',
    },
    attention_level: {
      title: 'Attention Level',
      indicator: 'Compresses trend, relative strength, volume anomaly, and errors into an operating priority.',
      logic: 'High needs immediate review; medium belongs on the watch queue; low stays in routine monitoring.',
      enumMeaning: [
        { label: 'high', meaning: 'Handle first. Can indicate strong continuation, risk deterioration, volume anomaly, or data error.' },
        { label: 'medium', meaning: 'Watch next. Wait for a second confirmation or add fundamental context.' },
        { label: 'low', meaning: 'Routine monitoring; no immediate action.' },
      ],
      nextAction: 'Scan high first, then medium; review low during portfolio or weekly checks.',
    },
    trigger_reason: {
      title: 'Trigger Reason',
      indicator: 'Shows why the system raised attention or assigned the trend state.',
      logic: 'Generated from trend rules, moving averages, relative strength, volume ratio, and data errors.',
      enumMeaning: [
        { label: 'price_above_ma / price_below_ma', meaning: 'Moving-average structure changed.' },
        { label: 'volume_expansion', meaning: 'Participation changed; judge breakout versus distribution.' },
        { label: 'relative_strength', meaning: 'Ticker is outperforming or underperforming SPY/QQQ.' },
        { label: 'error / insufficient_data', meaning: 'Data quality issue; fix before deciding.' },
      ],
      nextAction: 'Treat triggers as review questions, not trade instructions.',
    },
    volume_ratio: {
      title: 'Volume Ratio',
      indicator: 'Current volume compared with recent average volume.',
      logic: 'Current volume divided by recent average volume; direction must be read with price.',
      enumMeaning: [
        { label: '> 1.5', meaning: 'Large volume expansion; confirm whether it supports breakout or distribution.' },
        { label: '0.8 - 1.5', meaning: 'Normal range; limited standalone meaning.' },
        { label: '< 0.8', meaning: 'Volume contraction; useful for basing, weaker for breakout confirmation.' },
      ],
      nextAction: 'Pair volume with price location to avoid treating noise as trend.',
    },
    relative_strength: {
      title: 'Relative SPY / QQQ',
      indicator: 'Compares the ticker against broad-market and growth benchmarks.',
      logic: 'Relative comparison versus SPY and QQQ; above benchmark implies outperformance.',
      enumMeaning: [
        { label: '> 1', meaning: 'Outperforming; raise research priority if trend is also constructive.' },
        { label: '≈ 1', meaning: 'Market-like behavior; needs more single-name evidence.' },
        { label: '< 1', meaning: 'Underperforming; beware even if absolute price is up.' },
      ],
      nextAction: 'Compare growth names to QQQ first; broad or defensive names to SPY first.',
    },
  },
}

const sectionLabels: Record<AppState['language'], { indicator: string; logic: string; enumMeaning: string; nextAction: string; close: string }> = {
  zh: {
    indicator: '指标说明',
    logic: '指标逻辑',
    enumMeaning: '指标下枚举带来的意义',
    nextAction: '下一步动作',
    close: '关闭说明',
  },
  en: {
    indicator: 'Indicator',
    logic: 'Logic',
    enumMeaning: 'Enum Meaning',
    nextAction: 'Next Action',
    close: 'Close help',
  },
}

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
    ${renderMetricHelpPanel(state)}
    ${renderPanel(t('tickerTrendsCurrent'), t('tickerTrendsCurrentDesc'), renderTrendTable(rows, state, t))}
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

function renderMetricHelpPanel(state: AppState): string {
  const topic = state.tickerTrendHelpTopic
  if (!topic) return ''
  const copy = metricHelpCopy[state.language][topic]
  const labels = sectionLabels[state.language]
  return `
    <section class="mb-4 rounded-md border border-sky-200 bg-sky-50 px-4 py-4 shadow-sm">
      <div class="flex items-start justify-between gap-3">
        <div>
          <div class="text-sm font-semibold text-sky-950">${escapeHtml(copy.title)}</div>
          <p class="mt-1 text-sm text-sky-800">${escapeHtml(copy.indicator)}</p>
        </div>
        <button type="button" data-ticker-help="${topic}" class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-sky-200 bg-white text-sm font-semibold text-sky-700 hover:border-sky-400" aria-label="${escapeHtml(labels.close)}">×</button>
      </div>
      <div class="mt-4 grid gap-3 lg:grid-cols-3">
        ${renderHelpBlock(labels.indicator, copy.indicator)}
        ${renderHelpBlock(labels.logic, copy.logic)}
        <div class="rounded-md border border-sky-100 bg-white p-3">
          <div class="text-xs font-semibold uppercase tracking-normal text-sky-900">${escapeHtml(labels.enumMeaning)}</div>
          <div class="mt-2 space-y-2">
            ${copy.enumMeaning.map((item) => `<div class="text-sm text-slate-700"><span class="font-semibold text-ink">${escapeHtml(item.label)}</span>: ${escapeHtml(item.meaning)}</div>`).join('')}
          </div>
        </div>
      </div>
      <div class="mt-3 rounded-md border border-sky-100 bg-white px-3 py-2 text-sm text-sky-900"><span class="font-semibold">${escapeHtml(labels.nextAction)}：</span>${escapeHtml(copy.nextAction)}</div>
    </section>
  `
}

function renderHelpBlock(title: string, body: string): string {
  return `
    <div class="rounded-md border border-sky-100 bg-white p-3">
      <div class="text-xs font-semibold uppercase tracking-normal text-sky-900">${escapeHtml(title)}</div>
      <p class="mt-2 text-sm leading-6 text-slate-700">${escapeHtml(body)}</p>
    </div>
  `
}

function renderTrendTable(rows: TickerTrendSnapshot[], state: AppState, t: Translator): string {
  return renderTable<TickerTrendSnapshot>([
    { key: 'ticker', label: t('ticker'), render: (row) => `<span class="font-semibold text-ink">${escapeHtml(row.ticker)}</span><div class="mt-1 text-xs text-muted">${escapeHtml(row.signal_date ?? 'N/A')}</div>` },
    { key: 'trend_state', label: t('trendState'), header: renderHelpHeader('trend_state', t('trendState'), state), render: (row) => renderStatusPill(escapeHtml(row.trend_state), trendTone(row.trend_state)) },
    { key: 'attention_level', label: t('attentionLevel'), header: renderHelpHeader('attention_level', t('attentionLevel'), state), render: (row) => renderStatusPill(escapeHtml(row.attention_level), attentionTone(row.attention_level)) },
    { key: 'price', label: t('spyClose'), align: 'right', render: (row) => `<span class="font-medium text-ink">${escapeHtml(formatNumber(row.close, 2))}</span><div class="mt-1 text-xs text-muted">MA20 ${escapeHtml(formatNumber(row.ma20, 2))} · MA50 ${escapeHtml(formatNumber(row.ma50, 2))}</div>` },
    { key: 'volume_ratio', label: t('volumeRatio'), header: renderHelpHeader('volume_ratio', t('volumeRatio'), state), align: 'right', render: (row) => escapeHtml(formatNumber(row.volume_ratio, 2)) },
    { key: 'rs', label: t('relativeStrengthSpy'), header: renderHelpHeader('relative_strength', t('relativeStrengthSpy'), state), align: 'right', render: (row) => `<span>${escapeHtml(formatNumber(row.relative_strength_spy, 3))}</span><div class="mt-1 text-xs text-muted">QQQ ${escapeHtml(formatNumber(row.relative_strength_qqq, 3))}</div>` },
    { key: 'trigger_reason', label: t('triggerReason'), header: renderHelpHeader('trigger_reason', t('triggerReason'), state), render: (row) => renderReasons(row) },
    { key: 'error', label: t('error'), render: (row) => row.error ? `<span class="text-rose-700">${escapeHtml(row.error)}</span>` : `<span class="text-muted">-</span>` },
  ], rows, t('noRows'))
}

function renderHelpHeader(topic: TickerTrendHelpTopic, label: string, state: AppState): string {
  const active = state.tickerTrendHelpTopic === topic
  return `
    <span class="inline-flex items-center gap-1.5 ${topic === 'volume_ratio' || topic === 'relative_strength' ? 'justify-end' : ''}">
      <span>${escapeHtml(label)}</span>
      <button type="button" data-ticker-help="${topic}" class="inline-flex h-5 w-5 items-center justify-center rounded-full border ${active ? 'border-accent bg-accent text-white' : 'border-line bg-white text-muted hover:border-accent hover:text-accent'} text-[11px] font-bold leading-none" aria-label="${escapeHtml(label)} help">?</button>
    </span>
  `
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
