import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/svelte'
import UiGallery from './UiGallery.svelte'

afterEach(() => cleanup())

const SECTIONS = [
  '令牌', '按钮', '徽标', '表格', '确认对话框', '抽屉', '页内页签', '路由页签', '表单', '提示与浮层', '折叠', '提示条', '骨架', '分隔与卡片', '轻提示',
]

describe('UiGallery', () => {
  it('renders every component section', () => {
    render(UiGallery)
    expect(screen.getByText('开发模式组件画廊（不进生产包）')).toBeInTheDocument()
    for (const name of SECTIONS) {
      expect(screen.getByRole('heading', { name }), name).toBeInTheDocument()
    }
  })

  it('shows every button variant and the busy / disabled states', () => {
    render(UiGallery)
    for (const v of ['primary', 'outline', 'ghost', 'link', 'destructive']) {
      expect(screen.getAllByRole('button', { name: new RegExp(`^${v}`) }).length, v).toBeGreaterThan(0)
    }
    expect(screen.getAllByRole('button', { busy: true }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button').some((b) => (b as HTMLButtonElement).disabled)).toBe(true)
  })

  it('shows tables in plain, grouped, expandable and card form', () => {
    render(UiGallery)
    expect(screen.getAllByRole('table').length).toBeGreaterThanOrEqual(3)
    expect(screen.getAllByRole('button', { name: '展开详情' }).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /已结束/ })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('button', { name: /显示更多/ })).toBeInTheDocument()
  })
})
