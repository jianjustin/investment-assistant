<script lang="ts">
  import { onMount } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import DataTable from '$lib/ui/data-table/DataTable.svelte'
  import type { Column } from '$lib/ui/data-table/types'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import SampleSize from '$lib/ui/domain/SampleSize.svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import * as api from '../api'
  import { ATTACH } from '../knowledge'
  import { CITED_FIELD_TEXT, growthError, sampleLine } from '../growth'
  import type { KnowledgePerf } from '../growth'
  import { KIND_TEXT, rText } from '../workbench'

  // 条目页的「表现回看」（spec §7）：样本行常驻在最上方；少于 min_sample 个有结果的不给均值；
  // 复查中被引用的次数单列，不进样本。证据状态「未验证」常驻。
  let { id }: { id: number } = $props()

  let perf = $state<KnowledgePerf | null>(null)
  let error = $state('')

  onMount(() => {
    api.getKnowledgePerformance(id).then(next => { perf = next }).catch((e: unknown) => { error = growthError(e) })
  })
  const versionText = (n: number | null) => (n != null ? ` 第 ${n} 版` : '')

  type Row = KnowledgePerf['rows'][number]
  type Version = KnowledgePerf['by_version'][number]
  const rowColumns: Column<Row>[] = [
    { key: 'unit', header: '单元', cell: unitCell }, { key: 'plan', header: '计划', cell: planCell },
    { key: 'cited', header: '引用', cell: citedCell }, { key: 'status', header: '状态', value: r => r.status_text },
    { key: 'r', header: 'R', align: 'num', value: r => rText(r.r) }, { key: 'result', header: '成交 / 结果', cell: resultCell },
  ]
  const versionColumns: Column<Version>[] = [
    { key: 'version', header: '知识版本', value: v => `第 ${v.version} 版` },
    { key: 'plans', header: '计划数', align: 'num' }, { key: 'units', header: '单元数', align: 'num' },
  ]
</script>

{#snippet unitCell(row: Row)}<a class="text-primary underline" href={`#plan/${row.plan_id}`}>{row.unit.ticker} {row.unit.signal_date}</a>{/snippet}
{#snippet planCell(row: Row)}{KIND_TEXT[row.kind] ?? row.kind}{versionText(row.version_no)}{/snippet}
{#snippet citedCell(row: Row)}引用第 {row.cited_version} 版知识{#if row.fields.length} · {row.fields.map(f => CITED_FIELD_TEXT[f] ?? f).join('、')}{/if}{/snippet}
{#snippet resultCell(row: Row)}{row.fill_date ?? '—'} → {row.outcome_date ?? '—'}{/snippet}

{#if perf}
  <section aria-label="表现回看" class="grid gap-2 text-sm">
    <h3 class="text-base font-medium">表现回看 <span class="text-xs font-normal"><ConceptTerm id={ATTACH.myKnowledge.performance}>说明</ConceptTerm></span></h3>
    <p data-sample class="font-medium">{sampleLine(perf.sample, perf.min_sample, rText)}</p>
    <p class="flex items-center gap-2 text-xs text-muted-foreground"><span>有结果的样本</span><SampleSize n={perf.sample.determined} min={perf.min_sample} /></p>
    <p class="text-xs text-muted-foreground">{perf.note}</p>
    <p class="text-xs text-muted-foreground">证据：未验证 <ConceptTerm id={ATTACH.agentCard.evidence}>证据状态</ConceptTerm></p>
    {#if perf.rows.length}
      <DataTable columns={rowColumns} rows={perf.rows} rowKey={r => r.plan_id} ariaLabel="每个单元的首个引用版本" cards="narrow" />
    {/if}
    {#if perf.by_version.length}
      <DataTable columns={versionColumns} rows={perf.by_version} rowKey={v => v.version} ariaLabel="按知识版本" />
    {/if}
    <p class="text-xs">复查中被引用 {perf.reviews_cited} 次</p>
  </section>
{:else if error}
  <Alert variant="danger"><Icon name="circle-x" /><AlertDescription>表现回看加载失败：<span>{error}</span></AlertDescription></Alert>
{:else}
  <DataBlock state="loading" skeleton="row" />
{/if}
