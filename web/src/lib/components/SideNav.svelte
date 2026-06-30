<script lang="ts">
  type NavChild = { id: string; label: string }
  type NavItem = { id: string; label: string; icon: string; children?: NavChild[] }

  let { current, sub }: { current: string; sub?: string } = $props()

  const nav: NavItem[] = [
    {
      id: 'tools', label: '工具', icon: '🔧', children: [
        { id: 'tasks',   label: '任务中心' },
        { id: 'runs',    label: '运行记录' },
        { id: 'ops',     label: '运维指标' },
        { id: 'results', label: '数据结果' },
      ],
    },
    {
      id: 'data', label: '数据', icon: '📊', children: [
        { id: 'signals', label: '信号总览' },
        { id: 'trend',   label: '趋势分析' },
        { id: 'tickers', label: '技术面趋势' },
      ],
    },
    {
      id: 'strategy', label: '策略', icon: '🎯', children: [
        { id: 'scores',   label: '策略评分' },
        { id: 'runs',     label: '运行历史' },
        { id: 'backtest', label: '回测' },
      ],
    },
    {
      id: 'trade', label: '交易', icon: '🤖', children: [
        { id: 'macro',    label: '宏观分析' },
        { id: 'decision', label: '决策证据' },
        { id: 'orders',   label: '交易指令' },
      ],
    },
    {
      id: 'settings', label: '设置', icon: '⚙️', children: [
        { id: 'system',    label: '系统' },
        { id: 'watchlist', label: '关注列表' },
        { id: 'discord',   label: 'Discord 推送' },
        { id: 'jobs',      label: '定时任务' },
        { id: 'env',       label: '环境变量' },
      ],
    },
  ]

  let collapsed = $state(false)
  let openIds = $state<Set<string>>(new Set<string>())

  // Keep the active parent expanded whenever current changes
  $effect(() => {
    if (!openIds.has(current)) openIds = new Set([...openIds, current])
  })

  function toggleOpen(id: string, e: MouseEvent) {
    e.preventDefault()
    const next = new Set(openIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    openIds = next
    // also navigate to the zone
    location.hash = id
  }

  function isActive(item: NavItem): boolean {
    return item.id === current
  }

  function isChildActive(item: NavItem): boolean {
    return item.id === current && !!sub
  }
</script>

<nav
  class="flex flex-col bg-surface border-r border-border h-full transition-all duration-200 {collapsed ? 'w-14' : 'w-48'}"
>
  <!-- collapse toggle -->
  <button
    onclick={() => collapsed = !collapsed}
    class="flex items-center justify-center h-10 mt-1 mb-2 mx-1 rounded text-muted hover:bg-surface-2 hover:text-ink transition-colors"
    aria-label={collapsed ? '展开菜单' : '收起菜单'}
  >
    {#if collapsed}
      <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
    {:else}
      <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
    {/if}
  </button>

  <div class="flex flex-col gap-0.5 px-1 overflow-y-auto overflow-x-hidden flex-1">
    {#each nav as item}
      {@const hasChildren = !!item.children?.length}
      {@const open = openIds.has(item.id)}
      {@const active = isActive(item)}

      <!-- parent row -->
      {#if hasChildren}
        <button
          onclick={e => toggleOpen(item.id, e)}
          class="flex items-center gap-2 w-full px-2 py-2 rounded text-sm transition-colors text-left
            {active ? 'bg-accent/10 text-accent' : 'text-muted hover:bg-surface-2 hover:text-ink'}"
          aria-expanded={open}
        >
          <span class="text-base shrink-0 w-5 text-center">{item.icon}</span>
          {#if !collapsed}
            <span class="flex-1 truncate">{item.label}</span>
            <svg
              xmlns="http://www.w3.org/2000/svg"
              class="w-3 h-3 shrink-0 transition-transform {open ? 'rotate-90' : ''}"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            ><polyline points="9 18 15 12 9 6"/></svg>
          {/if}
        </button>

        <!-- children -->
        {#if open && !collapsed}
          <div class="ml-3 pl-3 border-l border-border flex flex-col gap-0.5 mb-1">
            {#each item.children! as child}
              {@const childActive = active && sub === child.id}
              <a
                href="#{item.id}/{child.id}"
                class="block px-2 py-1.5 rounded text-xs transition-colors
                  {childActive ? 'bg-accent/10 text-accent font-medium' : 'text-muted hover:bg-surface-2 hover:text-ink'}"
              >
                {child.label}
              </a>
            {/each}
          </div>
        {/if}

      {:else}
        <!-- leaf node -->
        <a
          href="#{item.id}"
          class="flex items-center gap-2 px-2 py-2 rounded text-sm transition-colors
            {active ? 'bg-accent/10 text-accent' : 'text-muted hover:bg-surface-2 hover:text-ink'}"
        >
          <span class="text-base shrink-0 w-5 text-center">{item.icon}</span>
          {#if !collapsed}
            <span class="truncate">{item.label}</span>
          {/if}
        </a>
      {/if}
    {/each}
  </div>
</nav>
