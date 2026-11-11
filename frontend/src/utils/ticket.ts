export const ticketTitles = {
  contract: 'AF_Non-standard process_Contract issue',
  cannot_send_rejection_letters: 'AF_System Issues_Cannot send rejection letters',
} as const
export type IssueType = keyof typeof ticketTitles
export function englishTicket(value: string) {
  return /[a-zA-Z]{2}/.test(value) && !/[ăâđêôơưĂÂĐÊÔƠƯ\u1ea0-\u1ef9]/u.test(value.normalize('NFC'))
}
