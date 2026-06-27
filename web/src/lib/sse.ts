import { readable } from 'svelte/store'

export interface SseEvent {
  run_id: string
  status: string
  kind?: string
}

export function createEventStream(path = '/api/events') {
  return readable<SseEvent | null>(null, (set) => {
    let es: EventSource
    let timer: ReturnType<typeof setTimeout>

    function connect() {
      es = new EventSource(path)
      es.addEventListener('message', (e: MessageEvent) => {
        try { set(JSON.parse(e.data) as SseEvent) } catch {}
      })
      es.onerror = () => {
        es.close()
        timer = setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      clearTimeout(timer)
      es?.close()
    }
  })
}
