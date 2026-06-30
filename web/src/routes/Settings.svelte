<script lang="ts">
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import DataTable from '../lib/components/DataTable.svelte'
  import Drawer from '../lib/components/Drawer.svelte'

  let { sub = 'system' }: { sub?: string } = $props()
  let loading = $state(true)

  // system
  let status = $state<any>(null)
  let ops = $state<any[]>([])

  // watchlist
  let watchlist = $state<any[]>([])
  let drawerOpen = $state(false)
  let addForm = $state({ ticker: '', status: 'active', thesis: '' })
  let saving = $state(false)

  const wlCols = [
    { key: 'ticker', label: 'Ticker' },
    { key: 'status', label: '状态' },
    { key: 'thesis', label: '论点' },
  ]

  // discord
  let notify = $state<any>({
    webhooks: {},
    task_channels: {},
    task_enabled: {},
    discord_enabled: true,
  })
  let webhookInput = $state<Record<string, string>>({ earnings: '', signals: '', daily: '' })
  let testResult = $state<Record<string, string>>({})

  // jobs
  let jobs = $state<any[]>([])

  // env
  let env = $state<Record<string, boolean>>({})

  async function load() {
    loading = true
    try {
      if (sub === 'system') {
        ;[status, ops] = await Promise.all([
          api.getStatus(),
          api.getOperations().then((r: any) => r.operations ?? []),
        ])
      } else if (sub === 'watchlist') {
        watchlist = (await api.getWatchlist() as any).rows ?? []
      } else if (sub === 'discord') {
        notify = await api.getNotifySettings()
        webhookInput = { earnings: '', signals: '', daily: '' }
        testResult = {}
      } else if (sub === 'jobs') {
        jobs = (await api.getScheduledJobs()).jobs
      } else {
        env = await api.getEnvStatus()
      }
    } finally {
      loading = false
    }
  }

  // Watchlist actions
  async function addItem() {
    saving = true
    try {
      await api.addWatchlistItem(addForm)
      addForm = { ticker: '', status: 'active', thesis: '' }
      drawerOpen = false
      await load()
    } finally {
      saving = false
    }
  }

  async function removeItem(ticker: string) {
    await api.deleteWatchlistItem(ticker)
    await load()
  }

  // Discord actions
  async function verify(ch: string) {
    const url = webhookInput[ch]?.trim() || undefined
    const r = await api.testNotifyChannel({ channel: ch, url })
    testResult = { ...testResult, [ch]: r.ok ? '✅ 成功' : `❌ ${(r as any).error ?? '失败'}` }
  }

  async function saveNotify() {
    const webhooks: Record<string, string> = {}
    for (const ch of ['earnings', 'signals', 'daily']) {
      if (webhookInput[ch]?.trim()) webhooks[ch] = webhookInput[ch]
    }
    await api.patchNotifySettings({
      discord_enabled: notify.discord_enabled,
      webhooks,
      task_enabled: notify.task_enabled,
      task_channels: notify.task_channels,
    })
    webhookInput = { earnings: '', signals: '', daily: '' }
    await load()
  }

  // Jobs actions
  async function toggleJob(name: string, enabled: boolean) {
    await api.patchScheduledJob(name, { enabled })
    await load()
  }

  async function saveTime(name: string, time_local: string) {
    await api.patchScheduledJob(name, { time_local })
    await load()
  }

  $effect(() => { sub; load() })
</script>

{#if loading}
  <Skeleton rows={4} />
{:else if sub === 'system'}
  <div>
    <h2 class="text-lg font-semibold mb-4">系统</h2>
    {#if status}
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {#each Object.entries(status as any) as [k, v]}
          {#if typeof v === 'object' && v !== null && 'status' in v}
            <div class="bg-surface rounded p-3 shadow-elev-1">
              <div class="text-xs text-muted mb-1">{k}</div>
              <StatusPill status={(v as any).status ?? 'unknown'} />
            </div>
          {/if}
        {/each}
      </div>
    {/if}
    {#if ops.length > 0}
      <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
        <div class="px-4 py-2 border-b border-border text-sm font-medium">最近操作</div>
        <ul class="divide-y divide-border text-sm">
          {#each ops.slice(0, 20) as op}
            <li class="flex justify-between px-4 py-2">
              <span class="text-muted">{(op as any).type} — {(op as any).run_id?.slice(0, 12) ?? '—'}</span>
              <StatusPill status={(op as any).status ?? 'unknown'} />
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  </div>
{:else if sub === 'watchlist'}
  <div>
    <div class="flex justify-between items-center mb-4">
      <h2 class="text-lg font-semibold">关注列表</h2>
      <button onclick={() => drawerOpen = true} class="px-3 py-1 bg-accent text-white rounded text-sm">+ 添加</button>
    </div>
    <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden mb-4">
      <DataTable rows={watchlist} columns={wlCols} />
    </div>
    <ul class="divide-y divide-border text-sm">
      {#each watchlist as row}
        <li class="flex justify-between items-center py-2 px-1">
          <span class="font-mono text-xs">{row.ticker}</span>
          <button class="text-red-500 text-xs" onclick={() => removeItem(row.ticker)}>删除</button>
        </li>
      {/each}
    </ul>
  </div>

  <Drawer open={drawerOpen} onclose={() => drawerOpen = false}>
    <h3 class="font-semibold mb-3">添加关注</h3>
    <div class="flex flex-col gap-2">
      <input bind:value={addForm.ticker} placeholder="Ticker (如 NVDA)" class="border border-border rounded px-2 py-1 text-sm bg-bg" />
      <input bind:value={addForm.thesis} placeholder="论点" class="border border-border rounded px-2 py-1 text-sm bg-bg" />
      <button onclick={addItem} disabled={saving} class="px-3 py-1 bg-accent text-white rounded text-sm disabled:opacity-50">
        {saving ? '保存中…' : '保存'}
      </button>
    </div>
  </Drawer>
{:else if sub === 'discord'}
  <div class="space-y-4 max-w-lg">
    <h2 class="text-lg font-semibold">Discord 通知</h2>
    <label class="flex items-center gap-2 text-sm">
      <input type="checkbox" bind:checked={notify.discord_enabled} />
      启用 Discord 推送
    </label>
    {#each ['earnings', 'signals', 'daily'] as ch}
      <div class="space-y-1">
        <div class="text-sm font-medium">
          {ch}
          {#if notify.webhooks?.[ch]?.configured}
            <span class="text-green-600 text-xs ml-1">（已配置）</span>
          {:else}
            <span class="text-muted text-xs ml-1">（未配置）</span>
          {/if}
        </div>
        <div class="flex gap-2">
          <input
            type="password"
            bind:value={webhookInput[ch]}
            placeholder="留空则不修改"
            class="border border-border rounded px-2 py-1 text-sm bg-surface flex-1"
          />
          <button
            class="text-accent text-xs whitespace-nowrap px-2 py-1 border border-accent/30 rounded"
            onclick={() => verify(ch)}
          >验证 {ch}</button>
        </div>
        {#if testResult[ch]}
          <div class="text-xs text-muted">{testResult[ch]}</div>
        {/if}
      </div>
    {/each}
    <div class="pt-2">
      <button class="px-3 py-1.5 rounded bg-accent/10 text-accent text-sm" onclick={saveNotify}>保存</button>
    </div>
    <p class="text-xs text-muted">webhook 明文不回显；留空字段不会覆盖已存值。</p>
  </div>
{:else if sub === 'jobs'}
  <div>
    <h2 class="text-lg font-semibold mb-4">定时任务</h2>
    <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-muted text-left border-b border-border">
            <th class="px-4 py-2">任务</th>
            <th class="px-4 py-2">时间</th>
            <th class="px-4 py-2">启用</th>
          </tr>
        </thead>
        <tbody>
          {#each jobs as j}
            <tr class="border-t border-border">
              <td class="px-4 py-2">{j.name}</td>
              <td class="px-4 py-2">
                <input
                  value={j.time_local}
                  class="border border-border rounded px-2 py-1 w-24 bg-bg text-sm"
                  onchange={(e) => saveTime(j.name, (e.target as HTMLInputElement).value)}
                />
              </td>
              <td class="px-4 py-2">
                <input
                  type="checkbox"
                  checked={j.enabled}
                  onchange={(e) => toggleJob(j.name, (e.target as HTMLInputElement).checked)}
                />
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{:else}
  <div>
    <h2 class="text-lg font-semibold mb-4">环境变量</h2>
    <div class="bg-surface rounded-lg shadow-elev-1 overflow-hidden">
      <ul class="divide-y divide-border text-sm">
        {#each Object.entries(env) as [k, v]}
          <li class="flex justify-between items-center px-4 py-2">
            <span class="font-mono text-xs">{k}</span>
            <span class={v ? 'text-green-600' : 'text-muted'}>{v ? '✅ 已设置' : '— 未设置'}</span>
          </li>
        {/each}
      </ul>
    </div>
  </div>
{/if}
