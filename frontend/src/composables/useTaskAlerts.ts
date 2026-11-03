import { watch } from 'vue'
import type { Pinia } from 'pinia'
import type { Router } from 'vue-router'
import type { Task } from '../types/api.generated'
import { useTasksStore } from '../stores/tasks'
import { i18n } from '../i18n'
export function installTaskAlerts(pinia: Pinia, router: Router) {
  const tasks = useTasksStore(pinia)
  let audio: AudioContext | null = null,
    disposed = false
  function unlock() {
    if (disposed) return
    try {
      audio ??= new AudioContext()
      void audio.resume().catch(() => {})
    } catch {
      /* Unsupported browser: reminders remain visual. */
    }
  }
  window.addEventListener('pointerdown', unlock, { passive: true })
  window.addEventListener('keydown', unlock, { passive: true })
  function alert(task: Task) {
    if (tasks.preferences.task_sound && audio?.state === 'running')
      try {
        const tone = audio.createOscillator(),
          volume = audio.createGain()
        tone.frequency.value = 660
        volume.gain.setValueAtTime(0.035, audio.currentTime)
        volume.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + 0.18)
        tone.connect(volume)
        volume.connect(audio.destination)
        tone.start()
        tone.stop(audio.currentTime + 0.18)
      } catch {
        /* Visual reminder stays available. */
      }
    if (
      tasks.preferences.web_notifications &&
      typeof Notification !== 'undefined' &&
      Notification.permission === 'granted'
    )
      try {
        const notice = new Notification(i18n.global.t('taskUi.browserTitle'), {
          body: i18n.global.t('task_due_toast', { key: task.display_key }),
          tag: `task-${task.id}`,
          silent: true,
        })
        notice.onclick = () => {
          window.focus()
          tasks.openBooking(task.booking_key)
          notice.close()
        }
      } catch {
        /* OS notifications may be unavailable. */
      }
  }
  const updateTitle = () => {
    document.title =
      tasks.dueCount > 0
        ? i18n.global.t('taskUi.documentTitle', { count: tasks.dueCount })
        : `${i18n.global.t(router.currentRoute.value.meta.titleKey ?? 'app.name')} · ${i18n.global.t('app.name')}`
  }
  const stop = watch(() => [tasks.dueCount, router.currentRoute.value.fullPath], updateTitle, {
    immediate: true,
  })
  return {
    alert,
    stop() {
      disposed = true
      stop()
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
      void audio?.close().catch(() => {})
    },
  }
}
