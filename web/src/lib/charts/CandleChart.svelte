<script lang="ts">
  import { createChart, type IChartApi, type ISeriesApi, type CandlestickData, type LineData } from 'lightweight-charts'
  import { onMount, onDestroy } from 'svelte'
  import type { Marker, Segment } from '../knowledge'
  import { onThemeChange } from '../theme'
  import { candleOptions, readChartTheme, roleColor, type ChartTheme } from './theme'

  type Overlay = { color: string; data: { time: string; value: number }[] }
  // markers / segments (v2.6 §9.3) are optional; without them the chart is exactly the candles plus the overlays.
  let { data, overlays = [], markers = [], segments = [] }:
    { data: CandlestickData[]; overlays?: Overlay[]; markers?: Marker[]; segments?: Segment[] } = $props()
  let el: HTMLDivElement
  let chart: IChartApi | undefined
  let series: ISeriesApi<'Candlestick'> | undefined
  let lineSeries: ISeriesApi<'Line'>[] = []
  let segmentSeries: ISeriesApi<'Line'>[] = []
  let markersSet = false
  let ro: ResizeObserver | undefined
  let stopTheme: (() => void) | undefined
  // Every colour comes from the design tokens through the chart theme (hex strings the canvas can parse).
  let theme: ChartTheme = readChartTheme()
  // Bumped whenever a chart instance is (re)built; the effects below depend on it to draw everything again.
  let ready = $state(0)

  // Segments by plan source; a voided plan (status other than ok) is drawn in the fill colour whatever its source.
  function segmentColor(seg: Segment): string {
    if (seg.status && seg.status !== 'ok') return theme.fill   // #rrggbbaa is fine for line strokes: the alpha is honoured
    return seg.kind === 'rule' || seg.kind === 'own' || seg.kind === 'agent' ? roleColor(theme, seg.kind) : theme.mutedForeground
  }

  // lightweight-charts bakes fonts, grid and colours in when the instance is created: a new theme needs a new one.
  function build() {
    theme = readChartTheme()
    const options = candleOptions(theme)
    chart = createChart(el, { ...options.chart, width: el.clientWidth, height: 320 })
    series = chart.addCandlestickSeries(options.series)
    lineSeries = []
    segmentSeries = []
    markersSet = false
    ready += 1
  }

  onMount(() => {
    build()
    ro = new ResizeObserver(() => { if (el) chart?.applyOptions({ width: el.clientWidth }) })
    ro.observe(el)
    stopTheme = onThemeChange(() => {
      chart?.remove()
      chart = undefined
      series = undefined
      build()
    })
  })

  function markerColor(m: Marker): string {
    if (m.color) return m.color
    // fills are squares (B / S in the text, below / above the bar): a buy is up, a sell is down
    if (m.kind === 'trade') {
      const sell = /^\s*S\b/.test(m.text ?? '') || (!m.text && !/below/i.test(m.position ?? ''))
      return sell ? theme.down : theme.up
    }
    // candidates (arrows and watch circles) are what the rules raised
    return roleColor(theme, 'rule')
  }

  function syncMarkers() {
    if (!series) return
    if (!markers?.length && !markersSet) return
    // lightweight-charts needs ascending time; a stable sort keeps same-day order as the backend gave it.
    const sorted = [...(markers ?? [])].sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0))
    series.setMarkers(sorted.map(m => ({
      time: m.time as any, shape: m.shape as any, text: m.text ?? '', color: markerColor(m),
      position: (m.position && /below/i.test(m.position) ? 'belowBar' : m.position === 'inBar' ? 'inBar' : 'aboveBar') as any,
    })))
    markersSet = sorted.length > 0
  }

  function syncOverlays() {
    if (!chart) return
    for (const s of lineSeries) chart.removeSeries(s)
    lineSeries = overlays.map((o) => {
      const s = chart!.addLineSeries({ color: o.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      s.setData(o.data as LineData[])
      return s
    })
  }

  function syncSegments() {
    if (!chart) return
    for (const s of segmentSeries) chart.removeSeries(s)
    segmentSeries = (segments ?? []).filter(seg => seg.from <= seg.to).map((seg) => {
      const s = chart!.addLineSeries({
        color: segmentColor(seg), lineWidth: 1, lineStyle: seg.level === 'stop' ? 2 : 0,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      })
      const value = Number(seg.value)
      s.setData((seg.from === seg.to ? [{ time: seg.from, value }] : [{ time: seg.from, value }, { time: seg.to, value }]) as LineData[])
      return s
    })
  }

  $effect(() => { ready; series?.setData(data) })
  $effect(() => { ready; overlays; syncOverlays() })
  $effect(() => { ready; markers; syncMarkers() })
  $effect(() => { ready; segments; syncSegments() })

  onDestroy(() => {
    stopTheme?.()
    ro?.disconnect()
    chart?.remove()
    chart = undefined
  })
</script>

<div bind:this={el} style="width:100%;height:320px"></div>
