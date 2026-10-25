<script lang="ts">
  import * as api from '../lib/api'
  import Skeleton from '../lib/components/Skeleton.svelte'
  import StatusPill from '../lib/components/StatusPill.svelte'
  import Watchlist from '../lib/components/Watchlist.svelte'

  let { sub = 'system' }: { sub?: string } = $props()
  let loading = $state(true)

  // system
  let status = $state<any>(null)
  let ops = $state<any[]>([])

  // notify（Discord / 邮件）
  let notify = $state<any>({
    channel: 'discord',
    webhooks: {},
    task_channels: {},
    task_enabled: {},
    discord_enabled: true,
    email: { from_addr: '', to_addr: '' },
  })
  let webhookInput = $state<Record<string, string>>({ earnings: '', signals: '' })
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
        // Shared editor owns its read-back lifecycle.
      } else if (sub === 'discord') {
        ;[notify, env] = await Promise.all([api.getNotifySettings(), api.getEnvStatus()])
        if (!notify.email) notify.email = { from_addr: '', to_addr: '' }
        webhookInput = { earnings: '', signals: '' }
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

  // Discord actions
  async function verify(ch: string) {
    const url = webhookInput[ch]?.trim() || undefined
    const r = await api.testNotifyChannel({ channel: ch, url })
    testResult = { ...testResult, [ch]: r.ok ? '✅ 成功' : `❌ ${(r as any).error ?? '失败'}` }
  }

  async function verifyEmail() {
    const r = await api.testNotifyChannel({ channel: 'email', email: notify.email })
    testResult = { ...testResult, email: r.ok ? '✅ 成功' : `❌ ${(r as any).error ?? '失败'}` }
  }

  async function saveNotify() {
    const webhooks: Record<string, string> = {}
    for (const ch of ['earnings', 'signals']) {
      if (webhookInput[ch]?.trim()) webhooks[ch] = webhookInput[ch]
    }
    await api.patchNotifySettings({
      channel: notify.channel,
      discord_enabled: notify.discord_enabled,
      webhooks,
      email: notify.email,
      task_enabled: notify.task_enabled,
      task_channels: notify.task_channels,
    })
    webhookInput = { earnings: '', signals: '' }
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
  <Watchlist />
{:else if sub === 'discord'}
  <div class="space-y-4 max-w-lg">
    <h2 class="text-lg font-semibold">通知</h2>
    <div class="flex gap-4 text-sm">
      <label class="flex items-center gap-1">
        <input type="radio" bind:group={notify.channel} value="discord" /> Discord
      </label>
      <label class="flex items-center gap-1">
        <input type="radio" bind:group={notify.channel} value="email" /> 邮件
      </label>
    </div>
    {#if notify.channel === 'email'}
      <div class="space-y-2">
        <div class="text-sm font-medium">发件地址（Gmail）</div>
        <input bind:value={notify.email.from_addr} placeholder="you@gmail.com"
               class="border border-border rounded px-2 py-1 text-sm bg-surface w-full" />
        <div class="text-sm font-medium">收件地址</div>
        <input bind:value={notify.email.to_addr} placeholder="you@outlook.com"
               class="border border-border rounded px-2 py-1 text-sm bg-surface w-full" />
        <div class="text-xs {env.SMTP_PASSWORD ? 'text-green-600' : 'text-red-500'}">
          SMTP_PASSWORD {env.SMTP_PASSWORD ? '✅ 已配置' : '未配置——需以环境变量注入 Gmail 应用专用密码'}
        </div>
        <button class="text-accent text-xs whitespace-nowrap px-2 py-1 border border-accent/30 rounded"
                onclick={verifyEmail}>发送测试邮件</button>
        {#if testResult.email}
          <div class="text-xs text-muted">{testResult.email}</div>
        {/if}
      </div>
    {:else}
      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={notify.discord_enabled} />
        启用 Discord 推送
      </label>
      {#each ['earnings', 'signals'] as ch}
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
    {/if}
    <div class="pt-2">
      <button class="px-3 py-1.5 rounded bg-accent/10 text-accent text-sm" onclick={saveNotify}>保存</button>
    </div>
    <p class="text-xs text-muted">webhook 明文不回显；留空字段不会覆盖已存值。SMTP 密码只能通过环境变量配置。</p>
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
                <span class="text-xs text-muted ml-2">{j.timezone === 'Asia/Shanghai' ? '北京' : j.timezone}</span>
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
