<script lang="ts">
  import ConceptTerm from './ConceptTerm.svelte'
  import { ATTACH } from '../knowledge'
  import { fmtBeijing } from '../format'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // 「标的」页计划历史（spec §10.3）：日期 · 链与版本 · 入场 / 止损 / T1 · 变化点（宿主 diff）· 变化原因 · 结束方式。
  // 每条链开头一行 chain_open（灰底，写「为什么又开」），结尾一行 chain_end；链与链之间留一道分隔；
  // 并入的单元（retrigger）是链内一行。两个开关是请求参数：切换时回调 onToggle，由页面重新请求。
  let { rows, chains = [], ticker = '', includeReviews = false, includeBaselines = false, onToggle }: {
    rows: wb.HistoryRow[]; chains?: wb.HistoryChain[]; ticker?: string
    includeReviews?: boolean; includeBaselines?: boolean
    onToggle?: (next: { include_reviews: boolean; include_baselines: boolean }) => void
  } = $props()

  const I = ATTACH.instrument
  const KIND_TEXT: Record<string, string> = {
    chain_open: '新开链', version: '版本', retrigger: '再次触发', review: '复查', fill: '成交', chain_end: '结束',
  }

  // 按链分组：连续的同链行一组，保持时间顺序（行已按 at 正序）；没有链的行（如规则基线）按原位置自成一组，
  // 不并到别处。
  const groups = $derived.by(() => {
    const out: { signal: string | null; rows: wb.HistoryRow[] }[] = []
    for (const r of rows ?? []) {
      const last = out[out.length - 1]
      if (last && last.signal === r.chain_signal_date) last.rows.push(r)
      else out.push({ signal: r.chain_signal_date, rows: [r] })
    }
    return out
  })

  const md = (d: string) => d.slice(5)
  const chainText = (r: wb.HistoryRow) => r.chain_signal_date
    ? `${ticker ? `${ticker}·` : ''}${md(r.chain_signal_date)}${r.version_no != null ? ` 第 ${r.version_no} 版` : ''}`
    : '—'
  const levelsText = (r: wb.HistoryRow) => r.levels
    ? `入场 ${r.levels.entry_low}–${r.levels.entry_high} · 止损 ${r.levels.stop} · T1 ${r.levels.target1}` : ''
  const diffItems = (r: wb.HistoryRow) => (r.diff ?? []).map(d =>
    `${tl.CHANGE_FIELD_TEXT[d.field] ?? d.field} ${tl.diffValueText(d.field, d.before)} → ${tl.diffValueText(d.field, d.after)}`)
  const changeTexts = (r: wb.HistoryRow) => (r.changes ?? []).map(c => (typeof c === 'string' ? c : c.text)).filter(Boolean)
  const signalsText = (r: wb.HistoryRow) => (r.signals_fired ?? []).map(k => tl.SIGNAL_TEXT[k] ?? k).join('、')
  const reasonLine = (r: wb.HistoryRow) => [
    r.decided_by ? (tl.DECIDED_BY_TEXT[r.decided_by as tl.DecidedBy] ?? r.decided_by) : '', r.reason ?? '',
  ].filter(Boolean).join('：')
  const endText = (r: wb.HistoryRow) => {
    if (r.kind !== 'chain_end') return ''
    const end = r.end as { text?: string } | string | null | undefined
    return r.text || (typeof end === 'string' ? end : end?.text ?? '')
  }

  // 开关先在本地生效，再通知页面重新请求；页面回传的值覆盖本地值。
  let reviews = $state(false)
  let baselines = $state(false)
  $effect(() => { reviews = includeReviews; baselines = includeBaselines })
  function change() {
    onToggle?.({ include_reviews: reviews, include_baselines: baselines })
  }
</script>

<div class="space-y-2 text-sm">
  <div class="flex flex-wrap items-center gap-4 text-xs">
    <label class="flex items-center gap-1">
      <input type="checkbox" bind:checked={reviews} onchange={change} />
      显示每日维持的复查
    </label>
    <label class="flex items-center gap-1">
      <input type="checkbox" bind:checked={baselines} onchange={change} />
      显示规则基线
    </label>
    <span class="text-muted"><ConceptTerm id={I.chainState}>链状态说明</ConceptTerm></span>
  </div>

  {#if !rows?.length}
    <p class="text-xs text-muted">该标的还没有计划历史</p>
  {:else}
    <div class="overflow-x-auto">
      <table aria-label="计划历史" class="text-xs w-full min-w-[720px]">
        <thead><tr class="text-left text-muted">
          <th>日期</th><th>链与版本</th><th>入场 / 止损 / T1</th><th>变化点</th><th>变化原因</th><th>结束方式</th>
        </tr></thead>
        {#each groups as g, gi (gi)}
          <tbody data-chain={g.signal ?? ''} class={gi > 0 ? (g.signal ? 'border-t-4 border-border' : 'border-t-2 border-border') : ''}>
            {#each g.rows as r, i (`${r.kind}|${r.at}|${i}`)}
              {#if r.kind === 'chain_open'}
                <tr data-kind="chain_open" class="bg-surface-2 align-top">
                  <td class="whitespace-nowrap">{r.session}</td>
                  <td>{chainText(r)}</td>
                  <td colspan="4">{r.text}</td>
                </tr>
              {:else if r.kind === 'chain_end'}
                <tr data-kind="chain_end" class="align-top border-t border-border">
                  <td class="whitespace-nowrap">{r.session}</td>
                  <td>{chainText(r)}</td>
                  <td colspan="3"></td>
                  <td class="font-medium">{endText(r)}</td>
                </tr>
              {:else}
                <tr data-kind={r.kind} class="align-top border-t border-border">
                  <td class="whitespace-nowrap">{r.session}</td>
                  <td>{chainText(r)} <span class="text-muted">{KIND_TEXT[r.kind] ?? r.kind}</span></td>
                  <td>{levelsText(r)}{#if r.validity}<span class="block text-muted">有效期 {r.validity.valid_from} 至 {r.validity.valid_until}</span>{/if}</td>
                  <td>
                    {#each diffItems(r) as d, di (di)}<span class="block">{d}</span>{/each}
                  </td>
                  <td>
                    {#each changeTexts(r) as c, ci (ci)}<span class="block">{c}</span>{/each}
                    {#if signalsText(r)}<span class="block text-muted">触发：{signalsText(r)}</span>{/if}
                    {#if reasonLine(r)}<span class="block">{reasonLine(r)}</span>{/if}
                    {#if !changeTexts(r).length && !reasonLine(r)}<span class="block">{r.text}</span>{/if}
                    <span class="block text-muted">{fmtBeijing(r.at)}</span>
                  </td>
                  <td></td>
                </tr>
              {/if}
            {/each}
          </tbody>
        {/each}
      </table>
    </div>
    {#if chains.length}
      <p class="text-xs text-muted">共 {chains.length} 条链</p>
    {/if}
  {/if}
</div>
