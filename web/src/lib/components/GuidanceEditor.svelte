<script lang="ts">
 import { untrack, onDestroy, onMount } from 'svelte'
 import { registerNavigationGuard } from '../navigation-guard'
 import * as api from '../api'
 import type { GuidanceRecord, GuidanceComparison } from '../api'
 import { metricName, number, basisName, missingReason } from '../us-research-format'
 import { Alert, AlertDescription } from '$lib/ui/alert/index'
 import { Button } from '$lib/ui/button/index'
 import * as Card from '$lib/ui/card/index'
 import Field from '$lib/ui/field/Field.svelte'
 import { Input } from '$lib/ui/input/index'
 import { Textarea } from '$lib/ui/textarea/index'
 import Section from '$lib/ui/domain/Section.svelte'
 let { symbol, records=[], comparisons=[], readonly=false, onSaved }: {symbol:string;records?:GuidanceRecord[];comparisons?:GuidanceComparison[];readonly?:boolean;onSaved?:()=>Promise<void>}=$props()
 const knownMetrics=['revenue','gross_margin','operating_income','net_income','consolidated_net_income','common_net_income','eps_diluted','cfo','cash_capex','fcf']
 const knownBases=['us-gaap:consolidated','us-gaap:parent','us-gaap:common']
 const uid=$props.id()
 const SELECT='h-8 w-full min-w-0 rounded-md border border-input bg-card px-2 text-sm text-foreground disabled:opacity-50'
 const NUM='text-right tabular-nums'
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
<Card.Root class="min-w-0 px-4">
<Section level={2} title="公司指引与兑现比较">
 <p class="text-sm text-muted-foreground">未接入一致预期</p><p class="text-sm text-muted-foreground">指引属于公司披露。兑现仅比较同指标、同实际期间、同单位和同会计口径；每次修订追加记录，保留原始版本。</p>
 {#each saved as record}
 {@const comparison=comparisons.find(c=>c.guidance_id===record.id)}
 <article class="grid gap-1 border-t border-border py-3 wrap-anywhere"><div class="flex flex-wrap items-center justify-between gap-3"><h3 class="text-base font-medium">{record.supersedes_id?'修订指引':'原始指引'} · {metricName(record.metric)}</h3>{#if !readonly}<Button size="sm" onclick={()=>revise(record)}>修订此版本</Button>{/if}</div>
 <p class="text-sm text-muted-foreground">{record.target_start} → {record.target_end} · {basisName(record.basis)} · {number(record.low)}—{number(record.high)} {record.unit}</p>
 <p class="text-sm text-muted-foreground">区间中点 {number(record.low/2+record.high/2)} {record.unit} · （下限 + 上限）÷ 2</p>
 <p class="text-sm text-muted-foreground">发布 {record.issued_at} · {comparison?outcome[comparison.status]??'暂不可比':'等待实际值比较'}{#if comparison?.actual!=null} · 实际 {number(comparison.actual)} {record.unit}{/if}</p>
 {#if comparison?.reason}<p class="text-sm text-muted-foreground">{missingReason(comparison.reason)}</p>{/if}
 <p class="text-sm text-muted-foreground"><a class="text-primary underline" href={record.source_url} target="_blank" rel="noreferrer">指引原文 ↗</a> · {record.source_locator}</p>
 <details class="text-xs"><summary class="cursor-pointer text-primary">版本与比较输入</summary><p class="my-2 text-sm text-muted-foreground">本机首次记录 {record.first_seen_at??'未知'} · {record.note}</p><pre class="max-w-full whitespace-pre-wrap text-xs wrap-anywhere">{JSON.stringify({record,comparison},null,2)}</pre></details>
 </article>
 {:else}<p class="text-sm text-muted-foreground">尚未记录指引；可从公司财报原文核验后录入。</p>{/each}
 {#if !readonly}
 <details open class="grid gap-3 text-sm"><summary class="cursor-pointer text-primary">{draft.supersedes_id?'追加修订':'记录公司原始指引'}</summary>
 <div class="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
 <Field label="指引指标" id={`${uid}-metric`}>{#snippet children({id,describedby})}<select {id} aria-describedby={describedby} class={SELECT} bind:value={draft.metric} disabled={!!draft.supersedes_id}><option value="">请选择指标</option>{#each knownMetrics as metric}<option value={metric}>{metricName(metric)}</option>{/each}{#if draft.metric&&!knownMetrics.includes(draft.metric)}<option value={draft.metric}>公司自定义指标</option>{/if}</select>{/snippet}</Field>
 <Field label="目标期间开始" id={`${uid}-start`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} type="date" bind:value={draft.target_start} readonly={!!draft.supersedes_id} />{/snippet}</Field>
 <Field label="目标期间结束" id={`${uid}-end`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} type="date" bind:value={draft.target_end} readonly={!!draft.supersedes_id} />{/snippet}</Field>
 <Field label="会计口径" id={`${uid}-basis`}>{#snippet children({id,describedby})}<select {id} aria-describedby={describedby} class={SELECT} bind:value={draft.basis}><option value="">请选择明确口径</option>{#each knownBases as basis}<option value={basis}>{basisName(basis)}</option>{/each}{#if draft.basis&&!knownBases.includes(draft.basis)}<option value={draft.basis}>公司特定口径（暂不自动比较）</option>{/if}</select>{/snippet}</Field>
 <Field label="单位" id={`${uid}-unit`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} bind:value={draft.unit} placeholder="例如 USD、USD/shares 或 ratio" />{/snippet}</Field>
 <Field label="指引下限" id={`${uid}-low`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} type="number" step="any" inputmode="decimal" class={NUM} bind:value={draft.low} />{/snippet}</Field>
 <Field label="指引上限" id={`${uid}-high`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} type="number" step="any" inputmode="decimal" class={NUM} bind:value={draft.high} />{/snippet}</Field>
 <Field label="发布时间（本机时区）" id={`${uid}-issued`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} type="datetime-local" bind:value={draft.issued_at} />{/snippet}</Field>
 <Field label="原文链接" id={`${uid}-url`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} type="url" bind:value={draft.source_url} />{/snippet}</Field>
 <Field label="原文定位" id={`${uid}-locator`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} bind:value={draft.source_locator} placeholder="页码、表格或原句" />{/snippet}</Field>
 </div>
 <details class="text-xs"><summary class="cursor-pointer text-primary">公司自定义指标与特定口径</summary><p class="my-2 text-sm text-muted-foreground">标准指标以外的业务指引请保留公司原始定义。完整口径须标明 company: 或 non-gaap:，并说明具体定义及调整项；未核验口径不自动比较实际值。</p><div class="grid gap-3 sm:grid-cols-2">
  <Field label="自定义指引指标" id={`${uid}-custom-metric`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} bind:value={draft.metric} readonly={!!draft.supersedes_id} placeholder="保留原文指标定义" />{/snippet}</Field>
  <Field label="完整会计口径" id={`${uid}-custom-basis`}>{#snippet children({id,describedby})}<Input {id} aria-describedby={describedby} bind:value={draft.basis} placeholder="例如 company:公司披露口径名称" />{/snippet}</Field>
 </div></details>
 <Field label="口径与调整项说明" id={`${uid}-note`}>{#snippet children({id,describedby})}<Textarea {id} aria-describedby={describedby} bind:value={draft.note} rows={2} />{/snippet}</Field>
 <p class="text-sm text-muted-foreground">ratio 采用小数比例，例如 0.5 表示 50%。请按原文填写，不推测未来财季日期。</p>
 <div class="flex flex-wrap items-center gap-3"><Button variant="primary" onclick={save} {busy} busyText="保存中…">追加指引版本</Button>{#if draft.supersedes_id}<Button onclick={()=>draft=blank()}>改录原始指引</Button>{/if}</div>
 </details>
 {/if}
 {#if error}<Alert variant="danger"><AlertDescription>{error}</AlertDescription></Alert>{/if}{#if message}<Alert variant="info"><AlertDescription>{message}</AlertDescription></Alert>{/if}
</Section>
</Card.Root>
