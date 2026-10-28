<script lang="ts">
  type NavChild = { id: string; label: string; href?: string }
  type NavItem = { id: string; label: string; icon: string; children?: NavChild[] }

  let { current, sub }: { current: string; sub?: string } = $props()

  const primary: NavItem[] = [
    { id: 'today', label: '今日', icon: '🗓️' },
    { id: 'instrument', label: '标的', icon: '🔎' },
    {
      id: 'review', label: '复盘', icon: '🧾', children: [
        { id: 'trades', label: '交易与持仓' },
        { id: 'shadow', label: '对照组' },
        { id: 'weekly', label: '周度复盘' },
      ],
    },
    { id: 'data', label: '数据', icon: '🗄️' },
    {
      // 概念浏览页是 #knowledge 本身，没有子路径
      id: 'knowledge', label: '知识', icon: '📚', children: [
        { id: 'concepts', label: '概念', href: '#knowledge' },
        { id: 'principles', label: '原理' },
      ],
    },
  ]

  // Shared-base entries stay reachable, folded under 更多.
  const legacy: NavItem[] = [
    {
      id: 'tools', label: '工具', icon: '🔧', children: [
        { id: 'tasks',   label: '任务中心' },
        { id: 'runs',    label: '运行记录' },
        { id: 'filings', label: 'SEC 文件' },
      ],
    },
    {
      id: 'settings', label: '设置', icon: '⚙️', children: [
        { id: 'system',    label: '系统' },
        { id: 'watchlist', label: '关注列表' },
        { id: 'discord',   label: '推送配置' },
        { id: 'jobs',      label: '定时任务' },
        { id: 'env',       label: '环境变量' },
      ],
    },
  ]

  const legacyIds = legacy.map(item => item.id)
  let collapsed = $state(false)
  let openIds = $state<Set<string>>(new Set<string>())
  let moreOpen = $state(false)

  $effect(() => {
    if (legacyIds.includes(current)) moreOpen = true
  })

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

  // 概念页是知识区的默认页：没有子路径（或 concepts / 具体的卡）时都算「概念」。
  function isChildCurrent(item: NavItem, child: NavChild): boolean {
    if (item.id !== current) return false
    if (item.id === 'knowledge') return child.id === 'principles' ? sub === 'principles' : sub !== 'principles'
    return sub === child.id
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
    {#snippet entry(item: NavItem)}
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
              {@const childActive = isChildCurrent(item, child)}
              <a
                href={child.href ?? `#${item.id}/${child.id}`}
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
    {/snippet}

    {#each primary as item}{@render entry(item)}{/each}

    <button
      onclick={() => moreOpen = !moreOpen}
      class="flex items-center gap-2 w-full px-2 py-2 mt-2 rounded text-sm text-left border-t border-border transition-colors
        {legacyIds.includes(current) ? 'text-accent' : 'text-muted hover:bg-surface-2 hover:text-ink'}"
      aria-expanded={moreOpen}
    >
      <span class="text-base shrink-0 w-5 text-center">⋯</span>
      {#if !collapsed}<span class="flex-1 truncate">更多</span>{/if}
    </button>
    {#if moreOpen}
      {#each legacy as item}{@render entry(item)}{/each}
    {/if}
  </div>
</nav>
