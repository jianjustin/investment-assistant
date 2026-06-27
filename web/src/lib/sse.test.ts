import { describe, it, expect, vi, afterEach } from 'vitest'
import { get } from 'svelte/store'
import { createEventStream } from './sse'

afterEach(() => vi.restoreAllMocks())

describe('SSE store', () => {
  it('delivers parsed message events to subscribers', async () => {
    const handlers: Record<string, ((e: MessageEvent) => void)> = {}
    class FakeEventSource {
      onerror: (() => void) | null = null
      addEventListener(type: string, fn: (e: MessageEvent) => void) { handlers[type] = fn }
      close() {}
    }
    vi.stubGlobal('EventSource', FakeEventSource)

    const stream = createEventStream('/api/events')
    const received: unknown[] = []
    const unsub = stream.subscribe((v) => { if (v !== null) received.push(v) })

    handlers['message']?.({ data: JSON.stringify({ run_id: 'x', status: 'done' }) } as MessageEvent)

    expect(received).toEqual([{ run_id: 'x', status: 'done' }])
    unsub()
  })
})
