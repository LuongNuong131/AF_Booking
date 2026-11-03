import { i18n } from '../i18n'
import { formatBookingKey } from './bookingKey'
import type { NotificationItem, NotificationNewData } from '../types/api.generated'

export function notificationText(item: NotificationItem | NotificationNewData): string {
  const t = i18n.global.t
  const user =
    ('by_agent' in item ? item.by_agent?.full_name : item.by_agent_name) || t('common.someone')
  const params = { user, key: formatBookingKey(item.booking_key) }
  switch (item.type) {
    case 'taken_over':
      return t('notif_taken_over', params)
    case 'watch_update':
      return t('notif_watch', params)
    case 'assigned':
      return t('notif_assigned', params)
    case 'assignment_done':
      return t('notifications.assignmentDone', params)
    case 'task_due':
      return t('notifications.taskDue', params)
    case 'stale':
      return t('notifications.stale', params)
  }
}
