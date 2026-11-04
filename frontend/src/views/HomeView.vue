<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useBookingsStore } from '../stores/bookings'
import BookingWorkspace from '../components/BookingWorkspace.vue'
import { useTasksStore } from '../stores/tasks'
import TaskList from '../components/TaskList.vue'
import MyBookings from '../components/MyBookings.vue'
import CollaborationList from '../components/CollaborationList.vue'
import { useCollaborationStore } from '../stores/collaboration'
const { t } = useI18n(),
  store = useBookingsStore(),
  tasks = useTasksStore(),
  collaboration = useCollaborationStore()
const initialKey = store.homeKey || undefined
const workspace = ref<InstanceType<typeof BookingWorkspace> | null>(null)
function open(key: string) {
  void workspace.value?.open(key)
  workspace.value?.focus()
}
watch(
  () => tasks.openBookingRequest,
  async (request) => {
    if (!request) return
    await nextTick()
    if (!request.key) {
      tasks.rightTab = 'tasks'
      tasks.openBookingRequest = null
      return
    }
    if (await workspace.value?.open(request.key)) {
      if (request.note) workspace.value?.focusNote()
      if (tasks.openBookingRequest?.seq === request.seq) tasks.openBookingRequest = null
    }
  },
  { immediate: true },
)
</script>
<template>
  <section class="home-view">
    <header class="page-heading home-heading">
      <div>
        <p class="page-eyebrow">{{ t('bookingUi.homeEyebrow') }}</p>
        <h1>{{ t('pages.homeTitle') }}</h1>
        <p>{{ t('bookingUi.homeIntro') }}</p>
      </div>
      <span class="workspace-date">{{ t('bookingUi.keyboardReady') }}</span>
    </header>
    <div class="booking-workspace-grid">
      <BookingWorkspace ref="workspace" :initial-key="initialKey" /><MyBookings
        :show-tasks="tasks.rightTab !== 'bookings'"
        @open="open"
        @select-bookings="tasks.rightTab = 'bookings'"
        ><template #tabs
          ><button
            type="button"
            class="mine-tab task-tab"
            :class="{ due: tasks.dueCount > 0 }"
            :aria-pressed="tasks.rightTab === 'tasks'"
            @click="tasks.rightTab = 'tasks'"
          >
            {{ t('taskUi.tab', { count: tasks.dueCount }) }}</button
          ><button
            v-for="tab in ['assignments', 'watching'] as const"
            :key="tab"
            type="button"
            class="mine-tab"
            :aria-pressed="tasks.rightTab === tab"
            @click="tasks.rightTab = tab"
          >
            {{ t(tab === 'assignments' ? 'collabUi.assignedTab' : 'collabUi.watching')
            }}<span v-if="tab === 'assignments'">{{ collaboration.assignedCount }}</span>
          </button></template
        ><template #tasks
          ><TaskList v-if="tasks.rightTab === 'tasks'" /><CollaborationList
            v-else
            :mode="tasks.rightTab === 'assignments' ? 'assignments' : 'watching'" /></template
      ></MyBookings>
    </div>
  </section>
</template>
