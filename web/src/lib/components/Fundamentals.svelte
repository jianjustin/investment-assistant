<script lang="ts">
 import { untrack } from 'svelte'
 import type { EChartsOption } from 'echarts'
 import * as api from '../api'
 import { captureResearchDrafts, confirmResearchNavigation } from '../navigation-guard'
 import { datasetName, statusName, number, missingReason, metricName } from '../us-research-format'
 import FinancialSeries from './FinancialSeries.svelte'
 import MetricDetails from './MetricDetails.svelte'
 import GuidanceEditor from './GuidanceEditor.svelte'
 import EChart from '../charts/EChart.svelte'
 import { Alert, AlertDescription } from '$lib/ui/alert/index'
 import { Button } from '$lib/ui/button/index'
 import * as Card from '$lib/ui/card/index'
 import { DataTable } from '$lib/ui/data-table/index'
 import type { Column } from '$lib/ui/data-table/types'
 import Field from '$lib/ui/field/Field.svelte'
 import { Input } from '$lib/ui/input/index'
 import PageHeader from '$lib/ui/domain/PageHeader.svelte'
 import Section from '$lib/ui/domain/Section.svelte'
 let { ticker }: { ticker: string } = $props()
 const uid=$props.id()
 let symbol=$state('')
 let view=$state<api.USResearchView|null>(null)
 let loading=$state(false)
 let busy=$state(false)
 let error=$state('')
 let info=$state('')
 let asOf=$state('')
 let generation=0
 let readGeneration=0
 let syncGeneration=0
 let runId=$state('')
 let reportOpen=$state(false)
 let reports=$state<any[]>([])
 let reportsError=$state('')
 let reportsGeneration=0
 function select(next:string){
  if(!next||next===symbol)return
  generation++;readGeneration++;syncGeneration++;reportsGeneration++
  symbol=next;view=null;busy=false;loading=false;error='';info='';asOf='';runId='';reports=[];reportsError='';reportOpen=false
  load()
 }
 // The instrument page owns ticker selection; this panel only follows it.
 $effect(()=>{const next=ticker;untrack(()=>{if(next)select(next)})})
 async function load(){
  if(!symbol)return
  const draftsUnchanged=captureResearchDrafts()
  const token=++readGeneration;const selected=symbol;const scope=generation
  loading=true;error=''
  try{
   const next=await api.getUSResearch(selected,asOf?new Date(asOf).toISOString():undefined)
   if(token!==readGeneration||scope!==generation)return
   if(next.ticker!==selected||next.security_id!==`US:stock:${selected}`)throw new Error('响应证券身份不匹配')
   if((next.pit.as_of??null)!==(view?.pit.as_of??null)&&!draftsUnchanged()){info='读取期间出现新编辑，已保留当前内容；请保存后重新读取历史。';return}
   view=next
  }catch(e){if(token===readGeneration&&scope===generation)error=`加载失败：${String(e)}。已显示数据保留原日期，不代表更新成功。`}
  finally{if(token===readGeneration&&scope===generation)loading=false}
 }
 function refresh(){if(confirmResearchNavigation())load()}
 async function update(retry=false){
  if(!symbol||!confirmResearchNavigation())return
  const token=++syncGeneration;const scope=generation;const selected=symbol
  busy=true;error='';info=''
  try{
   const pending=await api.syncUSResearch(selected,retry)
   if(scope!==generation||token!==syncGeneration)return
   runId=pending.run_id
   const run=await api.pollRun(runId,{timeoutMs:600_000})
   if(scope!==generation||token!==syncGeneration)return
   if(run.status!=='done')throw new Error(run.error??'运行失败')
   const result=run.result as any
   const failures=result?.summary?.errors
   info=result?.status==='success'&&Array.isArray(failures)&&!failures.length?'手动更新完成，请结合实际覆盖判断可用性。':'更新有缺失或失败；成功部分与旧数据已保留，可续跑失败项。'
   await load()
   if(reportOpen)await loadReports()
  }catch(e){if(scope===generation&&token===syncGeneration)error=`更新未完成：${String(e)}。请核对持久运行报告；原数据及日期保留。`}
  finally{if(scope===generation&&token===syncGeneration)busy=false}
 }
 async function loadReports(){
  reportOpen=true
  const token=++reportsGeneration;const scope=generation
  try{const result=await api.getJobReports('us-research',10);if(token===reportsGeneration&&scope===generation){reports=result.reports;reportsError=result.degraded?'持久运行报告当前不可用。':''}}
  catch{if(token===reportsGeneration&&scope===generation)reportsError='持久运行报告读取失败，请在工具运行记录核对。'}
 }
 let company=$derived(view?.statuses.find(s=>s.dataset==='financials')?.last_success_details?.identity?.name)
 let displayedAsOf=$derived(view?.pit.as_of)
 let bars=$derived.by(()=>{
  const rows=view?.market.bars??[]
  if(!rows.length)return []
  const cutoff=new Date(rows.at(-1).date+'T00:00:00Z');cutoff.setUTCFullYear(cutoff.getUTCFullYear()-1)
  return rows.filter(r=>r.date>=cutoff.toISOString().slice(0,10))
 })
 let priceOption=$derived<EChartsOption>({tooltip:{trigger:'axis'},grid:{left:60,right:20,top:25,bottom:40},xAxis:{type:'category',data:bars.map(r=>r.date)},yAxis:{type:'value',scale:true,name:view?.currency??''},series:[{name:'调整收盘价',type:'line',showSymbol:false,connectNulls:false,data:bars.map(r=>r.adjusted_close??null)}]})
 const barColumns:Column<any>[]=[
  {key:'date',header:'日期'},
  {key:'close',header:'未调整收盘',align:'num',value:b=>`${number(b.close)} ${b.currency??''}`.trim()},
  {key:'adjusted_close',header:'调整收盘',align:'num',value:b=>`${number(b.adjusted_close)} ${b.currency??''}`.trim()},
  {key:'volume',header:'成交量',align:'num',value:b=>number(b.volume,0)},
  {key:'source',header:'来源',cell:sourceCell}
 ]
</script>
{#snippet sourceCell(bar:any)}{#if bar.source_url}<a class="text-primary underline" href={bar.source_url} target="_blank" rel="noreferrer">价格原文 ↗</a>{/if}<details class="my-1 text-xs"><summary class="cursor-pointer text-primary">来源记录</summary><pre class="max-w-100 whitespace-pre-wrap text-xs wrap-anywhere">{JSON.stringify(bar,null,2)}</pre></details>{/snippet}
<section class="grid min-w-0 gap-4 wrap-anywhere">
 <PageHeader level={2} title="基本面">
  {#snippet meta()}{#if company}<span>{company}</span>{/if}{/snippet}
  {#snippet actions()}
   <Button onclick={refresh} disabled={!symbol||loading}>读取本地数据</Button>
   <Button variant="primary" onclick={()=>update()} disabled={!symbol||!!asOf} busy={busy} busyText="采集中…">手动更新</Button>
   <Button onclick={()=>update(true)} disabled={!symbol||busy||!!asOf}>续跑失败项</Button>
  {/snippet}
 </PageHeader>
 <p class="text-sm text-muted-foreground">币种 {view?.currency??'待确认'} · 财季采用公司实际起止日 · 来源先于判断</p>
 {#if error}<Alert variant="danger"><AlertDescription>{error}</AlertDescription></Alert>{/if}{#if info}<Alert variant="info"><AlertDescription>{info}</AlertDescription></Alert>{/if}
 {#if loading}<p role="status" class="text-sm text-muted-foreground">正在读取本地数据…</p>{/if}
 {#if symbol}<details class="text-xs"><summary class="cursor-pointer text-primary" onclick={()=>{if(!reportOpen)loadReports()}}>采集运行与历史报告</summary><p class="my-2 text-sm text-muted-foreground">研究更新逐项保存，不发送通知；页面读取只访问本机已保存的数据。{runId?'当前运行 '+runId:''}</p><div class="flex flex-wrap items-center gap-3"><a class="text-primary underline" href="#tools/runs">查看持久运行报告</a><Button size="sm" onclick={loadReports}>读取最近报告</Button></div>
 {#if reportsError}<Alert variant="danger" class="mt-2"><AlertDescription>{reportsError}</AlertDescription></Alert>{/if}
 {#each reports as report}<details class="my-2 text-xs"><summary class="cursor-pointer text-primary">{report.started_at??report.created_at??report.run_id} · {report.status==='success'?'执行完成，需核对逐项覆盖':'存在缺失或失败'}</summary><pre class="max-w-full whitespace-pre-wrap text-xs wrap-anywhere">{JSON.stringify(report,null,2)}</pre></details>{/each}
 </details>{/if}
 {#if view}
 {#if view.financials.length}
 <FinancialSeries rows={view.financials} />
 {:else}<Alert variant="warn" role="status"><AlertDescription>尚未采集：本机没有该股票的财季数据，可点「手动更新」采集。</AlertDescription></Alert>{/if}
 <Card.Root class="min-w-0 px-4"><Section level={2} title="来源覆盖与更新状态"><p class="text-sm text-muted-foreground">采集完成不代表所有指标齐全。以下状态属于当前采集；旧值保留实际期间及上次成功时间。</p>
 <div class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,240px),1fr))] gap-3">{#each view.statuses as state}{@const coverage=state.last_success_details?.coverage??state.details?.coverage}<Card.Root size="sm" class={`min-w-0 gap-1 px-3 text-sm ${state.status!=='ready'?'border-warn/40 bg-warn/10':''}`}><h3 class="text-sm font-medium">{datasetName(state.dataset)} · {statusName(state.status)}</h3>
 {#if state.retained_old_values}<strong class="text-xs">显示旧值</strong>{/if}<p class="text-muted-foreground">最近尝试 {state.attempted_at??'尚未尝试'}<br />上次成功 {state.succeeded_at??'尚无成功记录'}</p>
 {#if state.error}<p class="text-muted-foreground">{missingReason(state.error)}</p>{/if}
 {#if coverage}<p class="text-muted-foreground">实际来源范围 {coverage.start??'未知'} → {coverage.end??'未知'} · 完整性{coverage.complete===true?'已核验':'尚未确认'}</p>{/if}
 {#each state.last_success_details?.limitations??[] as limitation}<p class="text-muted-foreground">{missingReason(limitation)}</p>{/each}
 {#if state.dataset==='financials'}<p class="text-muted-foreground">已转换 {view.financials.length} 个财季，目标 12 季；逐项缺口见财务表。</p>{/if}
 {#if state.dataset==='market'}<p class="text-muted-foreground">本地日线 {view.market.bars[0]?.date??'未知'} → {view.market.bars.at(-1)?.date??'未知'} · {view.market.bars.length} 条；SPY {view.market.benchmarks.SPY?.length??0} 条 / QQQ {view.market.benchmarks.QQQ?.length??0} 条。</p>{/if}
 <details class="text-xs"><summary class="cursor-pointer text-primary">来源覆盖明细</summary><pre class="max-w-full whitespace-pre-wrap text-xs wrap-anywhere">{JSON.stringify(state,null,2)}</pre></details></Card.Root>{/each}</div>
 <details class="text-xs"><summary class="cursor-pointer text-primary">本机历史观察</summary><p class="my-2 text-sm text-muted-foreground">{view.pit.limitation??'来源回补不代表严格历史可用'}。{view.pit.metadata_scope}</p>
 <div class="flex flex-wrap items-end gap-3"><Field label="本机观察截止时间" id={`${uid}-asof`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} type="datetime-local" bind:value={asOf} />{/snippet}</Field><Button onclick={refresh} disabled={loading}>按截止时间读取</Button><Button onclick={()=>{if(confirmResearchNavigation()){asOf='';load()}}}>回到当前数据</Button></div></details>
 {#if displayedAsOf}<Alert variant="warn" role="status"><AlertDescription>历史观察截止 {displayedAsOf}；指引编辑入口隐藏。采集状态与行业问题为当前信息。</AlertDescription></Alert>{/if}
 </Section></Card.Root>
 <Card.Root class="min-w-0 px-4"><Section level={2} title="价格、同期表现与估值"><p class="text-sm text-muted-foreground">近一年价格趋势 {bars[0]?.date??'尚无数据'} → {bars.at(-1)?.date??'尚无数据'}。收益采用来源调整收盘价，可能随分红及拆股历史回补变化，不能视作严格总回报或严格历史可用数据。</p>
 {#if bars.some(r=>r.adjusted_close!=null)}<EChart option={priceOption} />{/if}
 <div class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,240px),1fr))] gap-3">{#each ['3m','6m','12m'] as key}{@const window=view.market.performance.windows[key]}<Card.Root size="sm" class="min-w-0 gap-1 px-3 text-sm"><h3 class="text-sm font-medium">{key.replace('m',' 个月')}</h3>
 <p class="text-muted-foreground">实际 {window?.start??'未知'} → {window?.end??'未知'}<br />{window?.observations??0} 个观测日 · 最大日期间隔 {window?.max_gap_days??'未知'} 天</p>
 {#each ['return','max_drawdown'] as metric}<h4 class="mt-2 text-xs font-medium">{metricName(metric)}</h4><MetricDetails metric={window?.[metric]} />{/each}
 {#each ['SPY','QQQ'] as benchmark}<h4 class="mt-2 text-xs font-medium">{metricName(benchmark)}</h4><MetricDetails metric={window?.relative?.[benchmark]} period={(window?.relative?.[benchmark]?.start??'未知')+' → '+(window?.relative?.[benchmark]?.end??'未知')} />{/each}
 </Card.Root>{/each}</div>
 {#each view.market.limitations as limitation}<Alert variant="warn" role="status"><AlertDescription>{missingReason(limitation)}</AlertDescription></Alert>{/each}
 <div class="grid grid-cols-[repeat(auto-fit,minmax(min(100%,240px),1fr))] gap-3">{#each ['pe_ttm','ps_ttm','fcf_yield'] as key}<Card.Root size="sm" class="min-w-0 gap-1 px-3 text-sm"><h3 class="text-sm font-medium">{metricName(key)}</h3><MetricDetails metric={view.valuation[key]} period={'行情日期 '+(view.valuation[key]?.market_date??'未知')} /></Card.Root>{/each}</div>
 <p class="text-sm text-muted-foreground">估值须核验同币种、同股权类别及行情时点。当前 Yahoo 市值及股权类别尚未核验；原始报价不替代该核验。常规 PE 须使用正的普通股股东 TTM 利润。</p>
 <details class="text-xs"><summary class="cursor-pointer text-primary">价格原始记录与报价来源</summary><p class="my-2 text-sm text-muted-foreground">调整价用于收益；估值使用可比未调整价格及市值来源。没有核验时保持空白。</p><pre class="max-w-full whitespace-pre-wrap text-xs wrap-anywhere">{JSON.stringify(view.market.quote,null,2)}</pre>
 <DataTable columns={barColumns} rows={[...bars].reverse()} rowKey={b=>b.date} ariaLabel="价格原始记录" sticky={false} /></details>
 </Section></Card.Root>
 {#key displayedAsOf}<GuidanceEditor {symbol} records={view.guidance.records} comparisons={view.guidance.comparisons} readonly={!!displayedAsOf} onSaved={load} />{/key}
 <Card.Root class="min-w-0 px-4"><Section level={2} title="财报原文与披露摘录"><p class="text-sm text-muted-foreground">本地原文摘录用于核验，不代替标准季度财务事实；解析失败或未披露的经营指标仍需手动核对。</p>
 {#each view.filings as filing}<Card.Root size="sm" class="min-w-0 gap-1 px-3 text-sm"><h3 class="text-sm font-medium">{filing.form} · {filing.filing_date}</h3><a class="text-primary underline" href={filing.source_url} target="_blank" rel="noreferrer">财报原文 ↗</a>
 {#each filing.analysis?.guidance??[] as excerpt}<p class="text-muted-foreground">{excerpt.text??excerpt.quote??excerpt}</p>{/each}
 {#each filing.analysis?.warnings??[] as warning}<p class="text-muted-foreground">{missingReason(warning)}</p>{/each}
 <details class="text-xs"><summary class="cursor-pointer text-primary">原文摘录、覆盖与定位</summary><pre class="max-w-full whitespace-pre-wrap text-xs wrap-anywhere">{JSON.stringify(filing.analysis,null,2)}</pre><pre class="max-w-full whitespace-pre-wrap text-xs wrap-anywhere">{JSON.stringify(filing.limitations??[],null,2)}</pre></details></Card.Root>
 {:else}<p class="text-sm text-muted-foreground">暂无本机已处理原文，请核对本地财报来源覆盖。</p>{/each}
 </Section></Card.Root>
 {:else if !loading}
 <Alert variant="warn" role="status"><AlertDescription>尚未采集：本机没有该股票的基本面数据，可点「手动更新」采集。</AlertDescription></Alert>
 {/if}
</section>
