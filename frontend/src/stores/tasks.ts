import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '../api/client'
import { useRequest, type RequestContext } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { useAuthStore } from './auth'
import { useNotificationsStore } from './notifications'
import type {
  BookingUpdatedData,
  DueTasks,
  Page,
  Task,
  TaskCreate,
  TaskDueData,
  TaskEdit,
} from '../types/api.generated'
import type { RequestFailure } from '../api/errors'
import { reminderPreferences, reminderParts, reminderInstant } from '../utils/taskDates'

export const useTasksStore = defineStore('tasks', () => {
  const records = ref<Record<number, Task>>({}),
    dueIds = ref<number[]>([]),
    dueCount = ref(0)
  const listIds = ref<number[]>([]),
    listTotal = ref(0),
    page = ref(1),
    view = ref<'pending' | 'done'>('pending')
  const pendingCounts = ref<Record<string, number>>({}),
    bookIds = ref<Record<string, number[]>>({})
  const reminderIds = ref<number[]>([]),
    summaryOpen = ref(false),
    dialog = ref<{
      key: string
      taskId?: number
      mode: 'create' | 'edit' | 'snooze'
      nonce: number
      presetDays?: number
    } | null>(null)
  const noteSuggestion = ref<string | null>(null),
    rightTab = ref<'bookings' | 'tasks' | 'assignments' | 'watching'>('bookings')
  const openBookingRequest = ref<{
    key: string
    note: boolean
    seq: number
  } | null>(null)
  const actionError = ref<RequestFailure | null>(null),
    busyIds = ref<number[]>([])
  const dirty = ref(false)
  const items = computed(() =>
    listIds.value.map((id) => records.value[id]).filter((t): t is Task => !!t),
  )
  const dueTasks = computed(() =>
    dueIds.value.map((id) => records.value[id]).filter((t): t is Task => !!t),
  )
  const reminderTasks = computed(() =>
    reminderIds.value
      .map((id) => records.value[id])
      .filter((t): t is Task => !!t && t.status === 'pending'),
  )
  const preferences = computed(() => reminderPreferences(useAuthStore().user?.settings))
  let epoch = 0,
    revision = 0,
    nonce = 0,
    sequence = 0,
    listActive = false,
    interruptedList = false,
    summaryWanted = false
  let dueTimer: ReturnType<typeof setTimeout> | undefined
  const deferredDue = new Map<number, TaskDueData>(),
    suppressed = new Set<string>()
  const seen = new Set<string>(),
    attempts = new Map<string, string>(),
    active = new Set<() => void>()
  function merge(task: Task) {
    const old = records.value[task.id]
    if (old && old.booking.updated_at > task.booking.updated_at)
      task = {
        ...task,
        booking: old.booking,
        booking_changed_since: old.booking.updated_at > task.created_at,
      }
    records.value[task.id] = {
      ...task,
      booking_changed_since: task.booking.updated_at > task.created_at,
    }
  }
  const dueRequest = useRequest(
    async ({ signal, timeoutMs }) =>
      (await api.get<DueTasks>('/tasks/due', { signal, timeout: timeoutMs })).data,
    { timeoutMs: timeouts.task, retry: true },
  )
  const listRequest = useRequest(
    async ({ signal, timeoutMs }, selected: 'pending' | 'done', selectedPage: number) =>
      (
        await api.get<Page<Task>>('/tasks', {
          params: { view: selected, page: selectedPage, size: 10 },
          signal,
          timeout: timeoutMs,
        })
      ).data,
    { timeoutMs: timeouts.task, retry: true },
  )
  async function refreshDue(showSummary = false) {
    summaryWanted ||= showSummary
    if (busyIds.value.length) return
    const generation = epoch,
      stamp = revision
    const result = await dueRequest.run()
    if (!result || generation !== epoch || stamp !== revision) return
    result.items.forEach(merge)
    dueIds.value = result.items.map((t) => t.id)
    dueCount.value = result.total
    reminderIds.value = reminderIds.value.filter((id) =>
      result.items.some((t) => t.id === id && t.is_due),
    )
    if (summaryWanted && result.total) summaryOpen.value = true
    summaryWanted = false
    dirty.value = false
  }
  async function refreshList(selected = view.value, selectedPage = page.value) {
    view.value = selected
    page.value = selectedPage
    if (busyIds.value.length) return
    interruptedList = false
    const generation = epoch,
      stamp = revision
    const result = await listRequest.run(selected, selectedPage)
    if (!result || generation !== epoch || stamp !== revision) return
    result.items.forEach(merge)
    listIds.value = result.items.map((t) => t.id)
    listTotal.value = result.total
    if (!result.items.length && selectedPage > 1 && result.total <= (selectedPage - 1) * 10)
      await refreshList(selected, Math.max(1, Math.ceil(result.total / 10)))
  }
  async function bookTasks(ctx: RequestContext, key: string) {
    const generation = epoch,
      stamp = revision
    const result = (
      await api.get<Task[]>(`/bookings/${key}/tasks`, {
        signal: ctx.signal,
        timeout: ctx.timeoutMs,
      })
    ).data
    if (
      generation === epoch &&
      stamp === revision &&
      !ctx.signal.aborted &&
      !busyIds.value.some((id) => records.value[id]?.booking_key === key)
    ) {
      result.forEach(merge)
      bookIds.value[key] = result.map((t) => t.id)
      pendingCounts.value[key] = result.length
    }
    return result
  }
  async function create(
    ctx: RequestContext,
    key: string,
    payload: Omit<TaskCreate, 'client_request_id'>,
  ) {
    const signature = JSON.stringify([key, payload]),
      generation = epoch
    let id = attempts.get(signature)
    if (!id) {
      id = crypto.randomUUID()
      attempts.set(signature, id)
    }
    const result = (
      await api.post<Task>(
        `/bookings/${key}/tasks`,
        { ...payload, client_request_id: id },
        { signal: ctx.signal, timeout: ctx.timeoutMs },
      )
    ).data
    if (generation !== epoch || ctx.signal.aborted) return result
    attempts.delete(signature)
    revision++
    dueRequest.cancel()
    listRequest.cancel()
    if (!records.value[result.id]) merge(result)
    if (
      records.value[result.id]?.status === 'pending' &&
      !(bookIds.value[key] ?? []).includes(result.id)
    ) {
      bookIds.value[key] = [...(bookIds.value[key] ?? []), result.id]
      if (pendingCounts.value[key] !== undefined) pendingCounts.value[key]++
    }
    if (listActive) void refreshList()
    return result
  }
  function openDialog(
    key: string,
    task?: Task,
    mode: 'create' | 'edit' | 'snooze' = 'create',
    presetDays?: number,
  ) {
    if (task) merge(task)
    dialog.value = { key, taskId: task?.id, mode, nonce: ++nonce, presetDays }
  }
  function openBooking(key: string, note = false) {
    openBookingRequest.value = { key, note, seq: ++sequence }
    summaryOpen.value = false
  }
  function dismissReminder(id: number) {
    reminderIds.value = reminderIds.value.filter((value) => value !== id)
  }
  async function mutate(
    task: Task,
    operation: 'complete' | 'cancel' | 'snooze' | 'edit',
    body?: TaskEdit,
  ): Promise<boolean> {
    if (busyIds.value.includes(task.id)) return false
    const generation = epoch,
      before = JSON.parse(JSON.stringify(task)) as Task,
      hadDue = task.status === 'pending' && (task.is_due || dueIds.value.includes(task.id)),
      hadReminder = reminderIds.value.includes(task.id)
    const wasListed = listIds.value.includes(task.id),
      countKnown = pendingCounts.value[task.booking_key] !== undefined
    busyIds.value.push(task.id)
    actionError.value = null
    revision++
    dueRequest.cancel()
    listRequest.cancel()
    const terminal = operation === 'complete' || operation === 'cancel'
    const changed: Task = {
      ...task,
      ...(terminal
        ? {
            status: operation === 'complete' ? ('done' as const) : ('cancelled' as const),
            completed_at: operation === 'complete' ? new Date().toISOString() : null,
          }
        : {}),
      is_due: terminal ? false : task.is_due,
      is_overdue: terminal ? false : task.is_overdue,
    }
    if (body?.remind_date || body?.remind_time) {
      const oldTime = reminderParts(task.remind_at, preferences.value.timezone),
        instant = reminderInstant(
          body.remind_date ?? oldTime.date,
          body.remind_time ?? oldTime.time,
          preferences.value.timezone,
        )
      if (instant) {
        changed.remind_at = instant
        changed.is_due = Date.parse(instant) <= Date.now()
        changed.is_overdue = Date.parse(instant) < Date.now()
        if (operation === 'snooze' && instant !== task.remind_at) changed.snooze_count++
      }
    }
    if (body?.message !== undefined && body.message !== null) changed.message = body.message
    const oldStamp = `${task.id}:${task.remind_at}`,
      wasSuppressed = suppressed.has(oldStamp),
      suppressOld = terminal || changed.remind_at !== task.remind_at
    if (suppressOld) suppressed.add(oldStamp)
    while (suppressed.size > 2000) suppressed.delete(suppressed.values().next().value!)
    const removedDue = hadDue && !changed.is_due
    merge(changed)
    if (!changed.is_due) dismissReminder(task.id)
    if (removedDue) {
      dueIds.value = dueIds.value.filter((id) => id !== task.id)
      dueCount.value = Math.max(0, dueCount.value - 1)
    }
    if (terminal && countKnown)
      pendingCounts.value[task.booking_key] = Math.max(
        0,
        pendingCounts.value[task.booking_key]! - 1,
      )
    if (terminal && wasListed && view.value === 'pending') {
      listIds.value = listIds.value.filter((id) => id !== task.id)
      listTotal.value = Math.max(0, listTotal.value - 1)
    }
    const request = useRequest(
      async ({ signal, timeoutMs }) => {
        const config = { signal, timeout: timeoutMs }
        if (operation === 'cancel')
          return (await api.delete<Task>(`/tasks/${task.id}`, config)).data
        if (operation === 'edit')
          return (await api.patch<Task>(`/tasks/${task.id}`, body, config)).data
        return (await api.post<Task>(`/tasks/${task.id}/${operation}`, body, config)).data
      },
      { timeoutMs: timeouts.task },
    )
    active.add(request.cancel)
    try {
      const result = await request.run()
      if (generation !== epoch) return false
      revision++
      if (!result) {
        if (suppressOld && !wasSuppressed) suppressed.delete(oldStamp)
        merge({
          ...before,
          booking: records.value[task.id]?.booking ?? before.booking,
        })
        if (removedDue && !dueIds.value.includes(task.id)) {
          dueIds.value.push(task.id)
          dueCount.value++
        }
        if (hadReminder && !reminderIds.value.includes(task.id)) reminderIds.value.push(task.id)
        if (terminal && countKnown) pendingCounts.value[task.booking_key]++
        if (terminal && wasListed && view.value === 'pending' && !listIds.value.includes(task.id)) {
          listIds.value.push(task.id)
          listTotal.value++
        }
        actionError.value = request.error.value
        return false
      }
      if (result.status === 'pending') {
        suppressed.delete(`${result.id}:${result.remind_at}`)
        const pending = deferredDue.get(task.id)
        if (pending?.task.remind_at !== result.remind_at) deferredDue.delete(task.id)
      } else deferredDue.delete(task.id)
      merge(result)
      if (result.status !== 'pending')
        bookIds.value[task.booking_key] = (bookIds.value[task.booking_key] ?? []).filter(
          (id) => id !== task.id,
        )
      if (operation === 'complete') noteSuggestion.value = task.booking_key
      void useNotificationsStore().refresh()
      return true
    } finally {
      active.delete(request.cancel)
      if (generation === epoch) {
        busyIds.value = busyIds.value.filter((id) => id !== task.id)
        const pending = deferredDue.get(task.id)
        deferredDue.delete(task.id)
        if (pending) incoming(pending)
        void refreshDue(false)
        if (listActive) void refreshList()
      }
    }
  }
  function incoming(data: TaskDueData): boolean {
    if (busyIds.value.includes(data.task.id)) {
      deferredDue.set(data.task.id, data)
      return false
    }
    const task = data.task,
      old = records.value[task.id],
      stamp = `${task.id}:${task.remind_at}`
    if (seen.has(stamp) || (old && old.status !== 'pending') || suppressed.has(stamp)) return false
    seen.add(stamp)
    while (seen.size > 2000) seen.delete(seen.values().next().value!)
    revision++
    dueRequest.cancel()
    interruptedList ||= listActive && listRequest.pending.value
    listRequest.cancel()
    merge(task)
    if (!dueIds.value.includes(task.id)) {
      dueIds.value.push(task.id)
      dueCount.value++
    }
    if (!reminderIds.value.includes(task.id)) reminderIds.value.push(task.id)
    if (summaryWanted) {
      summaryOpen.value = true
      summaryWanted = false
    }
    clearTimeout(dueTimer)
    dueTimer = setTimeout(() => {
      void refreshDue(false)
      if (interruptedList && listActive) void refreshList()
    }, timeouts.notificationDebounce)
    return true
  }
  function bookingUpdated(event: BookingUpdatedData) {
    for (const task of Object.values(records.value))
      if (task.booking_key === event.booking_key && task.booking.updated_at < event.updated_at) {
        task.booking = {
          last_status: event.status_code
            ? {
                code: event.status_code,
                label: useBookingsStatus(event.status_code),
              }
            : null,
          last_agent:
            event.last_agent_id && event.last_agent_name
              ? { id: event.last_agent_id, full_name: event.last_agent_name }
              : null,
          is_done: event.is_done,
          updated_at: event.updated_at,
        }
        task.booking_changed_since = event.updated_at > task.created_at
      }
  }
  function seedCount(key: string, count?: number) {
    if (count !== undefined && pendingCounts.value[key] === undefined)
      pendingCounts.value[key] = count
  }
  function invalidate() {
    dirty.value = true
  }
  function setDueTasks(values: Task[]) {
    values.forEach(merge)
    dueIds.value = values.map((t) => t.id)
    dueCount.value = values.length
    dirty.value = false
  }
  function reset() {
    epoch++
    revision++
    dueRequest.cancel()
    listRequest.cancel()
    active.forEach((cancel) => cancel())
    active.clear()
    clearTimeout(dueTimer)
    records.value = {}
    dueIds.value = []
    dueCount.value = 0
    listIds.value = []
    listTotal.value = 0
    page.value = 1
    view.value = 'pending'
    listActive = false
    interruptedList = false
    pendingCounts.value = {}
    bookIds.value = {}
    reminderIds.value = []
    summaryOpen.value = false
    dialog.value = null
    noteSuggestion.value = null
    openBookingRequest.value = null
    busyIds.value = []
    actionError.value = null
    rightTab.value = 'bookings'
    summaryWanted = false
    seen.clear()
    attempts.clear()
    deferredDue.clear()
    suppressed.clear()
    dirty.value = false
  }
  function setListActive(value: boolean) {
    listActive = value
  }
  return {
    records,
    dueTasks,
    dueCount,
    items,
    listTotal,
    page,
    view,
    pendingCounts,
    bookIds,
    reminderTasks,
    summaryOpen,
    dialog,
    noteSuggestion,
    rightTab,
    openBookingRequest,
    actionError,
    busyIds,
    dirty,
    preferences,
    dueRequest,
    listRequest,
    refreshDue,
    refreshList,
    bookTasks,
    create,
    openDialog,
    openBooking,
    dismissReminder,
    mutate,
    incoming,
    bookingUpdated,
    seedCount,
    invalidate,
    setDueTasks,
    reset,
    setListActive,
  }
})
import { useBookingsStore } from './bookings'
function useBookingsStatus(code: string) {
  return useBookingsStore().statuses.find((s) => s.code === code)?.label ?? code
}
