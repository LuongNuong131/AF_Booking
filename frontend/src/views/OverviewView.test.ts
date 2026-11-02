import { createPinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { i18n } from '../i18n'
import { checkServices } from '../api/health'
import OverviewView from './OverviewView.vue'

vi.mock('../api/health', () => ({ checkServices: vi.fn() }))

describe('workspace readiness', () => {
  it('shows an actionable error and lets the user retry successfully', async () => {
    vi.mocked(checkServices)
      .mockResolvedValueOnce({ api: 'offline', database: 'unavailable' })
      .mockResolvedValueOnce({ api: 'online', database: 'connected' })
    const wrapper = mount(OverviewView, { global: { plugins: [createPinia(), i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('The application service is unavailable.')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.el-tag').map((tag) => tag.text())).toEqual(['Connected', 'Connected'])
    expect(wrapper.text()).not.toContain('The application service is unavailable.')
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})
