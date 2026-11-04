import { useRealtime } from './useRealtime'
import { parseServerFrame } from '../api/realtime-protocol'
import { parseBookingKey } from '../utils/bookingKey'
import type { LockInfo, WebSocketClientFrame } from '../types/api.generated'
import type { ConnectionState } from '../stores/realtime'
type Options = Parameters<typeof useRealtime>[0]
/** One physical socket for a shared browser session; no bearer token in channel messages. */
export function useSharedRealtime(options: Options): ReturnType<typeof useRealtime> {
  let identity: string
  try {
    const raw = JSON.parse(
      atob(options.token.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/')),
    )
    if (!/^\d+$/.test(raw.sub) || !/^[0-9a-f-]{36}$/.test(raw.sid))
      throw new Error('Invalid identity')
    identity = `booking.realtime.${raw.sub}.${raw.sid}`
  } catch {
    return useRealtime(options)
  }
  if (typeof navigator.locks?.request !== 'function' || typeof BroadcastChannel === 'undefined')
    return useRealtime(options)
  let channel: BroadcastChannel | null = null,
    physical: ReturnType<typeof useRealtime> | null = null
  let controller: AbortController | null = null,
    release: (() => void) | null = null,
    leader = false,
    wanted = false,
    running = false,
    connected = false,
    wasReady = false
  let key = options.activeKey(),
    state: ConnectionState = 'disconnected'
  let health: Extract<Parameters<Options['onFrame']>[0], { event: 'system.health' }> | null =
    null
  const tabId = crypto.randomUUID()
  const locks = new Map<string, LockInfo>()
  const post = (value: Record<string, unknown>) =>
    channel?.postMessage({ ...value, from: tabId })
  function updateState(value: ConnectionState) {
    state = value
    connected = value === 'connected'
    options.onState(value)
    if (leader) post({ type: 'state', value })
  }
  function snapshot() {
    return { event: 'lock.snapshot' as const, data: { locks: [...locks.values()] } }
  }
  function incoming(frame: Parameters<Options['onFrame']>[0]) {
    if (frame.event === 'lock.snapshot') {
      locks.clear()
      for (const item of frame.data.locks) locks.set(item.booking_key, item)
    } else if (frame.event === 'lock.acquired' || frame.event === 'lock.denied')
      locks.set(frame.data.booking_key, {
        ...frame.data,
        expires_at: new Date(Date.now() + 150000).toISOString(),
      })
    else if (
      frame.event === 'lock.released' &&
      locks.get(frame.data.booking_key)?.user_id === frame.data.user_id
    )
      locks.delete(frame.data.booking_key)
    else if (frame.event === 'system.health') health = frame
    options.onFrame(frame)
  }
  function ready() {
    options.onReady(wasReady)
    wasReady = true
  }
  function validCommand(value: unknown): value is WebSocketClientFrame {
    if (!value || typeof value !== 'object') return false
    const frame = value as { event?: string; data?: { booking_key?: unknown } }
    if (
      !['lock.acquire', 'lock.release', 'lock.heartbeat'].includes(frame.event ?? '') ||
      typeof frame.data?.booking_key !== 'string'
    )
      return false
    const parsed = parseBookingKey(frame.data.booking_key)
    return !!parsed && 'key' in parsed && parsed.key === frame.data.booking_key
  }
  function command(frame: WebSocketClientFrame) {
    if ('booking_key' in frame.data) {
      if (frame.event === 'lock.acquire') key = frame.data.booking_key
      else if (frame.event === 'lock.release' && frame.data.booking_key === key) key = null
    }
    return physical?.send(frame) ?? false
  }
  function halt() {
    running = false
    connected = false
    physical?.stop()
    physical = null
    if (leader) post({ type: 'state', value: 'disconnected' })
    leader = false
    release?.()
    release = null
    controller?.abort()
    controller = null
    channel?.close()
    channel = null
  }
  function onHide() {
    halt()
  }
  function onShow() {
    if (wanted && !running) launch()
  }
  function launch() {
    if (running) return
    running = true
    options.onState('connecting')
    const current = new AbortController()
    controller = current
    channel = new BroadcastChannel(identity)
    channel.onmessage = ({ data }) => {
      if (!running || !data || typeof data !== 'object' || (data.to && data.to !== tabId))
        return
      if (data.type === 'hello' && leader) {
        post({ type: 'frame', value: snapshot(), to: data.from })
        if (health) post({ type: 'frame', value: health, to: data.from })
        post({ type: 'state', value: state, to: data.from })
        if (connected) post({ type: 'ready', to: data.from })
      } else if (data.type === 'command' && leader && validCommand(data.value))
        command(data.value)
      else if (!leader && data.type === 'frame') {
        const frame = parseServerFrame(data.value)
        if (frame) incoming(frame)
      } else if (
        !leader &&
        data.type === 'state' &&
        ['connecting', 'connected', 'disconnected', 'reconnecting', 'superseded'].includes(
          data.value,
        )
      ) {
        state = data.value
        connected = state === 'connected'
        options.onState(state)
      } else if (!leader && data.type === 'ready') {
        ready()
      } else if (!leader && data.type === 'logout' && typeof data.reason === 'string') {
        options.onForceLogout(data.reason)
      }
    }
    post({ type: 'hello' })
    void navigator.locks
      .request(identity, { signal: current.signal }, async () => {
        if (!running || current.signal.aborted) return
        leader = true
        physical = useRealtime({
          ...options,
          activeKey: () => key,
          onState: updateState,
          onFrame: (frame) => {
            incoming(frame)
            post({ type: 'frame', value: frame })
          },
          onReady: () => {
            ready()
            post({ type: 'ready' })
          },
          onForceLogout: (reason) => {
            post({ type: 'logout', reason })
            options.onForceLogout(reason)
          },
        })
        const held = new Promise<void>((resolve) => {
          release = resolve
        })
        physical.start()
        await held
      })
      .catch(() => {
        /* Abort releases only this tab's queued lock request. */
      })
  }
  function start() {
    halt()
    wanted = true
    wasReady = false
    key = options.activeKey()
    window.addEventListener('pagehide', onHide)
    window.addEventListener('pageshow', onShow)
    launch()
  }
  function stop() {
    wanted = false
    window.removeEventListener('pagehide', onHide)
    window.removeEventListener('pageshow', onShow)
    halt()
    options.onState('disconnected')
  }
  function send(frame: WebSocketClientFrame) {
    if (leader) return command(frame)
    post({ type: 'command', value: frame })
    return connected
  }
  function resume() {
    if (!wanted) return
    if (!running) launch()
    else if (leader) physical?.resume()
    else post({ type: 'hello' })
  }
  return { start, stop, send, resume }
}
