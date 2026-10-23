export type Zone = 'today' | 'instrument' | 'review' | 'tools' | 'data' | 'strategy' | 'trade' | 'settings' | 'technicals'
export const workbenchZones: Zone[] = ['today', 'instrument', 'review']
export const legacyZones: Zone[] = ['tools', 'data', 'strategy', 'trade', 'settings', 'technicals']
export const zones: Zone[] = [...workbenchZones, ...legacyZones]

export const isLegacyZone = (zone: string) => legacyZones.includes(zone as Zone)

export function parseHash(hash: string): { zone: Zone; sub: string | undefined } {
  const [rawZone, rawSub] = hash.replace(/^#/, '').split('?')[0].split('/')
  const zone = zones.includes(rawZone as Zone) ? (rawZone as Zone) : 'today'
  return { zone, sub: rawSub || undefined }
}
