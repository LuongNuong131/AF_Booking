<script setup lang="ts">
import { computed, nextTick, onMounted, onScopeDispose, reactive, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import { ElDialog } from 'element-plus'
import 'element-plus/es/components/dialog/style/css'
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import TaskButton from './TaskButton.vue'
import TaskSuggestionBar from './TaskSuggestionBar.vue'
import { useBookingsStore } from '../stores/bookings'
import { useBookingWorkspace } from '../composables/useBookingWorkspace'
import { useSmartSearch } from '../composables/useSmartSearch'
import SmartSearchResults from './SmartSearchResults.vue'
import SupplierFolder from './SupplierFolder.vue'
import FolderCard from './FolderCard.vue'
import { useBookingShortcuts } from '../composables/useBookingShortcuts'
import { useRequest } from '../composables/useRequest'
import { api } from '../api/client'
import { parseBookingKey, formatBookingKey, build_key } from '../utils/bookingKey'
import { useFoldersStore } from '../stores/folders'
import { timeouts } from '../config/timeouts'
import type { StationOption } from '../types/api.generated'
import BookingSummaryCard from './BookingSummaryCard.vue'
import BookingTimeline from './BookingTimeline.vue'
import NoteForm from './NoteForm.vue'
import RequestStatus from './RequestStatus.vue'
import BaseIcon from './BaseIcon.vue'
const props = defineProps<{ initialKey?: string; detail?: boolean }>()
const emit = defineEmits<{ saved: [key: string]; opened: [key: string] }>()
const { t } = useI18n(),
  store = useBookingsStore(),
  tasks = useTasksStore()
const w = reactive(useBookingWorkspace())
const folders = useFoldersStore()
const nav = reactive(useSmartSearch(w, (key) => emit('opened', key)))
const inputRef = ref<HTMLInputElement | null>(null),
  formScope = ref<HTMLElement | null>(null)
const station = ref('')
const suggestion = ref<{
  key: string
  strong: boolean
  days: number | null
  nonce: number
} | null>(null)
let suggestionNonce = 0
let disposed = false
onScopeDispose(() => {
  disposed = true
})
const stationRequest = useRequest(
  async ({ signal, timeoutMs }, q: string) =>
    (
      await api.get<StationOption[]>('/stations', {
        params: { q },
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.search, retry: true },
)
const fetchStations = useDebounceFn(() => {
  if (!disposed) return stationRequest.run(station.value)
}, timeouts.searchDebounce)
watch(station, () => {
  stationRequest.cancel()
  void fetchStations()
})
const conflictData = computed(() =>
  w.conflictRequest.data?.booking_key === w.key ? w.conflictRequest.data : null,
)
async function open(value?: string) {
  return nav.openBooking(value ?? w.input)
}
async function lookup() {
  await nav.submit()
}
watch(
  () => w.lastSaved,
  (saved) => {
    if (!saved || saved.key !== w.key) return
    const status = store.statuses.find((s) => s.code === saved.status)
    suggestion.value = {
      key: saved.key,
      strong: status?.suggest_task ?? false,
      days: status?.default_task_days ?? null,
      nonce: ++suggestionNonce,
    }
    emit('saved', saved.key)
  },
)
async function save(allowDuplicate = false) {
  if (await w.save(allowDuplicate === true)) {
    await nextTick()
    inputRef.value?.focus()
  }
}

async function confirmDuplicate() {
  w.duplicate = false
  await save(true)
}
function clear() {
  if (props.detail) return
  nav.root()
  station.value = ''
  inputRef.value?.focus()
}
function stationInput(event: Event) {
  station.value = (event.target as HTMLInputElement).value
    .toUpperCase()
    .replace(/[^A-Z]/g, '')
    .slice(0, 3)
}
useBookingShortcuts({
  enabled: () => !w.conflict && !w.duplicate,
  input: () => inputRef.value,
  scope: () => formScope.value,
  lookup,
  save,
  task: () => {
    if (w.key && w.current?.exists && w.inputMatches && (props.detail || nav.level === 'booking'))
      tasks.openDialog(w.key)
  },
  clear,
  back: props.detail ? undefined : back,
  statuses: () => store.statuses,
  selectStatus: (code) => {
    if (!props.detail && nav.level !== 'booking') return
    w.statusCode = code
    w.engage()
  },
})
function back() {
  nav.back()
  inputRef.value?.focus()
}
function resultsKeyboard(event: KeyboardEvent) {
  if (props.detail || event.ctrlKey || event.metaKey || event.altKey || event.isComposing) return
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
  const target = event.target as HTMLElement
  if (
    target.closest('textarea,select,[contenteditable="true"]') ||
    (target instanceof HTMLInputElement && target !== inputRef.value)
  )
    return
  const results = Array.from(
    formScope.value?.querySelectorAll<HTMLButtonElement>('[data-search-result]') ?? [],
  )
  if (!results.length) return
  const current = results.indexOf(document.activeElement as HTMLButtonElement)
  const next =
    event.key === 'ArrowDown'
      ? (current + 1) % results.length
      : current <= 0
        ? results.length - 1
        : current - 1
  event.preventDefault()
  results[next]?.focus()
}
const stationMismatch = computed(() => {
  const parsed = parseBookingKey(w.input),
    group = w.current?.group
  if (parsed && 'key' in parsed && group && parsed.station_code !== group.station_code) {
    const key = build_key(parsed.cw_number, group.station_code, parsed.period)
    return {
      key,
      display: formatBookingKey(key),
      expected: group.station_code,
      cw: parsed.cw_number,
    }
  }
  const error =
    w.lookupRequest.error?.code === 'STATION_MISMATCH' ? w.lookupRequest.error : w.saveRequest.error
  if (error?.code !== 'STATION_MISMATCH' || !error.details || typeof error.details !== 'object')
    return null
  const d = error.details as Record<string, unknown>
  const key = typeof d.suggested_key === 'string' ? parseBookingKey(d.suggested_key) : null
  return key && 'key' in key && typeof d.expected_station === 'string'
    ? {
        key: key.key,
        display: key.display_key,
        expected: d.expected_station,
        cw: key.cw_number,
      }
    : null
})
watch(
  () => props.initialKey,
  (value) => {
    if (value) void open(value)
  },
  { immediate: true },
)
onMounted(() => {
  void w.statusRequest.run()
  if (!props.detail) inputRef.value?.focus()
})
defineExpose({
  open,
  focus: () => inputRef.value?.focus(),
  focusNote: () => formScope.value?.querySelector<HTMLTextAreaElement>('#booking-note')?.focus(),
})
</script>
<template>
  <section
    ref="formScope"
    class="work-card"
    :class="{ 'detail-work-card': detail }"
    :aria-label="t('bookingUi.work')"
    @keydown="resultsKeyboard"
  >
    <header v-if="!detail" class="work-card-heading">
      <div>
        <p class="page-eyebrow">{{ t('bookingUi.workspaceEyebrow') }}</p>
        <h2>{{ t('bookingUi.work') }}</h2>
      </div>
      <span class="shortcut-hint">{{ t('bookingUi.focusShortcut') }}</span>
    </header>
    <div v-if="!detail" class="booking-lookup">
      <label for="booking-input" class="field-label">{{ t('folderUi.searchLabel') }}</label>
      <div class="lookup-input-row">
        <input
          id="booking-input"
          ref="inputRef"
          v-model="w.input"
          autocomplete="off"
          autocapitalize="characters"
          spellcheck="false"
          :placeholder="t('search_placeholder')"
          maxlength="100"
          :aria-describedby="w.validation ? 'booking-input-error' : 'booking-format'"
          @blur="w.normalizeInput"
          @input="nav.typed"
        /><button
          type="button"
          class="button primary lookup-button"
          :aria-label="t('bookingUi.lookUp')"
          @click="lookup"
        >
          <BaseIcon name="arrow" /></button
        ><button
          v-if="w.input"
          type="button"
          class="icon-button"
          :aria-label="t('bookingUi.clearBooking')"
          @click="clear"
        >
          <BaseIcon name="close" />
        </button>
      </div>
      <p id="booking-format" class="input-hint">
        {{ t('folderUi.searchHint') }}
      </p>
      <p v-if="w.validation" id="booking-input-error" class="field-error" role="alert">
        {{ w.validation }}
      </p>
    </div>
    <nav
      v-if="!detail && (nav.level !== 'root' || nav.query)"
      class="folder-breadcrumbs"
      :aria-label="t('folderUi.breadcrumb')"
    >
      <button type="button" class="text-button" @click="nav.root">
        {{ t('folderUi.search') }}
      </button>
      <template v-if="nav.station"
        ><span aria-hidden="true">›</span
        ><button type="button" class="text-button" @click="nav.stationRoot">
          {{ nav.station }}
        </button></template
      >
      <template v-if="nav.cw"
        ><span aria-hidden="true">›</span
        ><button
          type="button"
          class="text-button breadcrumb-folder"
          :aria-current="nav.level === 'folder' ? 'page' : undefined"
          @click="nav.openFolder(nav.cw)"
        >
          {{ nav.cw }}<span v-if="nav.folderName"> — {{ nav.folderName }}</span>
        </button></template
      >
      <template v-if="nav.level === 'booking' && w.key"
        ><span aria-hidden="true">›</span
        ><span aria-current="page">{{ formatBookingKey(w.key) }}</span></template
      >
      <button type="button" class="text-button breadcrumb-back" @click="back">
        {{ t('folderUi.back') }}
      </button>
    </nav>
    <template v-if="!detail && nav.level === 'root'">
      <RequestStatus
        :state="nav.request.state"
        :error="nav.request.error"
        @retry="nav.search(true)"
      />
      <div
        v-if="nav.request.pending && !nav.result"
        class="folder-skeleton"
        role="status"
        :aria-label="t('common.loading')"
      >
        <div v-for="n in 3" :key="n" class="skeleton-line" />
      </div>
      <SmartSearchResults
        v-if="nav.result"
        :result="nav.result"
        @folder="nav.openFolder"
        @booking="nav.openBooking($event, true)"
        @page="nav.changePage"
      />
      <section v-else-if="!nav.query && folders.recent.length" class="recent-folders">
        <h3>{{ t('folderUi.recent') }}</h3>
        <FolderCard
          v-for="folder in folders.recent"
          :key="folder.cw_number"
          :folder="folder"
          @open="nav.openFolder"
        />
      </section>
    </template>
    <SupplierFolder
      v-if="!detail && nav.level === 'folder' && nav.cw"
      :cw="nav.cw"
      @open="nav.openBooking($event, true)"
    />
    <template v-if="detail || nav.level === 'booking'">
      <RequestStatus
        :state="w.lookupRequest.state"
        :error="w.lookupRequest.error"
        @retry="w.key ? w.refresh() : lookup()"
      />
      <div v-if="stationMismatch" class="resolution-panel" role="alert">
        <p>
          {{
            t('station_mismatch', {
              cw: stationMismatch.cw,
              expected: stationMismatch.expected,
              key: stationMismatch.display,
            })
          }}
        </p>
        <button type="button" class="button primary" @click="open(stationMismatch.key)">
          {{ t('bookingUi.useBooking') }}
        </button>
      </div>
      <div
        v-if="w.lookupRequest.pending && !w.current"
        class="booking-skeleton"
        role="status"
        :aria-label="t('common.loading')"
      >
        <div class="skeleton-line" />
        <div class="skeleton-line" />
        <div class="skeleton-line short" />
      </div>
      <div
        v-if="w.resolution?.resolution.status === 'resolved_from_partial'"
        class="resolution-panel"
        role="status"
      >
        <p>
          {{
            t('key_did_you_mean', {
              display_key: w.resolution.resolution.display_key,
            })
          }}
        </p>
        <button type="button" class="button primary" @click="lookup">
          {{ t('bookingUi.useBooking') }}
        </button>
      </div>
      <div v-else-if="w.resolution?.resolution.status === 'ambiguous'" class="resolution-panel">
        <p>
          {{
            t('key_ambiguous', {
              cw: parseBookingKey(w.input)?.cw_number || '',
            })
          }}
        </p>
        <button
          v-for="candidate in w.resolution.resolution.candidates"
          :key="candidate.key"
          type="button"
          class="candidate-button"
          @click="open(candidate.key)"
        >
          <strong>{{ candidate.display_key }}</strong
          ><span>{{ candidate.supplier_name }}</span>
        </button>
      </div>
      <form
        v-else-if="w.resolution?.resolution.status === 'needs_station'"
        class="resolution-panel"
        @submit.prevent="w.applyStation(station)"
      >
        <p>
          {{ t(w.resolution.group_exists ? 'station_required' : 'new_cw_station_prompt') }}
        </p>
        <label class="field-label" for="station-input">{{ t('station_input_label') }}</label>
        <div class="station-input-row">
          <input
            id="station-input"
            :value="station"
            list="station-options"
            maxlength="3"
            autocomplete="off"
            :placeholder="t('station_input_placeholder')"
            @input="stationInput"
          /><button type="submit" class="button primary" :disabled="!/^[A-Z]{3}$/.test(station)">
            {{ t('bookingUi.continue') }}
          </button>
        </div>
        <datalist id="station-options">
          <option
            v-for="option in stationRequest.data.value || []"
            :key="option.code"
            :value="option.code"
          >
            {{ option.name || option.code }}
          </option></datalist
        ><RequestStatus
          :state="stationRequest.state.value"
          :error="stationRequest.error.value"
          @retry="stationRequest.run(station)"
        />
      </form>
      <template v-if="w.current && (w.inputMatches || detail)">
        <div v-if="w.hasUpdate" class="booking-update-banner" role="status">
          <span>{{ t('updated_banner') }}</span
          ><button type="button" class="text-button" @click="w.refresh">
            {{ t('bookingUi.refresh') }}
          </button>
        </div>
        <aside v-if="!w.current.exists" class="booking-new-confirm" role="status">
          <p v-if="w.suggestions.length">{{ t('suggest_title') }}</p>
          <p v-else>{{ t('new_booking') }}</p>
          <button
            v-for="suggestion in w.suggestions"
            :key="suggestion.booking_key"
            type="button"
            data-search-result
            class="candidate-button"
            @click="open(suggestion.booking_key)"
          >
            <strong>{{ suggestion.display_key }}</strong
            ><span
              >{{ suggestion.last_status?.label }} · {{ suggestion.last_agent?.full_name }}</span
            >
          </button>
          <button
            type="button"
            class="button"
            :class="{ selected: w.newConfirmed }"
            :aria-pressed="w.newConfirmed"
            @click="w.newConfirmed = !w.newConfirmed"
          >
            {{ t('confirm_new') }}
          </button>
        </aside>
        <BookingSummaryCard :booking="w.current" @supplier-updated="w.refresh" />
        <BookingTimeline
          :notes="w.notes"
          :cursor="w.cursor"
          :state="w.historyRequest.state"
          :error="w.historyRequest.error"
          @more="w.loadMore"
        />
        <div v-if="w.inputMatches || detail" class="note-form-container">
          <RequestStatus
            :state="w.statusRequest.state"
            :error="w.statusRequest.error"
            @retry="w.statusRequest.run(true)"
          />
          <NoteForm
            v-model:status-code="w.statusCode"
            v-model:note="w.note"
            :statuses="store.statuses"
            :pending="w.saveRequest.pending"
            :can-save="w.canSave"
            :online="w.online"
            :state="w.saveRequest.state"
            :error="w.saveRequest.error"
            :has-draft="w.hasDraft"
            :draft-failed="w.draftFailed"
            :draft-pending="w.draftPending"
            :restored="w.draftRestored"
            @save="save()"
            @discard="w.discardDraft"
            @engage="w.engage"
            ><template #fields
              ><section v-if="w.showInvoice" class="invoice-declaration">
                <label class="field-label" for="note-invoices">{{ t('invoice_label') }}</label
                ><textarea
                  :aria-invalid="!!w.invalidInvoice"
                  id="note-invoices"
                  v-model="w.invoiceText"
                  rows="2"
                  maxlength="2000"
                  :placeholder="t('invoice_placeholder')"
                  @input="w.noInvoice = false"
                /><label class="invoice-none"
                  ><input
                    v-model="w.noInvoice"
                    type="checkbox"
                    :disabled="!!w.invoiceText.trim()"
                  />{{ t('no_invoice_checkbox') }}</label
                >
                <p v-if="w.invalidInvoice" class="field-error">
                  {{ t('invoice_invalid', { value: w.invalidInvoice }) }}
                </p>
                <p v-else-if="!w.invoiceValid" class="input-hint">
                  {{ t('invoice_required_hint') }}
                </p>
                <p v-if="w.invoiceText.trim()" class="input-hint">
                  {{ t('no_invoice_disabled_hint') }}
                </p>
              </section>
              <fieldset v-if="w.needsSupplier" class="supplier-setup">
                <legend>{{ t('bookingUi.supplier') }}</legend>
                <p>{{ t('new_folder_prompt') }}</p>
                <label class="field-label" for="new-supplier-name">{{
                  t('bookingUi.supplierName')
                }}</label
                ><input
                  id="new-supplier-name"
                  v-model="w.supplierName"
                  minlength="3"
                  maxlength="255"
                  autocomplete="organization"
                /><label class="field-label" for="new-supplier-type">{{
                  t('bookingUi.type')
                }}</label
                ><select id="new-supplier-type" v-model="w.supplierType">
                  <option value="hotel">{{ t('supplier_types.hotel') }}</option>
                  <option value="transportation">
                    {{ t('supplier_types.transportation') }}
                  </option>
                </select>
                <div class="supplier-type-options">
                  <button
                    v-for="type in ['hotel', 'transportation'] as const"
                    :key="type"
                    type="button"
                    class="button"
                    :class="{ selected: w.supplierType === type }"
                    :aria-pressed="w.supplierType === type"
                    @click="w.supplierType = type"
                  >
                    {{ t(`supplier_types.${type}`) }}
                  </button>
                </div>
                <p v-if="w.supplierName && w.supplierName.trim().length < 3" class="field-error">
                  {{ t('folderUi.supplierMinimum') }}
                </p>
              </fieldset></template
            ><template #task-action
              ><TaskButton
                v-if="w.key"
                :booking-key="w.key"
                :count="w.current?.my_tasks?.length"
                :disabled="!w.current?.exists" /><slot name="task-action" /></template></NoteForm
          ><TaskSuggestionBar
            v-if="suggestion && suggestion.key === w.key"
            :booking-key="suggestion.key"
            :strong="suggestion.strong"
            :days="suggestion.days"
            :nonce="suggestion.nonce"
          />
        </div>
      </template>
    </template>
    <ElDialog
      v-model="w.duplicate"
      :destroy-on-close="true"
      :title="t('guardUi.duplicateTitle')"
      width="600px"
      align-center
      :close-on-click-modal="false"
    >
      <p>{{ t('duplicate_note', { seconds: w.duplicateSeconds }) }}</p>
      <BookingTimeline v-if="w.duplicateNote" :notes="[w.duplicateNote]" compact />
      <template #footer
        ><button type="button" class="button" @click="w.duplicate = false">
          {{ t('guardUi.cancel') }}</button
        ><button type="button" class="button primary" @click="confirmDuplicate">
          {{ t('guardUi.sendAnyway') }}
        </button></template
      >
    </ElDialog>
    <ElDialog
      v-model="w.conflict"
      :title="
        t('conflict_title', {
          user: conflictData?.snapshot?.last_agent?.full_name || t('common.someone'),
        })
      "
      :show-close="false"
      width="640px"
      align-center
      class="conflict-dialog"
      ><template #header
        ><div class="dialog-heading">
          <h2>
            {{
              t('conflict_title', {
                user: conflictData?.snapshot?.last_agent?.full_name || t('common.someone'),
              })
            }}
          </h2>
          <button
            type="button"
            class="icon-button"
            :aria-label="t('common.close')"
            @click="w.conflict = false"
          >
            <BaseIcon name="close" />
          </button></div
      ></template>
      <p>{{ t('conflict_body') }}</p>
      <BookingTimeline
        v-if="conflictData"
        :notes="conflictData.history.items.slice(0, 1)"
        compact
      /><RequestStatus
        :state="w.conflictRequest.state"
        :error="w.conflictRequest.error"
        @retry="w.loadConflict"
      /><template #footer
        ><button
          type="button"
          class="button primary"
          :disabled="!conflictData || w.conflictRequest.pending"
          @click="w.reviewConflict"
        >
          {{ t('bookingUi.reviewLatest') }}
        </button></template
      ></ElDialog
    >
  </section>
</template>
