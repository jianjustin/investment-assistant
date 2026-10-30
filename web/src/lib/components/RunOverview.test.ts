import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/svelte'
import RunOverview from './RunOverview.svelte'
import * as api from '../api'
import { resetConceptIndex } from '../knowledge'
import type { RunOverviewView, StageLine } from '../knowledge'

const IDS = ['collect', 'screen', 'regime', 'signals', 'plan', 'agent', 'review', 'push']
const TITLES: Record<string, string> = {
  collect: '数据采集', screen: '筛选', regime: '市场环境', signals: '信号', plan: '规则计划', agent: 'Agent',
  review: '每日复查', push: '推送',
}
const line = (id: string, over: Partial<StageLine> = {}): StageLine => ({
  id, title: TITLES[id], purpose: `用途-${id}`, status: 'success', status_text: '成功', sentence: `句子-${id}`,
  input_count: 10, output_count: 8, skips: [], failures: [], degradations: [], reason: null, reason_text: null,
  duration_ms: 1234, concepts: [], ...over,
})
const overview = (over: Partial<RunOverviewView> = {}): RunOverviewView => ({
  session: '2026-10-27', ready: true, note: null,
  runs: [{ run_id: 'run-1', trigger: 'scheduled', trigger_text: '定时', stages_version: 'stages-2',
           started_at: '2026-10-27T22:30:00Z', finished_at: '2026-10-27T22:33:12Z', rows: 8, closed: false }],
  selected_run_id: 'run-1',
  headline: '定时运行 · 06:30 开始 · 用时 3 分 12 秒 · 8 个阶段：成功 8',
  stages: IDS.map(id => line(id)), ...over,
})

beforeEach(() => {
  resetConceptIndex()
  vi.spyOn(api, 'getConcepts').mockRejectedValue(new Error('offline'))
  vi.spyOn(api, 'getRunOverview').mockResolvedValue(overview())
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('RunOverview', () => {
  it('renders eight lines with status text, sentence and counts', async () => {
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({ stages: IDS.map(id => id === 'collect'
      ? line(id, { status: 'partial', status_text: '部分失败', sentence: '采集 141/174 个目标；1 处失败',
                   input_count: 174, output_count: 141, duration_ms: 65000 })
      : line(id)) }))
    render(RunOverview, {})
    expect(await screen.findByText('定时运行 · 06:30 开始 · 用时 3 分 12 秒 · 8 个阶段：成功 8')).toBeInTheDocument()
    const lines = await screen.findAllByRole('listitem')
    expect(lines).toHaveLength(8)
    expect(lines[0]).toHaveTextContent('数据采集')
    expect(lines[0]).toHaveTextContent('部分失败')
    expect(lines[0]).toHaveTextContent('采集 141/174 个目标；1 处失败')
    expect(lines[0]).toHaveTextContent('输入 174 · 产出 141')
    expect(lines[0]).toHaveTextContent('1 分 5 秒')
    expect(lines[1]).toHaveTextContent('输入 10 · 产出 8')
    expect(lines[7]).toHaveTextContent('推送')
    expect(api.getRunOverview).toHaveBeenCalledWith(undefined, undefined)
  })

  it('运行详情 link with selected_run_id', async () => {
    const id = 'workbench-20261027223000-0a1b2c3d'
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({
      runs: [{ run_id: id, trigger: 'scheduled', trigger_text: '定时', stages_version: 'stages-2',
               started_at: '2026-10-27T22:30:00Z', finished_at: '2026-10-27T22:33:12Z', rows: 8, closed: false }],
      selected_run_id: id }))
    render(RunOverview, {})
    const link = await screen.findByRole('link', { name: '运行详情' })
    expect(link.getAttribute('href')).toBe(`#tools/runs/${id}`)
    // the link sits beside the title, before the headline
    const header = link.closest('header')!
    expect(header.querySelector('h2')!.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('no 运行详情 link without a run, or with an id the detail page cannot take', async () => {
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({ selected_run_id: null, runs: [] }))
    const first = render(RunOverview, {})
    await first.findByText('定时运行 · 06:30 开始 · 用时 3 分 12 秒 · 8 个阶段：成功 8')
    expect(screen.queryByRole('link', { name: '运行详情' })).toBeNull()
    first.unmount()
    vi.mocked(api.getRunOverview).mockResolvedValue(overview())       // selected_run_id: 'run-1'
    render(RunOverview, {})
    await screen.findByText('定时运行 · 06:30 开始 · 用时 3 分 12 秒 · 8 个阶段：成功 8')
    expect(screen.queryByRole('link', { name: '运行详情' })).toBeNull()
  })

  it('each stage status is a node StatusPill with the backend wording; missing / not_recorded borrow a tone', async () => {
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({ stages: IDS.map(id =>
      id === 'collect' ? line(id, { status: 'partial', status_text: '部分失败' })
      : id === 'review' ? line(id, { status: 'not_recorded', status_text: '未记录' })
      : id === 'agent' ? line(id, { status: 'missing', status_text: '缺失' }) : line(id)) }))
    render(RunOverview, {})
    const rows = await screen.findAllByRole('listitem')
    const pill = (row: HTMLElement) => row.querySelector('[data-domain="node"]')!
    expect(pill(rows[0])).toHaveAttribute('data-tone', 'warn')
    expect(pill(rows[0])).toHaveTextContent('部分失败')
    expect(pill(rows[1])).toHaveAttribute('data-tone', 'success')
    expect(pill(rows[6])).toHaveAttribute('data-tone', 'neutral')
    expect(pill(rows[6])).toHaveTextContent('未记录')
    expect(pill(rows[5])).toHaveAttribute('data-tone', 'danger')
    expect(pill(rows[5])).toHaveTextContent('缺失')
  })

  it('a missing table is 没算 with its reason, an empty day is plain empty text (no badge)', async () => {
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({
      ready: false, note: '迁移 025 未执行，暂无阶段证据', stages: [], runs: [], selected_run_id: null, headline: '' }))
    const first = render(RunOverview, {})
    expect(await screen.findByText('迁移 025 未执行，暂无阶段证据')).toBeInTheDocument()
    expect(screen.getByText('没算')).toBeInTheDocument()
    first.unmount()
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({
      note: '这一天没有阶段证据：当天没有运行', stages: [], runs: [], selected_run_id: null, headline: '' }))
    render(RunOverview, {})
    expect(await screen.findByText('这一天没有阶段证据：当天没有运行')).toBeInTheDocument()
    expect(screen.queryByText('没算')).toBeNull()
  })

  it('stages-1 placeholder line', async () => {
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({ stages: IDS.map(id => id === 'review'
      ? line(id, { status: 'not_recorded', status_text: '未记录', input_count: null, output_count: null,
                   duration_ms: null, sentence: '这次运行按 stages-1 记账（早于 v2.5 或迁移 026 未执行），没有每日复查阶段' })
      : line(id)) }))
    render(RunOverview, {})
    const row = (await screen.findAllByRole('listitem'))[6]
    expect(row).toHaveTextContent('未记录')
    expect(row).toHaveTextContent('这次运行按 stages-1 记账')
    expect(row).toHaveTextContent('输入 — · 产出 —')
  })

  it('not ready and no-evidence notes', async () => {
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({
      ready: false, note: '迁移 025 未执行，暂无阶段证据', stages: [], runs: [], selected_run_id: null, headline: '' }))
    render(RunOverview, {})
    expect(await screen.findByText('迁移 025 未执行，暂无阶段证据')).toBeInTheDocument()
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
    cleanup()
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({
      note: '这一天没有阶段证据：当天没有运行，或运行早于 v2.4（2026-10-27 起才记录）', stages: [], runs: [],
      selected_run_id: null, headline: '' }))
    render(RunOverview, {})
    expect(await screen.findByText(/这一天没有阶段证据/)).toBeInTheDocument()
  })

  it('date input reloads', async () => {
    render(RunOverview, {})
    await screen.findAllByRole('listitem')
    const input = screen.getByLabelText('日期') as HTMLInputElement
    expect(input.value).toBe('2026-10-27')
    await fireEvent.change(input, { target: { value: '2026-10-24' } })
    await waitFor(() => expect(api.getRunOverview).toHaveBeenLastCalledWith('2026-10-24', undefined))
  })

  it('run switcher when several runs', async () => {
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({
      runs: [
        { run_id: 'run-2', trigger: 'manual', trigger_text: '手动', stages_version: 'stages-2',
          started_at: '2026-10-27T23:30:00Z', finished_at: '2026-10-27T23:31:00Z', rows: 8, closed: false },
        { run_id: 'run-1', trigger: 'scheduled', trigger_text: '定时', stages_version: 'stages-2',
          started_at: '2026-10-27T22:30:00Z', finished_at: '2026-10-27T22:33:12Z', rows: 8, closed: false },
        { run_id: 'run-0', trigger: 'scheduled', trigger_text: '休市', stages_version: 'stages-2',
          started_at: '2026-10-28T10:30:00Z', finished_at: '2026-10-28T10:30:05Z', rows: 8, closed: true },
      ], selected_run_id: 'run-2' }))
    render(RunOverview, {})
    const select = (await screen.findByLabelText('运行')) as HTMLSelectElement
    expect([...select.options].map(o => o.value)).toEqual(['run-2', 'run-1', 'run-0'])
    expect(select.value).toBe('run-2')
    expect(select.options[0].textContent).toMatch(/^手动 · /)
    expect(select.options[2].textContent).toMatch(/^休市 · /)
    await fireEvent.change(select, { target: { value: 'run-1' } })
    await waitFor(() => expect(api.getRunOverview).toHaveBeenLastCalledWith(undefined, 'run-1'))
  })

  it('no switcher with a single run', async () => {
    render(RunOverview, {})
    await screen.findAllByRole('listitem')
    expect(screen.queryByLabelText('运行')).toBeNull()
    expect(screen.getByRole('link', { name: '原理' })).toHaveAttribute('href', '#knowledge/principles')
  })

  it('expands skips with samples', async () => {
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({ stages: IDS.map(id => id === 'agent'
      ? line(id, { status: 'degraded', status_text: '降级', sentence: 'Agent 处理 3 个单元',
          skips: [{ reason: 'token_budget', text: '超出 token 上限', count: 2, samples: ['ABC', 'XYZ'] }],
          failures: [{ target: 'NVDA', reason: 'model_error' }],
          degradations: [{ kind: 'agent_unavailable', text: 'Agent 不可用', detail: '未配置' }] })
      : line(id)) }))
    render(RunOverview, {})
    const row = (await screen.findAllByRole('listitem'))[5]
    expect(within(row).queryByText(/样本/)).toBeNull()
    const toggle = within(row).getByRole('button', { name: '展开明细' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    await fireEvent.click(toggle)
    expect(within(row).getByText('超出 token 上限 × 2（样本：ABC、XYZ）')).toBeInTheDocument()
    expect(within(row).getByText('NVDA：model_error')).toBeInTheDocument()
    expect(within(row).getByText('Agent 不可用：未配置')).toBeInTheDocument()
    // lines without anything to expand have no toggle
    expect(within((await screen.findAllByRole('listitem'))[0]).queryByRole('button', { name: '展开明细' })).toBeNull()
  })

  it('expands repeated degradation kinds, identical failures and skips without key errors', async () => {
    vi.mocked(api.getRunOverview).mockResolvedValue(overview({ stages: IDS.map(id => id === 'signals'
      ? line(id, { status: 'degraded', status_text: '降级', sentence: '评估 5 只',
          skips: [{ reason: 'a', text: '原因 A', count: 1, samples: ['X'] }, { reason: 'a', text: '原因 A', count: 1, samples: ['X'] }],
          failures: [{ target: 'NVDA', reason: 'boom' }, { target: 'NVDA', reason: 'boom' }],
          degradations: [{ kind: 'conflict', text: '与已存记录不一致（未覆盖）', detail: 'NVDA' },
                         { kind: 'conflict', text: '与已存记录不一致（未覆盖）', detail: 'MU' }] })
      : line(id)) }))
    render(RunOverview, {})
    const row = (await screen.findAllByRole('listitem'))[3]
    await fireEvent.click(within(row).getByRole('button', { name: '展开明细' }))
    expect(within(row).getAllByText('NVDA：boom')).toHaveLength(2)
    expect(within(row).getByText('与已存记录不一致（未覆盖）：NVDA')).toBeInTheDocument()
    expect(within(row).getByText('与已存记录不一致（未覆盖）：MU')).toBeInTheDocument()
    expect(within(row).getAllByText('原因 A × 1（样本：X）')).toHaveLength(2)
  })

  it('onlyStage renders one line', async () => {
    render(RunOverview, { session: '2026-10-24', compact: true, onlyStage: 'plan' })
    const rows = await screen.findAllByRole('listitem')
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('规则计划')
    expect(rows[0]).toHaveTextContent('句子-plan')
    expect(screen.getByText('当天这一步（2026-10-27）')).toBeInTheDocument()
    expect(screen.queryByLabelText('日期')).toBeNull()
    expect(api.getRunOverview).toHaveBeenCalledWith('2026-10-24', undefined)
  })

  it('shares one request between lines that mount together', async () => {
    render(RunOverview, { session: '2026-10-24', compact: true, onlyStage: 'plan' })
    render(RunOverview, { session: '2026-10-24', compact: true, onlyStage: 'agent' })
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(2))
    expect(api.getRunOverview).toHaveBeenCalledTimes(1)
  })

  it('can be collapsed', async () => {
    render(RunOverview, {})
    await screen.findAllByRole('listitem')
    await fireEvent.click(screen.getByRole('button', { name: '收起运行一览' }))
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
    await fireEvent.click(screen.getByRole('button', { name: '展开运行一览' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(8)
  })

  it('shows the error when the request fails', async () => {
    vi.mocked(api.getRunOverview).mockRejectedValue(new Error('数据库未就绪'))
    render(RunOverview, {})
    expect(await screen.findByRole('alert')).toHaveTextContent('数据库未就绪')
  })
})
