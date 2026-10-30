<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../api'
  import ConceptTerm from './ConceptTerm.svelte'
  import { ATTACH, derivationStepConcept, ruleConcept } from '../knowledge'
  import { CLAUSE_TEXT, CONSISTENCY_TEXT, SOURCE_TEXT } from '../derivation'
  import type { Derivation, Step, TriggerItem, UnitDerivation } from '../derivation'

  // 二者给一个：planId 展开完整四段推导，unit 只展开触发段；挂载时请求一次。
  let { planId, unit }: { planId?: string; unit?: { ticker: string; signal_date: string } } = $props()

  let loading = $state(true)
  let error = $state('')
  let plan = $state<Derivation | null>(null)
  let triggerOnly = $state<UnitDerivation | null>(null)
  const D = ATTACH.derivation

  onMount(() => { void load() })

  async function load() {
    loading = true
    error = ''
    try {
      if (planId) plan = await api.getPlanDerivation(planId)
      else if (unit) triggerOnly = await api.getUnitDerivation(unit.ticker, unit.signal_date)
    } catch (e) {
      error = String((e as Error)?.message ?? e)
    } finally {
      loading = false
    }
  }

  // 数字照后端字符串原样展示：不做任何 Number() / toFixed。
  const text = (value: unknown): string => value == null ? '—' : String(value)
  const operand = (value: unknown): string =>
    Array.isArray(value) ? (value.join(',') || '无') : value == null ? '无' : String(value)
  const pairs = (entries: Record<string, unknown> | undefined): string =>
    Object.entries(entries ?? {}).map(([k, v]) => `${k}=${operand(v)}`).join(' · ') || '—'

  const consistency = $derived(plan?.consistency ?? triggerOnly?.consistency ?? null)
  const candidates = $derived<TriggerItem[]>(plan?.trigger.candidates ?? triggerOnly?.trigger ?? [])
  const triggerNote = $derived(plan?.trigger.note ?? triggerOnly?.note ?? '')
  const steps = $derived(plan?.steps ?? [])
  const trSteps = $derived(steps.filter(s => s.key.startsWith('tr_')))      // TR1..TR14 明细默认折叠
  const mainSteps = $derived(steps.filter(s => !s.key.startsWith('tr_')))

  const BADGE_CLASS: Record<string, string> = {
    consistent: 'bg-primary/10 text-primary', mismatch: 'bg-red-100 text-red-700', incomplete: 'bg-amber-100 text-amber-800',
  }
  const clauseClass = (result: string): string =>
    result === 'violated' ? 'text-red-600' : result === 'not_frozen' ? 'text-amber-700' : 'text-muted-foreground'
  const sourceLabel = (step: Step): string => {
    const refs = step.refs?.length ? ` ${step.refs.join('、')}` : ''
    return `${SOURCE_TEXT[step.source] ?? step.source}${refs}`
  }
</script>

{#snippet stepTable(label: string, rows: Step[])}
  <div class="overflow-x-auto">
    <table aria-label={label} class="w-full text-xs text-left whitespace-nowrap">
      <thead><tr class="text-muted-foreground">
        <th class="pr-2 py-1">项目</th><th class="pr-2 py-1">公式</th><th class="pr-2 py-1">代入</th>
        <th class="pr-2 py-1">结果</th><th class="pr-2 py-1">已存</th><th class="pr-2 py-1">一致</th>
      </tr></thead>
      <tbody>
        {#each rows as step (step.key)}
          <tr class="border-t border-border">
            <td class="pr-2 py-1">{step.label}（{sourceLabel(step)}）{#if derivationStepConcept(step.key)} <ConceptTerm id={derivationStepConcept(step.key)!} />{/if}</td>
            <td class="pr-2 py-1">{step.formula}</td>
            <td class="pr-2 py-1 whitespace-normal">{pairs(step.substitutions)}</td>
            <td class="pr-2 py-1">{text(step.result)}</td>
            <td class="pr-2 py-1">{text(step.stored)}</td>
            <td class="pr-2 py-1 {step.consistent === false ? 'text-red-600' : 'text-muted-foreground'}">
              {step.consistent == null ? '—' : step.consistent ? '一致' : '不一致'}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/snippet}

<section class="text-sm border-l-2 border-border pl-2 space-y-2" aria-label="计划推导">
  {#if error}
    <p role="alert" class="text-xs text-red-600">{error}</p>
  {:else if loading}
    <p class="text-xs text-muted-foreground">推导加载中…</p>
  {:else}
    {#if consistency}
      <p class="flex flex-wrap items-center gap-2">
        <span class="text-xs px-1.5 py-0.5 rounded-sm {BADGE_CLASS[consistency.status]}">{CONSISTENCY_TEXT[consistency.status]}</span>
        <span class="text-xs"><ConceptTerm id={D.consistency}>推导核对</ConceptTerm></span>
        <span class="text-xs text-muted-foreground">{plan?.derivation_version ?? triggerOnly?.derivation_version}</span>
      </p>
      {#each consistency.mismatches as m (m.key)}
        <p class="text-xs text-red-600">差异 {m.key}：推导 {text(m.result)} ≠ 已存 {text(m.stored)}</p>
      {/each}
      {#each consistency.missing as item (item)}
        <p class="text-xs text-amber-700">缺失 {item}</p>
      {/each}
    {/if}
    <p class="text-xs text-muted-foreground">{plan?.evidence ?? triggerOnly?.evidence} <ConceptTerm id={D.evidence} /></p>

    <details open class="space-y-1">
      <summary class="cursor-pointer font-medium text-xs">触发</summary>
      {#if triggerNote}<p class="text-xs text-muted-foreground">{triggerNote}</p>{/if}
      {#each candidates as c (c.candidate_id)}
        <div class="space-y-0.5">
          <p class="text-xs"><ConceptTerm id={ruleConcept(c.rule_id)}>{c.rule_id}</ConceptTerm> · v{c.rule_version} · {c.action}{c.note ? ` · ${c.note}` : ''}</p>
          <div class="overflow-x-auto">
            <table aria-label="触发条件 {c.rule_id}" class="w-full text-xs text-left whitespace-nowrap">
              <thead><tr class="text-muted-foreground">
                <th class="pr-2 py-1">条件句</th><th class="pr-2 py-1">冻结取值</th><th class="pr-2 py-1">结果</th>
              </tr></thead>
              <tbody>
                {#each c.clauses as clause, i (i)}
                  <tr class="border-t border-border">
                    <td class="pr-2 py-1">{clause.text}</td>
                    <td class="pr-2 py-1 whitespace-normal">{pairs(clause.operands)}</td>
                    <td class="pr-2 py-1 {clauseClass(clause.result)}">{CLAUSE_TEXT[clause.result]}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </div>
      {:else}
        <p class="text-xs text-muted-foreground">无候选</p>
      {/each}
    </details>

    {#if plan}
      <details open class="space-y-1">
        <summary class="cursor-pointer font-medium text-xs">输入快照</summary>
        <p class="text-xs"><ConceptTerm id={D.refPrice}>参考价</ConceptTerm> {text(plan.inputs.ref_price?.value)}（bar {text(plan.inputs.ref_price?.source_bar_id)}）</p>
        <p class="text-xs"><ConceptTerm id={D.earnings}>财报</ConceptTerm> {plan.inputs.earnings ? `${plan.inputs.earnings.status ?? '—'} · ${text(plan.inputs.earnings.earnings_date)} · 取于 ${text(plan.inputs.earnings.fetched_at)}` : text(plan.inputs.earnings_note)}</p>
        <p class="text-xs"><ConceptTerm id={D.snapshot}>资金快照</ConceptTerm> {plan.inputs.snapshot ? `${text(plan.inputs.snapshot.as_of)} · equity {text(plan.inputs.snapshot.equity)}` : text(plan.inputs.snapshot_note)}</p>
        {#if plan.inputs.exposure}
          <p class="text-xs"><ConceptTerm id={D.exposure}>敞口</ConceptTerm> 该票 {text(plan.inputs.exposure.ticker_value)} / 总持仓 {text(plan.inputs.exposure.total_value)}（{plan.inputs.exposure.note}）</p>
        {/if}
        {#if plan.inputs.sizing_params}
          <p class="text-xs"><ConceptTerm id={D.sizingParams}>仓位参数</ConceptTerm> risk_pct {text(plan.inputs.sizing_params.risk_pct)} · single_cap {text(plan.inputs.sizing_params.single_cap)} · total_cap {text(plan.inputs.sizing_params.total_cap)}（{plan.inputs.sizing_params.note}）</p>
        {/if}
        {#if plan.inputs.regime}
          <p class="text-xs"><ConceptTerm id={D.regime}>区制</ConceptTerm> {text(plan.inputs.regime.label)}（{text(plan.inputs.regime.calc_version)}）</p>
        {/if}
        {#if plan.inputs.sector}
          <p class="text-xs"><ConceptTerm id={D.sector}>行业</ConceptTerm> {text(plan.inputs.sector.etf)} rs20 {text(plan.inputs.sector.rs20)} · rs60 {text(plan.inputs.sector.rs60)} · {text(plan.inputs.sector.state)}</p>
        {/if}
        {#if plan.inputs.next_earnings}<p class="text-xs">下次财报 {plan.inputs.next_earnings}</p>{/if}
        {#if plan.inputs.pool_tier}<p class="text-xs">池 {plan.inputs.pool_tier}</p>{/if}
        {#if plan.inputs.source}<p class="text-xs">来源 {plan.inputs.source}</p>{/if}
        {#if plan.inputs.screen}
          <p class="text-xs">筛选 run {text(plan.inputs.screen.screen_run_id)} · {text(plan.inputs.screen.screen_group)} · RS {text(plan.inputs.screen.rs)} · 排名 {text(plan.inputs.screen.rank)}</p>
        {/if}
        {#if plan.inputs.agent_run}
          <p class="text-xs">Agent {text(plan.inputs.agent_run.model)} · {text(plan.inputs.agent_run.agent_version)}</p>
        {/if}
        {#if plan.inputs.bars}
          <details class="space-y-1">
            <summary class="cursor-pointer text-xs">日线（{plan.inputs.bars.length} 根，{plan.inputs.bars_note}）</summary>
            <p class="text-xs"><ConceptTerm id={D.bars} /></p>
            <div class="overflow-x-auto">
              <table aria-label="输入日线" class="w-full text-xs text-left whitespace-nowrap">
                <thead><tr class="text-muted-foreground">
                  <th class="pr-2 py-1">日期</th><th class="pr-2 py-1">开</th><th class="pr-2 py-1">高</th>
                  <th class="pr-2 py-1">低</th><th class="pr-2 py-1">收</th><th class="pr-2 py-1">修订号</th>
                </tr></thead>
                <tbody>
                  {#each plan.inputs.bars as bar (bar.id)}
                    <tr class="border-t border-border">
                      <td class="pr-2 py-1">{bar.price_date}</td>
                      <td class="pr-2 py-1">{text(bar.open)}</td>
                      <td class="pr-2 py-1">{text(bar.high)}</td>
                      <td class="pr-2 py-1">{text(bar.low)}</td>
                      <td class="pr-2 py-1">{text(bar.close)}</td>
                      <td class="pr-2 py-1">{text(bar.revision)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </details>
        {/if}
      </details>

      <details open class="space-y-1">
        <summary class="cursor-pointer font-medium text-xs">逐项计算</summary>
        {#if trSteps.length}
          <details class="space-y-1">
            <summary class="cursor-pointer text-xs">TR 明细（{trSteps.length} 步）</summary>
            {@render stepTable('TR 明细', trSteps)}
          </details>
        {/if}
        {#if mainSteps.length}
          {@render stepTable('逐项计算', mainSteps)}
        {:else}
          <p class="text-xs text-muted-foreground">无可推导项</p>
        {/if}
      </details>

      <details open class="space-y-1">
        <summary class="cursor-pointer font-medium text-xs">校验</summary>
        {#each plan.checks as check (check.key)}
          <p class="text-xs">{check.label}：{check.formula}（{pairs(check.substitutions)}）
            <span class={check.holds ? 'text-muted-foreground' : 'text-red-600'}>{check.holds ? '成立' : '不成立'}</span></p>
        {:else}
          <p class="text-xs text-muted-foreground">无校验项</p>
        {/each}
      </details>

      {#if plan.run}
        <p class="text-xs text-muted-foreground"><span class="font-medium"><ConceptTerm id={D.run}>运行证据：</ConceptTerm></span>
          {#if !plan.run.ready}
            <span>{text(plan.run.note)}</span>
          {:else if plan.run.run_id}
            <span>{plan.run.run_id} · 阶段 {text(plan.run.stage)} · {text(plan.run.status)}{#if plan.run.derivation} · 推导核对 {plan.run.derivation.checked} 份：consistent {plan.run.derivation.consistent} · mismatch {plan.run.derivation.mismatch} · incomplete {plan.run.derivation.incomplete}{/if}</span>
          {:else}
            <span>{text(plan.run.note)}</span>
          {/if}
        </p>
      {/if}
    {/if}
  {/if}
</section>
