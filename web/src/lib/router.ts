export type Zone = 'today' | 'instrument' | 'review' | 'data' | 'knowledge' | 'tools' | 'settings' | 'plan' | 'discuss'
export const workbenchZones: Zone[] = ['today', 'instrument', 'review']
export const zones: Zone[] = [...workbenchZones, 'data', 'knowledge', 'tools', 'settings', 'plan', 'discuss']

// Zones whose pages have a path of their own below the first segment: #review/cards/12, #knowledge/mine/3@2.
const nestedZones: Zone[] = ['review', 'knowledge']

export function parseHash(hash: string): { zone: Zone; sub: string | undefined } {
  const [rawZone, ...rest] = hash.replace(/^#/, '').split('?')[0].split('/')
  const known = zones.includes(rawZone as Zone)
  const rawSub = nestedZones.includes(rawZone as Zone) ? rest.join('/') : rest[0]
  // Legacy zones (technicals/strategy/trade) land on today with no sub; so do #plan and #discuss without an id.
  if (!known || ((rawZone === 'plan' || rawZone === 'discuss') && !rawSub)) return { zone: 'today', sub: undefined }
  return { zone: rawZone as Zone, sub: rawSub || undefined }
}
