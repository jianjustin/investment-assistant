import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import Knowledge from './Knowledge.svelte'
import * as api from '../lib/api'
import { WorkbenchError } from '../lib/workbench'
import { entry, itemView, knowledgeDraft, perf } from '../lib/growth-fixtures'
import { resetConceptIndex } from '../lib/knowledge'
import type { ConceptCard, ConceptsView, PrinciplesView, RunOverviewView } from '../lib/knowledge'

const GROUPS = [
  ['family', '数据族'], ['indicator', '指标'], ['rule', '规则 v1'], ['plan', '规则计划 `plan-1`'],
  ['agent', 'Agent 计划'], ['review', '复盘'], ['system', '系统运作'],
] as const
const concept = (id: string, title: string, summary: string, over: Record<string, unknown> = {}) => {
  const group = id.split('.')[0]
  return { id, ref: `concept:${id}@1`, title, group, version: 1, applies_to: ['plan-1'], summary, related: [], ...over }
}
const CONCEPTS = [
  concept('family.bars', '日线', '拆股调整的日线价量。', { applies_to: [] }),
  concept('indicator.atr14', '14 日 ATR', '14 日平均真实波幅。'),
  concept('rule.trend_reclaim', '趋势回踩修复', '收盘重新站上 MA20。', { applies_to: ['rules-1'] }),
  concept('plan.stop', '止损', '参考价减 2 倍 ATR14，四舍五入到分。'),
  concept('plan.target1', '第一目标', '参考价加 4 倍 ATR14。'),
  concept('agent.thesis', '论点', 'Agent 的买入理由。', { applies_to: ['agent-2'] }),
  concept('review.r_multiple', 'R 倍数', '盈亏除以初始风险。', { applies_to: ['review-6'] }),
  concept('system.gate_hold', '证据状态', '所有规则与 Agent 都未经验证。', { applies_to: [] }),
]
const index = (): ConceptsView => ({
  knowledge_version: 'knowledge-1',
  groups: GROUPS.map(([id, title]) => ({ id, title, count: CONCEPTS.filter(c => c.group === id).length })),
  concepts: CONCEPTS,
})
const card = (over: Partial<ConceptCard> = {}): ConceptCard => ({
  ...(CONCEPTS[3] as any), html: '<h2>是什么</h2><p>止损是<a href="#knowledge/indicator.atr14" data-concept="indicator.atr14">ATR</a>的两倍。</p>',
  related_cards: [{ id: 'indicator.atr14', title: '14 日 ATR' }, { id: 'plan.target1', title: '第一目标' }],
  backlinks: [{ id: 'rule.trend_reclaim', title: '趋势回踩修复' }], stale: null, ...over,
})
const line = (id: string, title: string) => ({
  id, title, purpose: '', status: 'success', status_text: '成功', sentence: `句子-${id}`, input_count: 3,
  output_count: 2, skips: [], failures: [], degradations: [], reason: null, reason_text: null, duration_ms: 10, concepts: [],
})
const overview = (session = '2026-10-27'): RunOverviewView => ({
  session, ready: true, note: null, runs: [], selected_run_id: 'r', headline: '定时运行',
  stages: [line('collect', '数据采集'), line('plan', '规则计划')],
})
const principles = (): PrinciplesView => ({
  title: '系统每天怎么跑', version: 1, sections: [
    { heading: '系统做什么、不做什么', html: '<p>出研究候选。</p>', stage: null, concepts: ['system.gate_hold'] },
    { heading: '① 数据采集', html: '<p>采集六个数据族。<a href="#today" data-stage="collect">当天这一步</a></p>', stage: 'collect', concepts: ['family.bars'] },
    { heading: '⑤ 规则计划', html: '<p>plan-1 公式。</p>', stage: 'plan', concepts: ['plan.stop'] },
  ],
})
const failure = (status: number, message: string, problems: string[] = []) =>
  Object.assign(new Error(message), { status, problems })

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockResolvedValue(index())
  vi.spyOn(api, 'getConcept').mockResolvedValue(card())
  vi.spyOn(api, 'getPrinciples').mockResolvedValue(principles())
  vi.spyOn(api, 'getRunOverview').mockImplementation(async (session?: string) => overview(session ?? '2026-10-27'))
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('Knowledge browse', () => {
  it('browse lists seven groups in order with counts', async () => {
    render(Knowledge, {})
    const headings = await screen.findAllByRole('heading', { level: 2 })
    expect(headings.map(h => h.textContent!.trim())).toEqual([
      '数据族 · 1 张', '指标 · 1 张', '规则 v1 · 1 张', '规则计划 plan-1 · 2 张',
      'Agent 计划 · 1 张', '复盘 · 1 张', '系统运作 · 1 张',
    ])
    expect(screen.getByText(/^概念卡随代码版本更新/)).toHaveTextContent('knowledge-1；所有规则与 Agent 都未经验证')
    const stop = screen.getByRole('link', { name: '止损' })
    expect(stop).toHaveAttribute('href', '#knowledge/plan.stop')
    const row = stop.closest('li')!
    expect(row).toHaveTextContent('plan.stop')
    expect(row).toHaveTextContent('参考价减 2 倍 ATR14')
    expect(row).toHaveTextContent('plan-1')
  })

  it('filter narrows by id, title and summary', async () => {
    render(Knowledge, {})
    await screen.findByRole('link', { name: '止损' })
    const input = screen.getByLabelText('过滤')
    await fireEvent.input(input, { target: { value: 'atr' } })
    // id match (indicator.atr14), summary match (plan.stop / plan.target1 mention ATR14)
    expect(screen.getAllByRole('listitem').map(li => li.querySelector('a')!.textContent)).toEqual(
      ['14 日 ATR', '止损', '第一目标'])
    expect(screen.queryByRole('heading', { name: /数据族/ })).toBeNull()
    await fireEvent.input(input, { target: { value: '回踩' } })     // title
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    await fireEvent.input(input, { target: { value: 'gate_hold' } })    // id
    expect(screen.getByRole('link', { name: '证据状态' })).toBeInTheDocument()
    await fireEvent.input(input, { target: { value: 'zzz' } })
    expect(screen.getByText('没有匹配的概念卡')).toBeInTheDocument()
  })

  it('empty directory shows 还没有概念卡', async () => {
    vi.mocked(api.getConcepts).mockResolvedValue({ knowledge_version: 'knowledge-1', groups: [], concepts: [] })
    render(Knowledge, {})
    expect(await screen.findByText('还没有概念卡')).toBeInTheDocument()
  })

  it('503 shows first 10 problems', async () => {
    const problems = Array.from({ length: 12 }, (_, i) => `concepts/x${i}.md: 问题 ${i}`)
    vi.mocked(api.getConcepts).mockRejectedValue(failure(503, '概念卡加载失败：x', problems))
    render(Knowledge, {})
    expect(await screen.findByText('概念卡加载失败')).toBeInTheDocument()
    expect(screen.getAllByText(/^concepts\/x\d+\.md/)).toHaveLength(10)
    expect(screen.queryByText(/问题 10/)).toBeNull()
    cleanup()
    vi.mocked(api.getConcept).mockRejectedValue(failure(503, '概念卡加载失败：x', problems))
    render(Knowledge, { sub: 'plan.stop' })
    expect(await screen.findByText('概念卡加载失败')).toBeInTheDocument()
    expect(screen.getAllByText(/^concepts\/x\d+\.md/)).toHaveLength(10)
  })
})

describe('Knowledge card', () => {
  it('card page renders html, related and backlinks', async () => {
    render(Knowledge, { sub: 'plan.stop' })
    expect(await screen.findByRole('heading', { name: '止损' })).toBeInTheDocument()
    expect(api.getConcept).toHaveBeenCalledWith('plan.stop')
    expect(screen.getByText('concept:plan.stop@1')).toBeInTheDocument()
    expect(screen.getByText('参考价减 2 倍 ATR14，四舍五入到分。')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '是什么' })).toBeInTheDocument()     // from html
    expect(screen.getByRole('link', { name: 'ATR' })).toHaveAttribute('href', '#knowledge/indicator.atr14')
    const related = screen.getByRole('region', { name: '相关' })
    expect(within(related).getByRole('link', { name: '14 日 ATR' })).toHaveAttribute('href', '#knowledge/indicator.atr14')
    expect(within(related).getByRole('link', { name: '第一目标' })).toBeInTheDocument()
    const back = screen.getByRole('region', { name: '被这些卡提到' })
    expect(within(back).getByRole('link', { name: '趋势回踩修复' })).toHaveAttribute('href', '#knowledge/rule.trend_reclaim')
    expect(screen.getByRole('link', { name: '返回概念列表' })).toHaveAttribute('href', '#knowledge')
  })

  it('stale note', async () => {
    vi.mocked(api.getConcept).mockResolvedValue(card({
      stale: { requested: 1, current: 2, note: '该引用指向第 1 版，当前为第 2 版；概念卡不保存旧版正文' } }))
    render(Knowledge, { sub: 'plan.stop@1' })
    expect(await screen.findByText('该引用指向第 1 版，当前为第 2 版；概念卡不保存旧版正文')).toBeInTheDocument()
    expect(api.getConcept).toHaveBeenCalledWith('plan.stop@1')
  })

  it('404 shows 没有这张概念卡', async () => {
    vi.mocked(api.getConcept).mockRejectedValue(failure(404, '没有这张概念卡：plan.nope'))
    render(Knowledge, { sub: 'plan.nope@2' })
    expect(await screen.findByText('没有这张概念卡：plan.nope')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回概念列表' })).toHaveAttribute('href', '#knowledge')
  })

  it('reloads when the route changes', async () => {
    const { rerender } = render(Knowledge, { sub: 'plan.stop' })
    await screen.findByRole('heading', { name: '止损' })
    vi.mocked(api.getConcept).mockResolvedValue(card({ id: 'plan.target1', title: '第一目标', summary: '加 4 倍。' }))
    await rerender({ sub: 'plan.target1' })
    expect(await screen.findByRole('heading', { name: '第一目标' })).toBeInTheDocument()
    expect(api.getConcept).toHaveBeenLastCalledWith('plan.target1')
  })
})

describe('Knowledge body and tabs', () => {
  it('body html still rendered in .knowledge-body', async () => {
    const { container } = render(Knowledge, { sub: 'plan.stop' })
    await screen.findByRole('heading', { name: '止损' })
    const body = container.querySelector('.knowledge-body')!
    expect(body.querySelector('h2')).toHaveTextContent('是什么')
    expect(body.querySelector('a[href="#knowledge/indicator.atr14"]')).toHaveTextContent('ATR')
    expect(container.querySelector('style')).toBeNull()          // typography lives in styles/knowledge-body.css
    cleanup()
    const principlesView = render(Knowledge, { sub: 'principles' })
    await screen.findByRole('heading', { name: '系统每天怎么跑' })
    const bodies = principlesView.container.querySelectorAll('.knowledge-body')
    expect(bodies).toHaveLength(3)
    expect(bodies[0]).toHaveTextContent('出研究候选。')
  })

  it('concept, principles and mine are route tabs (links, aria-current)', async () => {
    const view = render(Knowledge, {})
    await screen.findByRole('link', { name: '止损' })
    const tabs = () => within(screen.getByRole('navigation', { name: '知识' }))
    expect(tabs().getAllByRole('link').map(a => [a.textContent!.trim(), a.getAttribute('href')])).toEqual([
      ['概念', '#knowledge'], ['原理', '#knowledge/principles'], ['我的知识', '#knowledge/mine']])
    expect(tabs().getByRole('link', { name: '概念' })).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByRole('tablist')).toBeNull()
    await view.rerender({ sub: 'principles' })
    expect(tabs().getByRole('link', { name: '原理' })).toHaveAttribute('aria-current', 'page')
    expect(tabs().getByRole('link', { name: '概念' })).not.toHaveAttribute('aria-current')
  })
})

describe('Knowledge principles', () => {
  it('principles render sections with 当天这一步 box for stage sections', async () => {
    render(Knowledge, { sub: 'principles' })
    expect(await screen.findByRole('heading', { name: '系统每天怎么跑' })).toBeInTheDocument()
    const sections = await screen.findAllByRole('region', { name: /^(系统做什么|①|⑤)/ })
    expect(sections.map(s => s.getAttribute('aria-label'))).toEqual(['系统做什么、不做什么', '① 数据采集', '⑤ 规则计划'])
    expect(screen.getByText('出研究候选。')).toBeInTheDocument()
    // only the two stage sections carry the box; the plain one does not
    expect(within(sections[0]).queryByTestId('stage-box')).toBeNull()
    const box = await within(sections[1]).findByTestId('stage-box')
    expect(box).toHaveTextContent('当天这一步（2026-10-27）')
    expect(box).toHaveTextContent('句子-collect')
    expect(within(box).getByRole('link', { name: /在『今日』看完整运行一览/ })).toHaveAttribute('href', '#today')
    expect(within(sections[2]).getByTestId('stage-box')).toHaveTextContent('句子-plan')
    expect(within(sections[2]).getByTestId('stage-box')).not.toHaveTextContent('句子-collect')
    // the in-body link comes from the API and points at #today
    expect(within(sections[1]).getByRole('link', { name: '当天这一步' })).toHaveAttribute('href', '#today')
  })

  it('principles date change reloads overview only', async () => {
    render(Knowledge, { sub: 'principles' })
    await screen.findAllByTestId('stage-box')
    await waitFor(() => expect(api.getRunOverview).toHaveBeenCalled())
    expect(api.getPrinciples).toHaveBeenCalledTimes(1)
    vi.mocked(api.getRunOverview).mockClear()
    await fireEvent.change(screen.getByLabelText('日期'), { target: { value: '2026-10-24' } })
    await waitFor(() => expect(api.getRunOverview).toHaveBeenCalledWith('2026-10-24', undefined))
    expect(api.getPrinciples).toHaveBeenCalledTimes(1)
    expect(await screen.findAllByText('当天这一步（2026-10-24）')).toHaveLength(2)
  })

  it('principles 404 and 503', async () => {
    vi.mocked(api.getPrinciples).mockRejectedValue(failure(404, '没有原理页'))
    render(Knowledge, { sub: 'principles' })
    expect(await screen.findByText('还没有原理页')).toBeInTheDocument()
    cleanup()
    vi.mocked(api.getPrinciples).mockRejectedValue(failure(503, '概念卡加载失败：x', ['concepts/a.md: 坏']))
    render(Knowledge, { sub: 'principles' })
    expect(await screen.findByText('概念卡加载失败')).toBeInTheDocument()
    expect(screen.getByText('concepts/a.md: 坏')).toBeInTheDocument()
  })
})

// ---- v2.7: 我的知识 ----

describe('我的知识', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getMyKnowledge').mockResolvedValue({ items: [entry()] })
    vi.spyOn(api, 'getKnowledgeDrafts').mockResolvedValue({ drafts: [] })
    vi.spyOn(api, 'getKnowledgeItem').mockResolvedValue(itemView())
    vi.spyOn(api, 'getKnowledgePerformance').mockResolvedValue(perf())
  })

  it('side entry 我的知识', async () => {
    render(Knowledge, { sub: undefined })
    expect(await screen.findByRole('link', { name: '我的知识' })).toHaveAttribute('href', '#knowledge/mine')
  })

  it('#knowledge/mine lists my knowledge', async () => {
    render(Knowledge, { sub: 'mine' })
    expect(await screen.findByRole('heading', { name: '我的知识' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: '回踩别追' })).toHaveAttribute('href', '#knowledge/mine/3')
  })

  it('#knowledge/mine/3@2 opens version 2 of entry 3, and plain /3 the latest', async () => {
    const first = render(Knowledge, { sub: 'mine/3@2' })
    await screen.findByRole('heading', { name: /回踩别追/ })
    expect(api.getKnowledgeItem).toHaveBeenCalledWith(3, 2)
    first.unmount()
    render(Knowledge, { sub: 'mine/3' })
    await waitFor(() => expect(api.getKnowledgeItem).toHaveBeenLastCalledWith(3, undefined))
  })

  it('#knowledge/mine/new writes a first version, prefilled from the ticker in the hash', async () => {
    history.replaceState(null, '', '#knowledge/mine/new?ticker=NVDA')
    const post = vi.spyOn(api, 'postMyKnowledge').mockResolvedValue({ status: 'created', record: { id: 9 } } as any)
    render(Knowledge, { sub: 'mine/new' })
    expect(await screen.findByRole('button', { name: '移除标的 NVDA' })).toBeInTheDocument()
    await fireEvent.input(screen.getByLabelText('标题'), { target: { value: '新经验' } })
    await fireEvent.input(screen.getByLabelText('正文'), { target: { value: '正文' } })
    await fireEvent.input(screen.getByLabelText('适用范围'), { target: { value: '范围' } })
    await fireEvent.click(screen.getByRole('button', { name: '提交' }))
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post.mock.calls[0][0]).toMatchObject({ title: '新经验', body: '正文', scope: '范围', tickers: ['NVDA'], concepts: [] })
    expect(post.mock.calls[0][0].request_id).toMatch(/^[0-9a-f-]{36}$/)
    await waitFor(() => expect(location.hash).toBe('#knowledge/mine/9'))
  })

  it('drafts page: discussion drafts can be adopted (editable) or dismissed; card drafts only link to the card', async () => {
    vi.mocked(api.getKnowledgeDrafts).mockResolvedValue({ drafts: [
      knowledgeDraft(),
      knowledgeDraft({ id: 202, origin: 'review_card', card_id: 12, discussion_id: null, discussion_turn_id: null, title: '卡上的草稿' }),
    ] })
    const verdict = vi.spyOn(api, 'postDraftVerdict').mockResolvedValue({ status: 'created' } as any)
    render(Knowledge, { sub: 'mine/drafts' })
    expect(await screen.findByRole('heading', { name: '待审定的草稿' })).toBeInTheDocument()
    expect(api.getKnowledgeDrafts).toHaveBeenCalledWith('open')
    const card = (await screen.findByText('卡上的草稿')).closest('li')!
    expect(within(card).getByRole('link', { name: '到复盘卡审定' })).toHaveAttribute('href', '#review/cards/12')
    expect(within(card).queryByRole('button', { name: '采纳' })).toBeNull()
    const draft = screen.getByText('止损别拖').closest('li')!
    await fireEvent.click(within(draft).getByRole('button', { name: '采纳' }))
    await fireEvent.input(within(draft).getByLabelText('标题'), { target: { value: '止损别拖延' } })
    await fireEvent.click(within(draft).getByRole('button', { name: '确认采纳' }))
    await waitFor(() => expect(verdict).toHaveBeenCalledTimes(1))
    expect(verdict.mock.calls[0][0]).toBe(201)
    expect(verdict.mock.calls[0][1]).toMatchObject({ action: 'approve', title: '止损别拖延', concepts: ['plan.stop'], tickers: ['NVDA'] })
    expect('base_version' in verdict.mock.calls[0][1]).toBe(false)
    await fireEvent.click(within(draft).getByRole('button', { name: '不采纳' }))
    await waitFor(() => expect(verdict).toHaveBeenCalledTimes(2))
    expect(verdict.mock.calls[1][1].action).toBe('dismiss')
  })

  it('a draft that rewrites an entry sends the base version it was written against', async () => {
    vi.mocked(api.getKnowledgeDrafts).mockResolvedValue({ drafts: [
      knowledgeDraft({ target_knowledge_id: 3, target_version: 2 })] })
    const verdict = vi.spyOn(api, 'postDraftVerdict').mockResolvedValue({ status: 'created' } as any)
    render(Knowledge, { sub: 'mine/drafts' })
    const draft = (await screen.findByText('止损别拖')).closest('li')!
    expect(draft).toHaveTextContent('改写 know:3@2')
    await fireEvent.click(within(draft).getByRole('button', { name: '采纳' }))
    await fireEvent.click(within(draft).getByRole('button', { name: '确认采纳' }))
    await waitFor(() => expect(verdict).toHaveBeenCalledTimes(1))
    expect(verdict.mock.calls[0][1]).toMatchObject({ action: 'approve', base_version: 2 })
  })

  it('a rewrite draft whose target moved on cannot be adopted, only dismissed', async () => {
    vi.mocked(api.getKnowledgeDrafts).mockResolvedValue({ drafts: [
      knowledgeDraft({ target_knowledge_id: 3, target_version: 2, target_current_version: 4 })] })
    const verdict = vi.spyOn(api, 'postDraftVerdict').mockResolvedValue({ status: 'created' } as any)
    render(Knowledge, { sub: 'mine/drafts' })
    const draft = (await screen.findByText('止损别拖')).closest('li')!
    const hint = '草稿基于第 2 版，现在是第 4 版：只能不采纳，或在讨论里基于第 4 版重新改写'
    expect(draft).toHaveTextContent(hint)
    expect(within(draft).getByRole('button', { name: '采纳' })).toBeDisabled()
    await fireEvent.click(within(draft).getByRole('button', { name: '采纳' }))
    expect(within(draft).queryByRole('button', { name: '确认采纳' })).toBeNull()
    await fireEvent.click(within(draft).getByRole('button', { name: '不采纳' }))
    await waitFor(() => expect(verdict).toHaveBeenCalledTimes(1))
    expect(verdict.mock.calls[0][1].action).toBe('dismiss')
  })

  it('a backend stale sentence on adopt is shown as it is', async () => {
    vi.mocked(api.getKnowledgeDrafts).mockResolvedValue({ drafts: [
      knowledgeDraft({ target_knowledge_id: 3, target_version: 2, target_current_version: 2 })] })   // moved after loading
    const sentence = '草稿基于第 2 版，现在是第 3 版：只能不采纳，或在讨论里基于第 3 版重新改写'
    vi.spyOn(api, 'postDraftVerdict').mockRejectedValue(new WorkbenchError(`knowledge_stale: ${sentence}`, 409))
    render(Knowledge, { sub: 'mine/drafts' })
    const draft = (await screen.findByText('止损别拖')).closest('li')!
    await fireEvent.click(within(draft).getByRole('button', { name: '采纳' }))
    await fireEvent.click(within(draft).getByRole('button', { name: '确认采纳' }))
    expect(await within(draft).findByText(sentence)).toBeInTheDocument()
  })

  it('concept page lists attached knowledge', async () => {
    render(Knowledge, { sub: 'plan.stop@1' })
    const section = await screen.findByRole('region', { name: '挂在这张卡上的我的知识' })
    expect(api.getMyKnowledge).toHaveBeenCalledWith({ concept: 'plan.stop', status: 'active' })
    const link = await within(section).findByRole('link', { name: '回踩别追' })
    expect(link).toHaveAttribute('href', '#knowledge/mine/3')
    expect(link.closest('li')).toHaveTextContent('第 2 版')
  })

  it('concept page without attached knowledge says so; an unreadable list stays out of the way', async () => {
    vi.mocked(api.getMyKnowledge).mockResolvedValue({ items: [] })
    const first = render(Knowledge, { sub: 'plan.stop@1' })
    expect(await screen.findByRole('region', { name: '挂在这张卡上的我的知识' })).toHaveTextContent('还没有挂在这张卡上的经验')
    first.unmount()
    vi.mocked(api.getMyKnowledge).mockRejectedValue(new WorkbenchError('迁移 027 未执行', 503))
    render(Knowledge, { sub: 'plan.stop@1' })
    await screen.findByRole('heading', { name: '止损' })
    expect(await screen.findByRole('region', { name: '挂在这张卡上的我的知识' })).toHaveTextContent('迁移 027 未执行')
    expect(screen.getByRole('heading', { name: '止损' })).toBeInTheDocument()       // the card itself is unaffected
  })

  it('migration missing note', async () => {
    vi.mocked(api.getMyKnowledge).mockRejectedValue(new WorkbenchError('迁移 027 未执行', 503))
    render(Knowledge, { sub: 'mine' })
    expect(await screen.findByText('迁移 027 未执行')).toBeInTheDocument()
  })

  it('keeps unrelated hashes working: a concept id that merely starts with mine', async () => {
    render(Knowledge, { sub: 'minefield.x@1' })
    await waitFor(() => expect(api.getConcept).toHaveBeenCalledWith('minefield.x@1'))
  })
})
