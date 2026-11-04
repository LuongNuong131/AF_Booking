<script setup lang="ts">
import { ref, onScopeDispose, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useRequest } from '../composables/useRequest'
import { timeouts } from '../config/timeouts'
import { api } from '../api/client'
import type { AgentSummary } from '../types/api.generated'
import RequestStatus from './RequestStatus.vue'
const props = defineProps<{ modelValue: number | null; message: string }>(),
  emit = defineEmits<{
    'update:modelValue': [number | null]
    'update:message': [string]
  }>(),
  { t } = useI18n(),
  auth = useAuthStore()
const query = ref(''),
  name = ref(''),
  results = ref<AgentSummary[]>([])
const request = useRequest(
  async ({ signal, timeoutMs }, q: string) =>
    (
      await api.get<AgentSummary[]>('/users/lookup', {
        params: { q, limit: 20 },
        signal,
        timeout: timeoutMs,
      })
    ).data,
  { timeoutMs: timeouts.list },
)
let timer: ReturnType<typeof setTimeout> | undefined
watch(query, (value) => {
  clearTimeout(timer)
  request.cancel()
  results.value = []
  if (!value.trim()) return
  timer = setTimeout(async () => {
    const rows = await request.run(value)
    if (rows) results.value = rows.filter((r) => r.id !== auth.user?.id)
  }, 200)
})
watch(
  () => props.modelValue,
  (value) => {
    if (value === null) {
      name.value = ''
      query.value = ''
      results.value = []
    }
  },
)
function clear() {
  emit('update:modelValue', null)
  emit('update:message', '')
}
function choose(user: AgentSummary) {
  emit('update:modelValue', user.id)
  name.value = user.full_name
  query.value = ''
  results.value = []
}
onScopeDispose(() => clearTimeout(timer))
</script>
<template>
  <fieldset class="assignee-picker">
    <legend>{{ t('collabUi.assignLabel') }}</legend>
    <template v-if="modelValue"
      ><p>
        {{ name || t('collabUi.assigneeId', { id: modelValue }) }}
        <button type="button" class="text-button" @click="clear">
          {{ t('collabUi.clear') }}
        </button>
      </p>
      <label
        >{{ t('collabUi.message')
        }}<input
          :value="message"
          maxlength="255"
          @input="
            emit('update:message', ($event.target as HTMLInputElement).value)
          " /></label></template
    ><label v-else
      >{{ t('collabUi.findUser')
      }}<input
        v-model="query"
        autocomplete="off"
        :placeholder="t('collabUi.findUserPlaceholder')" /></label
    ><RequestStatus
      :state="request.state.value"
      :error="request.error.value"
      @retry="request.run(query)"
    />
    <ul v-if="results.length" class="assignee-results">
      <li v-for="user in results" :key="user.id">
        <button type="button" @click="choose(user)">
          {{ user.full_name }}
        </button>
      </li>
    </ul>
  </fieldset>
</template>
