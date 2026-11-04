import { it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import NoteHighlight from './NoteHighlight.vue'
it('renders marks and escapes HTML instead of creating elements', () => {
  const wrapper = mount(NoteHighlight, {
    props: { text: '<img src=x onerror=alert(1)>Khách sạn', query: 'khách sạn' },
  })
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('mark').text()).toBe('Khách sạn')
  expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
  wrapper.unmount()
})
