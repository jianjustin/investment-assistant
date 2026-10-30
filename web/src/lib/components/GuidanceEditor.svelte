<script lang="ts">
 import { untrack, onDestroy, onMount } from 'svelte'
 import { registerNavigationGuard } from '../navigation-guard'
 import * as api from '../api'
 import type { GuidanceRecord, GuidanceComparison } from '../api'
 import { metricName, number, basisName, missingReason } from '../us-research-format'
 let { symbol, records=[], comparisons=[], readonly=false, onSaved }: {symbol:string;records?:GuidanceRecord[];comparisons?:GuidanceComparison[];readonly?:boolean;onSaved?:()=>Promise<void>}=$props()
 const knownMetrics=['revenue','gross_margin','operating_income','net_income','consolidated_net_income','common_net_income','eps_diluted','cfo','cash_capex','fcf']
 const knownBases=['us-gaap:consolidated','us-gaap:parent','us-gaap:common']
 const blank=()=>({metric:'',target_start:'',target_end:'',basis:'',unit:'',low:undefined as number|undefined,high:undefined as number|undefined,issued_at:'',source_url:'',source_locator:'',note:'',supersedes_id:null as number|null})
 let draft=$state(blank())
 let discardDraft:string|null=null
 let dirty=$derived(JSON.stringify(draft)!==JSON.stringify(blank()))
 let saved=$state<GuidanceRecord[]>([])
 let busy=$state(false)
 let error=$state('')
 let message=$state('')
 let loaded=''
 let generation=0
 $effect(()=>{const next=symbol;const incoming=records;untrack(()=>{
  if(loaded!==next){loaded=next;generation++;draft=blank();discardDraft=null;saved=[];busy=false;error='';message=''}
  else if(discardDraft===JSON.stringify(draft)){draft=blank();discardDraft=null}
  const unique=new Map([...saved,...incoming].map(r=>[r.id,r]));saved=[...unique.values()]
 })})
 onDestroy(()=>{generation++})
 onMount(()=>{
  const dispose=registerNavigationGuard({snapshot:()=>JSON.stringify(draft),dirty:()=>dirty,discard:snapshot=>{discardDraft=snapshot}})
  const unload=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();event.returnValue=''}}
  window.addEventListener('beforeunload',unload)
  return ()=>{dispose();window.removeEventListener('beforeunload',unload)}
 })
 function revise(record:GuidanceRecord){
  draft={...Object.fromEntries(Object.keys(blank()).map(key=>[key,(record as any)[key]??(blank() as any)[key]])) as ReturnType<typeof blank>,supersedes_id:record.id,issued_at:new Date(new Date(record.issued_at).getTime()-new Date(record.issued_at).getTimezoneOffset()*60000).toISOString().slice(0,16)}
  message='';error=''
 }
 async function save(){
  error='';message=''
  const data=$state.snapshot(draft)
  if(!data.metric.trim()||!data.target_start||!data.target_end||!data.basis.trim()||!data.unit.trim()||data.low==null||data.high==null||!data.issued_at||!data.source_url.trim()||!data.source_locator.trim()) {error='请完整填写指标、期间、会计口径、单位、区间、发布时间与原文定位。';return}
  if(data.target_start>data.target_end||data.low>data.high||!Number.isFinite(data.low)||!Number.isFinite(data.high)){error='目标期间或上下限不连贯。';return}
  const token=generation;const selected=symbol;const submitted=JSON.stringify(data)
  busy=true
  try{
   const result=await api.appendUSGuidance(selected,{...data,low:data.low,high:data.high,issued_at:new Date(data.issued_at).toISOString()})
   if(token!==generation||selected!==symbol)return
   if(!result.record?.id)throw new Error('指引保存回读缺少记录，请核对运行结果')
   saved=[...saved.filter(r=>r.id!==result.record.id),result.record]
   if(JSON.stringify(draft)===submitted)draft=blank()
   message='指引版本已追加，原始记录保留。'
   await onSaved?.()
  }catch(e){if(token===generation)error=`保存失败：${String(e)}。输入已保留。`}
  finally{if(token===generation)busy=false}
 }
 const outcome:Record<string,string>={in_range:'在指引区间内',below_range:'低于指引区间',above_range:'高于指引区间',not_comparable:'暂不可比'}
</script>
<section>
 <h2>公司指引与兑现比较</h2><p>未接入一致预期</p><p>指引属于公司披露。兑现仅比较同指标、同实际期间、同单位和同会计口径；每次修订追加记录，保留原始版本。</p>
 {#each saved as record}
 {@const comparison=comparisons.find(c=>c.guidance_id===record.id)}
 <article><div class="heading"><h3>{record.supersedes_id?'修订指引':'原始指引'} · {metricName(record.metric)}</h3>{#if !readonly}<button onclick={()=>revise(record)}>修订此版本</button>{/if}</div>
 <p>{record.target_start} → {record.target_end} · {basisName(record.basis)} · {number(record.low)}—{number(record.high)} {record.unit}</p>
 <p>区间中点 {number(record.low/2+record.high/2)} {record.unit} · （下限 + 上限）÷ 2</p>
 <p>发布 {record.issued_at} · {comparison?outcome[comparison.status]??'暂不可比':'等待实际值比较'}{#if comparison?.actual!=null} · 实际 {number(comparison.actual)} {record.unit}{/if}</p>
 {#if comparison?.reason}<p>{missingReason(comparison.reason)}</p>{/if}
 <p><a href={record.source_url} target="_blank" rel="noreferrer">指引原文 ↗</a> · {record.source_locator}</p>
 <details><summary>版本与比较输入</summary><p>本机首次记录 {record.first_seen_at??'未知'} · {record.note}</p><pre>{JSON.stringify({record,comparison},null,2)}</pre></details>
 </article>
 {:else}<p>尚未记录指引；可从公司财报原文核验后录入。</p>{/each}
 {#if !readonly}
 <details open><summary>{draft.supersedes_id?'追加修订':'记录公司原始指引'}</summary>
 <div class="fields">
 <label>指引指标<select bind:value={draft.metric} disabled={!!draft.supersedes_id}><option value="">请选择指标</option>{#each knownMetrics as metric}<option value={metric}>{metricName(metric)}</option>{/each}{#if draft.metric&&!knownMetrics.includes(draft.metric)}<option value={draft.metric}>公司自定义指标</option>{/if}</select></label>
 <label>目标期间开始<input type="date" bind:value={draft.target_start} readonly={!!draft.supersedes_id} /></label>
 <label>目标期间结束<input type="date" bind:value={draft.target_end} readonly={!!draft.supersedes_id} /></label>
 <label>会计口径<select bind:value={draft.basis}><option value="">请选择明确口径</option>{#each knownBases as basis}<option value={basis}>{basisName(basis)}</option>{/each}{#if draft.basis&&!knownBases.includes(draft.basis)}<option value={draft.basis}>公司特定口径（暂不自动比较）</option>{/if}</select></label>
 <label>单位<input bind:value={draft.unit} placeholder="例如 USD、USD/shares 或 ratio" /></label>
 <label>指引下限<input type="number" step="any" bind:value={draft.low} /></label><label>指引上限<input type="number" step="any" bind:value={draft.high} /></label>
 <label>发布时间（本机时区）<input type="datetime-local" bind:value={draft.issued_at} /></label>
 <label>原文链接<input type="url" bind:value={draft.source_url} /></label><label>原文定位<input bind:value={draft.source_locator} placeholder="页码、表格或原句" /></label>
 </div><details><summary>公司自定义指标与特定口径</summary><p>标准指标以外的业务指引请保留公司原始定义。完整口径须标明 company: 或 non-gaap:，并说明具体定义及调整项；未核验口径不自动比较实际值。</p><div class="fields"><label>自定义指引指标<input bind:value={draft.metric} readonly={!!draft.supersedes_id} placeholder="保留原文指标定义" /></label><label>完整会计口径<input bind:value={draft.basis} placeholder="例如 company:公司披露口径名称" /></label></div></details><label>口径与调整项说明<textarea bind:value={draft.note} rows="2"></textarea></label>
 <p>ratio 采用小数比例，例如 0.5 表示 50%。请按原文填写，不推测未来财季日期。</p>
 <div class="heading"><button class="primary" onclick={save} disabled={busy}>{busy?'保存中…':'追加指引版本'}</button>{#if draft.supersedes_id}<button onclick={()=>draft=blank()}>改录原始指引</button>{/if}</div>
 </details>
 {/if}
 {#if error}<p role="alert">{error}</p>{/if}{#if message}<p role="status">{message}</p>{/if}
</section>
<style>
 section{min-width:0;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:1.2rem}h2{font-size:1.1rem;font-weight:650}h3{font-weight:600}p{font-size:.85rem;color:var(--muted-foreground);margin:.65rem 0;overflow-wrap:anywhere}.heading{display:flex;gap:1rem;justify-content:space-between;align-items:center;flex-wrap:wrap}.fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));gap:.7rem;margin:.8rem 0}label{display:grid;font-size:.8rem;gap:.3rem}input,select,textarea{width:100%;min-width:0;padding:.5rem;border:1px solid var(--border);border-radius:5px;background:var(--muted);color:var(--foreground)}button{padding:.5rem .8rem;border:1px solid var(--border);border-radius:6px;background:var(--muted);font-size:.8rem}.primary{background:var(--primary);color:white}button:disabled{opacity:.5}article{padding:1rem 0;border-bottom:1px solid var(--border)}details{margin-top:.8rem;font-size:.8rem}summary,a{color:var(--primary);cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}[role=alert]{color:var(--destructive,#b33)}
</style>
