import { CW_PATTERN } from './bookingKey'
export function folderKey(folder: { cw_number: string; station_code: string }): string {
  return `${folder.cw_number}-${folder.station_code}`
}

export const isFolderKey = (value: string): boolean => new RegExp(`^${CW_PATTERN}(?:-[A-Z]{3})?$`).test(value)
