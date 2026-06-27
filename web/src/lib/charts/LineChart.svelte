<script lang="ts">
  import { createChart, type IChartApi, type ISeriesApi, type LineData } from 'lightweight-charts'
  import { onMount, onDestroy } from 'svelte'

  let { data }: { data: LineData[] } = $props()
  let el: HTMLDivElement
  let chart: IChartApi | undefined
  let series: ISeriesApi<'Line'> | undefined

  onMount(() => {
    const up = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#0f766e'
    chart = createChart(el, { width: el.clientWidth, height: 240, layout: { background: { color: 'transparent' } } })
    series = chart.addLineSeries({ color: up })
    series.setData(data)
    const ro = new ResizeObserver(() => chart?.applyOptions({ width: el.clientWidth }))
    ro.observe(el)
  })

  $effect(() => { series?.setData(data) })

  onDestroy(() => { chart?.remove() })
</script>

<div bind:this={el} style="width:100%;height:240px"></div>
