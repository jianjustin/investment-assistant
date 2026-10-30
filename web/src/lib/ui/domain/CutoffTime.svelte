<script lang="ts">
  import { fmtBeijing } from '$lib/format'
  import StatusPill from './StatusPill.svelte'

  // 截止 2026-10-30 17:00:00 北京 (fmtBeijing as it is); the tooltip is the relative time. An empty value is
  // the not-computed state, never fmtBeijing's dash.
  let { at, label = '截止' }: { at: string | null | undefined; label?: string } = $props()

  function relative(value: string): string | undefined {
    const t = new Date(value).getTime()
    if (Number.isNaN(t)) return undefined
    const diff = Date.now() - t
    const mins = Math.round(Math.abs(diff) / 60000)
    const tail = diff >= 0 ? '前' : '后'
    if (mins < 1) return '刚刚'
    if (mins < 60) return `${mins} 分钟${tail}`
    if (mins < 60 * 24) return `${Math.round(mins / 60)} 小时${tail}`
    return `${Math.round(mins / 1440)} 天${tail}`
  }

  const empty = $derived(at === null || at === undefined || at === '')
</script>

{#if empty}
  <span class="inline-flex items-center gap-1.5">{label} <StatusPill domain="block" value="not_computed" /></span>
{:else}
  <time datetime={at ?? undefined} title={relative(at!)}>{label} {fmtBeijing(at)}</time>
{/if}
