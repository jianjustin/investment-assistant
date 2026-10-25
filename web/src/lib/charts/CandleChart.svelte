<script lang="ts">
  import { createChart, type IChartApi, type ISeriesApi, type CandlestickData, type LineData } from 'lightweight-charts'
  import { onMount, onDestroy } from 'svelte'

  type Overlay = { color: string; data: { time: string; value: number }[] }
  let { data, overlays = [] }: { data: CandlestickData[]; overlays?: Overlay[] } = $props()
  let el: HTMLDivElement
  let chart: IChartApi | undefined
  let series: ISeriesApi<'Candlestick'> | undefined
  let lineSeries: ISeriesApi<'Line'>[] = []
  let ro: ResizeObserver | undefined

  onMount(() => {
    const style = getComputedStyle(document.documentElement)
    const up = style.getPropertyValue('--up').trim() || '#16a34a'
    const down = style.getPropertyValue('--down').trim() || '#dc2626'
    chart = createChart(el, { width: el.clientWidth, height: 320, layout: { background: { color: 'transparent' } } })
    series = chart.addCandlestickSeries({ upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down })
    series.setData(data)
    syncOverlays()
    ro = new ResizeObserver(() => { if (el) chart?.applyOptions({ width: el.clientWidth }) })
    ro.observe(el)
  })

  function syncOverlays() {
    if (!chart) return
    for (const s of lineSeries) chart.removeSeries(s)
    lineSeries = overlays.map((o) => {
      const s = chart!.addLineSeries({ color: o.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      s.setData(o.data as LineData[])
      return s
    })
  }

  $effect(() => { series?.setData(data) })
  $effect(() => { overlays; syncOverlays() })

  onDestroy(() => {
    ro?.disconnect()
    chart?.remove()
    chart = undefined
  })
</script>

<div bind:this={el} style="width:100%;height:320px"></div>
