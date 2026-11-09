<script setup lang="ts">
import { folderKey } from '../utils/folderKey'
import { computed, ref, inject, watch, nextTick } from 'vue'
import { ElDialog } from 'element-plus'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useUiStore } from '../stores/ui'
import { useAuthStore } from '../stores/auth'
import { useTasksStore } from '../stores/tasks'
import { useRealtimeStore } from '../stores/realtime'
import { useCollaborationStore } from '../stores/collaboration'
import { useRecentBookingsStore } from '../stores/recentBookings'
import { useFoldersStore } from '../stores/folders'
import { shortcutRegistryKey } from '../composables/useBookingShortcuts'
import { useRequest } from '../composables/useRequest'
import { api } from '../api/client'
import type { PerformanceReport } from '../types/api.generated'
import { downloadDaily, saveDownload } from '../utils/download'
import { zonedToday } from '../utils/summaryFilters'
import { parseBookingKey, formatBookingKey } from '../utils/bookingKey'
import { commandNames, fuzzyScore } from '../utils/palette'
import { timeouts } from '../config/timeouts'
import RequestStatus from './RequestStatus.vue'
const { t } = useI18n(),
  ui = useUiStore(),
  auth = useAuthStore(),
  tasks = useTasksStore(),
  live = useRealtimeStore(),
  collab = useCollaborationStore(),
  recent = useRecentBookingsStore(),
  folders = useFoldersStore(),
  router = useRouter()
const registry = inject(shortcutRegistryKey),
  query = ref(''),
  active = ref(0),
  input = ref<HTMLInputElement | null>(null)
const exportDate = ref('')
const exporting = useRequest(
  async (ctx) => {
    const report = (
      await api.get<PerformanceReport>('/reports/performance', {
        params: { period: 'day' },
        signal: ctx.signal,
        timeout: ctx.timeoutMs,
      })
    ).data
    exportDate.value = zonedToday(report.timezone)
    return downloadDaily(ctx, { date: exportDate.value, format: 'xlsx' })
  },
  { timeoutMs: timeouts.export },
)
type Command = {
  id: string
  label: string
  action: () => unknown
  disabled?: boolean
}
function open(key: string) {
  recent.remember(key)
  tasks.openBooking(key)
}
const commands = computed<Command[]>(() => {
  const key = live.activeBookingKey,
    commands: Command[] = []
  const parsed = parseBookingKey(query.value)
  if (parsed)
    commands.push({
      id: 'open-key',
      label: t('collabUi.openKey', {
        key: formatBookingKey('key' in parsed ? parsed.key : parsed.normalized),
      }),
      action: () => {
        if ('key' in parsed) open(parsed.key)
        else {
          tasks.openBooking(parsed.normalized)
        }
      },
    })
  for (const name of commandNames(auth.user?.role ?? 'agent'))
    commands.push({
      id: name,
      label: t(`collabUi.command_${name}`),

      action: async () => {
        if (name === 'theme') ui.toggleTheme()
        else if (name === 'logout') {
          await auth.logout()
          await router.replace({ name: 'login' })
        } else if (name === 'notes') {
          await router.push({ name: 'note-search' })
        } else if (name === 'export') {
          const file = await exporting.run()
          if (file) saveDownload(file, `daily-record-${exportDate.value}.xlsx`)
        } else await router.push({ name })
      },
    })
  if (key) {
    commands.push(
      {
        id: 'task',
        label: t('collabUi.command_task'),
        action: () => {
          const fn = registry?.current.value?.task
          if (fn) fn()
          else tasks.openDialog(key)
        },
      },
      {
        id: 'watch',
        label: t(collab.watched[key] ? 'collabUi.unwatch' : 'collabUi.watch'),
        action: () => collab.toggle(key),
      },
    )
  }
  for (const key of recent.items)
    commands.push({
      id: `recent:${key}`,
      label: `${t('collabUi.recent')} · ${formatBookingKey(key)}`,
      action: () => open(key),
    })
  for (const folder of folders.recent)
    commands.push({
      id: `folder:${folderKey(folder)}`,
      label: `${t('collabUi.recentFolders')} · ${folder.cw_number} — ${folder.supplier_name}`,
      action: () =>
        router.push({
          name: 'summary-folder',
          params: { cw: folderKey(folder) },
        }),
    })
  return commands
    .map((value, i) => ({
      value,
      score: value.id === 'open-key' ? 10000 : fuzzyScore(query.value, value.label),
      i,
    }))
    .filter((c) => c.score >= 0)
    .sort((a, b) => b.score - a.score || a.i - b.i)
    .slice(0, 40)
    .map((c) => c.value)
})
watch(query, () => (active.value = 0))
watch(
  () => ui.paletteOpen,
  async (value) => {
    if (value) {
      query.value = ''
      active.value = 0
      await nextTick()
      input.value?.focus()
    }
  },
)
async function choose(command?: Command) {
  if (!command || command.disabled || exporting.pending.value) return
  if (command.id === 'export') {
    await command.action()
    if (exporting.state.value === 'success') ui.paletteOpen = false
  } else {
    ui.paletteOpen = false
    await command.action()
  }
}
function keydown(e: KeyboardEvent) {
  if (['ArrowDown', 'ArrowUp', 'Enter'].includes(e.key)) {
    e.preventDefault()
    e.stopPropagation()
    if (e.key === 'Enter') void choose(commands.value[active.value])
    else {
      active.value = Math.max(
        0,
        Math.min(commands.value.length - 1, active.value + (e.key === 'ArrowDown' ? 1 : -1)),
      )
      document
        .getElementById(`palette-option-${active.value}`)
        ?.scrollIntoView({ block: 'nearest' })
    }
  }
}
</script>
<template>
  <ElDialog
    v-model="ui.paletteOpen"
    :title="t('collabUi.palette')"
    width="650px"
    class="command-palette"
    @opened="input?.focus()"
    ><label class="sr-only" for="palette-query">{{ t('collabUi.paletteSearch') }}</label
    ><input
      id="palette-query"
      ref="input"
      v-model="query"
      autocomplete="off"
      role="combobox"
      aria-autocomplete="list"
      aria-controls="palette-results"
      :aria-expanded="true"
      :aria-activedescendant="commands.length ? `palette-option-${active}` : undefined"
      :placeholder="t('collabUi.palettePlaceholder')"
      @keydown="keydown"
    /><RequestStatus :state="exporting.state.value" :error="exporting.error.value" />
    <ul id="palette-results" role="listbox">
      <li
        v-for="(command, i) in commands"
        :id="`palette-option-${i}`"
        :key="command.id"
        role="option"
        :aria-selected="active === i"
        :aria-disabled="command.disabled"
        @mouseenter="active = i"
      >
        <button type="button" :disabled="command.disabled" tabindex="-1" @click="choose(command)">
          {{ command.label }}
        </button>
      </li>
    </ul>
    <p v-if="!commands.length" class="muted">{{ t('collabUi.noCommands') }}</p>
    <small>{{ t('collabUi.paletteHint') }}</small></ElDialog
  >
</template>
