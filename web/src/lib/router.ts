export type Zone = 'today' | 'instrument' | 'review' | 'data' | 'knowledge' | 'tools' | 'settings' | 'plan'
export const workbenchZones: Zone[] = ['today', 'instrument', 'review']
export const zones: Zone[] = [...workbenchZones, 'data', 'knowledge', 'tools', 'settings', 'plan']

export function parseHash(hash: string): { zone: Zone; sub: string | undefined } {
  const [rawZone, rawSub] = hash.replace(/^#/, '').split('?')[0].split('/')
  const known = zones.includes(rawZone as Zone)
  // Legacy zones (technicals/strategy/trade) land on today with no sub; so does #plan without an id.
  if (!known || (rawZone === 'plan' && !rawSub)) return { zone: 'today', sub: undefined }
  return { zone: rawZone as Zone, sub: rawSub || undefined }
}
