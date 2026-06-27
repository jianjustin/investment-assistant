<script lang="ts">
  import { onMount } from 'svelte'
  import { applyTheme } from './lib/theme'
  import AppShell from './lib/components/AppShell.svelte'
  import Dashboard from './routes/Dashboard.svelte'
  import Market from './routes/Market.svelte'
  import Watchlist from './routes/Watchlist.svelte'
  import Strategy from './routes/Strategy.svelte'
  import Hermes from './routes/Hermes.svelte'
  import System from './routes/System.svelte'

  type Zone = 'dashboard' | 'market' | 'watchlist' | 'strategy' | 'hermes' | 'system'
  const zones: Zone[] = ['dashboard', 'market', 'watchlist', 'strategy', 'hermes', 'system']

  function hashToZone(hash: string): Zone {
    const raw = hash.replace(/^#/, '') as Zone
    return zones.includes(raw) ? raw : 'dashboard'
  }

  let route = $state<Zone>(hashToZone(location.hash))

  onMount(() => {
    applyTheme()
    const onhashchange = () => { route = hashToZone(location.hash) }
    window.addEventListener('hashchange', onhashchange)
    return () => window.removeEventListener('hashchange', onhashchange)
  })
</script>

<AppShell {route}>
  {#if route === 'dashboard'}
    <Dashboard />
  {:else if route === 'market'}
    <Market />
  {:else if route === 'watchlist'}
    <Watchlist />
  {:else if route === 'strategy'}
    <Strategy />
  {:else if route === 'hermes'}
    <Hermes />
  {:else}
    <System />
  {/if}
</AppShell>
