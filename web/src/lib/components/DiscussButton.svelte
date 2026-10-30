<script lang="ts">
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import * as api from '../api'
  import { growthError, idempotentRequests, unwrapRecord } from '../growth'
  import type { Discussion, DiscussionContext } from '../growth'

  // 「就此讨论」（spec §8.1）：先新建一次讨论（带 request_id；失败后重试复用同一个，不重复建），再跳到 #discuss/<id>。
  // request_id 在点击时才生成，渲染时不碰 crypto。
  let { context, label }: { context: DiscussionContext; label?: string } = $props()

  const requests = idempotentRequests()
  let busy = $state(false)
  let error = $state('')
  const text = $derived(label ?? (context.kind === 'card' ? '就此卡讨论' : '就此计划讨论'))

  async function start() {
    if (busy) return
    busy = true
    error = ''
    try {
      const reply = await api.postDiscussion({ request_id: requests.idFor(context), context })
      const record = unwrapRecord<Discussion>(reply)
      requests.done()
      location.hash = `#discuss/${record.id}`
    } catch (e) {
      error = growthError(e)
    } finally {
      busy = false
    }
  }
</script>

<span class="inline-flex flex-wrap items-center gap-2">
  <Button size="sm" {busy} onclick={start}>{text}</Button>
  {#if error}<Alert variant="danger" class="w-auto py-1"><AlertDescription>{error}</AlertDescription></Alert>{/if}
</span>
