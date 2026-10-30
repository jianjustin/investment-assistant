<script lang="ts">
 import type { ResearchMetric } from '../api'
 import { metricValue, methodName, basisName, missingReason } from '../us-research-format'
 let { metric, period = '' }: { metric?:ResearchMetric; period?:string } = $props()
</script>
<span class="tabular-nums">{metricValue(metric)}</span>
{#if metric?.value == null}<small class="block min-w-36 whitespace-normal text-muted-foreground">{missingReason(metric?.missing_reason)}</small>{/if}
<details class="mt-1 whitespace-normal text-xs">
 <summary class="cursor-pointer text-primary">计算与来源</summary>
 <p class="my-1.5 wrap-anywhere text-muted-foreground">{period} · {basisName(metric?.basis)}</p><p class="my-1.5 wrap-anywhere text-muted-foreground">{methodName(metric?.method)}</p>
 {#each metric?.sources ?? [] as source}
 <p class="my-1.5 wrap-anywhere text-muted-foreground">{source.start ?? ''} → {source.end ?? source.date ?? ''} · 披露 {source.filed ?? '未知'}
 {#if source.source_url}<a class="text-primary underline" href={source.source_url} target="_blank" rel="noreferrer">原文 ↗</a>{/if}</p>
 {/each}
 <details class="mt-1">
  <summary class="cursor-pointer text-primary">原始口径及输入记录</summary>
  <pre class="max-w-120 whitespace-pre-wrap wrap-anywhere text-xs">{JSON.stringify(metric ?? {},null,2)}</pre>
 </details>
</details>
