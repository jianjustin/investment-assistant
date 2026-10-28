import { describe, expect, it } from 'vitest'
import {
  CARD_STATUS_TEXT, DECISION_TEXT, DISCIPLINE_TEXT, DISCUSS_POLL_MS, END_TEXT, EXIT_BASIS_TEXT,
  changedFields, conflictText, endText, growthError, idempotentRequests, isKnowRef, knowHref, knowledgeProblem, parseKnowRef,
  refKind, sampleLine, userInputRequestId, VERSION_BASIS_TEXT,
} from './growth'
import { WorkbenchError } from './workbench'
import { USER_INPUT_REQUEST_ID_VECTOR } from './growth-fixtures'

// Fixed vector shared with the Python test (tests/test_growth_frontend_sync.py, Task 5): the backend derives
//   user_inputs.request_id = uuid5(NAMESPACE_URL, 'discussion-turn:' + <turn request_id>)
// and the pair below (USER_INPUT_REQUEST_ID_VECTOR, in growth-fixtures.ts) was computed with
//   python3 -c "import uuid; print(uuid.uuid5(uuid.NAMESPACE_URL, 'discussion-turn:6f1b0a52-3c4d-4e8f-9a7b-2d5e8c1f0a34'))"
//   -> 28230603-464d-5148-8a74-17665f3f4fb1

describe('constants (spec 4.1, 4.3, 4.6, 13)', () => {
  it('carries the texts verbatim', () => {
    expect(END_TEXT).toEqual({ position_closed: '平仓', stop: '止损', target: '到 T1', expired: '过期未成交', invalidated: '作废' })
    expect(EXIT_BASIS_TEXT).toEqual({ stop: '按止损', target: '到 T1 后', other: '自行卖出' })
    expect(CARD_STATUS_TEXT).toEqual({
      reviewed: '已审定', to_review: '待审定', draft_failed: '起草失败（可手动审定或重新起草）', drafting: '起草中',
    })
    expect(DECISION_TEXT).toEqual({
      accept_rule: '采纳（照规则计划）', accept_agent: '采纳（照 Agent 第 {n} 版）',
      accept_agent_legacy: '采纳（照 Agent agent-1）', accept_own: '自改价位', reject: '否决', downgrade: '降为观察',
      none: '未决定（计划外成交）', accept: '采纳',
    })
    expect(VERSION_BASIS_TEXT).toEqual({ decision: '决定时看到的版本', first: '首版' })
    expect(DISCIPLINE_TEXT).toEqual({
      chase: '追高', early_take: '过早止盈', held_loser: '死扛亏损', unplanned: '计划外', pending: '待定',
    })
    expect(DISCUSS_POLL_MS).toBe(600_000)
  })
})

describe('parseKnowRef accepts and rejects', () => {
  it('accepts know:<id>@<version> and know:<id>', () => {
    expect(parseKnowRef('know:3@2')).toEqual({ id: 3, version: 2 })
    expect(parseKnowRef('know:12')).toEqual({ id: 12, version: null })
    expect(isKnowRef('know:3@2')).toBe(true)
  })
  it('rejects anything else', () => {
    for (const bad of ['know:0@1', 'know:3@0', 'know:03@1', 'know:3@', 'know:@1', 'know:-1', 'know:3@2x',
                       ' know:3@2', 'call:3', 'concept:plan.stop@1', 'know:', '']) {
      expect([bad, parseKnowRef(bad)]).toEqual([bad, null])
      expect(isKnowRef(bad)).toBe(false)
    }
  })
})

describe('knowHref', () => {
  it('links to the version page of the entry', () => {
    expect(knowHref('know:3@2')).toBe('#knowledge/mine/3@2')
    expect(knowHref('know:3')).toBe('#knowledge/mine/3')
    expect(knowHref('nonsense')).toBe('#knowledge/mine')
  })
})

describe('endText joins exit basis', () => {
  it('appends the exit basis to a closed position only', () => {
    expect(endText('position_closed')).toBe('平仓')
    expect(endText('position_closed', null)).toBe('平仓')
    expect(endText('position_closed', 'stop')).toBe('平仓（按止损）')
    expect(endText('position_closed', 'target')).toBe('平仓（到 T1 后）')
    expect(endText('position_closed', 'other')).toBe('平仓（自行卖出）')
    expect(endText('stop', 'other')).toBe('止损')
    expect(endText('target')).toBe('到 T1')
    expect(endText('expired')).toBe('过期未成交')
    expect(endText('invalidated')).toBe('作废')
    expect(endText('mystery')).toBe('mystery')
  })
})

describe('userInputRequestId is a stable uuid5', () => {
  it('matches the Python uuid5 vector', async () => {
    expect(await userInputRequestId(USER_INPUT_REQUEST_ID_VECTOR.turn_request_id))
      .toBe(USER_INPUT_REQUEST_ID_VECTOR.user_input_request_id)
  })
  it('is deterministic and differs per turn', async () => {
    const a = await userInputRequestId('aaaaaaaa-0000-4000-8000-000000000001')
    expect(await userInputRequestId('aaaaaaaa-0000-4000-8000-000000000001')).toBe(a)
    expect(await userInputRequestId('aaaaaaaa-0000-4000-8000-000000000002')).not.toBe(a)
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  })
})

describe('knowledgeProblem', () => {
  const ok = { title: 't', body: 'b', scope: 's', counter_examples: '', concepts: ['plan.stop'], tickers: [] as string[] }
  it('accepts a minimal entry', () => expect(knowledgeProblem(ok)).toBeNull())
  it('limits lengths by code point', () => {
    expect(knowledgeProblem({ ...ok, title: '' })).toMatch(/标题/)
    expect(knowledgeProblem({ ...ok, title: 'x'.repeat(61) })).toMatch(/标题最多 60 字/)
    expect(knowledgeProblem({ ...ok, title: '😀'.repeat(60) })).toBeNull()
    expect(knowledgeProblem({ ...ok, body: 'x'.repeat(4001) })).toMatch(/正文最多 4000 字/)
    expect(knowledgeProblem({ ...ok, scope: 'x'.repeat(501) })).toMatch(/适用范围最多 500 字/)
    expect(knowledgeProblem({ ...ok, counter_examples: 'x'.repeat(1001) })).toMatch(/反例最多 1000 字/)
  })
  it('requires scope, and counter examples when asked', () => {
    expect(knowledgeProblem({ ...ok, scope: '  ' })).toMatch(/适用范围必填/)
    expect(knowledgeProblem(ok, { requireCounter: true })).toMatch(/反例必填/)
    expect(knowledgeProblem({ ...ok, counter_examples: '会错的情况' }, { requireCounter: true })).toBeNull()
  })
  it('wants one to ten attachments', () => {
    expect(knowledgeProblem({ ...ok, concepts: [] })).toMatch(/挂靠.*1–10/)
    expect(knowledgeProblem({ ...ok, concepts: Array.from({ length: 6 }, (_, i) => `a.b${i}`), tickers: ['A', 'B', 'C', 'D', 'E'] }))
      .toMatch(/挂靠.*1–10/)
  })
})

describe('error texts', () => {
  it('conflictText turns 409 codes into Chinese and passes a backend sentence through', () => {
    expect(conflictText('card_reviewed')).toBe('这张卡已经审定过了，要改经验请到「我的知识」改版本')
    expect(conflictText('discussion_busy')).toBe('上一个问题还在回答')
    expect(conflictText('draft_exists')).toBe('这张卡已有成功的草稿')
    expect(conflictText('token_budget')).toBe('超出 token 上限')
    expect(conflictText('agent_unavailable: quota_exhausted')).toBe('Agent 不可用：额度用尽')
    expect(conflictText('agent_unavailable')).toBe('Agent 不可用')
    expect(conflictText('knowledge_stale: 这条知识已更新到第 3 版，请刷新后再改')).toBe('这条知识已更新到第 3 版，请刷新后再改')
    expect(conflictText('something_new')).toBe('something_new')
  })
  it('growthError reads migration 027 as exactly that sentence', () => {
    expect(growthError(new WorkbenchError('迁移 027 未执行', 503))).toBe('迁移 027 未执行')
    expect(growthError(new WorkbenchError('migration_027_missing', 503))).toBe('迁移 027 未执行')
    expect(growthError(new WorkbenchError('down', 503))).toBe('数据库未就绪：down')
    expect(growthError(new WorkbenchError('discussion_busy', 409))).toBe('上一个问题还在回答')
    expect(growthError(new WorkbenchError('bad', 400))).toBe('输入有误：bad')
    expect(growthError(new Error('boom'))).toBe('boom')
  })
})

describe('idempotentRequests', () => {
  it('reuses the id for the same payload, renews it for another one or after a success', () => {
    const r = idempotentRequests()
    const a = r.idFor({ x: 1 })
    expect(r.idFor({ x: 1 })).toBe(a)
    const b = r.idFor({ x: 2 })
    expect(b).not.toBe(a)
    r.done()
    expect(r.idFor({ x: 2 })).not.toBe(b)
  })
})

describe('small helpers', () => {
  it('refKind', () => {
    expect(['call:1', 'fact:plans', 'know:3@1', 'concept:plan.stop@1', 'user:7', 'zzz'].map(refKind))
      .toEqual(['call', 'fact', 'know', 'concept', 'user', 'other'])
  })
  it('changedFields lists the changed fields in form order', () => {
    const a = { title: 't', body: 'b', scope: 's', counter_examples: '', concepts: ['a.b'], tickers: ['X'] }
    expect(changedFields(a, a)).toEqual([])
    expect(changedFields(a, { ...a, scope: 'n', tickers: ['X', 'Y'], title: 'u' })).toEqual(['标题', '适用范围', '标的'])
  })
  it('sampleLine gives a mean only from min_sample results on', () => {
    const r = (v: number | null) => (v === null ? '—' : `${v}R`)
    expect(sampleLine({ count: 6, determined: 5, expired: 1, r_mean: 0.5, r_median: 0.4 }, 5, r))
      .toBe('样本 6 个单元 · 有结果 5 · 过期 1 · 均值 0.5R · 中位 0.4R')
    expect(sampleLine({ count: 4, determined: 4, expired: 0, r_mean: null, r_median: null }, 5, r))
      .toBe('样本 4 个单元 · 有结果 4 · 过期 0 · 少于 5 个不给均值')
  })
})
