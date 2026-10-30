<script lang="ts">
 import type { EChartsOption } from 'echarts'
 import type { FiscalRow } from '../api'
 import EChart from '../charts/EChart.svelte'
 import MetricDetails from './MetricDetails.svelte'
 import * as Card from '$lib/ui/card/index'
 import Field from '$lib/ui/field/Field.svelte'
 import * as Table from '$lib/ui/table/index'
 import Section from '$lib/ui/domain/Section.svelte'
 import { metricName, number, missingReason } from '../us-research-format'
 let { rows = [] }: {rows:FiscalRow[]} = $props()
 const uid = $props.id()
 const SELECT = 'h-8 max-w-full rounded-md border border-input bg-card px-2 text-sm text-foreground'
 let mode = $state<'metrics'|'ttm'>('metrics')
 let group = $state('main')
 let trend = $state('revenue')
 const groups:Record<string,string[]> = {
 main:['revenue','revenue_yoy','revenue_qoq','gross_profit','gross_margin','operating_income','operating_margin','net_income','consolidated_net_income','common_net_income','cfo','cash_capex','broad_capex','fcf','fcf_margin'],
 cash:['cfo','cash_capex','broad_capex','fcf','fcf_margin','receivables','inventory','receivable_days','inventory_days','repurchases'],
 balance:['cash','investments','debt','long_term_debt_total','long_term_debt','short_term_debt','short_term_borrowings','debt_with_leases_current','debt_with_leases_noncurrent','long_term_debt_with_leases_total','receivables','inventory'],
 dilution:['eps_diluted','shares','weighted_shares','sbc','repurchases']
 }
 const instant=new Set(['cash','investments','debt','long_term_debt_total','long_term_debt','short_term_debt','short_term_borrowings','debt_with_leases_current','debt_with_leases_noncurrent','long_term_debt_with_leases_total','receivables','inventory','shares'])
 let periods=$derived([...rows].sort((a,b)=>a.end.localeCompare(b.end)).slice(-12))
 function value(row:FiscalRow,key:string){return instant.has(key)?row.metrics[key]:row[mode][key]}
 let chartRows=$derived(periods.map(row=>({row,metric:value(row,trend)})))
 let units=$derived([...new Set(chartRows.filter(x=>x.metric?.value!=null).map(x=>x.metric.unit))])
 let option=$derived<EChartsOption>({tooltip:{trigger:'axis',valueFormatter:(v)=>units[0]==='ratio'?number(Number(v)*100)+'%':number(v)},grid:{left:65,right:20,top:25,bottom:45},xAxis:{type:'category',data:periods.map(p=>p.end)},yAxis:{type:'value',name:units[0]==='ratio'?'%':units[0]==='shares'?'股':units[0]??'',axisLabel:{formatter:(v:number)=>units[0]==='ratio'?number(v*100)+'%':new Intl.NumberFormat('zh-CN',{notation:'compact',maximumFractionDigits:1}).format(v)}},series:[{type:'line',name:metricName(trend),showSymbol:true,connectNulls:false,data:chartRows.map(x=>x.metric?.value??null)}]})
</script>
<Card.Root class="min-w-0 px-4">
<Section level={2} title="财务趋势与实际财季">
 {#snippet actions()}
 <Field label="财务期间口径" id={`${uid}-mode`}>
  {#snippet children({ id, describedby })}
  <select {id} aria-describedby={describedby} class={SELECT} bind:value={mode}><option value="metrics">单财季</option><option value="ttm">连续四季 TTM</option></select>
  {/snippet}
 </Field>
 <Field label="指标分组" id={`${uid}-group`}>
  {#snippet children({ id, describedby })}
  <select {id} aria-describedby={describedby} class={SELECT} bind:value={group}><option value="main">收入、利润与现金</option><option value="cash">现金与营运资本</option><option value="balance">资产及债务构成</option><option value="dilution">股本与稀释</option></select>
  {/snippet}
 </Field>
 {/snippet}
 <p class="text-sm text-muted-foreground">最近 {periods.length} 个实际财季（目标 12 季）。币种与单位随每个值显示；归母、合并及普通股股东利润分别列示。期末余额始终显示期末值。</p>
 <p class="text-sm text-muted-foreground">标准自由现金流 = 经营现金流 − 现金购建固定资产。广义生产性资产投资另列；股权激励及稀释另查。缺失值保留空白，不能当作零。</p>
 <div class="max-w-64">
  <Field label="趋势指标" id={`${uid}-trend`}>
   {#snippet children({ id, describedby })}
   <select {id} aria-describedby={describedby} class="{SELECT} w-full" bind:value={trend}>{#each ['revenue','gross_margin','operating_income','cfo','cash_capex','fcf','inventory','sbc','shares'] as key}<option value={key}>{metricName(key)}</option>{/each}</select>
   {/snippet}
  </Field>
 </div>
 {#if units.length===1}<EChart {option} />{:else}<p class="text-sm text-muted-foreground">{units.length>1?'币种或单位不一致，暂不连接成趋势线。':'暂无可比趋势数据，请核对来源覆盖。'}</p>{/if}
 <!-- A transposed matrix (the columns are the periods), which DataTable's per-column cells cannot express: Table primitives. -->
 <Table.Root>
  <Table.Header><Table.Row class="hover:bg-transparent"><Table.Head>指标</Table.Head>{#each periods as row}<Table.Head class="min-w-42 align-top">{row.end}<small class="block whitespace-nowrap text-xs font-normal text-muted-foreground">{row.start} 起 · {row.days} 天</small></Table.Head>{/each}</Table.Row></Table.Header>
  <Table.Body>
  {#each groups[group] as key}<Table.Row><Table.Head class="align-top whitespace-normal">{metricName(key)}{#if instant.has(key)}<small class="block whitespace-nowrap text-xs font-normal text-muted-foreground">期末余额</small>{/if}</Table.Head>{#each periods as row}<Table.Cell class="align-top whitespace-normal"><MetricDetails metric={value(row,key)} period={row.period} /></Table.Cell>{/each}</Table.Row>{/each}
  </Table.Body>
 </Table.Root>
 {#if !periods.length}<p class="text-sm text-muted-foreground">尚无可展示财季；读取本地数据不会触发来源采集。</p>{/if}
 <details class="text-xs">
 <summary class="cursor-pointer text-primary">期间差异、重述及历史可用性说明</summary>
 <p class="my-2 text-sm text-muted-foreground">累计差分须同财年、单位及版本可比；TTM 须四个连续财季。每股收益和股数不做累计差分。周转天数采用实际期间天数和期初期末平均余额。</p>
 {#each periods as row}<p class="my-2 text-sm text-muted-foreground">{row.period} · {row.days} 天</p>{#each row.warnings as warning}<p class="my-2 text-sm text-muted-foreground">{missingReason(warning)}</p>{/each}{/each}
 <p class="my-2 text-sm text-muted-foreground">财务来源为当前披露版本回补，不能代表启用本机前的严格历史可用数据。</p>
 </details>
</Section>
</Card.Root>
