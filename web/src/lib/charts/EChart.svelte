<script lang="ts">
  import * as echarts from 'echarts'
  import { onMount, onDestroy } from 'svelte'
  import { onThemeChange } from '../theme'
  import { readChartTheme, echartsTheme } from './theme'

  let { option }: { option: echarts.EChartsOption } = $props()
  let el: HTMLDivElement
  let chart: echarts.ECharts | undefined
  let ro: ResizeObserver | undefined
  let stopTheme: (() => void) | undefined

  function create() {
    chart = echarts.init(el, echartsTheme(readChartTheme()))
    chart.setOption(option)
  }

  onMount(() => {
    create()
    ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el)
    // ECharts bakes colours in at init: a new theme needs a new instance.
    stopTheme = onThemeChange(() => {
      chart?.dispose()
      create()
    })
  })

  $effect(() => { chart?.setOption(option) })

  onDestroy(() => {
    stopTheme?.()
    ro?.disconnect()
    chart?.dispose()
  })
</script>

<div bind:this={el} style="width:100%;height:320px"></div>
