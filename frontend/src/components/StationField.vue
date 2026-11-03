<script setup lang="ts">
import { onScopeDispose, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '../api/client'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import type { StationOption } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string]; change: [] }>(),
  { t } = useI18n(),
  id = useId()
let timer: ReturnType<typeof setTimeout> | undefined,
  disposed = false
const q = ref('')
const request = useRequest(
  async ({ signal, timeoutMs }, value: string) =>
    (
      await api.get<StationOption[]>('/stations', {
        params: { q: value },
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.search, retry: true },
)
function changed(event: Event) {
  const input = event.target as HTMLInputElement
  input.value = input.value
    .toUpperCase()
    .replace(/[^A-Z]/g, '')
    .slice(0, 3)
  q.value = input.value
  emit('update:modelValue', input.value)
  emit('change')
  search(input.value)
}
function search(value: string) {
  q.value = value
  clearTimeout(timer)
  request.cancel()
  timer = setTimeout(() => {
    if (!disposed) void request.run(q.value)
  }, timeouts.smartSearchDebounce)
}
onScopeDispose(() => {
  disposed = true
  clearTimeout(timer)
})
</script>
<template>
  <div class="station-field">
    <label :for="id + '-input'">{{ t('bookingUi.station') }}</label
    ><input
      :id="id + '-input'"
      :value="modelValue"
      :list="id"
      maxlength="3"
      autocomplete="off"
      :placeholder="t('station_input_placeholder')"
      @input="changed"
      @focus="search(modelValue)"
    /><datalist :id="id">
      <option v-for="option in request.data.value ?? []" :key="option.code" :value="option.code">
        {{ option.name || option.code }} · {{ option.folder_count }}
      </option></datalist
    ><RequestStatus
      v-if="request.state.value === 'slow' || request.error.value"
      :state="request.state.value"
      :error="request.error.value"
      @retry="request.run(q)"
    />
  </div>
</template>
