import type { Zone } from './router'
export type Market = 'US'

export function researchHash(zone: Zone, sub: string, market: Market, symbol: string): string {
  return `#${zone}/${sub}?${new URLSearchParams({ market, symbol })}`
}

export function readResearchSelection(hash: string): { market: Market; symbol: string } | null {
  const query = new URLSearchParams(hash.split('?')[1] ?? '')
  const market = query.get('market')
  const symbol = query.get('symbol')?.trim().toUpperCase() ?? ''
  if (market === 'US' && /^[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)*$/.test(symbol)) return { market, symbol }
  return null
}
