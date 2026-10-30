<script lang="ts">
 import type { EChartsOption } from 'echarts'
 import type { FiscalRow } from '../api'
 import EChart from '../charts/EChart.svelte'
 import MetricDetails from './MetricDetails.svelte'
 import { metricName, number, missingReason } from '../us-research-format'
 let { rows = [] }: {rows:FiscalRow[]} = $props()
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
<section>
 <div class="heading"><h2>财务趋势与实际财季</h2><div class="controls">
 <label>财务期间口径<select bind:value={mode}><option value="metrics">单财季</option><option value="ttm">连续四季 TTM</option></select></label>
 <label>指标分组<select bind:value={group}><option value="main">收入、利润与现金</option><option value="cash">现金与营运资本</option><option value="balance">资产及债务构成</option><option value="dilution">股本与稀释</option></select></label>
 </div></div>
 <p>最近 {periods.length} 个实际财季（目标 12 季）。币种与单位随每个值显示；归母、合并及普通股股东利润分别列示。期末余额始终显示期末值。</p>
 <p>标准自由现金流 = 经营现金流 − 现金购建固定资产。广义生产性资产投资另列；股权激励及稀释另查。缺失值保留空白，不能当作零。</p>
 <label class="trend">趋势指标<select bind:value={trend}>{#each ['revenue','gross_margin','operating_income','cfo','cash_capex','fcf','inventory','sbc','shares'] as key}<option value={key}>{metricName(key)}</option>{/each}</select></label>
 {#if units.length===1}<EChart {option} />{:else}<p>{units.length>1?'币种或单位不一致，暂不连接成趋势线。':'暂无可比趋势数据，请核对来源覆盖。'}</p>{/if}
 <div class="table-scroll"><table><thead><tr><th>指标</th>{#each periods as row}<th>{row.end}<small>{row.start} 起 · {row.days} 天</small></th>{/each}</tr></thead><tbody>
 {#each groups[group] as key}<tr><th>{metricName(key)}{#if instant.has(key)}<small>期末余额</small>{/if}</th>{#each periods as row}<td><MetricDetails metric={value(row,key)} period={row.period} /></td>{/each}</tr>{/each}
 </tbody></table></div>
 {#if !periods.length}<p>尚无可展示财季；读取本地数据不会触发来源采集。</p>{/if}
 <details><summary>期间差异、重述及历史可用性说明</summary>
 <p>累计差分须同财年、单位及版本可比；TTM 须四个连续财季。每股收益和股数不做累计差分。周转天数采用实际期间天数和期初期末平均余额。</p>
 {#each periods as row}<p>{row.period} · {row.days} 天</p>{#each row.warnings as warning}<p>{missingReason(warning)}</p>{/each}{/each}
 <p>财务来源为当前披露版本回补，不能代表启用本机前的严格历史可用数据。</p>
 </details>
</section>
<style>
 section{min-width:0;padding:1.2rem;background:var(--card);border:1px solid var(--border);border-radius:10px}h2{font-weight:650;font-size:1.1rem}p{font-size:.85rem;color:var(--muted-foreground);margin:.65rem 0}.heading,.controls{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;justify-content:space-between}label{min-width:0;max-width:100%;display:grid;gap:.25rem;font-size:.8rem}.trend{max-width:16rem;margin:.8rem 0}select{max-width:100%;padding:.4rem;background:var(--muted);border:1px solid var(--border);border-radius:5px}.table-scroll{overflow-x:auto;max-width:100%;margin-top:1rem}table{font-size:.8rem;border-collapse:collapse;min-width:100%}th,td{padding:.65rem;text-align:left;vertical-align:top;border-bottom:1px solid var(--border);min-width:10.5rem}th{white-space:normal}small{display:block;font-size:.7rem;color:var(--muted-foreground);font-weight:400;white-space:nowrap}summary{color:var(--primary);cursor:pointer;font-size:.8rem}details{margin-top:.7rem}
</style>
