<script lang="ts">
  import * as api from '../api'
  import StatusPill from './StatusPill.svelte'
  import { fmtBeijing } from '../format'
  import {
    fetchButtonLabel, fetchTarget, kindLabel, noteText, triggerLabel,
    type FamilyCard,
  } from '../data-families'

  let { card, onfetched }: { card: FamilyCard; onfetched: () => void } = $props()

  let busy = $state(false)
  let error = $state('')
  let note = $state('')

  // 全族拉取：提交后走现有 run 轮询；15 分钟上限，超时不算失败（后台仍在跑）。
  async function fetchAll() {
    if (busy) return
    busy = true
    error = ''
    note = ''
    try {
      const pending = await api.fetchDataFamily(fetchTarget(card), undefined)
      const run = await api.pollRun(pending.run_id, { timeoutMs: 900_000 })
      if ((run.result as { status?: string } | undefined)?.status === 'busy') {
        error = '该族正在采集'   // 探测后、持锁前被批处理抢到
      } else if (run.status === 'error') {
        error = run.error ?? '运行失败'
      }
      await onfetched()
    } catch (e) {
      const message = String((e as Error)?.message ?? e)
      if (message === 'run timeout') note = '仍在后台运行，稍后刷新'
      else error = message
    } finally {
      busy = false
    }
  }

  // 最新时点是纯日期（日线 / 申报 / FRED）时直接显示，不当成午夜时间戳
  const latestText = (value: string | null): string =>
    value == null ? '—' : value.length === 10 ? value : fmtBeijing(value)
</script>

<article aria-label={card.title} class="border border-border rounded p-3 space-y-2 bg-surface text-sm">
  <div class="flex flex-wrap items-center gap-2">
    <h2 class="font-semibold"><a class="hover:underline" href="#data/{card.id}">{card.title}</a></h2>
    <span class="text-xs px-1.5 py-0.5 rounded bg-accent/10 text-accent">{kindLabel(card.kind)}</span>
  </div>
  <p class="text-xs text-muted">{card.purpose}</p>
  <p>覆盖
    <span class="{card.coverage.lagging.length ? 'text-warn font-medium' : ''}">
      {card.coverage.covered} / {card.coverage.targets}</span>
    {#if card.coverage.lagging.length}
      <span class="text-xs text-warn">（滞后 {card.coverage.lagging.length}）</span>
    {/if}
    · 最新 {latestText(card.latest_at)}
  </p>
  {#if card.last_run}
    {@const run = card.last_run}
    <p class="flex flex-wrap items-center gap-1.5">
      最近拉取 <StatusPill status={run.status} />
      · <span>{triggerLabel(run.trigger)}</span> · <span>{fmtBeijing(run.finished_at)}</span>
      · <span>{run.ok_count}/{run.target_count}</span>
    </p>
    {#if run.failures.length}
      <ul class="text-xs text-red-600 space-y-0.5">
        {#each run.failures as f (f.target + f.reason)}
          <li>{f.target}：{f.reason}</li>
        {/each}
      </ul>
    {/if}
  {:else}
    <p class="text-xs text-muted">最近拉取 无记录</p>
  {/if}
  {#if card.notes.length}
    <ul class="text-xs text-amber-700 space-y-0.5">
      {#each card.notes as n (n)}<li>{noteText(n)}</li>{/each}
    </ul>
  {/if}
  <p class="text-xs text-muted">{card.evidence}</p>
  {#if card.job}
    {@const job = card.job}
    <p class="text-xs text-muted">所属任务
      <a class="underline" href="#tools/tasks">
        {job.name} · {job.enabled ? '开' : '关'} · 下次 {job.next_run_at ? fmtBeijing(job.next_run_at) : '—'}
      </a>
    </p>
  {:else}
    <p class="text-xs text-muted">所属任务 无</p>
  {/if}
  <div class="flex flex-wrap items-center gap-2">
    <button class="text-xs px-2 py-1 rounded bg-accent text-white disabled:opacity-50"
            disabled={busy} onclick={fetchAll}>
      {busy ? '采集中…' : fetchButtonLabel(card)}
    </button>
    {#if error}<span class="text-xs text-red-600">{error}</span>{/if}
    {#if note}<span class="text-xs text-muted">{note}</span>{/if}
  </div>
</article>
