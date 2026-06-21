import type { RouteGroup, RouteId, RouteItem } from './types'

export const defaultRoute: RouteId = 'workbench'

export const routeGroups: RouteGroup[] = [
  {
    labelKey: 'workspace',
    children: [
      { id: 'workbench', labelKey: 'workbench', descriptionKey: 'workbenchDesc', icon: 'layout-dashboard' },
    ],
  },
  {
    labelKey: 'marketData',
    children: [
      { id: 'market', labelKey: 'marketSignals', descriptionKey: 'marketSignalsDesc', icon: 'activity' },
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

export const routes: RouteItem[] = routeGroups.flatMap((group) => group.children)

export function routeFromHash(hash: string): RouteId {
  const route = hash.replace(/^#\/?/, '') as RouteId
  return routes.some((item) => item.id === route) ? route : defaultRoute
}
