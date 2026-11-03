import { afterEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import { nextTick } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useTasksStore } from '../stores/tasks'
import { user, task } from '../test/bookingFixtures'
import { installTaskAlerts } from './useTaskAlerts'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it('plays optional sound after interaction and uses only previously granted notifications', async () => {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().user = {
    ...user,
    settings: { task_sound: true, web_notifications: true },
  }
  const start = vi.fn(),
    permission = vi.fn(),
    displayed = vi.fn()
  vi.stubGlobal(
    'AudioContext',
    class {
      state = 'running'
      currentTime = 0
      destination = {}
      resume = vi.fn().mockResolvedValue(undefined)
      close = vi.fn().mockResolvedValue(undefined)
      createOscillator() {
        return {
          frequency: { value: 0 },
          connect: vi.fn(),
          start,
          stop: vi.fn(),
        }
      }
      createGain() {
        return {
          gain: {
            setValueAtTime: vi.fn(),
            exponentialRampToValueAtTime: vi.fn(),
          },
          connect: vi.fn(),
        }
      }
    },
  )
  class Notice {
    static permission = 'default'
    static requestPermission = permission
    constructor(...args: unknown[]) {
      displayed(...args)
    }
  }
  vi.stubGlobal('Notification', Notice)
  const router = createRouter({ history: createMemoryHistory(), routes: [] })
  const alerts = installTaskAlerts(pinia, router)
  try {
    alerts.alert(task())
    expect(start).not.toHaveBeenCalled()
    expect(displayed).not.toHaveBeenCalled()
    window.dispatchEvent(new Event('pointerdown'))
    alerts.alert(task())
    expect(start).toHaveBeenCalledTimes(1)
    Notice.permission = 'granted'
    alerts.alert(task())
    expect(displayed).toHaveBeenCalledTimes(1)
    expect(permission).not.toHaveBeenCalled()
    useTasksStore().setDueTasks([task()])
    await nextTick()
    expect(document.title).toContain('(1) Tasks due')
    useAuthStore().user!.settings = {
      task_sound: false,
      web_notifications: false,
    }
    alerts.alert(task())
    expect(start).toHaveBeenCalledTimes(2)
    expect(displayed).toHaveBeenCalledTimes(1)
  } finally {
    alerts.stop()
  }
})
