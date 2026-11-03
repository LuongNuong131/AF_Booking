import { getCurrentScope, onScopeDispose } from 'vue'
import { timeouts } from '../config/timeouts'
import { parseServerFrame } from '../api/realtime-protocol'
import type { WebSocketClientFrame, WebSocketServerFrame } from '../types/api.generated'
import type { ConnectionState } from '../stores/realtime'

export type SocketLike = Pick<
  WebSocket,
  'readyState' | 'send' | 'close' | 'onopen' | 'onclose' | 'onerror' | 'onmessage'
>
interface RealtimeOptions {
  url: string
  token: string
  activeKey: () => string | null
  onState: (state: ConnectionState) => void
  onFrame: (frame: WebSocketServerFrame) => void
  onReady: (reconnected: boolean) => void
  onForceLogout: (reason: string) => void
  socketFactory?: (url: string) => SocketLike
}

export function useRealtime(options: RealtimeOptions) {
  let socket: SocketLike | null = null
  let retryTimer: ReturnType<typeof setTimeout> | undefined
  let handshakeTimer: ReturnType<typeof setTimeout> | undefined
  let heartbeatTimer: ReturnType<typeof setInterval> | undefined
  let stopped = true
  let ready = false
  let generation = 0
  let attempt = 0
  let wasReady = false
  const factory = options.socketFactory ?? ((url: string) => new WebSocket(url))

  function clearTimers(): void {
    clearTimeout(retryTimer)
    clearTimeout(handshakeTimer)
    clearInterval(heartbeatTimer)
  }
  function retire(): void {
    ready = false
    clearTimeout(handshakeTimer)
    clearInterval(heartbeatTimer)
    if (socket) {
      socket.onopen = null
      socket.onmessage = null
      socket.onerror = null
      socket.onclose = null
      try {
        socket.close(1000)
      } catch {
        /* Socket may still be opening. */
      }
      socket = null
    }
  }
  function stop(): void {
    stopped = true
    generation++
    clearTimers()
    retire()
    options.onState('disconnected')
  }
  function send(frame: WebSocketClientFrame): boolean {
    if (!ready || socket?.readyState !== 1) return false
    try {
      socket.send(JSON.stringify(frame))
      return true
    } catch {
      return false
    }
  }
  function retry(): void {
    if (stopped) return
    options.onState('reconnecting')
    clearTimeout(retryTimer)
    const delay =
      timeouts.realtimeBackoff[Math.min(attempt++, timeouts.realtimeBackoff.length - 1)]!
    retryTimer = setTimeout(open, delay)
  }
  function open(): void {
    if (stopped) return
    retire()
    const ticket = ++generation
    options.onState(attempt ? 'reconnecting' : 'connecting')
    let current: SocketLike
    try {
      const url = new URL(options.url)
      url.searchParams.set('token', options.token)
      current = factory(url.toString())
      socket = current
    } catch {
      retry()
      return
    }
    handshakeTimer = setTimeout(() => {
      if (ticket === generation && !ready) {
        retire()
        retry()
      }
    }, timeouts.websocketConnect)
    current.onopen = () => {
      /* Authenticated readiness is lock.snapshot, not just open. */
    }
    current.onerror = () => {
      /* Do not log an event/URL containing the query token. */
    }
    current.onmessage = (message) => {
      if (stopped || ticket !== generation || typeof message.data !== 'string') return
      let value: unknown
      try {
        value = JSON.parse(message.data)
      } catch {
        return
      }
      const frame = parseServerFrame(value)
      if (!frame) return
      if (frame.event === 'session.force_logout') {
        stop()
        options.onForceLogout(frame.data.reason)
        return
      }
      if (frame.event === 'ping') {
        try {
          current.send(JSON.stringify({ event: 'pong', data: {} }))
        } catch {
          /* Close handler retries. */
        }
        return
      }
      if (frame.event === 'pong') return
      if (frame.event === 'lock.snapshot') {
        const reconnected = wasReady || attempt > 0
        ready = true
        wasReady = true
        attempt = 0
        clearTimeout(handshakeTimer)
        options.onFrame(frame)
        options.onState('connected')
        if (options.activeKey())
          send({ event: 'lock.acquire', data: { booking_key: options.activeKey()! } })
        clearInterval(heartbeatTimer)
        heartbeatTimer = setInterval(() => {
          const key = options.activeKey()
          if (key) send({ event: 'lock.heartbeat', data: { booking_key: key } })
        }, timeouts.lockHeartbeat)
        options.onReady(reconnected)
      } else if (ready) options.onFrame(frame)
    }
    current.onclose = (event) => {
      if (stopped || ticket !== generation) return
      retire()
      if (event.code === 4401) {
        stop()
        options.onForceLogout('session_revoked')
        return
      }
      if (event.code === 4409) {
        stopped = true
        clearTimers()
        options.onState('superseded')
        return
      }
      if ([4400, 1003, 1009].includes(event.code)) {
        stop()
        return
      }
      retry()
    }
  }
  function start(): void {
    stop()
    stopped = false
    attempt = 0
    wasReady = false
    open()
  }
  function resume(): void {
    if (!stopped && !ready) {
      clearTimeout(retryTimer)
      open()
    }
  }
  if (getCurrentScope()) onScopeDispose(stop)
  return { start, stop, send, resume }
}
