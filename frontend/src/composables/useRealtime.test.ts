import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useRealtime, type SocketLike } from './useRealtime'
import type { ConnectionState } from '../stores/realtime'

class FakeSocket implements SocketLike {
  readyState = 1
  onopen: WebSocket['onopen'] = null
  onclose: WebSocket['onclose'] = null
  onerror: WebSocket['onerror'] = null
  onmessage: WebSocket['onmessage'] = null
  sent: unknown[] = []
  close = vi.fn(() => {
    this.readyState = 3
  })
  send(value: string) {
    this.sent.push(JSON.parse(value))
  }
  frame(event: string, data: unknown = {}) {
    this.onmessage?.call(
      this as unknown as WebSocket,
      new MessageEvent('message', { data: JSON.stringify({ event, data }) }),
    )
  }
  disconnect(code = 1006) {
    this.onclose?.call(this as unknown as WebSocket, new CloseEvent('close', { code }))
  }
}
function setup() {
  const sockets: FakeSocket[] = [],
    states: ConnectionState[] = []
  const onReady = vi.fn(),
    onFrame = vi.fn(),
    onForceLogout = vi.fn()
  const factory = vi.fn(() => {
    const socket = new FakeSocket()
    sockets.push(socket)
    return socket
  })
  const realtime = useRealtime({
    url: 'ws://localhost:8000/api/v1/ws',
    token: 'test-only',
    activeKey: () => 'CW2154654-RDU-2609',
    onState: (s) => states.push(s),
    onFrame,
    onReady,
    onForceLogout,
    socketFactory: factory,
  })
  realtime.start()
  return {
    ...realtime,
    sockets,
    states,
    onReady,
    onFrame,
    onForceLogout,
    factory,
  }
}
beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())
it('requires authenticated snapshot, answers ping, reacquires and renews the active lease', async () => {
  const rt = setup(),
    socket = rt.sockets[0]!
  expect(rt.states.at(-1)).toBe('connecting')
  expect(
    rt.send({
      event: 'lock.release',
      data: { booking_key: 'CW2154654-RDU-2609' },
    }),
  ).toBe(false)
  socket.frame('ping')
  expect(socket.sent).toContainEqual({ event: 'pong', data: {} })
  socket.frame('lock.snapshot', { locks: [] })
  expect(rt.onReady).toHaveBeenCalledWith(false)
  expect(rt.states.at(-1)).toBe('connected')
  expect(socket.sent).toContainEqual({
    event: 'lock.acquire',
    data: { booking_key: 'CW2154654-RDU-2609' },
  })
  await vi.advanceTimersByTimeAsync(30000)
  expect(socket.sent).toContainEqual({
    event: 'lock.heartbeat',
    data: { booking_key: 'CW2154654-RDU-2609' },
  })
  rt.stop()
  expect(vi.getTimerCount()).toBe(0)
})
it('reconnects after backend restart and signals a view refresh only after snapshot', async () => {
  const rt = setup()
  rt.sockets[0]!.frame('lock.snapshot', { locks: [] })
  rt.sockets[0]!.disconnect(1001)
  expect(rt.states.at(-1)).toBe('reconnecting')
  await vi.advanceTimersByTimeAsync(999)
  expect(rt.sockets).toHaveLength(1)
  await vi.advanceTimersByTimeAsync(1)
  expect(rt.sockets).toHaveLength(2)
  expect(rt.onReady).toHaveBeenCalledTimes(1)
  rt.sockets[1]!.frame('lock.snapshot', { locks: [] })
  expect(rt.onReady).toHaveBeenLastCalledWith(true)
  rt.stop()
})
it('backs off 1, 2, 5, 15 seconds and caps further retries', async () => {
  const rt = setup()
  for (const delay of [1000, 2000, 5000, 15000, 15000]) {
    rt.sockets.at(-1)!.disconnect()
    const count = rt.sockets.length
    await vi.advanceTimersByTimeAsync(delay - 1)
    expect(rt.sockets).toHaveLength(count)
    await vi.advanceTimersByTimeAsync(1)
    expect(rt.sockets).toHaveLength(count + 1)
  }
  rt.stop()
})
it('bounds the handshake, ignores old socket events and malformed frames', async () => {
  const rt = setup(),
    old = rt.sockets[0]!,
    stale = old.onmessage
  old.frame('lock.snapshot', { locks: 'invalid' })
  expect(rt.onReady).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(9000)
  expect(rt.sockets).toHaveLength(2)
  stale?.call(
    old as unknown as WebSocket,
    new MessageEvent('message', {
      data: JSON.stringify({
        event: 'session.force_logout',
        data: { reason: 'new_login', message: 'Bye' },
      }),
    }),
  )
  expect(rt.onForceLogout).not.toHaveBeenCalled()
  rt.stop()
})
it('force logout stops timers and cannot reconnect', async () => {
  const rt = setup()
  rt.sockets[0]!.frame('session.force_logout', {
    reason: 'new_login',
    message: 'Bye',
  })
  expect(rt.onForceLogout).toHaveBeenCalledWith('new_login')
  await vi.advanceTimersByTimeAsync(60000)
  expect(rt.sockets).toHaveLength(1)
})
it('same-session duplicate tab stops reconnecting without clearing the login', async () => {
  const rt = setup()
  rt.sockets[0]!.disconnect(4409)
  expect(rt.states.at(-1)).toBe('superseded')
  expect(rt.onForceLogout).not.toHaveBeenCalled()
  rt.resume()
  await vi.advanceTimersByTimeAsync(60000)
  expect(rt.sockets).toHaveLength(1)
})
