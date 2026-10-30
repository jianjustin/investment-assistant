export type ChartTheme = {
  foreground: string
  mutedForeground: string
  border: string
  grid: string
  background: string
  card: string
  up: string
  down: string
  rule: string
  own: string
  agent: string
  fill: string
  series: [string, string, string, string, string]
}

/**
 * Resolves the design tokens to concrete hex strings for the canvas libraries, which cannot read
 * CSS variables themselves. Values are whatever the stylesheet defines; there is deliberately no fallback colour.
 */
export function readChartTheme(root: HTMLElement = document.documentElement): ChartTheme {
  const style = getComputedStyle(root)
  const v = (name: string) => style.getPropertyValue(name).trim()
  return {
    foreground: v('--foreground'),
    mutedForeground: v('--muted-foreground'),
    border: v('--border'),
    grid: v('--chart-grid'),
    background: v('--background'),
    card: v('--card'),
    up: v('--up'),
    down: v('--down'),
    rule: v('--chart-rule'),
    own: v('--chart-own'),
    agent: v('--chart-agent'),
    fill: v('--chart-fill'),
    series: [v('--chart-1'), v('--chart-2'), v('--chart-3'), v('--chart-4'), v('--chart-5')],
  }
}

/** ECharts theme object (pass to `echarts.init(el, theme)`). */
export function echartsTheme(t: ChartTheme): Record<string, unknown> {
  const axis = {
    axisLine: { lineStyle: { color: t.border } },
    axisTick: { lineStyle: { color: t.border } },
    axisLabel: { color: t.mutedForeground },
    splitLine: { lineStyle: { color: t.grid } },
  }
  return {
    color: t.series,
    backgroundColor: 'transparent',
    textStyle: { color: t.mutedForeground },
    title: { textStyle: { color: t.foreground }, subtextStyle: { color: t.mutedForeground } },
    legend: { textStyle: { color: t.mutedForeground } },
    categoryAxis: axis,
    valueAxis: axis,
    timeAxis: axis,
    logAxis: axis,
    tooltip: {
      backgroundColor: t.card,
      borderColor: t.border,
      textStyle: { color: t.foreground },
    },
  }
}

/** lightweight-charts options: `chart` for `createChart` / `applyOptions`, `series` for `addCandlestickSeries`. */
export function candleOptions(t: ChartTheme) {
  return {
    chart: {
      layout: { background: { color: t.card }, textColor: t.mutedForeground },
      grid: { vertLines: { color: t.grid }, horzLines: { color: t.grid } },
      rightPriceScale: { borderColor: t.border },
      timeScale: { borderColor: t.border },
    },
    series: {
      upColor: t.up,
      downColor: t.down,
      borderUpColor: t.up,
      borderDownColor: t.down,
      wickUpColor: t.up,
      wickDownColor: t.down,
    },
  }
}

/** Plan source role (rule baseline / own plan / agent plan) to its chart color. */
export function roleColor(t: ChartTheme, role: 'rule' | 'own' | 'agent'): string {
  return t[role]
}
