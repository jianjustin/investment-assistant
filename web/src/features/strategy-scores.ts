import type { AppState, RouteId, StrategyScore, StrategyScoreHelpTopic } from '../app/types'
import type { Translator } from '../i18n/messages'
import { renderPageHeader, renderPanel, renderStatusPill, renderTable } from '../shared/components'
import { escapeHtml } from '../shared/html'

type StrategyColumnHelp = {
  title: string
  field: string
  logic: string
  values: Array<{ label: string; meaning: string }>
  nextAction: string
}

const strategyColumnHelp: Record<AppState['language'], Record<StrategyScoreHelpTopic, StrategyColumnHelp>> = {
  zh: {
    ticker: {
      title: 'Ticker',
      field: '字段说明：标的代码与评分日期，表示这条策略评分对应哪只股票、哪一天的趋势快照。',
      logic: '生成逻辑：手动或自动运行会读取每个 ticker 最新一条 ticker_signal_snapshots，并把 signal_date 写为 score_date。',
      values: [
        { label: 'ticker', meaning: '美股标的代码，例如 TSLA、MSFT。' },
        { label: 'score_date', meaning: '评分归属日期，通常等于来源趋势快照的 signal_date。' },
      ],
      nextAction: '下一步动作：先确认评分日期是否是你要分析的交易日，再比较同一天不同标的。',
    },
    strategy: {
      title: '策略评分',
      field: '字段说明：策略名称，说明这条分数由哪套 Python 规则生成。',
      logic: '生成逻辑：当前由 score_trend_relative_strength 读取趋势状态、触发原因和宏观上下文后生成。',
      values: [
        { label: 'trend_relative_strength', meaning: '趋势相对强弱策略，关注趋势结构、相对大盘强弱、成交量和宏观状态。' },
      ],
      nextAction: '下一步动作：先理解策略假设，再看分数和证据是否支持你的研究问题。',
    },
    score: {
      title: '分数',
      field: '字段说明：0-100 的证据强度分，不是买入、卖出或仓位建议。',
      logic: '生成逻辑：uptrend、above_ma_stack、outperform_spy、outperform_qqq、volume_expansion、macro_offense 等证据按权重加总，最高封顶 100。',
      values: [
        { label: '75-100', meaning: '证据较强，适合提高研究优先级。' },
        { label: '50-74', meaning: '有部分证据，但需要更多确认。' },
        { label: '1-49', meaning: '证据较弱，只适合常规观察。' },
        { label: '0', meaning: '暂无正向策略证据或数据不足。' },
      ],
      nextAction: '下一步动作：高分只代表值得研究，不代表直接交易；需要继续看证据和限制。',
    },
    evidence: {
      title: '证据',
      field: '字段说明：列出本次得分来自哪些正向信号。',
      logic: '生成逻辑：评分函数命中某条规则时，将对应证据写入 evidence 数组。',
      values: [
        { label: 'uptrend', meaning: '趋势状态为上升。' },
        { label: 'above_ma_stack', meaning: '价格和均线结构偏强。' },
        { label: 'outperform_spy / outperform_qqq', meaning: '相对大盘或成长股基准更强。' },
        { label: 'volume_expansion', meaning: '成交量放大。' },
        { label: 'macro_offense', meaning: '宏观分析师判断当前环境偏进攻。' },
      ],
      nextAction: '下一步动作：逐条复核证据是否仍成立，避免只看总分。',
    },
    limits: {
      title: '限制',
      field: '字段说明：记录这条评分不能覆盖的边界和风险提示。',
      logic: '生成逻辑：评分函数固定写入使用边界；当没有正向证据时，会额外写入 no positive trend evidence。',
      values: [
        { label: 'strategy score is evidence, not trading instruction', meaning: '策略分数只是证据，不是交易指令。' },
        { label: 'no positive trend evidence', meaning: '没有命中正向趋势证据。' },
      ],
      nextAction: '下一步动作：限制项优先用于避免误用分数，必要时转入人工复核。',
    },
    run_id: {
      title: 'Run ID',
      field: '字段说明：运行批次 ID，用于追踪这条评分由哪次手动或自动任务生成。',
      logic: '生成逻辑：手动评分入口生成 manual-strategy-scores-时间戳-随机后缀；后续自动任务应使用独立前缀但复用同一评分链路。',
      values: [
        { label: 'manual-strategy-scores-*', meaning: '后台手动触发的策略评分批次。' },
        { label: 'future automatic prefix', meaning: '后续定时任务应使用可区分的自动运行前缀。' },
      ],
      nextAction: '下一步动作：排查数据时用 Run ID 串起输入快照、评分结果和操作日志。',
    },
  },
  en: {
    ticker: {
      title: 'Ticker',
      field: '字段说明: Ticker symbol and score date for the source trend snapshot.',
      logic: '生成逻辑: The run reads the latest ticker_signal_snapshots row per ticker and writes signal_date as score_date.',
      values: [
        { label: 'ticker', meaning: 'US equity ticker such as TSLA or MSFT.' },
        { label: 'score_date', meaning: 'Date the score belongs to, usually the source signal_date.' },
      ],
      nextAction: '下一步动作: Confirm the date before comparing tickers.',
    },
    strategy: {
      title: 'Strategy',
      field: '字段说明: Strategy name that generated the score.',
      logic: '生成逻辑: Current scores come from score_trend_relative_strength.',
      values: [{ label: 'trend_relative_strength', meaning: 'Trend and relative-strength evidence strategy.' }],
      nextAction: '下一步动作: Understand the strategy assumption before reading the score.',
    },
    score: {
      title: 'Score',
      field: '字段说明: 0-100 evidence strength. It is not a buy, sell, or sizing instruction.',
      logic: '生成逻辑: Weighted sum of trend, moving-average, relative-strength, volume, and macro evidence, capped at 100.',
      values: [
        { label: '75-100', meaning: 'Strong evidence; raise research priority.' },
        { label: '50-74', meaning: 'Partial evidence; needs confirmation.' },
        { label: '1-49', meaning: 'Weak evidence; routine monitoring.' },
        { label: '0', meaning: 'No positive evidence or insufficient data.' },
      ],
      nextAction: '下一步动作: Treat high scores as research priority, not trade instruction.',
    },
    evidence: {
      title: 'Evidence',
      field: '字段说明: Positive signals that contributed to the score.',
      logic: '生成逻辑: Each matched scoring rule appends a token to evidence.',
      values: [
        { label: 'uptrend', meaning: 'Trend state is uptrend.' },
        { label: 'above_ma_stack', meaning: 'Moving-average structure is constructive.' },
        { label: 'outperform_spy / outperform_qqq', meaning: 'Outperforming broad or growth benchmark.' },
        { label: 'volume_expansion', meaning: 'Volume expanded.' },
        { label: 'macro_offense', meaning: 'Macro analyst state is offense.' },
      ],
      nextAction: '下一步动作: Review each evidence item instead of only the total score.',
    },
    limits: {
      title: 'Limits',
      field: '字段说明: Boundaries and risk reminders for the score.',
      logic: '生成逻辑: The scorer always writes usage boundaries and adds data/evidence limits when needed.',
      values: [
        { label: 'strategy score is evidence, not trading instruction', meaning: 'Score is evidence only.' },
        { label: 'no positive trend evidence', meaning: 'No positive trend evidence matched.' },
      ],
      nextAction: '下一步动作: Use limits to avoid over-interpreting the score.',
    },
    run_id: {
      title: 'Run ID',
      field: '字段说明: Batch ID for tracing the run that generated this score.',
      logic: '生成逻辑: Manual runs use manual-strategy-scores timestamp ids; future automatic runs should use a distinct prefix.',
      values: [
        { label: 'manual-strategy-scores-*', meaning: 'Manually triggered scoring batch.' },
        { label: 'future automatic prefix', meaning: 'Reserved for scheduled scoring batches.' },
      ],
      nextAction: '下一步动作: Use Run ID to connect input snapshots, scores, and logs.',
    },
  },
}

const strategyHelpLabels: Record<AppState['language'], { field: string; logic: string; values: string; nextAction: string; close: string }> = {
  zh: {
    field: '字段说明',
    logic: '生成逻辑',
    values: '字段值/枚举意义',
    nextAction: '下一步动作',
    close: '关闭说明',
  },
  en: {
    field: 'Field',
    logic: 'Generation Logic',
    values: 'Values / Enum Meaning',
    nextAction: 'Next Action',
    close: 'Close help',
  },
}

export function renderStrategyScores(state: AppState, t: Translator, route: RouteId): string {
  const rows = state.strategyScores?.rows ?? []
  const averageScore = rows.length > 0 ? Math.round(rows.reduce((sum, row) => sum + Number(row.score ?? 0), 0) / rows.length) : 0
  return `
    ${renderPageHeader(t('strategyModule'), t('strategyModuleDesc'))}
    ${renderStrategyRunPanel(state, t)}
    <div class="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <div class="metric-panel"><div class="label">${escapeHtml(t('sampleSize'))}</div><div class="value mt-2">${rows.length}</div><div class="mt-2 text-sm text-muted">strategy_scores</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('score'))}</div><div class="value mt-2">${averageScore}</div><div class="mt-2 text-sm text-muted">0 - 100</div></div>
      <div class="metric-panel"><div class="label">${escapeHtml(t('source'))}</div><div class="value mt-2">${escapeHtml(rows[0]?.strategy ?? 'N/A')}</div><div class="mt-2 text-sm text-muted">Python strategy scoring</div></div>
    </div>
    ${route === 'strategy-runs' ? renderPanel(t('strategyRuns'), t('strategyRunsDesc'), `<div class="text-sm text-muted">${escapeHtml(t('strategyRunHistoryPlanned'))}</div>`, 'mb-4') : ''}
    ${renderStrategyScoreHelpPanel(state)}
    ${renderPanel(t('strategyScoresCurrent'), t('strategyScoresCurrentDesc'), renderStrategyScoreTable(rows, state, t))}
  `
}

function renderStrategyRunPanel(state: AppState, t: Translator): string {
  const result = state.strategyScoreRunResult
  const failures = result?.failures?.length ?? 0
  const status = state.strategyScoreRunInFlight
    ? `<div class="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800"><span class="inline-flex items-center gap-2"><i data-lucide="refresh-cw" class="h-4 w-4 animate-spin" aria-hidden="true"></i>${escapeHtml(t('runningStrategyScores'))}</span></div>`
    : result?.error
      ? `<div class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">${escapeHtml(result.error)}</div>`
      : result?.run_id
        ? `<div class="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">${escapeHtml(t('strategyScoreRunComplete'))}: ${result.count ?? 0} · ${escapeHtml(t('fetchFailure'))}: ${failures}</div>`
        : ''
  return `
    <div class="mb-4 section-panel">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div class="label">${escapeHtml(t('strategyManualRun'))}</div>
          <p class="mt-1 text-sm text-muted">${escapeHtml(t('strategyManualRunDesc'))}</p>
        </div>
        <button id="strategyScoreRunButton" type="button" class="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white hover:bg-teal-800 disabled:opacity-60" ${state.strategyScoreRunInFlight ? 'disabled' : ''}>
          <i data-lucide="refresh-cw" class="h-4 w-4 ${state.strategyScoreRunInFlight ? 'animate-spin' : ''}" aria-hidden="true"></i>${escapeHtml(state.strategyScoreRunInFlight ? t('runningStrategyScores') : t('runStrategyScores'))}
        </button>
      </div>
      ${status ? `<div class="mt-3">${status}</div>` : ''}
    </div>
  `
}

function renderStrategyScoreHelpPanel(state: AppState): string {
  const topic = state.strategyScoreHelpTopic
  if (!topic) return ''
  const copy = strategyColumnHelp[state.language][topic]
  const labels = strategyHelpLabels[state.language]
  return `
    <section class="mb-4 rounded-md border border-sky-200 bg-sky-50 px-4 py-4 shadow-sm">
      <div class="flex items-start justify-between gap-3">
        <div>
          <div class="text-sm font-semibold text-sky-950">${escapeHtml(copy.title)}</div>
          <p class="mt-1 text-sm text-sky-800">${escapeHtml(copy.field)}</p>
        </div>
        <button type="button" data-strategy-help="${topic}" class="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-sky-200 bg-white text-sm font-semibold text-sky-700 hover:border-sky-400" aria-label="${escapeHtml(labels.close)}">×</button>
      </div>
      <div class="mt-4 grid gap-3 lg:grid-cols-3">
        ${renderHelpBlock(labels.field, copy.field)}
        ${renderHelpBlock(labels.logic, copy.logic)}
        <div class="rounded-md border border-sky-100 bg-white p-3">
          <div class="text-xs font-semibold uppercase tracking-normal text-sky-900">${escapeHtml(labels.values)}</div>
          <div class="mt-2 space-y-2">
            ${copy.values.map((item) => `<div class="text-sm text-slate-700"><span class="font-semibold text-ink">${escapeHtml(item.label)}</span>: ${escapeHtml(item.meaning)}</div>`).join('')}
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

function renderStrategyScoreTable(rows: StrategyScore[], state: AppState, t: Translator): string {
  return renderTable<StrategyScore>([
    { key: 'ticker', label: t('ticker'), header: renderHelpHeader('ticker', t('ticker'), state), render: (row) => `<span class="font-semibold text-ink">${escapeHtml(row.ticker)}</span><div class="mt-1 text-xs text-muted">${escapeHtml(row.score_date ?? 'N/A')}</div>` },
    { key: 'strategy', label: t('strategyScores'), header: renderHelpHeader('strategy', t('strategyScores'), state), render: (row) => `<span class="font-medium text-ink">${escapeHtml(row.strategy)}</span>` },
    { key: 'score', label: t('score'), header: renderHelpHeader('score', t('score'), state), align: 'right', render: (row) => renderStatusPill(String(row.score), scoreTone(row.score)) },
    { key: 'evidence', label: t('strategyEvidence'), header: renderHelpHeader('evidence', t('strategyEvidence'), state), render: (row) => renderTags(row.evidence ?? []) },
    { key: 'limits', label: t('strategyLimits'), header: renderHelpHeader('limits', t('strategyLimits'), state), render: (row) => renderTags(row.limits ?? []) },
    { key: 'run_id', label: 'Run ID', header: renderHelpHeader('run_id', 'Run ID', state), render: (row) => `<span class="text-xs text-muted">${escapeHtml(row.run_id ?? '-')}</span>` },
  ], rows, t('noRows'))
}

function renderHelpHeader(topic: StrategyScoreHelpTopic, label: string, state: AppState): string {
  const active = state.strategyScoreHelpTopic === topic
  return `
    <span class="inline-flex items-center gap-1.5 ${topic === 'score' ? 'justify-end' : ''}">
      <span>${escapeHtml(label)}</span>
      <button type="button" data-strategy-help="${topic}" class="inline-flex h-5 w-5 items-center justify-center rounded-full border ${active ? 'border-accent bg-accent text-white' : 'border-line bg-white text-muted hover:border-accent hover:text-accent'} text-[11px] font-bold leading-none" aria-label="${escapeHtml(label)} help">?</button>
    </span>
  `
}

function renderTags(items: string[]): string {
  if (items.length === 0) return '<span class="text-muted">-</span>'
  return `<div class="flex flex-wrap gap-1">${items.map((item) => `<span class="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700">${escapeHtml(item)}</span>`).join('')}</div>`
}

function scoreTone(score: number): 'neutral' | 'good' | 'warn' | 'bad' {
  if (score >= 75) return 'good'
  if (score >= 50) return 'warn'
  if (score > 0) return 'neutral'
  return 'bad'
}
