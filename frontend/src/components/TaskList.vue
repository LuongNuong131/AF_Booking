<script setup lang="ts">
import { computed, onMounted, onScopeDispose } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTasksStore } from '../stores/tasks'
import { formatDateTime } from '../utils/dateTime'
import { zonedToday } from '../utils/summaryFilters'
import { reminderParts } from '../utils/taskDates'
import { useViewRefresh } from '../composables/useViewRefresh'
import TaskActions from './TaskActions.vue'
import StatusTag from './StatusTag.vue'
import EmptyState from './EmptyState.vue'
import RequestStatus from './RequestStatus.vue'
import PageControls from './PageControls.vue'
const { t } = useI18n(),
  tasks = useTasksStore()
const groups = computed(() => {
  const today = zonedToday(tasks.preferences.timezone)
  return ['overdue', 'today', 'upcoming']
    .map((kind) => ({
      kind,
      items: tasks.items.filter((task) =>
        tasks.view === 'done'
          ? kind === 'today'
          : kind ===
            (task.is_overdue
              ? 'overdue'
              : reminderParts(task.remind_at, tasks.preferences.timezone).date === today
                ? 'today'
                : 'upcoming'),
      ),
    }))
    .filter((group) => group.items.length)
})
onMounted(() => {
  tasks.setListActive(true)
  void tasks.refreshList()
})
onScopeDispose(() => tasks.setListActive(false))
useViewRefresh(() => tasks.refreshList())
</script>
<template>
  <section class="task-list" :aria-label="t('taskUi.tasks')">
    <div class="task-list-toolbar">
      <label
        >{{ t('taskUi.view')
        }}<select
          :value="tasks.view"
          @change="
            tasks.refreshList(($event.target as HTMLSelectElement).value as 'pending' | 'done', 1)
          "
        >
          <option value="pending">{{ t('taskUi.pending') }}</option>
          <option value="done">{{ t('taskUi.completed') }}</option>
        </select></label
      ><button type="button" class="text-button" @click="tasks.refreshList()">
        {{ t('bookingUi.refresh') }}
      </button>
    </div>
    <RequestStatus
      :state="tasks.listRequest.state"
      :error="tasks.listRequest.error"
      @retry="tasks.refreshList()"
    /><RequestStatus
      :state="tasks.actionError ? 'error' : 'idle'"
      :error="tasks.actionError"
      @retry="tasks.refreshList()"
    />
    <div
      v-if="tasks.listRequest.pending && !tasks.items.length"
      class="mine-skeleton"
      role="status"
      :aria-label="t('common.loading')"
    >
      <div v-for="n in 3" :key="n" class="skeleton-line" />
    </div>
    <template v-else-if="tasks.items.length"
      ><section v-for="group in groups" :key="group.kind" class="task-group">
        <h3>
          {{ t(tasks.view === 'done' ? 'taskUi.completed' : `taskUi.${group.kind}`) }}
        </h3>
        <article v-for="task in group.items" :key="task.id" class="task-row">
          <header>
            <button
              type="button"
              class="table-booking-link"
              @click="tasks.openBooking(task.booking_key)"
            >
              {{ task.display_key }}</button
            ><StatusTag :status="task.booking.last_status" />
          </header>
          <p class="task-message">{{ task.message }}</p>
          <time :datetime="task.remind_at">{{
            formatDateTime(task.remind_at, tasks.preferences.timezone)
          }}</time>
          <p v-if="task.booking_changed_since" class="task-warning">
            {{
              t('taskUi.bookingChanged', {
                user: task.booking.last_agent?.full_name || t('common.someone'),
              })
            }}
          </p>
          <p v-if="task.booking.is_done" class="task-warning">
            {{ t('taskUi.bookingDone') }}
          </p>
          <TaskActions :task="task" />
        </article></section></template
    ><EmptyState
      v-else
      :title="t('taskUi.empty')"
      :description="t('taskUi.emptyBody')"
    /><PageControls
      :page="tasks.page"
      :total="tasks.listTotal"
      :size="10"
      summary-key="taskUi.pageOf"
      @change="tasks.refreshList(tasks.view, $event)"
    />
  </section>
</template>
