<script lang="ts">
  import { Button } from '$lib/ui/button/index'
  import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '$lib/ui/collapsible/index'
  import { DataTable } from '$lib/ui/data-table/index'
  import type { Column } from '$lib/ui/data-table/types'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import MetricValue from '$lib/ui/domain/MetricValue.svelte'
  import PlanLevels from '$lib/ui/domain/PlanLevels.svelte'
  import Section from '$lib/ui/domain/Section.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import { useNarrow } from '$lib/ui/narrow.svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import PlanRowDetail from './PlanRowDetail.svelte'
  import { ATTACH } from '../knowledge'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // 「今日」计划表（spec §10.1）：三组——入场期（可执行）、持仓中、已结束。后端拼好文案，这里只排版。
  // 已结束默认收起、整组置灰；展开状态存 localStorage（读写失败按收起）。窄屏（< 768px）每行折成卡片。
  // 没有任何决定按钮；行尾的「已采纳 / 未执行」来自执行状态（spec §6.2）。
  let { groups, onExpand, onRecheck, onNote, rechecks = {} }: {
    groups: wb.PlanTableGroups
    onExpand?: (row: wb.PlanTableRow, open: boolean) => void
    onRecheck: (row: wb.PlanTableRow) => void
    onNote: (row: wb.PlanTableRow, body: string, requestId: string) => Promise<void>
    rechecks?: Record<string, { busy: boolean; text: string; since?: number }>
  } = $props()

  const ENDED_KEY = 'workbench.today.ended_open'
  function readEndedOpen(): boolean {
    try { return globalThis.localStorage?.getItem(ENDED_KEY) === '1' } catch { return false }
  }
  let endedOpen = $state(readEndedOpen())
  function setEndedOpen(next: boolean) {
    endedOpen = next
    try { globalThis.localStorage?.setItem(ENDED_KEY, next ? '1' : '0') } catch { /* 存储不可用：只在本页生效 */ }
  }

  const narrow = useNarrow()

  // 行展开：三张表共用一个集合（row_id 在三组之间唯一）；点代码或点行首的「展开详情」都走这里。
  let expandedSet = $state(new Set<string | number>())
  const allRows = $derived([...(groups.entry ?? []), ...(groups.holding ?? []), ...(groups.ended ?? [])])
  function setExpanded(next: Set<string | number>) {
    for (const id of next) if (!expandedSet.has(id)) onExpand?.(allRows.find(r => r.row_id === id)!, true)
    for (const id of expandedSet) if (!next.has(id)) onExpand?.(allRows.find(r => r.row_id === id)!, false)
    expandedSet = next
  }
  function toggle(row: wb.PlanTableRow) {
    const next = new Set(expandedSet)
    if (next.has(row.row_id)) next.delete(row.row_id)
    else next.add(row.row_id)
    setExpanded(next)
  }
  const isOpen = (row: wb.PlanTableRow) => expandedSet.has(row.row_id)

  const T = ATTACH.today
  const CASES: wb.OpenCase[] = ['in_zone', 'gap_up', 'gap_down']
  const md = (date: string | null | undefined) => (date ? date.slice(5) : '')
  const ACTION_TEXT: Record<string, string> = { buy: '买入', pass: '不建议买入' }

  function scenarioOf(row: wb.PlanTableRow, kase: wb.OpenCase): string | null {
    const hit = row.open_scenarios.find(s => s.case === kase)
    if (hit) return hit.text
    const p = row.plan
    return p?.entry_type ? wb.openCaseText(kase, p.entry_type, p) : null
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
  const entryTypeText = (p: wb.RowPlan) => p.entry_type_text ?? (p.entry_type ? wb.ENTRY_TYPE_TEXT[p.entry_type] : null)
  const resultText = (r: string | null | undefined) => (r ? (tl.CONDITION_RESULT_TEXT[r as tl.ConditionResultValue] ?? r) : '')
  const execText = (row: wb.PlanTableRow) => wb.rowExecutionText(row.status)
  const num = (v: unknown) => (v == null || v === '' ? null : Number(v))

  // 状态列：标签文字来自后端，语气取自链状态词汇（已结束的都是中性）。
  function chainKey(row: wb.PlanTableRow, group: wb.RowGroup): string {
    if (row.chain && row.chain.state) return row.chain.state
    const label = row.status.label
    if (group === 'holding') return 'holding'
    if (group === 'entry') return 'entry'
    if (label.startsWith('已作废')) return 'invalidated'
    if (label.startsWith('已平仓')) return 'position_closed'
    if (label.startsWith('被取代')) return 'superseded'
    return 'expired'
  }

  const entryRows = $derived(groups.entry ?? [])
  const holdingRows = $derived(groups.holding ?? [])
  const endedRows = $derived(groups.ended ?? [])

  // ---- columns ----
  const tickerCol: Column<wb.PlanTableRow> = { key: 'ticker', header: '标的', cell: tickerCell, cardLabel: '标的' }
  const chainCol: Column<wb.PlanTableRow> = { key: 'chain', header: '链与版本', cell: chainBlock }
  const actionCol: Column<wb.PlanTableRow> = { key: 'action', header: '动作', cell: actionCell, hideInCards: true }
  const rangeCol: Column<wb.PlanTableRow> = { key: 'range', header: '入场类型与区间', cell: rangeCell, hideInCards: true }
  const holdCol = (group: 'entry' | 'holding'): Column<wb.PlanTableRow>[] => [
    { key: 'stop', header: '止损', align: 'num', cell: group === 'holding' ? holdStopCell : stopCell, hideInCards: true },
    { key: 'target1', header: 'T1', align: 'num', cell: group === 'holding' ? holdT1Cell : t1Cell, hideInCards: true },
  ]
  const sharesCol: Column<wb.PlanTableRow> = { key: 'shares', header: '建议股数', align: 'num', cell: sharesCell, hideInCards: true }
  const validCol: Column<wb.PlanTableRow> = { key: 'valid', header: '有效期', cell: validCell }
  const levelsCol: Column<wb.PlanTableRow> = { key: 'levels', header: '价位', cell: levelsCell }   // cards only: one standard line
  const caseCols: Column<wb.PlanTableRow>[] = CASES.map(kase => ({
    key: `open_${kase}`, header: `开盘：${wb.OPEN_CASE_TEXT[kase]}`, cardLabel: `开盘·${wb.OPEN_CASE_TEXT[kase]}`,
    cell: ({ in_zone: scenarioInZone, gap_up: scenarioGapUp, gap_down: scenarioGapDown } as Record<wb.OpenCase, Column<wb.PlanTableRow>['cell']>)[kase],
  }))
  const voidCol: Column<wb.PlanTableRow> = { key: 'void', header: '本计划何时作废', cell: voidBlock }
  const statusCol = (group: wb.RowGroup): Column<wb.PlanTableRow> =>
    ({ key: 'status', header: '状态', cell: group === 'entry' ? entryStatus : group === 'holding' ? holdingStatusCell : endedStatus })

  const entryColumns = $derived<Column<wb.PlanTableRow>[]>(narrow.current
    ? [tickerCol, chainCol, levelsCol, validCol, ...caseCols, voidCol, statusCol('entry')]
    : [tickerCol, chainCol, actionCol, rangeCol, ...holdCol('entry'), sharesCol, validCol, ...caseCols, voidCol, statusCol('entry')])
  const holdingColumns = $derived<Column<wb.PlanTableRow>[]>(narrow.current
    ? [tickerCol, chainCol, levelsCol, validCol,
       { key: 'holding', header: '持仓状态', cell: holdingBlock }, { key: 'instruction', header: '指令', cell: instructionBlock },
       voidCol, statusCol('holding')]
    : [tickerCol, chainCol, actionCol, rangeCol, ...holdCol('holding'), sharesCol, validCol,
       { key: 'holding', header: '持仓状态', cell: holdingBlock }, { key: 'instruction', header: '指令', cell: instructionBlock },
       voidCol, statusCol('holding')])
  const endedColumns = $derived<Column<wb.PlanTableRow>[]>(narrow.current
    ? [tickerCol, chainCol, levelsCol, statusCol('ended'), { key: 'ended_at', header: '结束日', cell: endedAtCell }]
    : [tickerCol, chainCol, rangeCol, ...holdCol('entry'), statusCol('ended'), { key: 'ended_at', header: '结束日', cell: endedAtCell }])
</script>

{#snippet na()}<StatusPill domain="block" value="not_computed" />{/snippet}

{#snippet chainBlock(row: wb.PlanTableRow)}
  <span class="block">{row.chain ? row.chain.label : (row.plan ? `规则基线 ${row.plan.plan_version}` : '无计划')}</span>
  {#if row.plan}<span class="block text-xs text-muted-foreground">{wb.KIND_TEXT[row.plan.kind] ?? row.plan.kind} · {row.plan.plan_version}</span>{/if}
  {#if row.plan?.defaults_applied}<span class="block text-xs text-warn">{wb.DEFAULTS_APPLIED_TEXT}</span>{/if}
  {#if !row.chain && wb.activeChainText(row)}<span class="block text-xs text-warn">{wb.activeChainText(row)}</span>{/if}
  {#each row.chain?.retriggers ?? [] as r (r.unit_signal_date)}
    <!-- 版本号只在这一次触发自带 version_no，或链上只有一次触发时写；否则每条都会写成当前最新版 -->
    {@const v = r.version_no ?? (row.chain!.retriggers.length === 1 ? row.chain!.version_no : null)}
    <span class="block text-xs text-warn">{md(r.unit_signal_date)} 再次触发{v != null ? ` → 第 ${v} 版` : ''}</span>
  {/each}
{/snippet}

{#snippet voidBlock(row: wb.PlanTableRow)}
  {#if row.void_when.length}
    <ul class="grid gap-0.5 text-xs">
      {#each row.void_when as w, i (i)}
        <li>{w.text}{w.last_result ? `（最近判定：${resultText(w.last_result)}）` : ''}</li>
      {/each}
    </ul>
  {:else}
    <span class="text-xs text-muted-foreground">无作废条件</span>
  {/if}
{/snippet}

{#snippet statusPill(row: wb.PlanTableRow, group: wb.RowGroup)}
  <StatusPill domain="chain" value={chainKey(row, group)} text={row.status.label} />
{/snippet}

{#snippet statusExtras(row: wb.PlanTableRow)}
  {#each row.status.changes_text ?? [] as t, i (i)}<span class="block text-xs">变化：{t}</span>{/each}
  {#if row.status.diff?.length}
    <span class="block text-xs text-muted-foreground">相对上版：{row.status.diff.map(d => `${tl.CHANGE_FIELD_TEXT[d.field] ?? d.field} ${tl.diffValueText(d.field, d.before)} → ${tl.diffValueText(d.field, d.after)}`).join('；')}</span>
  {/if}
  {#if execText(row) && row.status.execution}
    <span class="block text-xs"><ConceptTerm id={T.basis}><StatusPill domain="execution" value={row.status.execution} text={execText(row)} /></ConceptTerm></span>
  {/if}
  {#if row.notes?.length}
    <span class="inline-block rounded-sm border border-border px-1 text-xs text-muted-foreground" title={row.notes.map(n => n.body).join('\n')}
          aria-label={`备注 ${row.notes.length} 条`}>备注 {row.notes.length}</span>
  {/if}
{/snippet}
{#snippet entryStatus(row: wb.PlanTableRow)}<span class="block">{@render statusPill(row, 'entry')}</span>{@render statusExtras(row)}{/snippet}
{#snippet holdingStatusCell(row: wb.PlanTableRow)}<span class="block">{@render statusPill(row, 'holding')}</span>{@render statusExtras(row)}{/snippet}
{#snippet endedStatus(row: wb.PlanTableRow)}<span class="block">{@render statusPill(row, 'ended')}</span>{@render statusExtras(row)}{/snippet}

{#snippet holdingBlock(row: wb.PlanTableRow)}
  {#if row.holding}
    <span class="block text-xs">{wb.holdingLine(row.holding)}</span>
    {#if row.holding.stale}<span class="block text-xs text-warn">{wb.STALE_HOLDING_TEXT}</span>{/if}
    {@const later = laterReview(row)}
    {#if later}<span data-testid="later-review" class="block text-xs text-muted-foreground">{later}</span>{/if}
  {:else}
    {@render na()}
  {/if}
{/snippet}

{#snippet instructionBlock(row: wb.PlanTableRow)}
  {#if row.holding}
    <StatusPill domain="instruction" value={row.holding.instruction} text={wb.INSTRUCTION_TEXT[row.holding.instruction] ?? row.holding.instruction} />
  {/if}
{/snippet}

{#snippet detail(row: wb.PlanTableRow)}
  <div id={`row-detail-${row.row_id}`}>
    <PlanRowDetail {row} recheck={rechecks[row.row_id]} onRecheck={() => onRecheck(row)}
                   onNote={(body, requestId) => onNote(row, body, requestId)} />
  </div>
{/snippet}

{#snippet tickerCell(row: wb.PlanTableRow)}
  <Button variant="link" size="sm" class="font-medium" aria-expanded={isOpen(row)} aria-controls={`row-detail-${row.row_id}`}
          onclick={() => toggle(row)}>{row.ticker}</Button>
  {#if row.pool === 'extended'}<span class="rounded-sm bg-muted px-1 text-xs">扩展池</span>{/if}
  <a class="block text-xs text-muted-foreground underline" href={`#instrument/${encodeURIComponent(row.ticker)}`}>标的页</a>
{/snippet}

{#snippet actionCell(row: wb.PlanTableRow)}
  {#if row.plan}{ACTION_TEXT[row.plan.action] ?? row.plan.action}{:else}{@render na()}{/if}
{/snippet}
{#snippet rangeCell(row: wb.PlanTableRow)}
  {#if row.plan}{entryTypeText(row.plan) ?? '入场类型未记录'} {row.plan.entry_low}–{row.plan.entry_high}{:else}{@render na()}{/if}
{/snippet}
{#snippet stopCell(row: wb.PlanTableRow)}<MetricValue value={num(row.plan?.stop)} />{/snippet}
{#snippet t1Cell(row: wb.PlanTableRow)}<MetricValue value={num(row.plan?.target1)} />{/snippet}
{#snippet holdStopCell(row: wb.PlanTableRow)}<MetricValue value={num(row.holding?.stop ?? row.plan?.stop)} />{/snippet}
{#snippet holdT1Cell(row: wb.PlanTableRow)}<MetricValue value={num(row.holding?.target1 ?? row.plan?.target1)} />{/snippet}
{#snippet sharesCell(row: wb.PlanTableRow)}
  {#if !row.plan}{@render na()}
  {:else if row.plan.shares != null}<MetricValue value={row.plan.shares} unit="股" digits={0} />
  {:else if row.plan.shares_note}{row.plan.shares_note}
  {:else}{@render na()}{/if}
{/snippet}
{#snippet validCell(row: wb.PlanTableRow)}
  {#if row.plan}{row.plan.valid_from} 至 {row.plan.valid_until}{:else}{@render na()}{/if}
{/snippet}
{#snippet levelsCell(row: wb.PlanTableRow)}
  {#if row.plan}
    {#if entryTypeText(row.plan)}<span class="block">{entryTypeText(row.plan)}</span>{/if}
    <PlanLevels low={num(row.plan.entry_low)} high={num(row.plan.entry_high)} stop={num(row.plan.stop)} target1={num(row.plan.target1)}
                shares={row.plan.shares ?? null} />
    {#if row.plan.shares == null && row.plan.shares_note}<span class="block text-xs text-muted-foreground">{row.plan.shares_note}</span>{/if}
  {:else}{@render na()}{/if}
{/snippet}
{#snippet endedAtCell(row: wb.PlanTableRow)}
  {#if row.ended_at}{row.ended_at}{:else}{@render na()}{/if}
{/snippet}

{#snippet scenarioCellFor(row: wb.PlanTableRow, kase: wb.OpenCase)}
  {@const text = scenarioOf(row, kase)}
  {#if text}{text}{:else}{@render na()}{/if}
{/snippet}
{#snippet scenarioInZone(row: wb.PlanTableRow)}{@render scenarioCellFor(row, 'in_zone')}{/snippet}
{#snippet scenarioGapUp(row: wb.PlanTableRow)}{@render scenarioCellFor(row, 'gap_up')}{/snippet}
{#snippet scenarioGapDown(row: wb.PlanTableRow)}{@render scenarioCellFor(row, 'gap_down')}{/snippet}

<section class="grid gap-6" aria-label="计划分组">
  <Section level={2} title={`入场期（可执行）${entryRows.length}`}>
    {#if entryRows.length === 0}
      <DataBlock state="empty" message="入场期暂无可执行的计划" />
    {:else}
      <DataTable columns={entryColumns} rows={entryRows} rowKey={r => r.row_id} cards="narrow" sticky={false}
                 bind:expanded={() => expandedSet, setExpanded}>
        {#snippet expandable(row)}{@render detail(row)}{/snippet}
      </DataTable>
    {/if}
  </Section>

  <Section level={2} title={`持仓中 ${holdingRows.length}`}>
    {#if holdingRows.length === 0}
      <DataBlock state="empty" message="当前无持仓" />
    {:else}
      <DataTable columns={holdingColumns} rows={holdingRows} rowKey={r => r.row_id} cards="narrow" sticky={false}
                 bind:expanded={() => expandedSet, setExpanded}>
        {#snippet expandable(row)}{@render detail(row)}{/snippet}
      </DataTable>
    {/if}
  </Section>

  <section aria-label="已结束" class="grid gap-3">
    <Collapsible open={endedOpen} onOpenChange={setEndedOpen}>
      <h2 class="text-base font-medium">
        <CollapsibleTrigger>
          {#snippet child({ props })}<Button variant="link" size="sm" class="font-medium" {...props} aria-controls="plan-table-ended">已结束 {endedRows.length}</Button>{/snippet}
        </CollapsibleTrigger>
      </h2>
      <!-- Bits keeps a closed CollapsibleContent in the DOM (hidden); the group is only built while it is open. -->
      {#if endedOpen}
        <CollapsibleContent forceMount id="plan-table-ended" data-testid="ended-group" class="pt-3 text-muted-foreground">
          {#if endedRows.length === 0}
            <DataBlock state="empty" message="最近 5 个交易日内没有结束的计划" />
          {:else}
            <DataTable columns={endedColumns} rows={endedRows} rowKey={r => r.row_id} cards="narrow" sticky={false}
                       muted={() => true} bind:expanded={() => expandedSet, setExpanded}>
              {#snippet expandable(row)}{@render detail(row)}{/snippet}
            </DataTable>
          {/if}
        </CollapsibleContent>
      {/if}
    </Collapsible>
  </section>
</section>
