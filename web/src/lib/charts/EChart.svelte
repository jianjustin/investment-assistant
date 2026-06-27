<script lang="ts">
  import * as echarts from 'echarts'
  import { onMount, onDestroy } from 'svelte'

  let { option }: { option: echarts.EChartsOption } = $props()
  let el: HTMLDivElement
  let chart: echarts.ECharts | undefined
  let ro: ResizeObserver | undefined

  onMount(() => {
    const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : undefined
    chart = echarts.init(el, theme)
    chart.setOption(option)
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el)
  })

  $effect(() => { chart?.setOption(option) })

  onDestroy(() => {
    ro?.disconnect()
    chart?.dispose()
  })
</script>

<div bind:this={el} style="width:100%;height:320px"></div>
