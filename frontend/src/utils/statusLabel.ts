import { i18n } from '../i18n'
const defaults: Record<string, string> = {
  DONE: 'Done', REJECTION: 'Rejection', PARKING: 'Parking', BUNDLE: 'Bundle', HRS_PREVIEW: 'HRS Preview',
}
export function statusLabel(status?: { code: string; label: string } | null): string {
  if (!status) return i18n.global.t('common.unknown')
  return defaults[status.code] === status.label
    ? i18n.global.t(`status_labels.${status.code.toLowerCase()}`)
    : status.label
}
