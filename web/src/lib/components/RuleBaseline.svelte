<script lang="ts">
  import { Button } from '$lib/ui/button/index'
  import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '$lib/ui/collapsible/index'
  import PlanLevels from '$lib/ui/domain/PlanLevels.svelte'
  import ConceptTerm from './ConceptTerm.svelte'
  import PlanDerivation from './PlanDerivation.svelte'
  import { ATTACH } from '../knowledge'
  import * as wb from '../workbench'

  // §10.1 规则基线：折叠时一行，展开后是 v2.4 的规则计划块（含「展开推导」）。
  // collapsible = false 时（旧布局、Agent 没有可用计划）只显示展开后的块，不给收起按钮。
  let { plan, expanded, ontoggle, collapsible = true }:
    { plan: wb.Plan | null; expanded: boolean; ontoggle: () => void; collapsible?: boolean } = $props()

  let derivationOpen = $state(false)
  const R = ATTACH.ruleBaseline

  const regimeText = (label?: string | null) => label ? (wb.REGIME_LABELS[label] ?? label) : '未知'
  const sectorText = (ctx: wb.PlanContext | undefined) => ctx?.sector
    ? `${ctx.sector.etf} ${ctx.sector.state ? (wb.SECTOR_STATE_LABELS[ctx.sector.state] ?? '数据不足') : '数据不足'}`
    : '未映射'
  const num = (v: unknown) => (v == null || v === '' ? null : Number(v))
</script>

{#snippet explain()}
  <p class="flex flex-wrap gap-x-2 text-xs text-muted-foreground">说明：<ConceptTerm id={R.entry}>入场区间</ConceptTerm> <ConceptTerm id={R.stop}>止损</ConceptTerm> <ConceptTerm id={R.target1}>T1</ConceptTerm> <ConceptTerm id={R.sizing}>建议股数</ConceptTerm> <ConceptTerm id={R.status}>有效与作废</ConceptTerm></p>
{/snippet}

{#if plan}
  {@const p = plan}
  {@const open = expanded || !collapsible}
  <Collapsible open={open} onOpenChange={() => ontoggle()} data-testid="rule-baseline" class="grid gap-1 border-l-2 border-primary/40 pl-2 text-sm">
    {#if !open}
      <p class="flex flex-wrap items-center gap-2">
        <span>规则基线 {p.plan_version}：<PlanLevels low={num(p.entry_low)} high={num(p.entry_high)} stop={num(p.stop)} target1={num(p.target1)} shares={p.sizing?.shares ?? null} />（{p.status === 'invalid' ? '已作废' : '有效'}）</span>
        <CollapsibleTrigger>
          {#snippet child({ props })}<Button variant="link" size="sm" {...props}>展开</Button>{/snippet}
        </CollapsibleTrigger>
      </p>
      {@render explain()}
    {:else}
      <p class="flex flex-wrap items-center gap-2 font-medium">计划（{p.kind === 'rule' ? '规则' : '自定'} · {p.plan_version}{p.status === 'invalid' ? ' · 已作废' : ''}）
        {#if collapsible}
          <CollapsibleTrigger>
            {#snippet child({ props })}<Button variant="link" size="sm" class="font-normal" {...props}>收起</Button>{/snippet}
          </CollapsibleTrigger>
        {/if}
      </p>
      <CollapsibleContent forceMount class="grid gap-1">
        <p>入场区间 {p.entry_low}–{p.entry_high} · 止损 {p.stop} · T1 {p.target1} · 有效期至 {p.valid_until}</p>
        {@render explain()}
        <p class="text-xs text-muted-foreground">区制 {regimeText(p.inputs?.context?.regime?.label)} · 下次财报 {p.inputs?.context?.next_earnings ?? '未知'} · 行业 {sectorText(p.inputs?.context)}</p>
        {#if p.sizing?.status === 'no_equity'}
          <p class="text-warn">缺资金快照，无法计算建议股数</p>
        {:else if p.sizing?.shares != null}
          <p>建议 {p.sizing.shares} 股 · 风险 {p.sizing.risk_amount}（资金日 {p.sizing.snapshot_as_of}）</p>
        {/if}
        {#each p.invalid_reasons as r}<p class="text-destructive">作废：{r}</p>{/each}
        {#each p.warnings as w}<p class="text-xs text-muted-foreground">提示：{w}</p>{/each}
        <p class="text-xs text-muted-foreground">证据：未验证</p>
        <div class="grid gap-1">
          <div><Button variant="link" size="sm" class="text-xs" aria-expanded={derivationOpen}
                  onclick={() => derivationOpen = !derivationOpen}>展开推导</Button></div>
          {#if derivationOpen}<PlanDerivation planId={p.id} />{/if}
        </div>
      </CollapsibleContent>
    {/if}
  </Collapsible>
{/if}
