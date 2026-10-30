<script lang="ts">
  import { onMount } from 'svelte'
  import AgentPlanCard from './AgentPlanCard.svelte'
  import DiscussButton from './DiscussButton.svelte'
  import Drawer from './Drawer.svelte'
  import PlanDerivation from './PlanDerivation.svelte'
  import PlanNotes from './PlanNotes.svelte'
  import UserInputs from './UserInputs.svelte'
  import * as api from '../api'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // 「今日」计划表的行展开（spec §10.1）：AgentPlanCard（没有决定表单）、规则基线一行、「我的补充」、备注输入、
  // 「重新复查」、「就此讨论」；版本号链接到计划页。布局开关只影响这里的顺序，键 workbench.today.layout 沿用。
  let { row, recheck, onRecheck, onNote }: {
    row: wb.PlanTableRow; recheck?: { busy: boolean; text: string }
    onRecheck: () => void; onNote: (body: string, requestId: string) => Promise<void>
  } = $props()

  type Layout = 'agent_first' | 'legacy'
  const LAYOUT_KEY = 'workbench.today.layout'
  // 读写失败（隐私模式、禁用存储）一律按默认「Agent 优先」。
  function readLayout(): Layout {
    try { return globalThis.localStorage?.getItem(LAYOUT_KEY) === 'legacy' ? 'legacy' : 'agent_first' } catch { return 'agent_first' }
  }
  let layout = $state<Layout>(readLayout())
  function setLayout(next: Layout) {
    layout = next
    try { globalThis.localStorage?.setItem(LAYOUT_KEY, next) } catch { /* 存储不可用：只在本页生效 */ }
  }

  let chain = $state<tl.Chain | null>(null)
  let chainError = $state('')
  let derivationOpen = $state(false)
  let callDrawer = $state<{ open: boolean; call: wb.AgentToolCall | null }>({ open: false, call: null })
  let callError = $state('')

  onMount(async () => {
    if (!row.chain) return
    try {
      chain = await api.getChain(row.ticker, row.chain.signal_date)
    } catch (e) {
      chainError = wb.describeError(e)
    }
  })

  const head = $derived(chain?.versions?.find(v => v.plan_id === chain!.head_plan_id) ?? chain?.versions?.[chain.versions.length - 1] ?? null)
  const agent = $derived(chain && head ? tl.versionAgentView(chain, head) : null)
  const reviewable = $derived(!!row.chain && tl.REVIEWABLE_STATES.includes(row.chain.state as tl.ChainState))
  const exiting = $derived(row.chain?.state === 'exiting')
  const discussPlanId = $derived(row.chain?.head_plan_id ?? row.plan?.plan_id ?? row.baseline?.plan_id ?? null)
  const b = $derived(row.baseline)

  async function showCall(ref: string) {
    if (!head) return
    callError = ''
    try {
      const detail = await wb.getAgentRun(head.run.id)
      const seq = Number(ref.split(':')[1])
      callDrawer = { open: true, call: detail.tool_calls.find(c => c.seq === seq) ?? null }
    } catch (e) {
      callError = wb.describeError(e)
    }
  }
</script>

<div data-testid="row-detail" class="space-y-3 text-sm">
  <div role="group" aria-label="布局" class="flex items-center gap-1 text-xs">
    <span class="text-muted">布局：</span>
    {#each [['agent_first', 'Agent 优先'], ['legacy', '规则优先（旧）']] as [value, label]}
      <button type="button" class="px-2 py-1 border border-border rounded {layout === value ? 'bg-accent/10 text-accent' : 'hover:bg-surface-2'}"
              aria-pressed={layout === value} onclick={() => setLayout(value as Layout)}>{label}</button>
    {/each}
  </div>

  {#snippet agentBlock()}
    {#if row.chain}
      {#if chainError}
        <p class="text-xs text-red-600">Agent 计划加载失败：{chainError}</p>
      {:else if agent}
        <AgentPlanCard {agent} onCall={showCall} />
        {#if callError}<p class="text-xs text-red-600">{callError}</p>{/if}
      {:else}
        <p class="text-xs text-muted">加载中…</p>
      {/if}
    {:else}
      <p class="text-xs text-muted">这一行没有 Agent 计划链。</p>
    {/if}
  {/snippet}
  {#snippet baselineBlock()}
    {#if b}
      <div data-testid="rule-baseline" class="border-l-2 border-accent/40 pl-2 space-y-1">
        <p>规则基线 {b.plan_version}：入场 {b.entry_low}–{b.entry_high} · 止损 {b.stop} · T1 {b.target1}{b.shares != null ? ` · 建议 ${b.shares} 股` : ''}（{b.status === 'invalid' ? '已作废' : '有效'}）
          <a class="text-xs text-accent underline" href={`#plan/${b.plan_id}`}>查看</a>
          <button type="button" class="text-xs text-accent underline" aria-expanded={derivationOpen}
                  onclick={() => derivationOpen = !derivationOpen}>展开推导</button></p>
        {#if wb.activeChainText(row)}<p class="text-xs text-amber-700">{wb.activeChainText(row)}</p>{/if}
        {#if derivationOpen}<PlanDerivation planId={b.plan_id} />{/if}
      </div>
    {/if}
  {/snippet}
  {#if layout === 'legacy'}
    {@render baselineBlock()}
    {@render agentBlock()}
  {:else}
    {@render agentBlock()}
    {@render baselineBlock()}
  {/if}

  <div class="flex flex-wrap items-center gap-3">
    {#if row.chain}
      <a class="text-xs text-accent underline" href={`#plan/${row.chain.head_plan_id}`}>第 {row.chain.version_no} 版计划页</a>
    {:else if row.plan}
      <a class="text-xs text-accent underline" href={`#plan/${row.plan.plan_id}`}>{row.plan.plan_version} 计划页</a>
    {/if}
    {#if row.chain}
      <button type="button" class="text-xs px-2 py-1 border border-border rounded hover:bg-surface-2 disabled:opacity-50"
              disabled={!reviewable || recheck?.busy}
              title={exiting ? wb.CHAIN_EXITING_TEXT : reviewable ? '' : '只有入场期或持仓期的链可以重新复查'}
              onclick={onRecheck}>重新复查</button>
      {#if recheck?.text}<span class="text-xs">{recheck.text}</span>{/if}
    {/if}
    <!-- 有链时「就此计划讨论」在 Agent 计划卡里；这里只补没有链的行（规则基线 / 自定） -->
    {#if !row.chain && discussPlanId}<DiscussButton context={{ kind: 'plan', plan_id: discussPlanId }} />{/if}
  </div>

  {#if row.chain}
    <UserInputs ticker={row.ticker} signalDate={row.chain.signal_date} />
  {:else}
    <UserInputs ticker={row.ticker} />
  {/if}
  <PlanNotes notes={row.notes ?? []} {onNote} />

  <Drawer open={callDrawer.open} onclose={() => callDrawer = { open: false, call: null }}>
    {#if callDrawer.call}
      {@const c = callDrawer.call}
      <h2 class="font-semibold">工具调用 call:{c.seq}</h2>
      <p class="text-xs text-muted">工具 {c.tool} · 阶段 {c.phase === 'propose' ? '建议' : '反方'} · {wb.dateTime(c.called_at)}</p>
      <p class="text-xs break-all">参数 {JSON.stringify(c.args)}</p>
      <p class="text-xs break-all">哈希 {c.result_sha256.slice(0, 8)}</p>
      <pre class="text-xs mt-2 whitespace-pre-wrap break-all">{JSON.stringify(c.result, null, 2)}</pre>
    {:else}
      <p class="text-sm text-muted">未找到该编号的工具调用</p>
    {/if}
  </Drawer>
</div>
