<script lang="ts">
  import { onMount } from 'svelte'
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
</script>

{#if perf}
  <section aria-label="表现回看" class="space-y-2 text-sm">
    <h3 class="font-semibold">表现回看 <span class="text-xs font-normal"><ConceptTerm id={ATTACH.myKnowledge.performance}>说明</ConceptTerm></span></h3>
    <p data-sample class="font-medium">{sampleLine(perf.sample, perf.min_sample, rText)}</p>
    <p class="text-xs text-muted-foreground">{perf.note}</p>
    <p class="text-xs text-muted-foreground">证据：未验证 <ConceptTerm id={ATTACH.agentCard.evidence}>证据状态</ConceptTerm></p>
    {#if perf.rows.length}
      <table aria-label="每个单元的首个引用版本" class="text-xs w-full">
        <thead><tr class="text-left text-muted-foreground"><th>单元</th><th>计划</th><th>引用</th><th>状态</th><th>R</th><th>成交 / 结果</th></tr></thead>
        <tbody>
          {#each perf.rows as row (row.plan_id)}
            <tr>
              <td><a class="text-primary underline" href={`#plan/${row.plan_id}`}>{row.unit.ticker} {row.unit.signal_date}</a></td>
              <td>{KIND_TEXT[row.kind] ?? row.kind}{versionText(row.version_no)}</td>
              <td>引用第 {row.cited_version} 版知识{#if row.fields.length} · {row.fields.map(f => CITED_FIELD_TEXT[f] ?? f).join('、')}{/if}</td>
              <td>{row.status_text}</td>
              <td>{rText(row.r)}</td>
              <td>{row.fill_date ?? '—'} → {row.outcome_date ?? '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
    {#if perf.by_version.length}
      <table aria-label="按知识版本" class="text-xs">
        <thead><tr class="text-left text-muted-foreground"><th>知识版本</th><th>计划数</th><th>单元数</th></tr></thead>
        <tbody>
          {#each perf.by_version as v (v.version)}
            <tr><td>第 {v.version} 版</td><td>{v.plans}</td><td>{v.units}</td></tr>
          {/each}
        </tbody>
      </table>
    {/if}
    <p class="text-xs">复查中被引用 {perf.reviews_cited} 次</p>
  </section>
{:else if error}
  <p role="alert" class="text-sm text-red-600">表现回看加载失败：<span>{error}</span></p>
{:else}
  <p class="text-xs text-muted-foreground">表现回看加载中…</p>
{/if}
