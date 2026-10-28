<script lang="ts">
  import { createChart, type IChartApi, type ISeriesApi, type CandlestickData, type LineData } from 'lightweight-charts'
  import { onMount, onDestroy } from 'svelte'
  import type { Marker, Segment } from '../knowledge'

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
  let ready = $state(false)

  // Candidate arrows follow the up / down colours; fills are blue (B) / purple (S); watch circles are amber.
  const KIND_COLOR: Record<string, string> = { rule: '#0ea5e9', own: '#a855f7', agent: '#f97316' }

  onMount(() => {
    const style = getComputedStyle(document.documentElement)
    const up = style.getPropertyValue('--up').trim() || '#16a34a'
    const down = style.getPropertyValue('--down').trim() || '#dc2626'
    chart = createChart(el, { width: el.clientWidth, height: 320, layout: { background: { color: 'transparent' } } })
    series = chart.addCandlestickSeries({ upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down })
    ro = new ResizeObserver(() => { if (el) chart?.applyOptions({ width: el.clientWidth }) })
    ro.observe(el)
    ready = true
  })

  function markerColor(m: Marker): string {
    if (m.color) return m.color
    if (m.kind === 'trade') return m.shape === 'arrowDown' ? '#9333ea' : '#2563eb'
    if (m.shape === 'arrowUp') return '#16a34a'
    if (m.shape === 'arrowDown') return '#dc2626'
    return '#f59e0b'
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
        color: KIND_COLOR[seg.kind] ?? '#64748b', lineWidth: 1, lineStyle: seg.level === 'stop' ? 2 : 0,
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
    ro?.disconnect()
    chart?.remove()
    chart = undefined
  })
</script>

<div bind:this={el} style="width:100%;height:320px"></div>
