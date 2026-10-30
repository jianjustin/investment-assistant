<script lang="ts">
  import { Button } from '$lib/ui/button/index'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import { TONES, type Tone } from '$lib/ui/domain/status'
  import { useNarrow } from '$lib/ui/narrow.svelte'
  import { NODE_STATUS_TEXT, durationText } from '../runs'
  import type { RunNode } from '../runs'

  // 节点状态图（spec §7.3）：一行等宽格子，格子之间画箭头；窄屏（< 768px）折成两行、每行五个。
  // 状态不只靠颜色：每格另有图标、状态文字与 aria-label「<标题>：<状态文字>」；attempt > 1 的格子右上角标「×n」。
  let { nodes, selected, onselect }: { nodes: RunNode[]; selected: string | null; onselect: (id: string) => void } = $props()

  const PER_ROW = 5
  const narrow = useNarrow()

  const columns = $derived(narrow.current ? Math.min(PER_ROW, Math.max(nodes.length, 1)) : Math.max(nodes.length, 1))

  // success / failed use icons; the rest keep their text glyphs (decorative, the status text is next to them)
  const GLYPH: Record<string, string> = { degraded: '▲', partial: '▲', skipped: '–', pending: '○', running: '◐' }
  // The colour of a cell is the tone of the status in the shared vocabulary (status.ts), as token classes.
  const TONE_CLASS: Record<Tone, string> = {
    success: 'border-success text-success',
    warn: 'border-warn text-warn',
    danger: 'border-destructive text-destructive',
    info: 'border-info text-info',
    running: 'border-running text-running animate-running',
    neutral: 'border-border text-muted-foreground',
  }
  const toneOf = (status: string): Tone => (TONES.node as Record<string, Tone>)[status] ?? 'neutral'
  const statusText = (status: string) => NODE_STATUS_TEXT[status] ?? status
  const showArrow = (index: number) =>
    index < nodes.length - 1 && !(narrow.current && (index + 1) % PER_ROW === 0)
</script>

<ol aria-label="节点状态图" data-columns={columns} data-narrow={narrow.current}
    class="grid gap-x-5 gap-y-4 py-1"
    style:grid-template-columns={`repeat(${columns}, minmax(0, 1fr))`}>
  {#each nodes as node, index (node.id)}
    <li class="relative min-w-0" data-node={node.id}>
      <Button variant="outline"
              aria-label={`${node.title}：${statusText(node.status)}`}
              aria-pressed={selected === node.id}
              onclick={() => onselect(node.id)}
              class="relative h-auto w-full flex-col gap-0.5 border-2 px-1 py-2 text-center text-xs font-normal whitespace-normal
                     {TONE_CLASS[toneOf(node.status)]} {node.status === 'pending' ? 'border-dashed' : ''} {selected === node.id ? 'ring-2 ring-primary' : ''}">
        <span aria-hidden="true" class="flex h-4 items-center justify-center text-base leading-none">
          {#if node.status === 'success'}<Icon name="check" />
          {:else if node.status === 'failed'}<Icon name="x" />
          {:else}{GLYPH[node.status] ?? '?'}{/if}
        </span>
        <span class="max-w-full wrap-break-word font-medium text-foreground">{node.title}</span>
        <span class="text-xs">{statusText(node.status)}</span>
        <span class="min-h-4 text-xs text-muted-foreground">{durationText(node.duration_ms)}</span>
        {#if node.attempt > 1}
          <span class="absolute -right-1 -top-2 rounded-sm border border-border bg-muted px-1 text-xs font-medium text-foreground"
                title={`第 ${node.attempt} 次尝试`}>×{node.attempt}</span>
        {/if}
      </Button>
      {#if showArrow(index)}
        <svg data-arrow viewBox="0 0 20 12" aria-hidden="true" focusable="false"
             class="absolute top-1/2 h-3 w-4 -translate-y-1/2 text-muted-foreground" style="right: -1.15rem">
          <path d="M0 6h16M11 1l6 5-6 5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      {/if}
    </li>
  {/each}
</ol>
