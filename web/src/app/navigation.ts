import type { RouteEntry, RouteGroup, RouteId, RouteItem, RouteParent } from './types'

export const defaultRoute: RouteId = 'workbench'

export const routeGroups: RouteGroup[] = [
  {
    labelKey: 'workspace',
    children: [
      { id: 'workbench', labelKey: 'workbench', descriptionKey: 'workbenchDesc', icon: 'layout-dashboard' },
    ],
  },

  {
    labelKey: 'hermesModule',
    children: [
      {
        id: 'hermes',
        labelKey: 'hermesModule',
        descriptionKey: 'hermesModuleDesc',
        icon: 'activity',
        children: [
          { id: 'hermes-overview', labelKey: 'hermesOverview', descriptionKey: 'hermesOverviewDesc' },
          { id: 'hermes-agents', labelKey: 'hermesAgents', descriptionKey: 'hermesAgentsDesc' },
          { id: 'hermes-ideas', labelKey: 'hermesIdeas', descriptionKey: 'hermesIdeasDesc' },
          { id: 'decision-evidence', labelKey: 'decisionEvidence', descriptionKey: 'decisionEvidenceDesc' },
        ],
      },
    ],
  },

  {
    labelKey: 'watchlistModule',
    children: [
      {
        id: 'watchlist',
        labelKey: 'watchlistModule',
        descriptionKey: 'watchlistModuleDesc',
        icon: 'database',
        children: [
          { id: 'watchlist-list', labelKey: 'watchlistList', descriptionKey: 'watchlistListDesc' },
          { id: 'ticker-trends', labelKey: 'tickerTrends', descriptionKey: 'tickerTrendsDesc' },
        ],
      },
    ],
  },
  {
    labelKey: 'strategyModule',
    children: [
      {
        id: 'strategies',
        labelKey: 'strategyModule',
        descriptionKey: 'strategyModuleDesc',
        icon: 'gauge',
        children: [
          { id: 'strategy-scores', labelKey: 'strategyScores', descriptionKey: 'strategyScoresDesc' },
          { id: 'strategy-runs', labelKey: 'strategyRuns', descriptionKey: 'strategyRunsDesc' },
        ],
      },
    ],
  },
  {
    labelKey: 'marketModule',
    children: [
      {
        id: 'market-signals',
        labelKey: 'marketModule',
        descriptionKey: 'marketModuleDesc',
        icon: 'trending-up',
        children: [
          { id: 'market-overview', labelKey: 'marketOverview', descriptionKey: 'marketOverviewDesc' },
          { id: 'market-trend', labelKey: 'marketTrend', descriptionKey: 'marketTrendDesc' },
          { id: 'market-list', labelKey: 'marketList', descriptionKey: 'marketListDesc' },
          { id: 'market-fetch', labelKey: 'marketFetch', descriptionKey: 'marketFetchDesc' },
        ],
      },
    ],
  },
  {
    labelKey: 'marketData',
    children: [
      { id: 'filings', labelKey: 'filings', descriptionKey: 'filingsDesc', icon: 'file-text' },
    ],
  },
  {
    labelKey: 'automation',
    children: [
      { id: 'services', labelKey: 'services', descriptionKey: 'servicesDesc', icon: 'server' },
      { id: 'operations', labelKey: 'operations', descriptionKey: 'operationsDesc', icon: 'gauge' },
    ],
  },
  {
    labelKey: 'system',
    children: [
      { id: 'raw', labelKey: 'raw', descriptionKey: 'rawDesc', icon: 'braces' },
    ],
  },
]

export const routes: RouteItem[] = routeGroups.flatMap((group) =>
  group.children.flatMap((entry) => (isRouteParent(entry) ? entry.children : [entry])),
)
export const parents: RouteParent[] = routeGroups.flatMap((group) => group.children.filter(isRouteParent))

export function isRouteParent(entry: RouteEntry): entry is RouteParent {
  return 'children' in entry
}

export function routeFromHash(hash: string): RouteId {
  const route = hash.replace(/^#\/?/, '')
  if (route === 'market') return 'market-overview'
  if (route === 'hermes') return 'hermes-overview'
  return routes.some((item) => item.id === route) ? route as RouteId : defaultRoute
}

export function parentForRoute(routeId: RouteId): RouteParent | undefined {
  return parents.find((parent) => parent.children.some((child) => child.id === routeId))
}
