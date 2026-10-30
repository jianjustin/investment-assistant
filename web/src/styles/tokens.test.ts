import { describe, it, expect } from 'vitest'
import tokensCss from './tokens.css?raw'
import appCss from './app.css?raw'

type Tokens = Record<string, string>

function block(css: string, selector: string): string {
  const start = css.indexOf(selector)
  const open = css.indexOf('{', start)
  const close = css.indexOf('}', open)
  return css.slice(open + 1, close)
}

function parse(body: string): Tokens {
  const out: Tokens = {}
  for (const m of body.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim()
  return out
}

const light = parse(block(tokensCss, ':root'))
const dark = parse(block(tokensCss, "[data-theme='dark']"))
const NOT_COLORS = new Set(['radius', 'shadow-1', 'shadow-2'])
const colorKeys = (t: Tokens) => Object.keys(t).filter((k) => !NOT_COLORS.has(k))

function lum(hex: string): number {
  const h = hex.slice(1, 7)
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('design tokens', () => {
  it('color tokens are hex literals', () => {
    for (const [name, t] of [['light', light], ['dark', dark]] as const) {
      for (const key of colorKeys(t)) {
        expect(t[key], `${name} --${key}`).toMatch(/^#([0-9a-f]{6}|[0-9a-f]{8})$/)
      }
    }
  })

  it('both themes define the same token set', () => {
    // --radius is shape, not theme: it lives in :root only
    expect(Object.keys(dark).sort()).toEqual(Object.keys(light).filter((k) => k !== 'radius').sort())
    expect(light.radius).toBe('6px')
    expect(Object.keys(light)).toEqual(expect.arrayContaining([
      'background', 'card', 'card-foreground', 'popover', 'popover-foreground', 'muted', 'border', 'input', 'ring',
      'foreground', 'muted-foreground', 'primary', 'primary-foreground',
      'success', 'warn', 'destructive', 'info', 'running', 'neutral',
      'up', 'down', 'chart-rule', 'chart-own', 'chart-agent', 'chart-fill', 'chart-grid',
      'chart-1', 'chart-2', 'chart-3', 'chart-4', 'chart-5', 'radius', 'shadow-1', 'shadow-2',
    ]))
    for (const forbidden of ['secondary', 'accent', 'sidebar']) {
      expect(Object.keys(light).filter((k) => k.startsWith(forbidden))).toEqual([])
    }
  })

  it('AA contrast in both themes', () => {
    for (const [name, t] of [['light', light], ['dark', dark]] as const) {
      for (const surface of ['background', 'card']) {
        expect(contrast(t.foreground, t[surface]), `${name} foreground on ${surface}`).toBeGreaterThanOrEqual(4.5)
        expect(contrast(t['muted-foreground'], t[surface]), `${name} muted-foreground on ${surface}`).toBeGreaterThanOrEqual(3)
      }
      for (const k of ['primary', 'success', 'warn', 'destructive', 'info', 'running', 'up', 'down']) {
        expect(contrast(t[k], t.card), `${name} ${k} on card`).toBeGreaterThanOrEqual(4.5)
      }
      for (const k of ['primary', 'success', 'warn', 'destructive', 'info', 'running', 'neutral']) {
        expect(contrast(t[`${k}-foreground`], t[k]), `${name} ${k}-foreground on ${k}`).toBeGreaterThanOrEqual(4.5)
      }
    }
  })

  it('every @theme color maps to a defined token', () => {
    const mapped = [...appCss.matchAll(/--color-([\w-]+)\s*:\s*var\(--([\w-]+)\)/g)]
    expect(mapped.length).toBeGreaterThan(20)
    for (const [, name, source] of mapped) {
      expect(name).toBe(source)
      expect(light, `--${source} (light)`).toHaveProperty(source)
      expect(dark, `--${source} (dark)`).toHaveProperty(source)
    }
  })
})
