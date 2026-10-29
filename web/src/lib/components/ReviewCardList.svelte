<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../api'
  import { actualRText, CARD_STATUS_TEXT, DISCIPLINE_TEXT, endText, growthError, normalizeTicker } from '../growth'
  import type { CardStatus, ReviewCardRow } from '../growth'
  import { rText } from '../workbench'

  // 「复盘 → 复盘卡」列表（spec §4.7）：按结束日倒序；标的 · 结束类型 · 结束日 · 你的决定 · 实际 R（无成交写「未成交」）·
  // 规则 / Agent 轨道 R · 纪律标记（待定的灰显）· 状态 · headline（没有草稿写状态文案）。可按状态、标的筛选。
  let { oncounts }: { oncounts?: (counts: Partial<Record<CardStatus, number>>) => void } = $props()

  let status = $state('')
  let ticker = $state('')
  let cards = $state<ReviewCardRow[] | null>(null)
  let counts = $state<Partial<Record<CardStatus, number>>>({})
  let error = $state('')
  let generation = 0

  async function load() {
    const token = ++generation
    const params: { status?: string; ticker?: string } = {}
    if (status) params.status = status
    if (ticker) params.ticker = ticker
    try {
      const res = await api.getReviewCards(params)
      if (token !== generation) return
      cards = Array.isArray(res?.cards) ? res.cards : []
      counts = res?.counts ?? {}
      error = ''
      // only an unfiltered read says how many cards are waiting for review
      if (!status && !ticker) oncounts?.(counts)
    } catch (e) {
      if (token !== generation) return
      cards = null
      error = growthError(e)
    }
  }
  onMount(() => { void load() })

  const stateOrder: CardStatus[] = ['to_review', 'reviewed', 'drafting', 'draft_failed']
  const settled = (row: ReviewCardRow) => row.flags.filter(f => !row.immature.includes(f))
</script>

<div class="space-y-3">
  <div class="flex flex-wrap items-end gap-3 text-sm">
    <label class="flex flex-col text-xs">状态
      <select aria-label="状态" class="border border-border rounded px-2 py-1 bg-bg text-sm" bind:value={status} onchange={load}>
        <option value="">全部</option>
        {#each stateOrder as s (s)}<option value={s}>{CARD_STATUS_TEXT[s]}</option>{/each}
      </select>
    </label>
    <label class="flex flex-col text-xs">标的
      <input aria-label="标的" class="border border-border rounded px-2 py-1 bg-bg text-sm w-28" value={ticker}
             onchange={e => { ticker = normalizeTicker((e.currentTarget as HTMLInputElement).value); void load() }} />
    </label>
    {#if cards}
      <p class="text-xs text-muted">待审定 {counts.to_review ?? 0} · 已审定 {counts.reviewed ?? 0} · 起草中 {counts.drafting ?? 0}
        · 起草失败 {counts.draft_failed ?? 0}</p>
    {/if}
  </div>

  {#if error}
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if cards === null}
    <p class="text-sm text-muted">加载中…</p>
  {:else if cards.length === 0}
    <p class="text-sm text-muted">还没有复盘卡</p>
  {:else}
    <table class="text-sm w-full">
      <thead><tr class="text-left text-xs text-muted">
        <th>标的</th><th>结束</th><th>你的决定</th><th>实际 R</th><th>规则 / Agent R</th><th>纪律</th><th>状态</th><th>一句话</th>
      </tr></thead>
      <tbody>
        {#each cards as row (row.id)}
          <tr class="align-top border-t border-border">
            <td><a class="text-accent underline" href={`#review/cards/${row.id}`}>{row.ticker}</a>
              {#if row.signal_date}<span class="block text-xs text-muted">{row.signal_date}</span>{/if}</td>
            <td class="text-xs">{endText(row.end_kind, row.exit_basis)}<span class="block text-muted">{row.end_session}</span></td>
            <td class="text-xs">{row.decision_text}</td>
            <td class="text-xs">{actualRText(row)}</td>
            <td class="text-xs">规则 {rText(row.rule_r)}<span class="block">Agent {rText(row.agent_r)}</span></td>
            <td class="text-xs">
              {#each settled(row) as flag (flag)}<span class="mr-1 px-1 rounded bg-amber-100 text-amber-800">{DISCIPLINE_TEXT[flag] ?? flag}</span>{/each}
              {#each row.immature as flag (flag)}<span data-pending="true" class="mr-1 px-1 rounded bg-surface-2 text-muted">{DISCIPLINE_TEXT[flag] ?? flag}（待定）</span>{/each}
            </td>
            <td class="text-xs">{CARD_STATUS_TEXT[row.status] ?? row.status}</td>
            <td class="text-xs" data-headline>{row.headline ?? CARD_STATUS_TEXT[row.status] ?? row.status}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>
