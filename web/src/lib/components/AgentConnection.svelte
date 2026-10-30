<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import * as api from '../api'
  import { fmtBeijing } from '../format'
  import { newRequestId } from '../workbench'
  import { LOGIN_POLL_MAX_MS, LOGIN_POLL_MS } from '../runs'
  import type { AgentConnectionView, AgentModel } from '../runs'

  // 设置 → Agent 连接（spec §8.9）。只读取接口约定的字段，从不遍历响应对象：
  // 令牌、client_id、host_id、subject、完整邮箱即使出现在响应里也不会被渲染。
  const REVOKE_UNCONFIRMED = '本机凭据已删除，但远端断开未确认，请到 ChatGPT 设置里断开这个应用'

  let view = $state<AgentConnectionView | null>(null)
  let loadError = $state('')
  let models = $state<AgentModel[] | null>(null)
  let modelsError = $state('')
  let busy = $state(false)
  let actionError = $state('')
  let notice = $state('')
  let modelSaved = $state('')
  let now = $state(Date.now())
  // 失败后重试沿用同一个 request_id，成功后清掉
  let loginRequestId: string | null = null
  const modelRequestIds: Record<string, string> = {}

  let timer: ReturnType<typeof setTimeout> | null = null
  let pollStart = 0
  let destroyed = false

  function agentError(e: unknown): string {
    const code = e instanceof api.ApiError ? e.code : null
    const status = e instanceof api.ApiError ? e.status : null
    const message = e instanceof Error ? e.message : String(e)
    if (code === 'login_pending') return '已有未完成的登录，可先取消再重新连接'
    if (code === 'discovery_failed') return '无法连接 ChatGPT 授权服务，请稍后重试'
    if (code === 'not_connected') return 'ChatGPT 未连接'
    if (status === 503) return `数据库未就绪：${message}`
    return `请求失败：${message}`
  }

  function stopPolling() { if (timer) clearTimeout(timer); timer = null }

  async function loadModels() {
    modelsError = ''
    try {
      const res = await api.getAgentModels()
      if (destroyed) return
      models = Array.isArray(res?.models) ? res.models : []
    } catch (e) {
      if (destroyed) return
      models = null
      modelsError = agentError(e)
    }
  }

  async function refresh(): Promise<void> {
    try {
      const next = await api.getAgentConnection()
      if (destroyed) return
      view = next
      loadError = ''
      now = Date.now()
      if (next.status === 'connected' && models === null) void loadModels()
    } catch (e) {
      if (!destroyed) loadError = agentError(e)
    }
  }

  // 登录轮询：每 2 秒读一次连接状态，直到不再是 pending 或超过 10 分钟（setTimeout 链，销毁时清理）
  function schedule() {
    stopPolling()
    if (destroyed) return
    timer = setTimeout(tick, LOGIN_POLL_MS)
  }
  async function tick() {
    await refresh()
    if (destroyed) return
    if (view?.status !== 'pending') { stopPolling(); return }
    if (Date.now() - pollStart >= LOGIN_POLL_MAX_MS) {
      stopPolling()
      notice = '等待登录超时，请重新连接'
      return
    }
    schedule()
  }
  function startPolling() { pollStart = Date.now(); schedule() }

  onMount(async () => {
    await refresh()
    if (!destroyed && view?.status === 'pending') startPolling()
  })
  onDestroy(() => { destroyed = true; stopPolling() })

  async function connect() {
    if (busy) return
    busy = true; actionError = ''; notice = ''
    try {
      loginRequestId ??= newRequestId()
      const res = await api.startAgentLogin(loginRequestId)
      loginRequestId = null
      if (destroyed) return
      window.open(res.authorize_url, '_blank', 'noopener')
      view = { ...(view as AgentConnectionView), status: 'pending', pending: { expires_at: res.expires_at } }
      now = Date.now()
      startPolling()
    } catch (e) {
      actionError = agentError(e)
      if (e instanceof api.ApiError && e.code === 'login_pending') await refresh()
    } finally { busy = false }
  }

  async function cancel() {
    if (busy) return
    busy = true; actionError = ''
    try {
      await api.cancelAgentLogin()
      stopPolling()
      await refresh()
    } catch (e) { actionError = agentError(e) } finally { busy = false }
  }

  async function disconnect() {
    if (busy) return
    busy = true; actionError = ''; notice = ''
    try {
      const res = await api.disconnectAgent()
      stopPolling()
      models = null
      notice = res.revoked ? '已断开 ChatGPT' : REVOKE_UNCONFIRMED
      await refresh()
    } catch (e) { actionError = agentError(e) } finally { busy = false }
  }

  async function chooseModel(slug: string, select: HTMLSelectElement) {
    if (!slug || busy) return
    busy = true; actionError = ''; modelSaved = ''
    try {
      modelRequestIds[slug] ??= newRequestId()
      const res = await api.setAgentModel(slug, modelRequestIds[slug])
      delete modelRequestIds[slug]
      if (view) view = { ...view, model: res.model, model_display_name: res.model_display_name }
      modelSaved = '已保存，下一次运行生效'
    } catch (e) {
      actionError = agentError(e)
      select.value = view?.model ?? ''     // 没保存成功：下拉框回到当前生效的模型
    } finally { busy = false }
  }

  const remainingMinutes = $derived(view?.pending
    ? Math.max(0, Math.ceil((Date.parse(view.pending.expires_at) - now) / 60000)) : 0)
  const day = (iso: string | null) => (iso ? fmtBeijing(iso).slice(0, 10) : '—')
  const sharingMissing = $derived(view?.status === 'no_sharing' || (view?.status === 'connected' && view.scopes_ok === false))
  const modelMissing = $derived(!!view?.model && models !== null && !models.some(m => m.slug === view!.model))
</script>

<section aria-label="Agent 连接" class="space-y-3 text-sm">
  <h2 class="text-lg font-semibold">Agent 连接</h2>

  {#if view?.provider_setting === 'off'}
    <p class="text-xs text-muted-foreground">Agent 已关闭（WORKBENCH_AGENT_PROVIDER=off）</p>
  {/if}

  {#if loadError && !view}
    <p role="alert" class="text-sm text-destructive">{loadError}</p>
  {:else if !view}
    <p class="text-xs text-muted-foreground">加载中…</p>
  {:else if view.status === 'pending'}
    <div class="flex flex-wrap items-center gap-3">
      <p>等待你在浏览器里完成登录（{remainingMinutes} 分钟内有效）</p>
      <button type="button" class="rounded-sm border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
              disabled={busy} onclick={cancel}>取消</button>
    </div>
  {:else if view.status === 'needs_login'}
    <div class="flex flex-wrap items-center gap-3">
      <p role="alert" class="rounded-sm bg-destructive/10 px-2 py-1 text-destructive">ChatGPT 连接已失效，请重新连接</p>
      <button type="button" class="rounded-sm border border-primary/30 px-2 py-1 text-xs text-primary disabled:opacity-50"
              disabled={busy} onclick={connect}>重新连接</button>
    </div>
  {:else if view.status === 'connected' || view.status === 'no_sharing'}
    {#if sharingMissing}
      <p class="rounded-sm bg-warn/10 px-2 py-1 text-warn">已登录，但这个账号没有开启计划用量共享</p>
    {/if}
    <div class="flex flex-wrap items-center gap-3">
      {#if !sharingMissing}
        <p>已连接：{view.email_masked ?? '—'} · 登录有效至 {day(view.refresh_expires_at)}（每次运行自动续期）· 上次续期 {fmtBeijing(view.last_refresh_at)}</p>
      {:else if view.email_masked}
        <p class="text-xs text-muted-foreground">{view.email_masked}</p>
      {/if}
      <button type="button" class="rounded-sm border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
              disabled={busy} onclick={disconnect}>断开</button>
    </div>
  {:else if view.status === 'unknown'}
    <p role="alert" class="text-destructive">连接状态不可读</p>
  {:else}
    <div class="flex flex-wrap items-center gap-3">
      <p>未连接 ChatGPT</p>
      <button type="button" class="rounded-sm border border-primary/30 px-2 py-1 text-xs text-primary disabled:opacity-50"
              disabled={busy} onclick={connect}>连接 ChatGPT</button>
    </div>
  {/if}

  {#if view?.last_error && view.status !== 'connected'}
    <p class="text-xs text-muted-foreground">最近错误：{view.last_error}</p>
  {/if}

  {#if view?.status === 'connected' && !sharingMissing}
    <div class="space-y-1">
      <label class="flex flex-wrap items-center gap-2">
        <span>模型</span>
        {#if models !== null}
          <select aria-label="模型" class="rounded-sm border border-border bg-card px-2 py-1 text-sm"
                  value={view.model ?? ''} disabled={busy} onchange={e => chooseModel((e.currentTarget as HTMLSelectElement).value, e.currentTarget as HTMLSelectElement)}>
            {#if !view.model}<option value="" disabled>请选择模型</option>{/if}
            {#if modelMissing}<option value={view.model}>{view.model}（已不在可用清单里）</option>{/if}
            {#each models as m (m.slug)}<option value={m.slug}>{m.display_name}</option>{/each}
          </select>
        {:else if modelsError}
          <span class="text-xs text-destructive">{modelsError}</span>
        {:else}
          <span class="text-xs text-muted-foreground">加载中…</span>
        {/if}
      </label>
      {#if modelMissing}<p class="text-xs text-warn">当前所选模型已不在可用清单里，请重新选择</p>{/if}
      {#if modelSaved}<p class="text-xs text-muted-foreground">{modelSaved}</p>{/if}
    </div>
  {/if}

  {#if notice}<p class="text-xs text-muted-foreground">{notice}</p>{/if}
  {#if actionError}<p role="alert" class="text-xs text-destructive">{actionError}</p>{/if}
  {#if loadError && view}<p role="alert" class="text-xs text-destructive">{loadError}</p>{/if}
</section>
