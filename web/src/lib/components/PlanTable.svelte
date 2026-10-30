<script lang="ts">
  import { onMount } from 'svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import PlanRowDetail from './PlanRowDetail.svelte'
  import { ATTACH } from '../knowledge'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // 「今日」计划表（spec §10.1）：三组——入场期（可执行）、持仓中、已结束。后端拼好文案，这里只排版。
  // 已结束默认收起、整组置灰；展开状态存 localStorage（读写失败按收起）。窄屏（< 900px）每行折成卡片。
  // 没有任何决定按钮；行尾的「已采纳 / 未执行」来自执行状态（spec §6.2）。
  let { groups, onExpand, onRecheck, onNote, rechecks = {} }: {
    groups: wb.PlanTableGroups
    onExpand?: (row: wb.PlanTableRow, open: boolean) => void
    onRecheck: (row: wb.PlanTableRow) => void
    onNote: (row: wb.PlanTableRow, body: string, requestId: string) => Promise<void>
    rechecks?: Record<string, { busy: boolean; text: string }>
  } = $props()

  const ENDED_KEY = 'workbench.today.ended_open'
  function readEndedOpen(): boolean {
    try { return globalThis.localStorage?.getItem(ENDED_KEY) === '1' } catch { return false }
  }
  let endedOpen = $state(readEndedOpen())
  function toggleEnded() {
    endedOpen = !endedOpen
    try { globalThis.localStorage?.setItem(ENDED_KEY, endedOpen ? '1' : '0') } catch { /* 存储不可用：只在本页生效 */ }
  }

  const NARROW_QUERY = '(max-width: 899px)'
  let narrow = $state(false)
  onMount(() => {
    let mql: MediaQueryList | undefined
    try { mql = globalThis.matchMedia?.(NARROW_QUERY) } catch { mql = undefined }
    if (!mql) return
    narrow = mql.matches
    const listener = (e: MediaQueryListEvent) => { narrow = e.matches }
    mql.addEventListener?.('change', listener)
    return () => mql!.removeEventListener?.('change', listener)
  })

  let expanded = $state<Record<string, boolean>>({})
  function toggle(row: wb.PlanTableRow) {
    expanded[row.row_id] = !expanded[row.row_id]
    onExpand?.(row, !!expanded[row.row_id])
  }

  const T = ATTACH.today
  const CASES: wb.OpenCase[] = ['in_zone', 'gap_up', 'gap_down']
  const md = (date: string | null | undefined) => (date ? date.slice(5) : '—')
  const ACTION_TEXT: Record<string, string> = { buy: '买入', pass: '不建议买入' }

  function scenarioOf(row: wb.PlanTableRow, kase: wb.OpenCase): string {
    const hit = row.open_scenarios.find(s => s.case === kase)
    if (hit) return hit.text
    const p = row.plan
    return p?.entry_type ? wb.openCaseText(kase, p.entry_type, p) : '—'
  }
  // §7.3: 重新复查不写持仓状态行；当天行之后的复查结论显示在行旁
  function laterReview(row: wb.PlanTableRow): string {
    const r = row.status.latest_review
    const h = row.holding
    if (!r || !h) return ''
    const later = r.trigger === 'recheck' || (!!h.session && r.session > h.session)
    if (!later) return ''
    const who = r.decided_by ? (tl.DECIDED_BY_TEXT[r.decided_by as tl.DecidedBy] ?? r.decided_by) : ''
    return `之后的复查（${r.session}）：${tl.OUTCOME_TEXT[r.outcome as tl.Outcome] ?? r.outcome}${who ? ` · ${who}` : ''}${r.reason ? `：${r.reason}` : ''}`
  }
  const entryTypeText = (p: wb.RowPlan) => p.entry_type_text ?? (p.entry_type ? wb.ENTRY_TYPE_TEXT[p.entry_type] : '—')
  const sharesText = (p: wb.RowPlan) => (p.shares != null ? `${p.shares} 股` : (p.shares_note ?? '—'))
  const resultText = (r: string | null | undefined) => (r ? (tl.CONDITION_RESULT_TEXT[r as tl.ConditionResultValue] ?? r) : '')
  const execText = (row: wb.PlanTableRow) => wb.rowExecutionText(row.status)

  // 状态列保留颜色：作废红、过期橙、平仓绿、被取代灰，其余按强调色。
  function statusClass(row: wb.PlanTableRow): string {
    const label = row.status.label
    if (label.startsWith('已作废')) return 'text-red-600'
    if (label.startsWith('已过期')) return 'text-amber-600'
    if (label.startsWith('已平仓')) return 'text-green-700'
    if (label.startsWith('被取代')) return 'text-muted'
    return 'text-accent'
  }
  const instructionClass = (i: wb.Instruction) =>
    i === 'exit' ? 'text-red-600 font-semibold' : i === 'sell_half' ? 'text-orange-600 font-semibold' : ''

  const entryRows = $derived(groups.entry ?? [])
  const holdingRows = $derived(groups.holding ?? [])
  const endedRows = $derived(groups.ended ?? [])
</script>

{#snippet chainBlock(row: wb.PlanTableRow)}
  <span class="block">{row.chain ? row.chain.label : (row.plan ? `规则基线 ${row.plan.plan_version}` : '无计划')}</span>
  {#if row.plan}<span class="block text-xs text-muted">{wb.KIND_TEXT[row.plan.kind] ?? row.plan.kind} · {row.plan.plan_version}</span>{/if}
  {#if row.plan?.defaults_applied}<span class="block text-xs text-amber-700">{wb.DEFAULTS_APPLIED_TEXT}</span>{/if}
  {#if !row.chain && wb.activeChainText(row)}<span class="block text-xs text-amber-700">{wb.activeChainText(row)}</span>{/if}
  {#each row.chain?.retriggers ?? [] as r (r.unit_signal_date)}
    <!-- 版本号只在这一次触发自带 version_no，或链上只有一次触发时写；否则每条都会写成当前最新版 -->
    {@const v = r.version_no ?? (row.chain!.retriggers.length === 1 ? row.chain!.version_no : null)}
    <span class="block text-xs text-amber-700">{md(r.unit_signal_date)} 再次触发{v != null ? ` → 第 ${v} 版` : ''}</span>
  {/each}
{/snippet}

{#snippet voidBlock(row: wb.PlanTableRow)}
  <ul class="space-y-0.5 text-xs">
    {#each row.void_when as w, i (i)}
      <li>{w.text}{w.last_result ? `（最近判定：${resultText(w.last_result)}）` : ''}</li>
    {/each}
  </ul>
{/snippet}

{#snippet statusBlock(row: wb.PlanTableRow)}
  <span class="block font-medium {statusClass(row)}">{row.status.label}</span>
  {#each row.status.changes_text ?? [] as t, i (i)}<span class="block text-xs">变化：{t}</span>{/each}
  {#if row.status.diff?.length}
    <span class="block text-xs text-muted">相对上版：{row.status.diff.map(d => `${tl.CHANGE_FIELD_TEXT[d.field] ?? d.field} ${tl.diffValueText(d.field, d.before)} → ${tl.diffValueText(d.field, d.after)}`).join('；')}</span>
  {/if}
  {#if execText(row)}<span class="block text-xs"><ConceptTerm id={T.basis}>{execText(row)}</ConceptTerm></span>{/if}
  {#if row.notes?.length}
    <span class="inline-block text-xs text-muted border border-border rounded px-1" title={row.notes.map(n => n.body).join('\n')}
          aria-label={`备注 ${row.notes.length} 条`}>备注 {row.notes.length}</span>
  {/if}
{/snippet}

{#snippet holdingBlock(row: wb.PlanTableRow)}
  {#if row.holding}
    <span class="block text-xs">{wb.holdingLine(row.holding)}</span>
    {#if row.holding.stale}<span class="block text-xs text-amber-700">{wb.STALE_HOLDING_TEXT}</span>{/if}
    {@const later = laterReview(row)}
    {#if later}<span data-testid="later-review" class="block text-xs text-muted">{later}</span>{/if}
  {:else}
    <span class="text-xs text-muted">—</span>
  {/if}
{/snippet}

{#snippet instructionBlock(row: wb.PlanTableRow)}
  {#if row.holding}
    <span data-instruction={row.holding.instruction} class="text-xs {instructionClass(row.holding.instruction)}">{wb.INSTRUCTION_TEXT[row.holding.instruction] ?? row.holding.instruction}</span>
  {/if}
{/snippet}

{#snippet detail(row: wb.PlanTableRow)}
  <div id={`row-detail-${row.row_id}`}>
  <PlanRowDetail {row} recheck={rechecks[row.row_id]} onRecheck={() => onRecheck(row)}
                 onNote={(body, requestId) => onNote(row, body, requestId)} />
  </div>
{/snippet}

{#snippet expandButton(row: wb.PlanTableRow)}
  <button type="button" class="text-xs text-accent underline" aria-expanded={!!expanded[row.row_id]} aria-controls={`row-detail-${row.row_id}`}
          aria-label={`${expanded[row.row_id] ? '收起' : '展开'} ${row.ticker}`} onclick={() => toggle(row)}>{expanded[row.row_id] ? '收起' : '展开'}</button>
{/snippet}

{#snippet tickerCell(row: wb.PlanTableRow)}
  <button type="button" class="font-medium text-accent underline" aria-expanded={!!expanded[row.row_id]}
          aria-controls={`row-detail-${row.row_id}`} onclick={() => toggle(row)}>{row.ticker}</button>
  {#if row.pool === 'extended'}<span class="text-xs px-1 rounded bg-surface-2">扩展池</span>{/if}
  <a class="block text-xs text-muted underline" href={`#instrument/${encodeURIComponent(row.ticker)}`}>标的页</a>
{/snippet}

<!-- 窄屏：每行一张卡片，三种开盘情形纵排 -->
{#snippet cards(rows: wb.PlanTableRow[], group: wb.RowGroup)}
  <ul class="space-y-2">
    {#each rows as row (row.row_id)}
      <li data-testid="plan-card" data-group={group} class="border border-border rounded p-2 bg-surface space-y-1 text-sm">
        <div class={group === 'ended' ? 'opacity-60 space-y-1' : 'space-y-1'}>
        <div class="flex flex-wrap items-center gap-2">
          {@render tickerCell(row)}
          {#if row.plan}<span class="text-xs px-1.5 py-0.5 rounded bg-accent/10 text-accent">{ACTION_TEXT[row.plan.action] ?? row.plan.action}</span>{/if}
        </div>
        <div class="text-xs">{@render chainBlock(row)}</div>
        {#if row.plan}
          <p class="text-xs">{entryTypeText(row.plan)} {row.plan.entry_low}–{row.plan.entry_high} · 止损 {row.plan.stop} · T1 {row.plan.target1} · {sharesText(row.plan)} · 有效期 {row.plan.valid_from} 至 {row.plan.valid_until}</p>
        {/if}
        {#if group === 'entry'}
          <ul class="text-xs space-y-0.5">
            {#each CASES as kase (kase)}<li><span class="text-muted">开盘·{wb.OPEN_CASE_TEXT[kase]}：</span>{scenarioOf(row, kase)}</li>{/each}
          </ul>
        {:else if group === 'holding'}
          {@render holdingBlock(row)}
          <p>{@render instructionBlock(row)}</p>
        {/if}
        <div>{@render voidBlock(row)}</div>
        </div>
        <div>{@render statusBlock(row)}</div>
        {#if group === 'ended' && row.ended_at}<p class="text-xs text-muted">结束于 {row.ended_at}</p>{/if}
        <p>{@render expandButton(row)}</p>
        {#if expanded[row.row_id]}{@render detail(row)}{/if}
      </li>
    {/each}
  </ul>
{/snippet}

<section class="space-y-4" aria-label="计划分组">
  <section aria-label="入场期" class="space-y-2">
    <h2 class="font-semibold text-sm">入场期（可执行）{entryRows.length}</h2>
    {#if entryRows.length === 0}
      <p class="text-sm text-muted">入场期暂无可执行的计划</p>
    {:else if narrow}
      {@render cards(entryRows, 'entry')}
    {:else}
      <div class="overflow-x-auto">
        <table aria-label="入场期计划" class="text-xs w-full min-w-[1100px]">
          <thead><tr class="text-left text-muted align-bottom">
            <th>标的</th><th>链与版本</th><th>动作</th>
            <th>入场类型与区间</th><th>止损</th><th>T1</th><th>建议股数</th><th>有效期</th>
            <th>开盘：区间内</th><th>开盘：高开</th><th>开盘：低开</th><th>本计划何时作废</th><th>状态</th><th></th>
          </tr></thead>
          <tbody>
            {#each entryRows as row (row.row_id)}
              <tr class="align-top border-t border-border" data-group="entry">
                <td>{@render tickerCell(row)}</td>
                <td>{@render chainBlock(row)}</td>
                <td>{row.plan ? (ACTION_TEXT[row.plan.action] ?? row.plan.action) : '—'}</td>
                <td>{#if row.plan}{entryTypeText(row.plan)} {row.plan.entry_low}–{row.plan.entry_high}{:else}—{/if}</td>
                <td>{row.plan?.stop ?? '—'}</td>
                <td>{row.plan?.target1 ?? '—'}</td>
                <td>{row.plan ? sharesText(row.plan) : '—'}</td>
                <td>{#if row.plan}{row.plan.valid_from} 至 {row.plan.valid_until}{:else}—{/if}</td>
                {#each CASES as kase (kase)}<td>{scenarioOf(row, kase)}</td>{/each}
                <td>{@render voidBlock(row)}</td>
                <td>{@render statusBlock(row)}</td>
                <td>{@render expandButton(row)}</td>
              </tr>
              {#if expanded[row.row_id]}
                <tr><td colspan="14" class="p-2 bg-surface-2/40">{@render detail(row)}</td></tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section aria-label="持仓中" class="space-y-2">
    <h2 class="font-semibold text-sm">持仓中 {holdingRows.length}</h2>
    {#if holdingRows.length === 0}
      <p class="text-sm text-muted">当前无持仓</p>
    {:else if narrow}
      {@render cards(holdingRows, 'holding')}
    {:else}
      <div class="overflow-x-auto">
        <table aria-label="持仓计划" class="text-xs w-full min-w-[1000px]">
          <thead><tr class="text-left text-muted align-bottom">
            <th>标的</th><th>链与版本</th><th>动作</th><th>入场类型与区间</th><th>止损</th><th>T1</th><th>建议股数</th><th>有效期</th>
            <th>持仓状态</th><th>指令</th><th>本计划何时作废</th><th>状态</th><th></th>
          </tr></thead>
          <tbody>
            {#each holdingRows as row (row.row_id)}
              <tr class="align-top border-t border-border" data-group="holding">
                <td>{@render tickerCell(row)}</td>
                <td>{@render chainBlock(row)}</td>
                <td>{row.plan ? (ACTION_TEXT[row.plan.action] ?? row.plan.action) : '—'}</td>
                <td>{#if row.plan}{entryTypeText(row.plan)} {row.plan.entry_low}–{row.plan.entry_high}{:else}—{/if}</td>
                <td>{row.holding?.stop ?? row.plan?.stop ?? '—'}</td>
                <td>{row.holding?.target1 ?? row.plan?.target1 ?? '—'}</td>
                <td>{row.plan ? sharesText(row.plan) : '—'}</td>
                <td>{#if row.plan}{row.plan.valid_from} 至 {row.plan.valid_until}{:else}—{/if}</td>
                <td>{@render holdingBlock(row)}</td>
                <td>{@render instructionBlock(row)}</td>
                <td>{@render voidBlock(row)}</td>
                <td>{@render statusBlock(row)}</td>
                <td>{@render expandButton(row)}</td>
              </tr>
              {#if expanded[row.row_id]}
                <tr><td colspan="13" class="p-2 bg-surface-2/40">{@render detail(row)}</td></tr>
              {/if}
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section aria-label="已结束" class="space-y-2">
    <h2 class="font-semibold text-sm">
      <button type="button" class="underline" aria-expanded={endedOpen} aria-controls="plan-table-ended" onclick={toggleEnded}>已结束 {endedRows.length}</button>
    </h2>
    {#if endedOpen}
      <div id="plan-table-ended" data-testid="ended-group" class="text-muted">
        {#if endedRows.length === 0}
          <p class="text-sm">最近 5 个交易日内没有结束的计划</p>
        {:else if narrow}
          {@render cards(endedRows, 'ended')}
        {:else}
          <div class="overflow-x-auto">
            <table aria-label="已结束计划" class="text-xs w-full min-w-[700px]">
              <thead><tr class="text-left align-bottom">
                <th>标的</th><th>链与版本</th><th>入场类型与区间</th><th>止损</th><th>T1</th><th>状态</th><th>结束日</th><th></th>
              </tr></thead>
              <tbody>
                {#each endedRows as row (row.row_id)}
                  <tr class="align-top border-t border-border" data-group="ended">
                    <td class="opacity-60">{@render tickerCell(row)}</td>
                    <td class="opacity-60">{@render chainBlock(row)}</td>
                    <td class="opacity-60">{#if row.plan}{entryTypeText(row.plan)} {row.plan.entry_low}–{row.plan.entry_high}{:else}—{/if}</td>
                    <td class="opacity-60">{row.plan?.stop ?? '—'}</td>
                    <td class="opacity-60">{row.plan?.target1 ?? '—'}</td>
                    <td>{@render statusBlock(row)}</td>
                    <td class="opacity-60">{row.ended_at ?? '—'}</td>
                    <td>{@render expandButton(row)}</td>
                  </tr>
                  {#if expanded[row.row_id]}
                    <tr><td colspan="8" class="p-2">{@render detail(row)}</td></tr>
                  {/if}
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </div>
    {/if}
  </section>
</section>
