<script lang="ts">
  import type { Snippet } from 'svelte'
  import { Alert, AlertDescription } from '$lib/ui/alert/index'
  import { Button } from '$lib/ui/button/index'
  import { Skeleton } from '$lib/ui/skeleton/index'
  import { cn } from '$lib/utils.js'
  import Icon from './Icon.svelte'
  import StatusPill from './StatusPill.svelte'

  // The five states of a data block (spec 4.5) plus `ready`. Never express any of them with blank, a dash,
  // null or undefined. `message` says WHY (empty), WHAT IS MISSING (not_computed), WHICH PART is incomplete
  // (degraded) or the Chinese reason (error).
  let { state, message, skeleton = 'block', onRetry, retryLabel = '重试', page = false, children }: {
    state: 'loading' | 'empty' | 'not_computed' | 'degraded' | 'error' | 'ready'
    message?: string
    skeleton?: 'row' | 'block' | 'table'
    onRetry?: () => void
    retryLabel?: string
    page?: boolean
    children?: Snippet
  } = $props()

  // `page` fills the content area and centres the message; ready / degraded render the page content itself, full width.
  const centered = $derived(page && state !== 'ready' && state !== 'degraded')
</script>

<div class={cn('grid gap-2', centered && 'min-h-[50vh] content-center justify-items-center')} data-slot="data-block" data-state={state}>
  {#if state === 'loading'}
    <div class="grid w-full gap-2" role="status" aria-busy="true" aria-label="加载中">
      {#if skeleton === 'row'}
        <Skeleton class="h-4 w-full" />
      {:else if skeleton === 'table'}
        <Skeleton class="h-7 w-full" />
        {#each Array(5) as _, i (i)}<Skeleton class="h-5 w-full" />{/each}
      {:else}
        <Skeleton class="h-24 w-full" />
      {/if}
    </div>
  {:else if state === 'empty'}
    <p class="text-sm text-muted-foreground">{message ?? '暂无数据'}</p>
  {:else if state === 'not_computed'}
    <p class="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">{#if message}<span>{message}</span>{/if}<StatusPill domain="block" value="not_computed" /></p>
  {:else if state === 'degraded'}
    <Alert variant="warn" class="w-full"><Icon name="triangle-alert" /><AlertDescription>{message ?? '部分数据不全'}</AlertDescription></Alert>
    {@render children?.()}
  {:else if state === 'error'}
    <Alert variant="danger" class="w-full"><Icon name="circle-x" /><AlertDescription>{message ?? '加载失败'}</AlertDescription></Alert>
    {#if onRetry}<div><Button size="sm" onclick={() => onRetry?.()}>{retryLabel}</Button></div>{/if}
  {:else}
    {@render children?.()}
  {/if}
</div>
