<script setup lang="ts">
import EmptyState from '../../components/EmptyState.vue'
import { reactive, ref } from 'vue'
import { ElDialog } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { api } from '../../api/client'
import { useAuthStore } from '../../stores/auth'
import { useRequest } from '../../composables/useRequest'
import { usePagedApi } from '../../composables/usePagedApi'
import { timeouts } from '../../config/timeouts'
import { formatDateTime } from '../../utils/dateTime'
import type { AdminUser } from '../../types/api.generated'
import PageControls from '../../components/PageControls.vue'
import RequestStatus from '../../components/RequestStatus.vue'
const { t } = useI18n(),
  auth = useAuthStore(),
  q = ref(''),
  list = usePagedApi<AdminUser>(
    () => '/admin/users',
    () => ({ q: q.value }),
  )
const selected = ref<AdminUser | null>(null),
  mode = ref<'create' | 'edit' | 'reset' | 'kick' | 'lock' | null>(null)
const form = reactive({
  username: '',
  full_name: '',
  role: 'agent' as AdminUser['role'],
  temporary_password: '',
})
const mutation = useRequest(
  async ({ signal, timeoutMs }) => {
    const config = { signal, timeout: timeoutMs },
      id = selected.value?.id
    if (mode.value === 'create') return (await api.post('/admin/users', { ...form }, config)).data
    if (mode.value === 'reset')
      return (
        await api.post(
          `/admin/users/${id}/reset-password`,
          { temporary_password: form.temporary_password },
          config,
        )
      ).data
    if (mode.value === 'kick') return (await api.post(`/admin/users/${id}/kick`, {}, config)).data
    return (
      await api.patch(
        `/admin/users/${id}`,
        mode.value === 'lock'
          ? { is_active: !selected.value?.is_active }
          : { full_name: form.full_name, role: form.role },
        config,
      )
    ).data
  },
  { timeoutMs: timeouts.profile },
)
function open(value: NonNullable<typeof mode.value>, user: AdminUser | null = null) {
  mutation.cancel()
  mutation.error.value = null
  mutation.state.value = 'idle'
  selected.value = user
  Object.assign(form, {
    username: user?.username ?? '',
    full_name: user?.full_name ?? '',
    role: user?.role ?? 'agent',
    temporary_password: '',
  })
  mode.value = value
}
function close() {
  if (mutation.pending.value) return
  mode.value = null
  form.temporary_password = ''
}
async function save() {
  if (mutation.pending.value) return
  const result = await mutation.run()
  if (result) {
    mode.value = null
    form.temporary_password = ''
    await list.load()
  }
}
</script>
<template>
  <section>
    <header class="admin-section-heading">
      <h2>{{ t('adminUi.users') }}</h2>
      <button class="button primary" type="button" @click="open('create')">
        {{ t('adminUi.createUser') }}
      </button>
    </header>
    <form class="admin-filters" @submit.prevent="list.apply">
      <label>{{ t('adminUi.findUsers') }}<input v-model="q" maxlength="100" /></label
      ><button class="button" type="submit">{{ t('adminUi.apply') }}</button>
    </form>
    <RequestStatus
      :state="list.request.state.value"
      :error="list.request.error.value"
      @retry="list.load"
    />
    <EmptyState v-if="list.request.state.value === 'success' && !list.items.value.length" :title="t('common.noRecords')" :description="t('common.noRecordsHint')" />
    <div v-if="list.items.value.length" class="admin-table-wrap">
      <table class="admin-table admin-users-table">
        <thead>
          <tr>
            <th>{{ t('auth.username') }}</th>
            <th>{{ t('adminUi.fullName') }}</th>
            <th>{{ t('adminUi.role') }}</th>
            <th>{{ t('adminUi.active') }}</th>
            <th>{{ t('adminUi.lastLogin') }}</th>
            <th>{{ t('adminUi.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in list.items.value" :key="user.id">
            <td>{{ user.username }}</td>
            <td>{{ user.full_name }}</td>
            <td>{{ t(`roles.${user.role}`) }}</td>
            <td>
              {{ t(user.is_active ? 'adminUi.enabled' : 'adminUi.disabled') }}
            </td>
            <td>
              {{ user.last_login_at ? formatDateTime(user.last_login_at, auth.timezone) : '—' }}
            </td>
            <td class="admin-row-actions">
              <button type="button" class="text-button" @click="open('edit', user)">
                {{ t('adminUi.edit') }}</button
              ><button
                type="button"
                class="text-button"
                :disabled="user.id === auth.user?.id"
                @click="open('lock', user)"
              >
                {{ t(user.is_active ? 'adminUi.disable' : 'adminUi.enable') }}</button
              ><button type="button" class="text-button" @click="open('reset', user)">
                {{ t('adminUi.resetPassword') }}</button
              ><button
                type="button"
                class="text-button"
                :disabled="!user.has_session"
                @click="open('kick', user)"
              >
                {{ t('adminUi.kick') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <PageControls
      :page="list.page.value"
      :total="list.total.value"
      :size="20"
      summary-key="adminUi.userPageOf"
      @change="list.page.value = $event"
    /><ElDialog
      :model-value="!!mode"
      :title="
        t(
          mode === 'create'
            ? 'adminUi.createUser'
            : mode === 'edit'
              ? 'adminUi.editUser'
              : mode === 'reset'
                ? 'adminUi.resetPassword'
                : mode === 'kick'
                  ? 'adminUi.kick'
                  : 'adminUi.changeAccess',
        )
      "
      width="540px"
      :close-on-click-modal="false"
      :close-on-press-escape="!mutation.pending.value"
      :show-close="!mutation.pending.value"
      @update:model-value="close"
      ><form class="admin-edit-form" @submit.prevent="save">
        <template v-if="mode === 'create' || mode === 'edit'"
          ><label v-if="mode === 'create'"
            >{{ t('auth.username')
            }}<input
              v-model="form.username"
              required
              pattern="[A-Za-z0-9][A-Za-z0-9_.-]{2,49}"
              maxlength="50"
              autocomplete="off" /></label
          ><label
            >{{ t('adminUi.fullName')
            }}<input v-model="form.full_name" minlength="2" maxlength="100" required /></label
          ><label
            >{{ t('adminUi.role')
            }}<select
              :aria-label="t('adminUi.role')"
              v-model="form.role"
              :disabled="selected?.id === auth.user?.id"
            >
              <option v-for="role in ['agent', 'qc', 'admin']" :key="role" :value="role">
                {{ t(`roles.${role}`) }}
              </option>
            </select></label
          ></template
        ><label v-if="mode === 'create' || mode === 'reset'"
          >{{ t('adminUi.temporaryPassword')
          }}<input
            v-model="form.temporary_password"
            type="password"
            minlength="10"
            maxlength="128"
            autocomplete="new-password"
            required
        /></label>
        <p v-if="selected">{{ selected.username }} · {{ selected.full_name }}</p>
        <p v-if="mode === 'kick' || mode === 'lock' || mode === 'reset'" class="booking-warning">
          {{ t('adminUi.sessionWarning') }}
        </p>
        <RequestStatus :state="mutation.state.value" :error="mutation.error.value" @retry="save" />
        <div class="admin-form-actions">
          <button type="submit" class="button primary" :disabled="mutation.pending.value">
            {{ t(mutation.pending.value ? 'taskUi.saving' : 'adminUi.confirm') }}</button
          ><button type="button" class="button" :disabled="mutation.pending.value" @click="close">
            {{ t('common.cancel') }}
          </button>
        </div>
      </form></ElDialog
    >
  </section>
</template>
