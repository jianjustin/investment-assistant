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

  function parseHash(hash: string): { zone: Zone; sub: string | undefined } {
    const [rawZone, rawSub] = hash.replace(/^#/, '').split('/')
    const zone = zones.includes(rawZone as Zone) ? (rawZone as Zone) : 'dashboard'
    return { zone, sub: rawSub || undefined }
  }

  let { zone, sub } = $state(parseHash(location.hash))

  onMount(() => {
    applyTheme()
    const onhashchange = () => {
      const parsed = parseHash(location.hash)
      zone = parsed.zone
      sub = parsed.sub
    }
    window.addEventListener('hashchange', onhashchange)
    return () => window.removeEventListener('hashchange', onhashchange)
  })
</script>

<AppShell route={zone} {sub}>
  {#if zone === 'dashboard'}
    <Dashboard />
  {:else if zone === 'market'}
    <Market {sub} />
  {:else if zone === 'watchlist'}
    <Watchlist {sub} />
  {:else if zone === 'strategy'}
    <Strategy {sub} />
  {:else if zone === 'hermes'}
    <Hermes {sub} />
  {:else}
    <System />
  {/if}
</AppShell>
