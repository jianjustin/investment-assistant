<script lang="ts">
  import { onDestroy, onMount } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import ConfirmDialog from '$lib/ui/confirm-dialog/ConfirmDialog.svelte'
  import DataBlock from '$lib/ui/domain/DataBlock.svelte'
  import Icon from '$lib/ui/domain/Icon.svelte'
  import StatusPill from '$lib/ui/domain/StatusPill.svelte'
  import Field from '$lib/ui/field/Field.svelte'
  import * as Select from '$lib/ui/select/index'
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
  let pollStart = $state(0)
  let disconnectOpen = $state(false)
  const uid = $props.id()
  // 失败后重试沿用同一个 request_id，成功后清掉
  let loginRequestId: string | null = null
  const modelRequestIds: Record<string, string> = {}

  let timer: ReturnType<typeof setTimeout> | null = null
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
    } catch (e) { actionError = agentError(e) } finally { busy = false; disconnectOpen = false }
  }

  async function chooseModel(slug: string) {
    if (!slug || busy) return
    busy = true; actionError = ''; modelSaved = ''
    try {
      modelRequestIds[slug] ??= newRequestId()
      const res = await api.setAgentModel(slug, modelRequestIds[slug])
      delete modelRequestIds[slug]
      if (view) view = { ...view, model: res.model, model_display_name: res.model_display_name }
      modelSaved = '已保存，下一次运行生效'
    } catch (e) {
      actionError = agentError(e)          // 没保存成功：下拉框仍显示当前生效的模型（值取自 view.model）
    } finally { busy = false }
  }

  const remainingMinutes = $derived(view?.pending
    ? Math.max(0, Math.ceil((Date.parse(view.pending.expires_at) - now) / 60000)) : 0)
  const day = (iso: string | null) => (iso ? fmtBeijing(iso).slice(0, 10) : '—')
  const sharingMissing = $derived(view?.status === 'no_sharing' || (view?.status === 'connected' && view.scopes_ok === false))
  const modelMissing = $derived(!!view?.model && models !== null && !models.some(m => m.slug === view!.model))
  const waitedSeconds = $derived(Math.max(0, Math.floor((now - pollStart) / 1000)))
  const modelOptions = $derived([
    ...(modelMissing ? [{ value: view!.model!, label: `${view!.model}（已不在可用清单里）` }] : []),
    ...(models ?? []).map(m => ({ value: m.slug, label: m.display_name })),
  ])
  const modelLabel = $derived(modelOptions.find(o => o.value === (view?.model ?? ''))?.label ?? '请选择模型')
</script>

<section aria-label="Agent 连接" class="grid gap-3 text-sm">
  <h2 class="text-lg font-medium">Agent 连接</h2>

  {#if view?.provider_setting === 'off'}
    <p class="text-xs text-muted-foreground">Agent 已关闭（WORKBENCH_AGENT_PROVIDER=off）</p>
  {/if}

  {#if loadError && !view}
    <DataBlock state="error" message={loadError} />
  {:else if !view}
    <DataBlock state="loading" skeleton="row" />
  {:else if view.status === 'pending'}
    <div class="flex flex-wrap items-center gap-3">
      <StatusPill domain="connection" value="pending" />
      <span class="text-xs text-muted-foreground">已等待 {waitedSeconds} 秒</span>
      <p>等待你在浏览器里完成登录（{remainingMinutes} 分钟内有效）</p>
      <Button size="sm" disabled={busy} onclick={cancel}>取消</Button>
    </div>
  {:else if view.status === 'needs_login'}
    <div class="flex flex-wrap items-center gap-3">
      <Alert variant="danger" class="w-auto">
        <Icon name="circle-x" />
        <AlertDescription>ChatGPT 连接已失效，请重新连接</AlertDescription>
      </Alert>
      <Button variant="primary" size="sm" {busy} onclick={connect}>重新连接</Button>
    </div>
  {:else if view.status === 'connected' || view.status === 'no_sharing'}
    {#if sharingMissing}
      <Alert variant="warn"><Icon name="triangle-alert" /><AlertDescription>已登录，但这个账号没有开启计划用量共享</AlertDescription></Alert>
    {/if}
    <div class="flex flex-wrap items-center gap-3">
      <StatusPill domain="connection" value={view.status} />
      {#if !sharingMissing}
        <p>已连接：{view.email_masked ?? '未提供'} · 登录有效至 {day(view.refresh_expires_at)}（每次运行自动续期）· 上次续期 {fmtBeijing(view.last_refresh_at)}</p>
      {:else if view.email_masked}
        <p class="text-xs text-muted-foreground">{view.email_masked}</p>
      {/if}
      <Button size="sm" disabled={busy} onclick={() => disconnectOpen = true}>断开</Button>
    </div>
  {:else if view.status === 'unknown'}
    <Alert variant="danger"><Icon name="circle-x" /><AlertDescription>连接状态不可读</AlertDescription></Alert>
  {:else}
    <div class="flex flex-wrap items-center gap-3">
      <StatusPill domain="connection" value="disconnected" />
      <p>未连接 ChatGPT</p>
      <Button variant="primary" size="sm" {busy} onclick={connect}>连接 ChatGPT</Button>
    </div>
  {/if}

  {#if view?.last_error && view.status !== 'connected'}
    <p class="text-xs text-muted-foreground">最近错误：{view.last_error}</p>
  {/if}

  {#if view?.status === 'connected' && !sharingMissing}
    <div class="grid gap-1">
      {#if models !== null}
        <Field label="模型" id={`${uid}-model`}>
          {#snippet children({ id })}
            <Select.Root type="single" disabled={busy} bind:value={() => view?.model ?? '', v => { void chooseModel(v) }}>
              <Select.Trigger {id} class="w-64">{modelLabel}</Select.Trigger>
              <Select.Content>
                {#each modelOptions as o (o.value)}<Select.Item value={o.value} label={o.label} />{/each}
              </Select.Content>
            </Select.Root>
          {/snippet}
        </Field>
      {:else if modelsError}
        <p class="flex items-center gap-2"><span>模型</span><span class="text-xs text-destructive">{modelsError}</span></p>
      {:else}
        <p class="flex items-center gap-2"><span>模型</span><span class="text-xs text-muted-foreground">加载中…</span></p>
      {/if}
      {#if modelMissing}<p class="text-xs text-warn">当前所选模型已不在可用清单里，请重新选择</p>{/if}
      {#if modelSaved}<p class="text-xs text-muted-foreground">{modelSaved}</p>{/if}
    </div>
  {/if}

  {#if notice}<p class="text-xs text-muted-foreground">{notice}</p>{/if}
  {#if actionError}<Alert variant="danger"><Icon name="circle-x" /><AlertDescription>{actionError}</AlertDescription></Alert>{/if}
  {#if loadError && view}<Alert variant="danger"><Icon name="circle-x" /><AlertDescription>{loadError}</AlertDescription></Alert>{/if}

  <ConfirmDialog bind:open={disconnectOpen} title="断开 ChatGPT" destructive
                 consequence="断开后 Agent 不会再运行，直到重新连接 ChatGPT。" actionLabel="断开" {busy} onConfirm={disconnect} />
</section>
