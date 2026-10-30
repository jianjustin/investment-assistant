<script lang="ts">
  import { onMount } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import PlanLevels from '$lib/ui/domain/PlanLevels.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import * as Sheet from '$lib/ui/sheet/index'
  import AgentPlanCard from './AgentPlanCard.svelte'
  import DiscussButton from './DiscussButton.svelte'
  import PlanDerivation from './PlanDerivation.svelte'
  import PlanNotes from './PlanNotes.svelte'
  import UserInputs from './UserInputs.svelte'
  import * as api from '../api'
  import * as tl from '../timeline'
  import * as wb from '../workbench'

  // 「今日」计划表的行展开（spec §10.1）：AgentPlanCard（没有决定表单）、规则基线一行、「我的补充」、备注输入、
  // 「重新复查」、「就此讨论」；版本号链接到计划页。布局开关只影响这里的顺序，键 workbench.today.layout 沿用。
  let { row, recheck, onRecheck, onNote }: {
    row: wb.PlanTableRow; recheck?: { busy: boolean; text: string; since?: number }
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
  let callOpen = $state(false)
  let callDrawer = $state<{ seq: number | null; call: wb.AgentToolCall | null }>({ seq: null, call: null })
  let callError = $state('')

  // How long the recheck has been running (the page hands in when it started); ticks only while it runs.
  let tick = $state(Date.now())
  $effect(() => {
    if (!recheck?.busy || recheck.since == null) return
    tick = Date.now()
    const timer = setInterval(() => { tick = Date.now() }, 1000)
    return () => clearInterval(timer)
  })
  const waited = $derived(recheck?.since == null ? null : Math.max(0, Math.floor((tick - recheck.since) / 1000)))

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
      callDrawer = { seq, call: detail.tool_calls.find(c => c.seq === seq) ?? null }
      callOpen = true
    } catch (e) {
      callError = wb.describeError(e)
    }
  }
</script>

<div data-testid="row-detail" class="grid gap-3 text-sm">
  <div role="group" aria-label="布局" class="flex items-center gap-1 text-xs">
    <span class="text-muted-foreground">布局：</span>
    {#each [['agent_first', 'Agent 优先'], ['legacy', '规则优先（旧）']] as [value, label]}
      <Button size="sm" class={layout === value ? 'border-primary/40 bg-primary/10 text-primary' : ''}
              aria-pressed={layout === value} onclick={() => setLayout(value as Layout)}>{label}</Button>
    {/each}
  </div>

  {#snippet agentBlock()}
    {#if row.chain}
      {#if chainError}
        <Alert variant="danger"><AlertDescription>Agent 计划加载失败：{chainError}</AlertDescription></Alert>
      {:else if agent}
        <AgentPlanCard {agent} onCall={showCall} />
        {#if callError}<Alert variant="danger"><AlertDescription>{callError}</AlertDescription></Alert>{/if}
      {:else}
        <DataBlock state="loading" skeleton="block" />
      {/if}
    {:else}
      <p class="text-xs text-muted-foreground">这一行没有 Agent 计划链。</p>
    {/if}
  {/snippet}
  {#snippet baselineBlock()}
    {#if b}
      <div data-testid="rule-baseline" class="grid gap-1 border-l-2 border-primary/40 pl-2">
        <p class="flex flex-wrap items-center gap-x-2">
          <span>规则基线 {b.plan_version}：<PlanLevels low={Number(b.entry_low)} high={Number(b.entry_high)} stop={Number(b.stop)} target1={Number(b.target1)} shares={b.shares ?? null} />（{b.status === 'invalid' ? '已作废' : '有效'}）</span>
          <a class="text-xs text-primary underline" href={`#plan/${b.plan_id}`}>查看</a>
          <Button variant="link" size="sm" class="text-xs" aria-expanded={derivationOpen}
                  onclick={() => derivationOpen = !derivationOpen}>展开推导</Button></p>
        {#if wb.activeChainText(row)}<p class="text-xs text-warn">{wb.activeChainText(row)}</p>{/if}
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
      <a class="text-xs text-primary underline" href={`#plan/${row.chain.head_plan_id}`}>第 {row.chain.version_no} 版计划页</a>
    {:else if row.plan}
      <a class="text-xs text-primary underline" href={`#plan/${row.plan.plan_id}`}>{row.plan.plan_version} 计划页</a>
    {/if}
    {#if row.chain}
      <Button size="sm" disabled={!reviewable} busy={recheck?.busy}
              title={exiting ? wb.CHAIN_EXITING_TEXT : reviewable ? '' : '只有入场期或持仓期的链可以重新复查'}
              onclick={onRecheck}>重新复查</Button>
      {#if recheck?.busy}
        <StatusPill domain="run" value="running" text={recheck.text} />
        {#if waited != null}<span class="text-xs text-muted-foreground">已等待 {waited} 秒</span>{/if}
      {:else if recheck?.text}
        <span class="text-xs">{recheck.text}</span>
      {/if}
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

  <Sheet.Root bind:open={callOpen}>
    <Sheet.Content side="right" width="sm">
      <Sheet.Header>
        <Sheet.Title>工具调用 call:{callDrawer.seq}</Sheet.Title>
        <Sheet.Description class="sr-only">这次 Agent 运行里的一次工具调用</Sheet.Description>
      </Sheet.Header>
      <div class="grid gap-1 px-4 pb-4">
        {#if callDrawer.call}
          {@const c = callDrawer.call}
          <p class="text-xs text-muted-foreground">工具 {c.tool} · 阶段 {c.phase === 'propose' ? '建议' : '反方'} · {wb.dateTime(c.called_at)}</p>
          <p class="break-all text-xs">参数 {JSON.stringify(c.args)}</p>
          <p class="break-all text-xs">哈希 {c.result_sha256.slice(0, 8)}</p>
          <pre class="mt-2 whitespace-pre-wrap break-all text-xs">{JSON.stringify(c.result, null, 2)}</pre>
        {:else}
          <p class="text-sm text-muted-foreground">未找到该编号的工具调用</p>
        {/if}
      </div>
    </Sheet.Content>
  </Sheet.Root>
</div>
