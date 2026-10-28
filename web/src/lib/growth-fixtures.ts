/** Test fixtures for the v2.7 growth-loop components (shapes follow src/lib/growth.ts). Not imported by the app. */
import type {
  CardDraft, CardDraftRow, Discussion, DiscussionTurn, Facts, FactDiscipline, KnowledgeDraft, KnowledgeEntry,
  KnowledgeItemView, KnowledgePerf, KnowledgeVersion, LessonDraftRow, ReviewCardRow, ReviewCardView,
} from './growth'

/** turn request id -> the user_inputs.request_id the backend derives (uuid5, NAMESPACE_URL, 'discussion-turn:<id>'). */
export const USER_INPUT_REQUEST_ID_VECTOR = {
  turn_request_id: '6f1b0a52-3c4d-4e8f-9a7b-2d5e8c1f0a34',
  user_input_request_id: '28230603-464d-5148-8a74-17665f3f4fb1',
} as const

export const discipline = (over: Partial<FactDiscipline> = {}): FactDiscipline => ({
  trades: [{ trade_id: 't1', flags: ['chase'], immature: ['early_take'] }],
  totals: { chase: 1, early_take: 0, held_loser: 0, unplanned: 0, pending: 1 },
  as_of: '2026-10-23', ...over,
})

export const facts = (over: Partial<Facts> = {}): Facts => ({
  subject: { kind: 'unit', ticker: 'NVDA', signal_date: '2026-10-14', pool: 'core', end_kind: 'position_closed',
             end_text: '平仓（按止损）', end_session: '2026-10-23', exit_basis: 'stop' },
  plans: [
    { key: 'plan:p-rule', kind: 'rule', version_no: null, origin: null,
      levels: { entry_low: '98.50', entry_high: '101.50', stop: '94.00', target1: '112.00' },
      valid_from: '2026-10-15', valid_until: '2026-10-19', cutoff_at: null, status: 'ok', invalid_reasons: [],
      roles: ['reference', 'executed'] },
    { key: 'plan:p-agent', kind: 'agent', version_no: 2, origin: 'review',
      levels: { entry_low: '99.00', entry_high: '102.00', stop: '95.00', target1: '110.00' },
      valid_from: '2026-10-16', valid_until: '2026-10-20', cutoff_at: '2026-10-15T21:00:00Z', status: 'ok', invalid_reasons: [],
      roles: ['seen_at_decision', 'head'] },
  ],
  bars_after: {
    first_day: '2026-10-15', last_day: '2026-10-23', sessions: 7, high: '112.40', high_date: '2026-10-20',
    low: '93.10', low_date: '2026-10-23', close_end: '93.80',
    per_plan: [
      { key: 'plan:p-rule', entry_touched: '2026-10-15', stop_touched_on: '2026-10-23', t1_touched_on: null },
      { key: 'plan:p-agent', entry_touched: '2026-10-16', stop_touched_on: null, t1_touched_on: '2026-10-20' },
    ],
  },
  shadow: {
    'plan:p-rule': { status: 'closed', fill_date: '2026-10-15', fill_price: '100.00', r: -1,
                     legs: [{ fraction: 1, exit_date: '2026-10-23', exit_price: '94.00', reason: 'stop' }] },
    'plan:p-agent': { status: 'open', fill_date: '2026-10-16', fill_price: '100.50', r: null, legs: [] },
  },
  tracks: {
    rule: { status: 'closed', status_text: '已平仓', r: -1, plan_id: 'p-rule' },
    agent: { status: 'open', status_text: '未平仓', r: null, plan_id: 'p-agent', version_no: 2, version_basis: 'decision' },
    actual: { status: 'closed', status_text: '已平仓', r: -0.8, plan_id: 'p-rule', plan_kind: 'rule' },
  },
  decision: { decision: 'accept', final_action: 'buy', plan_kind: 'rule', plan_id: 'p-rule', agent_plan_id: null,
              agent_version_no: null, reason: '趋势回踩，按规则计划', decided_at: '2026-10-14T21:00:00Z',
              text: '采纳（照规则计划）' },
  trades: {
    trades: [
      { id: 't1', side: 'buy', quantity: 10, price: '101.00', fee: '1', executed_at: '2026-10-15T14:00:00Z' },
      { id: 't2', side: 'sell', quantity: 10, price: '94.00', fee: '1', executed_at: '2026-10-23T15:00:00Z' },
    ],
    segments: [{ buy_trade_id: 't1', sell_trade_id: 't2', quantity: 10, r: -0.8 }],
    actual_r: -0.8,
  },
  discipline: discipline(),
  reviews: { count: 2, outcomes: { maintain: 2, revise: 0, invalidate: 0, skipped: 0, error: 0 }, invalidated: null },
  knowledge: [{ ref: 'know:3@1', title_at_version: '回踩别追', fields: ['thesis'] }],
  ...over,
})

export const lessonRows = (): LessonDraftRow[] => [
  { id: 101, lesson_index: 0, title: '回踩不追高', body: '价格高于入场上沿就等回落。', scope: '趋势回踩修复触发后',
    counter_examples: '放量突破时追高可能是对的', concepts: ['review.discipline_chase'], tickers: ['NVDA'], refs: ['fact:discipline'] },
  { id: 102, lesson_index: 1, title: '止损按计划执行', body: '触及止损次日就卖。', scope: '持仓期间',
    counter_examples: '财报前后跳空除外', concepts: ['plan.stop'], tickers: [], refs: ['fact:trades', 'call:3'] },
]

export const draftOutput = (): CardDraft => ({
  headline: '回踩买入后触及止损，追高是主因',
  expected_vs_actual: [
    { text: '入场区间 98.50–101.50，10-15 当天触及并成交', refs: ['fact:plans', 'fact:bars_after'] },
    { text: '10-23 触及止损 94.00，按止损卖出', refs: ['call:2', 'know:3@1', 'concept:plan.stop@1'] },
  ],
  decision_review: { text: '决定照规则计划，买入价略高于入场上沿', refs: ['fact:decision', 'fact:discipline'] },
  lessons: lessonRows().map(({ id, lesson_index, ...lesson }) => lesson),
})

export const draftRow = (over: Partial<CardDraftRow> = {}): CardDraftRow => ({
  id: 1, attempt: 1, trigger: 'batch', agent_run_id: 'run-draft', status: 'ok', reason: null,
  output: draftOutput(), created_at: '2026-10-23T22:40:00Z', ...over,
})

export const cardView = (over: Partial<ReviewCardView> = {}): ReviewCardView => ({
  card: { id: 12, event_key: 'unit:NVDA:2026-10-23:closed:t2', subject: 'unit', ticker: 'NVDA', signal_date: '2026-10-14',
          end_kind: 'position_closed', end_session: '2026-10-23', created_at: '2026-10-23T22:30:00Z' },
  facts: facts(), status: 'to_review', drafts: [draftRow()], lesson_drafts: lessonRows(), verdict: null,
  discipline_now: discipline(), discussions: [], ...over,
})

export const cardRow = (over: Partial<ReviewCardRow> = {}): ReviewCardRow => ({
  id: 12, ticker: 'NVDA', subject: 'unit', signal_date: '2026-10-14', end_kind: 'position_closed', exit_basis: 'stop',
  end_session: '2026-10-23', decision_text: '采纳（照规则计划）', actual_r: -0.8, rule_r: -1, agent_r: null,
  flags: ['chase'], immature: ['early_take'], status: 'to_review', headline: '回踩买入后触及止损，追高是主因', ...over,
})

export const version = (n: number, over: Partial<KnowledgeVersion> = {}): KnowledgeVersion => ({
  id: 10 + n, knowledge_id: 3, version: n, supersedes_id: n > 1 ? 9 + n : null, draft_id: null,
  title: `回踩别追 v${n}`, body: `第 ${n} 版正文\n第二行`, scope: '趋势回踩触发后', counter_examples: '放量突破时除外',
  concepts: ['concept:review.discipline_chase@1'], tickers: ['NVDA'], created_at: `2026-10-2${n}T10:00:00Z`, ...over,
})

export const entry = (over: Partial<KnowledgeEntry> = {}): KnowledgeEntry => ({
  id: 3, origin: 'manual', title: '回踩别追', scope: '趋势回踩触发后', concepts: ['concept:review.discipline_chase@1'],
  tickers: ['NVDA'], current_version: 2, status: 'active', written_at: '2026-10-20T10:00:00Z',
  updated_at: '2026-10-22T10:00:00Z', citation_count: 4, sample_count: 3, ...over,
})

export const itemView = (over: Partial<KnowledgeItemView> = {}): KnowledgeItemView => ({
  item: { id: 3, origin: 'manual', source_card_id: null, source_discussion_id: null, created_at: '2026-10-20T10:00:00Z',
          status: 'active' },
  versions: [version(1), version(2, { title: '回踩别追（改）', scope: '趋势回踩触发后的第一天' })],
  status_history: [], current: version(2, { title: '回踩别追（改）', scope: '趋势回踩触发后的第一天' }),
  citations: [
    { ticker: 'NVDA', signal_date: '2026-10-22', plan_id: 'p-agent', head_plan_id: null, version_no: 1, review_id: null,
      cited_version: 1, field: 'thesis' },
    { ticker: 'NVDA', signal_date: '2026-10-22', plan_id: null, head_plan_id: 'p-agent', version_no: null, review_id: 9,
      cited_version: 2, field: 'review' },
  ],
  ...over,
})

export const perf = (over: Partial<KnowledgePerf> = {}): KnowledgePerf => ({
  calc_version: 'knowledge-perf-1', sample: { count: 6, determined: 5, expired: 1, r_mean: 0.42, r_median: 0.3 },
  min_sample: 5, note: '描述性统计，样本小且重叠，不代表这条经验有效',
  rows: [{ unit: { ticker: 'NVDA', signal_date: '2026-10-22' }, plan_id: 'p-agent', kind: 'agent', version_no: 1,
           cited_version: 1, fields: ['thesis'], status: 'closed', status_text: '已平仓', r: 0.5,
           fill_date: '2026-10-23', outcome_date: '2026-10-28' }],
  by_version: [{ version: 1, plans: 4, units: 4 }, { version: 2, plans: 2, units: 2 }], reviews_cited: 3, ...over,
})

export const knowledgeDraft = (over: Partial<KnowledgeDraft> = {}): KnowledgeDraft => ({
  id: 201, origin: 'discussion', card_id: null, discussion_id: 5, discussion_turn_id: 8, target_knowledge_id: null,
  target_version: null, title: '止损别拖', body: '触及止损次日就卖。', scope: '持仓期', counter_examples: '财报前后除外',
  concepts: ['plan.stop'], tickers: ['NVDA'], refs: ['call:1'], created_at: '2026-10-28T10:00:00Z', verdict: null, ...over,
})

export const userTurn = (over: Partial<DiscussionTurn> = {}): DiscussionTurn => ({
  id: 7, seq: 1, role: 'user', body: '这个止损怎么来的？', created_at: '2026-10-28T10:00:00Z',
  request_id: '6f1b0a52-3c4d-4e8f-9a7b-2d5e8c1f0a34', attachment: null, state: null, user_input_id: null, ...over,
})
export const answerTurn = (over: Partial<DiscussionTurn> = {}): DiscussionTurn => ({
  id: 8, seq: 2, role: 'assistant', body: '止损 = 参考价减 2 倍 ATR14。', created_at: '2026-10-28T10:00:20Z',
  status: 'ok', reason: null, refs: ['call:1', 'concept:plan.stop@1'], agent_run_id: 'run-answer',
  cutoff_at: '2026-10-28T10:00:00Z', detail: {}, knowledge_draft: null, ...over,
})
export const discussion = (turns: DiscussionTurn[] = [userTurn(), answerTurn()], over: Partial<Discussion> = {}): Discussion => ({
  id: 5, context_kind: 'plan', ticker: 'NVDA', signal_date: '2026-10-22', plan_id: 'p-agent', card_id: null,
  created_at: '2026-10-28T09:59:00Z',
  context: { version_no: 2, generated_at: '2026-10-27T13:00:00Z', cutoff_at: '2026-10-27T12:59:00Z' }, turns, ...over,
})
