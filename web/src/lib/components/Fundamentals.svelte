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
 let { ticker }: { ticker: string } = $props()
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
</script>
<section class="fundamentals">
 <div class="heading"><h2>基本面{#if company}<span>{company}</span>{/if}</h2>
 <div class="controls"><button onclick={refresh} disabled={!symbol||loading}>读取本地数据</button><button class="primary" onclick={()=>update()} disabled={!symbol||busy||!!asOf}>{busy?'采集中…':'手动更新'}</button><button onclick={()=>update(true)} disabled={!symbol||busy||!!asOf}>续跑失败项</button></div></div>
 <p>币种 {view?.currency??'待确认'} · 财季采用公司实际起止日 · 来源先于判断</p>
 {#if error}<p role="alert" class="notice">{error}</p>{/if}{#if info}<p role="status" class="notice">{info}</p>{/if}
 {#if loading}<p role="status">正在读取本地数据…</p>{/if}
 {#if symbol}<details><summary onclick={()=>{if(!reportOpen)loadReports()}}>采集运行与历史报告</summary><p>研究更新逐项保存，不发送通知；页面读取只访问本机已保存的数据。{runId?'当前运行 '+runId:''}</p><a href="#tools/runs">查看持久运行报告</a><button onclick={loadReports}>读取最近报告</button>
 {#if reportsError}<p role="alert">{reportsError}</p>{/if}
 {#each reports as report}<details><summary>{report.started_at??report.created_at??report.run_id} · {report.status==='success'?'执行完成，需核对逐项覆盖':'存在缺失或失败'}</summary><pre>{JSON.stringify(report,null,2)}</pre></details>{/each}
 </details>{/if}
 {#if view}
 {#if view.financials.length}
 <FinancialSeries rows={view.financials} />
 {:else}<p class="notice">尚未采集：本机没有该股票的财季数据，可点「手动更新」采集。</p>{/if}
 <section><h2>来源覆盖与更新状态</h2><p>采集完成不代表所有指标齐全。以下状态属于当前采集；旧值保留实际期间及上次成功时间。</p>
 <div class="coverage">{#each view.statuses as state}{@const coverage=state.last_success_details?.coverage??state.details?.coverage}<article class:warning={state.status!=='ready'}><h3>{datasetName(state.dataset)} · {statusName(state.status)}</h3>
 {#if state.retained_old_values}<strong>显示旧值</strong>{/if}<p>最近尝试 {state.attempted_at??'尚未尝试'}<br />上次成功 {state.succeeded_at??'尚无成功记录'}</p>
 {#if state.error}<p>{missingReason(state.error)}</p>{/if}
 {#if coverage}<p>实际来源范围 {coverage.start??'未知'} → {coverage.end??'未知'} · 完整性{coverage.complete===true?'已核验':'尚未确认'}</p>{/if}
 {#each state.last_success_details?.limitations??[] as limitation}<p>{missingReason(limitation)}</p>{/each}
 {#if state.dataset==='financials'}<p>已转换 {view.financials.length} 个财季，目标 12 季；逐项缺口见财务表。</p>{/if}
 {#if state.dataset==='market'}<p>本地日线 {view.market.bars[0]?.date??'未知'} → {view.market.bars.at(-1)?.date??'未知'} · {view.market.bars.length} 条；SPY {view.market.benchmarks.SPY?.length??0} 条 / QQQ {view.market.benchmarks.QQQ?.length??0} 条。</p>{/if}
 <details><summary>来源覆盖明细</summary><pre>{JSON.stringify(state,null,2)}</pre></details></article>{/each}</div>
 <details><summary>本机历史观察</summary><p>{view.pit.limitation??'来源回补不代表严格历史可用'}。{view.pit.metadata_scope}</p>
 <div class="controls"><label>本机观察截止时间<input type="datetime-local" bind:value={asOf} /></label><button onclick={refresh} disabled={loading}>按截止时间读取</button><button onclick={()=>{if(confirmResearchNavigation()){asOf='';load()}}}>回到当前数据</button></div></details>
 {#if displayedAsOf}<p class="notice">历史观察截止 {displayedAsOf}；指引编辑入口隐藏。采集状态与行业问题为当前信息。</p>{/if}
 </section>
 <section><h2>价格、同期表现与估值</h2><p>近一年价格趋势 {bars[0]?.date??'尚无数据'} → {bars.at(-1)?.date??'尚无数据'}。收益采用来源调整收盘价，可能随分红及拆股历史回补变化，不能视作严格总回报或严格历史可用数据。</p>
 {#if bars.some(r=>r.adjusted_close!=null)}<EChart option={priceOption} />{/if}
 <div class="performance">{#each ['3m','6m','12m'] as key}{@const window=view.market.performance.windows[key]}<article><h3>{key.replace('m',' 个月')}</h3>
 <p>实际 {window?.start??'未知'} → {window?.end??'未知'}<br />{window?.observations??0} 个观测日 · 最大日期间隔 {window?.max_gap_days??'未知'} 天</p>
 {#each ['return','max_drawdown'] as metric}<h4>{metricName(metric)}</h4><MetricDetails metric={window?.[metric]} />{/each}
 {#each ['SPY','QQQ'] as benchmark}<h4>{metricName(benchmark)}</h4><MetricDetails metric={window?.relative?.[benchmark]} period={(window?.relative?.[benchmark]?.start??'未知')+' → '+(window?.relative?.[benchmark]?.end??'未知')} />{/each}
 </article>{/each}</div>
 {#each view.market.limitations as limitation}<p class="notice">{missingReason(limitation)}</p>{/each}
 <div class="valuation">{#each ['pe_ttm','ps_ttm','fcf_yield'] as key}<article><h3>{metricName(key)}</h3><MetricDetails metric={view.valuation[key]} period={'行情日期 '+(view.valuation[key]?.market_date??'未知')} /></article>{/each}</div>
 <p>估值须核验同币种、同股权类别及行情时点。当前 Yahoo 市值及股权类别尚未核验；原始报价不替代该核验。常规 PE 须使用正的普通股股东 TTM 利润。</p>
 <details><summary>价格原始记录与报价来源</summary><p>调整价用于收益；估值使用可比未调整价格及市值来源。没有核验时保持空白。</p><pre>{JSON.stringify(view.market.quote,null,2)}</pre>
 <div class="table-scroll"><table><thead><tr><th>日期</th><th>未调整收盘</th><th>调整收盘</th><th>成交量</th><th>来源</th></tr></thead><tbody>{#each [...bars].reverse() as bar}<tr><td>{bar.date}</td><td>{number(bar.close)} {bar.currency??''}</td><td>{number(bar.adjusted_close)} {bar.currency??''}</td><td>{number(bar.volume,0)}</td><td>{#if bar.source_url}<a href={bar.source_url} target="_blank" rel="noreferrer">价格原文 ↗</a>{/if}<details><summary>来源记录</summary><pre>{JSON.stringify(bar,null,2)}</pre></details></td></tr>{/each}</tbody></table></div></details>
 </section>
 {#key displayedAsOf}<GuidanceEditor {symbol} records={view.guidance.records} comparisons={view.guidance.comparisons} readonly={!!displayedAsOf} onSaved={load} />{/key}
 <section><h2>财报原文与披露摘录</h2><p>本地原文摘录用于核验，不代替标准季度财务事实；解析失败或未披露的经营指标仍需手动核对。</p>
 {#each view.filings as filing}<article><h3>{filing.form} · {filing.filing_date}</h3><a href={filing.source_url} target="_blank" rel="noreferrer">财报原文 ↗</a>
 {#each filing.analysis?.guidance??[] as excerpt}<p>{excerpt.text??excerpt.quote??excerpt}</p>{/each}
 {#each filing.analysis?.warnings??[] as warning}<p>{missingReason(warning)}</p>{/each}
 <details><summary>原文摘录、覆盖与定位</summary><pre>{JSON.stringify(filing.analysis,null,2)}</pre><pre>{JSON.stringify(filing.limitations??[],null,2)}</pre></details></article>
 {:else}<p>暂无本机已处理原文，请核对本地财报来源覆盖。</p>{/each}
 </section>
 {:else if !loading}
 <p class="notice">尚未采集：本机没有该股票的基本面数据，可点「手动更新」采集。</p>
 {/if}
</section>
<style>
 .fundamentals{display:grid;gap:1rem;min-width:0;overflow-wrap:anywhere}.fundamentals>*{min-width:0}.heading,.controls{display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap}.controls{justify-content:flex-start}h2{font-size:1.1rem;font-weight:650}h2 span{font-size:.9rem;font-weight:400;margin-left:1rem}h3{font-size:.9rem;font-weight:600}h4{font-size:.8rem;margin-top:.8rem;font-weight:600}p{color:var(--muted);font-size:.85rem;margin:.65rem 0}section{padding:1.2rem;border:1px solid var(--border);border-radius:10px;background:var(--surface)}article{padding:.9rem;border:1px solid var(--border);border-radius:7px;min-width:0}section>article{margin-top:.7rem}.coverage,.performance,.valuation{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:1rem;margin:.8rem 0}.warning,.notice{border:1px solid #d99b27;background:#d99b2710}.notice{padding:.8rem;border-radius:7px}a,summary{color:var(--accent)}summary{cursor:pointer}details{font-size:.8rem;margin:.6rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%;font-size:.75rem}button{padding:.5rem .8rem;border:1px solid var(--border);background:var(--surface-2);border-radius:5px;font-size:.8rem}button:disabled{opacity:.5}.primary{background:var(--accent);color:white}label{min-width:0;max-width:100%;display:grid;gap:.25rem;font-size:.8rem}input{padding:.4rem;border:1px solid var(--border);background:var(--surface-2);min-width:0;max-width:100%}.table-scroll{max-width:100%;overflow-x:auto}table{border-collapse:collapse;min-width:100%;font-size:.8rem}th,td{text-align:left;padding:.6rem;white-space:nowrap;border-bottom:1px solid var(--border)}td pre{max-width:25rem}@media(max-width:600px){section{padding:.8rem}.controls{gap:.6rem}}
</style>
