<script lang="ts">
  import { createChart, type IChartApi, type ISeriesApi, type CandlestickData } from 'lightweight-charts'
  import { onMount, onDestroy } from 'svelte'

  let { data }: { data: CandlestickData[] } = $props()
  let el: HTMLDivElement
  let chart: IChartApi | undefined
  let series: ISeriesApi<'Candlestick'> | undefined

  onMount(() => {
    const style = getComputedStyle(document.documentElement)
    const up = style.getPropertyValue('--up').trim() || '#16a34a'
    const down = style.getPropertyValue('--down').trim() || '#dc2626'
    chart = createChart(el, { width: el.clientWidth, height: 320, layout: { background: { color: 'transparent' } } })
    series = chart.addCandlestickSeries({ upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down })
    series.setData(data)
    const ro = new ResizeObserver(() => chart?.applyOptions({ width: el.clientWidth }))
    ro.observe(el)
  })

  $effect(() => { series?.setData(data) })

  onDestroy(() => { chart?.remove() })
</script>

<div bind:this={el} style="width:100%;height:320px"></div>
