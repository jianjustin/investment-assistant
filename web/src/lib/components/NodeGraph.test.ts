import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/svelte'
import NodeGraph from './NodeGraph.svelte'
import type { RunNode } from '../runs'

const TITLES: Record<string, string> = {
  sec_monitor: 'SEC 监控', collect: '数据采集', screen: '筛选', regime: '市场环境', signals: '信号', plan: '规则计划',
  agent: 'Agent', review: '每日复查', push: '推送', retro: '复盘',
}
const STAGES_4 = Object.keys(TITLES)
const STAGES_3 = ['collect', 'screen', 'regime', 'signals', 'plan', 'agent', 'review', 'retro', 'push']
const STAGES_2 = STAGES_3.filter(id => id !== 'retro')
const STAGES_1 = STAGES_2.filter(id => id !== 'review')

const node = (id: string, over: Partial<RunNode> = {}): RunNode => ({
  id, title: TITLES[id], status: 'success', reason: null, reason_text: null, attempt: 1, attempts: [],
  started_at: null, finished_at: null, duration_ms: 1234, ...over,
})
const nodes = (ids: string[], over: Record<string, Partial<RunNode>> = {}) => ids.map(id => node(id, over[id]))

const matchMedia = (matches: boolean) => vi.stubGlobal('matchMedia', (query: string) => ({
  matches, media: query, addEventListener() {}, removeEventListener() {},
}))
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('NodeGraph', () => {
  it('ten cells in order with arrows', () => {
    const { container } = render(NodeGraph, { nodes: nodes(STAGES_4), selected: null, onselect: () => {} })
    const cells = screen.getAllByRole('listitem')
    expect(cells).toHaveLength(10)
    expect(cells.map(li => li.getAttribute('data-node'))).toEqual(STAGES_4)
    expect(cells[0]).toHaveTextContent('SEC 监控')
    expect(cells[0]).toHaveTextContent('1.2 秒')
    // 九个箭头：最后一格后面没有
    expect(container.querySelectorAll('svg[data-arrow]')).toHaveLength(9)
    expect(cells[9].querySelector('svg[data-arrow]')).toBeNull()
    expect(container.querySelector('ol')?.getAttribute('data-columns')).toBe('10')
  })

  it('status text and aria-label besides color', () => {
    render(NodeGraph, {
      nodes: nodes(['collect', 'screen', 'regime', 'signals', 'plan', 'agent', 'review'], {
        collect: { status: 'success' }, screen: { status: 'degraded' }, regime: { status: 'partial' },
        signals: { status: 'failed' }, plan: { status: 'skipped' }, agent: { status: 'pending', duration_ms: null },
        review: { status: 'running', duration_ms: null },
      }),
      selected: null, onselect: () => {},
    })
    const expected: [string, string][] = [
      ['数据采集', '成功'], ['筛选', '降级'], ['市场环境', '部分成功'], ['信号', '失败'],
      ['规则计划', '跳过'], ['Agent', '未开始'], ['每日复查', '运行中'],
    ]
    for (const [title, text] of expected) {
      const button = screen.getByRole('button', { name: `${title}：${text}` })
      expect(button).toHaveTextContent(text)                          // 状态文字可见
      expect(button.querySelector('[aria-hidden="true"]')?.textContent).toBeTruthy()  // 另有图标
    }
    // 颜色取主题变量，不写死色值
    expect(screen.getByRole('button', { name: '信号：失败' }).className).toContain('border-destructive')
    expect(screen.getByRole('button', { name: 'Agent：未开始' }).className).toContain('border-dashed')
    expect(screen.getByRole('button', { name: '每日复查：运行中' }).className).toContain('node-running')
  })

  it('attempt badge ×2', () => {
    render(NodeGraph, {
      nodes: nodes(['collect', 'screen'], { collect: { attempt: 2 } }), selected: null, onselect: () => {},
    })
    const [first, second] = screen.getAllByRole('listitem')
    expect(within(first).getByText('×2')).toBeInTheDocument()
    expect(within(second).queryByText(/×/)).toBeNull()
    // 徽标不改 aria-label
    expect(screen.getByRole('button', { name: '数据采集：成功' })).toBeInTheDocument()
  })

  it('narrow layout wraps to two rows of five', () => {
    matchMedia(true)
    const { container } = render(NodeGraph, { nodes: nodes(STAGES_4), selected: null, onselect: () => {} })
    const list = container.querySelector('ol')!
    expect(list.getAttribute('data-narrow')).toBe('true')
    expect(list.getAttribute('data-columns')).toBe('5')
    expect(list.style.gridTemplateColumns).toBe('repeat(5, minmax(0, 1fr))')
    expect(screen.getAllByRole('listitem')).toHaveLength(10)
    // 第五格与第十格行尾没有箭头：10 格共 8 个箭头
    expect(container.querySelectorAll('svg[data-arrow]')).toHaveLength(8)
    expect(screen.getAllByRole('listitem')[4].querySelector('svg[data-arrow]')).toBeNull()
  })

  it('click selects node', async () => {
    const onselect = vi.fn()
    render(NodeGraph, { nodes: nodes(STAGES_4), selected: 'screen', onselect })
    expect(screen.getByRole('button', { name: '筛选：成功' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '数据采集：成功' })).toHaveAttribute('aria-pressed', 'false')
    await fireEvent.click(screen.getByRole('button', { name: '数据采集：成功' }))
    expect(onselect).toHaveBeenCalledWith('collect')
  })

  it.each([[STAGES_1, 7], [STAGES_2, 8], [STAGES_3, 9]])('old runs render 8 or 9 cells (%j draws %i)', (ids, n) => {
    const { container } = render(NodeGraph, { nodes: nodes(ids), selected: null, onselect: () => {} })
    expect(screen.getAllByRole('listitem')).toHaveLength(n)
    expect(container.querySelector('ol')?.getAttribute('data-columns')).toBe(String(n))
    expect(container.querySelectorAll('svg[data-arrow]')).toHaveLength(n - 1)
  })
})
