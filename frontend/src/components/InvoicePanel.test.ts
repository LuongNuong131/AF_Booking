import { it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import InvoicePanel from './InvoicePanel.vue'
import InvoiceBadge from './InvoiceBadge.vue'
import { i18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { user } from '../test/bookingFixtures'
const wrappers: Array<{ unmount: () => void }> = []
afterEach(() => {
  wrappers.forEach((w) => w.unmount())
  wrappers.length = 0
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
function panel(props: Record<string, unknown> = {}) {
  setActivePinia(createPinia())
  useAuthStore().user = user
  const w = mount(InvoicePanel, {
    props: { items: [], state: 'unknown', canSave: true, ...props },
    global: { plugins: [i18n], stubs: { RouterLink: true } },
  })
  wrappers.push(w)
  return w
}
it('pastes invoice chips, disables the checkbox while chips exist and locks input when ticked', async () => {
  const w = panel()
  await w.find('input:not([type=checkbox])').setValue('INV1, inv2; INV1')
  await w.find('input:not([type=checkbox])').trigger('keydown', { key: 'Enter' })
  const value = w.emitted('update:modelValue')!.at(-1)![0] as object
  expect(value).toEqual({ add: ['INV1', 'INV2'], no_invoice: false })
  await w.setProps({ modelValue: value })
  expect(w.find('input[type=checkbox]').attributes('disabled')).toBeDefined()
  await w.setProps({ modelValue: { add: [], no_invoice: true } })
  expect(w.find('input:not([type=checkbox])').attributes('disabled')).toBeDefined()
})
it('marks invalid numbers, blocks standalone save and only offers removal to the owner or QC/Admin', async () => {
  const w = panel({
    modelValue: { add: ['BAD@VALUE'] },
    items: [
      {
        id: 1,
        invoice_number: 'INV100',
        added_by: { id: 999, full_name: 'Other' },
        created_at: '2026-11-01T00:00:00Z',
      },
    ],
  })
  expect(w.find('.invoice-chip.invalid').text()).toContain('BAD@VALUE')
  expect(w.find('button.button').attributes('disabled')).toBeDefined()
  expect(w.find('[aria-label="Remove invoice INV100"]').exists()).toBe(false)
  useAuthStore().user = { ...user, role: 'qc' }
  await w.vm.$nextTick()
  expect(w.find('[aria-label="Remove invoice INV100"]').exists()).toBe(true)
  const confirm = vi.fn().mockReturnValue(true)
  vi.stubGlobal('confirm', confirm)
  await w.find('[aria-label="Remove invoice INV100"]').trigger('click')
  expect(confirm).toHaveBeenCalled()
  expect(
    (w.emitted('update:modelValue')!.at(-1)![0] as { remove_ids: number[] }).remove_ids,
  ).toEqual([1])
})
it('shows the first two numbers and the remaining count without exposing markup', () => {
  const w = mount(InvoiceBadge, {
    props: {
      state: 'has_invoice',
      count: 4,
      preview: ['INV1', 'INV2', 'INV3'],
    },
    global: { plugins: [i18n] },
  })
  wrappers.push(w)
  expect(w.text()).toContain('INV1, INV2')
  expect(w.text()).toContain('+2')
  expect(w.text()).not.toContain('INV3')
})
