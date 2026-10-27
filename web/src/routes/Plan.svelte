<script lang="ts">
  import PlanDerivation from '../lib/components/PlanDerivation.svelte'
  import * as api from '../lib/api'
  import type { Derivation } from '../lib/derivation'

  // 整页渲染 PlanDerivation（spec 2026-10-27 §10）。标题取推导里的标的与日期，
  // 所以页面自己再请求一次；取不到（404/400/503）时退化为 id，错误文案交给组件呈现，不白屏。
  let { sub }: { sub: string } = $props()
  let title = $state('')

  $effect(() => {
    const id = sub
    let alive = true
    void api.getPlanDerivation(id)
      .then((d: Derivation) => { if (alive) title = `${d.plan.ticker ?? '—'} · ${d.plan.signal_date ?? '—'}` })
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
    <PlanDerivation planId={sub} />
  {/key}
</section>
