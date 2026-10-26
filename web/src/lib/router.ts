export type Zone = 'today' | 'instrument' | 'review' | 'data' | 'tools' | 'settings'
export const workbenchZones: Zone[] = ['today', 'instrument', 'review']
export const zones: Zone[] = [...workbenchZones, 'data', 'tools', 'settings']

export function parseHash(hash: string): { zone: Zone; sub: string | undefined } {
  const [rawZone, rawSub] = hash.replace(/^#/, '').split('?')[0].split('/')
  const known = zones.includes(rawZone as Zone)
  // Legacy zones (technicals/strategy/trade) land on today with no sub.
  return { zone: known ? (rawZone as Zone) : 'today', sub: known ? (rawSub || undefined) : undefined }
}
