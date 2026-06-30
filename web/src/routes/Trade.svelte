<script lang="ts">
  import { onMount } from 'svelte'
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Placeholder from './Placeholder.svelte'

  let { sub }: { sub?: string } = $props()
  type Tab = 'macro' | 'decision' | 'orders' | 'overview'
  const validTabs: Tab[] = ['macro', 'decision', 'orders', 'overview']
  // Default to 'macro'; legacy 'overview' maps to 'macro'
  let tab = $derived<Tab>(
    sub === 'decision' ? 'decision'
    : sub === 'orders' ? 'orders'
    : 'macro'
  )
  let hermes = $state<any>(null)
  let macro = $state<any>(null)
  let macroRunning = $state(false)
  let decisionRunning = $state(false)
  let decisionResult = $state<any>(null)
  let loading = $state(true)

  async function load() {
    loading = true
    try {
      ;[hermes, macro] = await Promise.all([api.getHermes(), api.getMacroAnalysis()])
    } finally { loading = false }
  }

  async function runMacro() {
    macroRunning = true
    try {
      const p = await api.runMacroLlm({ window: 30 })
      const rec = await api.pollRun(p.run_id)
      if (rec.status === 'done') macro = (rec.result as any)?.analysis ?? macro
    } finally { macroRunning = false }
  }

  async function runDecision() {
    decisionRunning = true
    try {
      const p = await api.runDecisionEvidence({ use_llm: true })
      const rec = await api.pollRun(p.run_id)
      if (rec.status === 'done') decisionResult = (rec.result as any)?.decision_evidence ?? null
    } finally { decisionRunning = false }
  }

  onMount(load)
</script>

<div>
  <div class="flex items-center gap-4 mb-4">
    <h2 class="text-lg font-semibold">交易</h2>
    <div class="flex gap-1">
      {#each (['macro', 'decision', 'orders'] as const) as k}
        <a
          href="#trade/{k}"
          class="px-3 py-1 text-sm rounded {tab === k ? 'bg-accent text-white' : 'bg-surface-2 text-muted hover:bg-surface'}"
        >{{ macro:'宏观分析', decision:'决策证据', orders:'交易指令' }[k]}</a>
      {/each}
    </div>
  </div>

  {#if loading}
    <Skeleton rows={3} />
  {:else if tab === 'orders'}
    <Placeholder
      title="交易指令"
      note="基于策略结果由大模型（DeepSeek 等）生成交易指令。"
      planned="计划于子项目 C 实现"
    />
  {:else if tab === 'decision'}
    <div class="flex justify-end mb-3">
      <button onclick={runDecision} disabled={decisionRunning} class="px-3 py-1 bg-accent text-white rounded text-sm disabled:opacity-50">
        {decisionRunning ? '生成中…' : '生成决策证据'}
      </button>
    </div>
    {#if decisionResult}
      <div class="bg-surface rounded-lg p-4 shadow-elev-1">
        <p class="text-sm mb-2">{(decisionResult as any).summary ?? '—'}</p>
        <ul class="list-disc pl-4 text-sm text-muted">
          {#each ((decisionResult as any).next_actions ?? []) as action}
            <li>{action}</li>
          {/each}
        </ul>
      </div>
    {/if}
  {:else}
    <div class="flex justify-end mb-3">
      <button onclick={runMacro} disabled={macroRunning} class="px-3 py-1 bg-accent text-white rounded text-sm disabled:opacity-50">
        {macroRunning ? '分析中…' : '运行 LLM 宏观分析'}
      </button>
    </div>
    {#if macro}
      <div class="bg-surface rounded-lg p-4 shadow-elev-1">
        <div class="font-semibold mb-2">{(macro as any).stance_label ?? '—'}</div>
        <p class="text-sm text-muted">{(macro as any).summary ?? '—'}</p>
      </div>
    {/if}
  {/if}
</div>
