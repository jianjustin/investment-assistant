<script lang="ts">
  import { NODE_STATUS_TEXT, durationText } from '../runs'
  import type { RunNode } from '../runs'

  // 节点状态图（spec §7.3）：一行等宽格子，格子之间画箭头；窄屏折成两行、每行五个。
  // 状态不只靠颜色：每格另有图标、状态文字与 aria-label「<标题>：<状态文字>」；attempt > 1 的格子右上角标「×n」。
  let { nodes, selected, onselect }: { nodes: RunNode[]; selected: string | null; onselect: (id: string) => void } = $props()

  const NARROW_QUERY = '(max-width: 900px)'
  const PER_ROW = 5
  let narrow = $state(typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(NARROW_QUERY).matches : false)

  $effect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia(NARROW_QUERY)
    const update = () => { narrow = mq.matches }
    update()
    mq.addEventListener?.('change', update)
    return () => mq.removeEventListener?.('change', update)
  })

  const columns = $derived(narrow ? Math.min(PER_ROW, Math.max(nodes.length, 1)) : Math.max(nodes.length, 1))

  const ICON: Record<string, string> = {
    success: '✓', degraded: '▲', partial: '▲', failed: '✕', skipped: '–', pending: '○', running: '◐',
  }
  // 颜色取主题变量（tailwind 的 success / warn / danger / accent / muted）
  const TONE: Record<string, string> = {
    success: 'border-success text-success',
    degraded: 'border-warn text-warn',
    partial: 'border-warn text-warn',
    failed: 'border-danger text-danger',
    skipped: 'border-border text-muted bg-surface-2',
    pending: 'border-dashed border-border text-muted',
    running: 'border-accent text-accent animate-pulse',
  }
  const statusText = (status: string) => NODE_STATUS_TEXT[status] ?? status
  const showArrow = (index: number) =>
    index < nodes.length - 1 && !(narrow && (index + 1) % PER_ROW === 0)
</script>

<ol aria-label="节点状态图" data-columns={columns} data-narrow={narrow}
    class="grid gap-x-5 gap-y-4 py-1"
    style:grid-template-columns={`repeat(${columns}, minmax(0, 1fr))`}>
  {#each nodes as node, index (node.id)}
    <li class="relative min-w-0" data-node={node.id}>
      <button type="button"
              aria-label={`${node.title}：${statusText(node.status)}`}
              aria-pressed={selected === node.id}
              onclick={() => onselect(node.id)}
              class="relative flex w-full flex-col items-center gap-0.5 rounded border-2 bg-surface px-1 py-2 text-center text-xs
                     {TONE[node.status] ?? 'border-border text-muted'} {selected === node.id ? 'ring-2 ring-accent' : ''}">
        <span aria-hidden="true" class="text-base leading-none">{ICON[node.status] ?? '?'}</span>
        <span class="max-w-full break-words font-medium text-ink">{node.title}</span>
        <span class="text-[11px]">{statusText(node.status)}</span>
        <span class="min-h-4 text-[11px] text-muted">{durationText(node.duration_ms)}</span>
        {#if node.attempt > 1}
          <span class="absolute -right-1 -top-2 rounded bg-surface-2 px-1 text-[11px] font-medium text-ink border border-border"
                title={`第 ${node.attempt} 次尝试`}>×{node.attempt}</span>
        {/if}
      </button>
      {#if showArrow(index)}
        <svg data-arrow viewBox="0 0 20 12" aria-hidden="true" focusable="false"
             class="absolute top-1/2 h-3 w-4 -translate-y-1/2 text-muted" style="right: -1.15rem">
          <path d="M0 6h16M11 1l6 5-6 5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      {/if}
    </li>
  {/each}
</ol>
