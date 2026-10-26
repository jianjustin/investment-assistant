<script lang="ts">
  import * as api from '../lib/api'
  import { KNOWN_FAMILIES, triggerLabel, type DataOverview, type FamilyDetail } from '../lib/data-families'
  import { fmtBeijing } from '../lib/format'
  import DataFamilyCard from '../lib/components/DataFamilyCard.svelte'
  import DataBrowse from '../lib/components/DataBrowse.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'

  let { sub }: { sub?: string } = $props()

  let overview = $state<DataOverview | null>(null)
  let detail = $state<FamilyDetail | null>(null)
  let error = $state('')
  let loading = $state(true)
  let onlyLagging = $state(false)
  let generation = 0
  let familyId = $derived(sub && (KNOWN_FAMILIES as readonly string[]).includes(sub) ? sub : null)
  let coverageRows = $derived(detail?.rows.filter(row => !onlyLagging || row.lagging) ?? [])
  let targets = $derived(detail?.rows.map(row => row.target) ?? [])

  async function load(id: string | null) {
    const token = ++generation
    try {
      const [next, nextDetail] = await Promise.all([
        api.getDataFamilies(), id ? api.getDataFamily(id) : Promise.resolve(null),
      ])
      if (token !== generation) return
      overview = next
      detail = nextDetail
      error = ''
    } catch (e) {
      if (token === generation) { error = String((e as Error)?.message ?? e); overview = null; detail = null }
    } finally {
      if (token === generation) loading = false
    }
  }

  $effect(() => {
    const id = familyId
    loading = true
    error = ''
    detail = null
    onlyLagging = false
    load(id)
    return () => { generation++ }
  })

  const latestText = (value: string | null): string =>
    value == null ? '—' : value.length === 10 ? value : fmtBeijing(value)
</script>

<section class="space-y-4 min-w-0">
  {#if error}
    <p role="alert" class="text-sm text-red-600">{error}</p>
  {:else if loading}
    <p class="text-sm text-muted">加载中…</p>
  {:else if overview}
    <header class="flex items-center justify-between">
      <div>
        <h1 class="text-lg font-semibold">{familyId ? `${detail?.card.title ?? familyId} · 数据族` : '数据'}</h1>
        <p class="text-xs text-muted">最近收盘交易日 {overview.session}</p>
      </div>
      {#if familyId}<a class="text-xs text-accent underline" href="#data">返回总览</a>{/if}
    </header>
    <p aria-label="证据说明" class="text-xs text-muted border border-border rounded p-2 bg-surface">{overview.evidence}</p>
    {#if !overview.fetch_runs_ready}
      <p class="text-xs text-warn border border-border rounded p-2 bg-surface"><span>迁移 024 未执行</span>：最近拉取不可见，拉取接口不可用。</p>
    {/if}
    {#if familyId && detail}
      <DataFamilyCard card={detail.card} onfetched={() => load(familyId)} />
      <section class="space-y-2">
        <div class="flex items-center justify-between">
          <h2 class="font-semibold">最近 20 次拉取</h2>
          <a class="text-xs text-accent underline" href="#tools/runs">运行记录</a>
        </div>
        <div class="overflow-x-auto border border-border rounded bg-surface">
          <table aria-label="最近拉取" class="w-full text-sm text-left whitespace-nowrap">
            <thead><tr class="text-muted">
              <th class="px-3 py-2">触发来源</th><th>状态</th><th>成功/目标</th><th>范围</th>
              <th>开始时间</th><th>完成时间</th><th>失败原因</th>
            </tr></thead>
            <tbody>
              {#each detail.runs as run (run.id)}
                <tr class="border-t border-border">
                  <td class="px-3 py-2">{triggerLabel(run.trigger)}</td>
                  <td><StatusPill status={run.status} /></td><td>{run.ok_count}/{run.target_count}</td>
                  <td>{run.scope === 'ticker' ? run.ticker : '全族'}</td>
                  <td>{fmtBeijing(run.started_at)}</td><td>{fmtBeijing(run.finished_at)}</td>
                  <td class="px-3 py-2 whitespace-normal min-w-40">
                    {#each run.failures as failure}<p class="text-red-600">{failure.target}：{failure.reason}</p>{:else}—{/each}
                  </td>
                </tr>
              {:else}<tr><td colspan="7" class="px-3 py-3 text-muted">无记录</td></tr>{/each}
            </tbody>
          </table>
        </div>
      </section>
      <section class="space-y-2">
        <div class="flex items-center justify-between">
          <h2 class="font-semibold">逐目标覆盖</h2>
          <label class="text-xs flex items-center gap-1"><input type="checkbox" bind:checked={onlyLagging} />仅看滞后</label>
        </div>
        <div class="overflow-x-auto border border-border rounded bg-surface">
          <table aria-label="逐目标覆盖" class="w-full text-sm text-left">
            <thead><tr class="text-muted"><th class="px-3 py-2">目标</th><th>最新时点</th><th>是否滞后</th><th>最近失败原因</th></tr></thead>
            <tbody>
              {#each coverageRows as row (row.target)}
                <tr class="border-t border-border">
                  <td class="px-3 py-2">{row.target}</td><td>{latestText(row.latest_at)}</td>
                  <td class={row.lagging ? 'text-warn' : 'text-muted'}>{row.lagging ? '滞后' : '否'}</td>
                  <td class="px-3 py-2 text-red-600">{row.last_failure ?? '—'}</td>
                </tr>
              {:else}<tr><td colspan="4" class="px-3 py-3 text-muted">{onlyLagging ? '无滞后目标' : '无目标'}</td></tr>{/each}
            </tbody>
          </table>
        </div>
      </section>
      {#key familyId}
        <DataBrowse family={detail.card} {targets} onfetched={() => load(familyId)} />
      {/key}
    {:else}
      <div class="grid gap-3 md:grid-cols-2">
        {#each overview.families as card (card.id)}
          <DataFamilyCard {card} onfetched={() => load(null)} />
        {/each}
      </div>
    {/if}
  {/if}
</section>
