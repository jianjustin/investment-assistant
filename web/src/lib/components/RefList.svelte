<script lang="ts">
  import RefLink from '$lib/ui/domain/RefLink.svelte'
  import * as wb from '../workbench'
  import { refKind } from '../growth'

  // 引用列表（复盘叙述与讨论回答共用）：fact: 回调页面去滚动，call: 就地展开那次工具调用，know: 链到那一版知识，
  // concept: 就地展开概念卡，其余（user: 等）是纯文本。call 只有给了 runId 才能展开；展开时才取一次运行详情。
  let { refs, runId = null, onFact }:
    { refs: string[]; runId?: string | null; onFact?: (key: string) => void } = $props()

  let open = $state<Record<number, boolean>>({})
  let calls = $state<Map<number, wb.AgentToolCall> | null>(null)
  let error = $state('')
  let fetching: Promise<void> | null = null

  const seqOf = (ref: string) => Number(ref.split(':')[1])

  function fetchCalls(): Promise<void> {
    if (!fetching) {
      fetching = wb.getAgentRun(runId!).then(detail => {
        calls = new Map((detail.tool_calls ?? []).map(c => [c.seq, c]))
      }).catch((e: unknown) => {
        error = wb.describeError(e)
        fetching = null
      })
    }
    return fetching
  }

  async function toggle(ref: string) {
    const seq = seqOf(ref)
    if (open[seq]) { open[seq] = false; return }
    open[seq] = true
    await fetchCalls()
  }

  const openSeqs = $derived(refs.filter(r => refKind(r) === 'call').map(seqOf).filter(seq => open[seq]))
</script>

<span class="refs">（{#each refs as ref, i (i)}{#if i}、{/if}<RefLink {ref} {onFact} onCall={runId ? toggle : undefined} expanded={refKind(ref) === 'call' && !!open[seqOf(ref)]} />{/each}）</span>
{#each openSeqs as seq (seq)}
  {@const call = calls?.get(seq)}
  <div role="region" aria-label={`工具调用 call:${seq}`} class="my-1 p-2 border border-border rounded-sm bg-card text-xs space-y-1">
    {#if error}
      <p class="text-destructive">{error}</p>
    {:else if !calls}
      <p class="text-muted-foreground">加载中…</p>
    {:else if call}
      <p class="text-muted-foreground">工具 {call.tool} · 阶段 {call.phase} · {wb.dateTime(call.called_at)}</p>
      <p class="break-all">参数 {JSON.stringify(call.args)}</p>
      <p class="break-all text-muted-foreground">哈希 {call.result_sha256.slice(0, 8)}</p>
      <pre class="whitespace-pre-wrap break-all max-h-64 overflow-auto">{JSON.stringify(call.result, null, 2)}</pre>
    {:else}
      <p class="text-muted-foreground">未找到该编号的工具调用</p>
    {/if}
  </div>
{/each}
