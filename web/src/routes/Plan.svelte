<script lang="ts">
  import PlanDerivation from '../lib/components/PlanDerivation.svelte'
  import PlanTimeline from '../lib/components/PlanTimeline.svelte'
  import UserInputs from '../lib/components/UserInputs.svelte'
  import * as api from '../lib/api'
  import type { Derivation } from '../lib/derivation'

  // 整页渲染 PlanDerivation（spec 2026-10-27 §10）。标题取推导里的标的与日期，
  // 所以页面自己再请求一次；取不到（404/400/503）时退化为 id，错误文案交给组件呈现，不白屏。
  // agent-2 计划另显示版本链、复查记录与「我的补充」（v2.5 spec §11）；其余计划页面不变。
  let { sub }: { sub: string } = $props()
  let title = $state('')
  let unit = $state<{ ticker: string; signal_date: string } | null>(null)

  $effect(() => {
    const id = sub
    let alive = true
    unit = null
    void api.getPlanDerivation(id)
      .then((d: Derivation) => {
        if (!alive) return
        title = `${d.plan.ticker ?? '—'} · ${d.plan.signal_date ?? '—'}`
        unit = d.plan.plan_version === 'agent-2' && d.plan.ticker && d.plan.signal_date
          ? { ticker: d.plan.ticker, signal_date: d.plan.signal_date } : null
      })
      .catch(() => { if (alive) title = id })
    return () => { alive = false }
  })

  // 有历史就后退；没有历史（直链打开）时不拦截，沿 href 落到「今日」。
  function goBack(e: MouseEvent) {
    if (history.length > 1) { e.preventDefault(); history.back() }
  }
</script>

<section class="space-y-4">
  <header class="flex items-center gap-3">
    <a href="#today" onclick={goBack} class="text-sm text-accent underline">返回</a>
    <h1 class="text-lg font-semibold">{title || '加载中…'}</h1>
  </header>
  {#key sub}
    {#if unit}
      <PlanTimeline ticker={unit.ticker} signalDate={unit.signal_date} currentPlanId={sub} />
    {/if}
    <PlanDerivation planId={sub} />
    {#if unit}
      <UserInputs ticker={unit.ticker} signalDate={unit.signal_date} />
    {/if}
  {/key}
</section>
