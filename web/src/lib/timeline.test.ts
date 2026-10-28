import { describe, expect, it } from 'vitest'
import {
  CONDITION_RESULT_TEXT, DECIDED_BY_TEXT, MODE_TEXT, ORIGIN_TEXT, OUTCOME_TEXT, SIGNAL_TEXT,
  conditionText, recheckConflictText, revisionFailureText, staleText, staleVersion,
} from './timeline'
import { WorkbenchError } from './workbench'

// 模板与后端 investment_assistant/workbench/agent/conditions.py 的 CONDITIONS / describe 逐字一致。
describe('conditionText', () => {
  it.each([
    ['close_below', { price: '95.5' }, '收盘跌破 95.50'],
    ['close_above', { price: 112 }, '收盘突破 112.00'],
    ['no_entry_by', { date: '2026-11-03' }, '2026-11-03 收盘前未进入入场区'],
    ['no_entry_before_earnings', {}, '财报前未进入入场区'],
    ['earnings_within', { sessions: 3 }, '距财报不足 3 个交易日'],
    ['regime_is', { label: 'risk_off' }, '区制变为 risk_off'],
    ['sector_weak', {}, '所属行业转弱'],
    ['rs_below', { window: 20, value: -0.1 }, '相对 SPY 20 日强弱低于 -0.1'],
    ['new_filing', { form: '8-K' }, '出现新的 8-K'],
    ['date_reached', { date: '2026-11-10' }, '到 2026-11-10 再看'],
    ['next_session', {}, '下一交易日'],
  ])('%s', (kind, params, text) => {
    expect(conditionText(kind, params)).toBe(text)
  })

  it('rounds prices half up to cents like Decimal.quantize', () => {
    expect(conditionText('close_below', { price: '1.005' })).toBe('收盘跌破 1.01')
    expect(conditionText('close_below', { price: '94' })).toBe('收盘跌破 94.00')
  })

  it('formats rs values like Python {:g} and falls back to the kind for unknown conditions', () => {
    expect(conditionText('rs_below', { window: 60, value: 0.25 })).toBe('相对 SPY 60 日强弱低于 0.25')
    expect(conditionText('rs_below', { window: 60, value: 0 })).toBe('相对 SPY 60 日强弱低于 0')
    expect(conditionText('mystery', { a: 1 })).toBe('mystery')
  })
})

describe('texts', () => {
  it('match the spec labels', () => {
    expect(OUTCOME_TEXT).toEqual({ maintain: '维持', revise: '修订', invalidate: '作废', skipped: '跳过', error: '出错' })
    expect(DECIDED_BY_TEXT).toEqual({ agent: 'Agent', host: '系统规则' })
    expect(MODE_TEXT).toEqual({ entry: '入场期', holding: '持仓期' })
    expect(ORIGIN_TEXT).toEqual({ signal: '信号日', review: '每日复查', recheck: '重新复查' })
    expect(CONDITION_RESULT_TEXT).toEqual({ met: '成立', not_met: '未成立', unknown: '无法判定' })
    expect(Object.keys(SIGNAL_TEXT).sort()).toEqual(['abnormal_move', 'expiry_near', 'new_8k', 'regime_change',
      'stop_touched', 't1_touched', 'user_input'])
  })

  it('reads the stale version from the reason code or the sentence', () => {
    expect(staleVersion(new WorkbenchError('agent_plan_stale: Agent 计划已更新到第 2 版，请刷新后再决定', 409))).toBe(2)
    expect(staleVersion(new WorkbenchError('agent_plan_stale: 3', 409))).toBe(3)
    expect(staleVersion(new WorkbenchError('Agent 计划已更新到第 4 版，请刷新后再决定', 409))).toBe(4)
    expect(staleVersion(new WorkbenchError('newer decision', 409))).toBeNull()
    expect(staleVersion(new WorkbenchError('agent_plan_stale: 2', 400))).toBeNull()
    expect(staleText(2)).toBe('Agent 计划已更新到第 2 版，请刷新后再决定')
  })

  it('explains failed revisions and recheck conflicts', () => {
    expect(revisionFailureText({ outcome: 'revise', new_plan_id: null, revision_status: 'rejected: changes_mismatch' }, 1))
      .toBe('Agent 建议修订，但修订未通过校验（变化说明与实际差异不符），当前仍为第 1 版')
    expect(revisionFailureText({ outcome: 'revise', new_plan_id: null, revision_status: 'plan_invalid: no_room' }, 0))
      .toBe('Agent 建议修订，但修订未通过校验（修订版按规则作废：no_room），当前仍为第 0 版')
    expect(revisionFailureText({ outcome: 'revise', new_plan_id: 'p2', revision_status: null }, 1)).toBeNull()
    expect(revisionFailureText({ outcome: 'maintain', new_plan_id: null, revision_status: null }, 1)).toBeNull()
    expect(recheckConflictText('review_in_progress')).toBe('正在复查')
    expect(recheckConflictText('agent_unavailable: disabled')).toBe('Agent 不可用：已关闭')
    expect(recheckConflictText('chain_not_active')).toContain('不在入场期或持仓期')
  })
})
