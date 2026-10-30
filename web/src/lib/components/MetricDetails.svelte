<script lang="ts">
 import type { ResearchMetric } from '../api'
 import { metricValue, methodName, basisName, missingReason } from '../us-research-format'
 let { metric, period = '' }: { metric?:ResearchMetric; period?:string } = $props()
</script>
<span class="value">{metricValue(metric)}</span>
{#if metric?.value == null}<small>{missingReason(metric?.missing_reason)}</small>{/if}
<details><summary>计算与来源</summary>
 <p>{period} · {basisName(metric?.basis)}</p><p>{methodName(metric?.method)}</p>
 {#each metric?.sources ?? [] as source}
 <p>{source.start ?? ''} → {source.end ?? source.date ?? ''} · 披露 {source.filed ?? '未知'}
 {#if source.source_url}<a href={source.source_url} target="_blank" rel="noreferrer">原文 ↗</a>{/if}</p>
 {/each}
 <details><summary>原始口径及输入记录</summary><pre>{JSON.stringify(metric ?? {},null,2)}</pre></details>
</details>
<style>
 .value{font-variant-numeric:tabular-nums}small{display:block;color:var(--muted-foreground);white-space:normal;min-width:9rem}details{font-size:.75rem;margin-top:.25rem;white-space:normal}summary{cursor:pointer;color:var(--primary)}p{margin:.4rem 0;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.7rem;max-width:30rem}a{color:var(--primary)}
</style>
