<script lang="ts">
  import { NODE_STATUS_TEXT, failedTargetsFirst } from '../runs'
  import type { FetchFamily, FetchTarget } from '../runs'
  import { fmtBeijing } from '../format'

  // 拉取详情（spec §7.3 ②）：按族分组；目标表默认只展开失败目标，「显示全部 n 个目标」展开全部。
  // 所有文本（含失败原因、error_kind）一律按原文纯文本显示。
  let { families }: { families: FetchFamily[] } = $props()

  const LEGACY_NOTE = '这次运行早于目标级明细（v2.8），只记录了失败的目标'
  let showAll = $state<Record<string, boolean>>({})

  const statusText = (status: string) => NODE_STATUS_TEXT[status] ?? status
  const tone = (status: string) =>
    status === 'success' ? 'text-success' : status === 'failed' ? 'text-danger'
      : status === 'partial' || status === 'degraded' ? 'text-warn' : 'text-muted'

  /** Rows of a family: its targets, or (rows older than v2.8) one failed row per recorded failure. */
  function targetsOf(family: FetchFamily): FetchTarget[] {
    if (family.targets && !family.legacy) return family.targets
    return (family.failures ?? []).map(f => ({
      target: f.target, ok: false, attempts: null, error_kind: null, http_status: null, reason: f.reason,
      rows: null, latest: null, elapsed_ms: null,
    }))
  }
  const shown = (family: FetchFamily): FetchTarget[] => {
    const all = failedTargetsFirst(targetsOf(family))
    return showAll[family.family] || family.legacy ? all : all.filter(t => !t.ok)
  }
  const cell = (value: unknown) => value === null || value === undefined || value === '' ? '—' : String(value)
  const resultText = (t: FetchTarget) => t.ok ? '成功'
    : `失败${t.error_kind ? `（${t.error_kind}）` : ''}${t.http_status != null ? ` HTTP ${t.http_status}` : ''}`
</script>

<div class="space-y-3">
  {#each families as family (family.family)}
    {@const total = targetsOf(family).length}
    <section aria-label={`拉取 ${family.title}`} class="space-y-1">
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h4 class="font-medium">{family.title}</h4>
        <span class="text-xs font-medium {tone(family.status)}">{statusText(family.status)}</span>
        <span class="text-xs text-muted">{family.ok_count} / {family.target_count}</span>
        {#if family.started_at || family.finished_at}
          <span class="text-xs text-muted">{fmtBeijing(family.started_at)} 至 {fmtBeijing(family.finished_at)}</span>
        {/if}
        {#if family.scope}<span class="text-xs text-muted">范围：{family.scope}</span>{/if}
      </div>
      {#if family.legacy}<p class="text-xs text-muted">{LEGACY_NOTE}</p>{/if}
      {#if shown(family).length}
        <div class="overflow-x-auto">
          <table class="w-full text-xs">
            <thead>
              <tr class="text-left text-muted">
                <th class="pr-3 font-normal">目标</th><th class="pr-3 font-normal">结果</th>
                <th class="pr-3 font-normal">尝试次数</th><th class="pr-3 font-normal">失败原因</th>
                <th class="pr-3 font-normal">行数</th><th class="font-normal">最新时点</th>
              </tr>
            </thead>
            <tbody>
              {#each shown(family) as t (t.target)}
                <tr class="border-t border-border align-top">
                  <td class="py-1 pr-3 font-mono">{t.target}</td>
                  <td class="pr-3 {t.ok ? 'text-success' : 'text-danger'}">{resultText(t)}</td>
                  <td class="pr-3">{cell(t.attempts)}</td>
                  <td class="pr-3 break-all">{cell(t.reason)}</td>
                  <td class="pr-3">{cell(t.rows)}</td>
                  <td>{cell(t.latest)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else if !family.legacy && total > 0}
        <p class="text-xs text-muted">没有失败的目标</p>
      {/if}
      {#if !family.legacy && total > 0 && total > shown(family).length}
        <button type="button" class="text-xs text-accent underline"
                onclick={() => showAll[family.family] = true}>显示全部 {total} 个目标</button>
      {:else if !family.legacy && showAll[family.family] && total > 0}
        <button type="button" class="text-xs text-accent underline"
                onclick={() => showAll[family.family] = false}>只看失败目标</button>
      {/if}
    </section>
  {/each}
</div>
