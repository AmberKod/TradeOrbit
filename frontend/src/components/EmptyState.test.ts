import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EmptyState from './EmptyState.vue'

describe('truthful empty state', () => {
  it('explains missing financial data and offers a real action', () => {
    const wrapper = mount(EmptyState, { props: { title: '没有权益快照', description: '缺失数据不会填 0' }, slots: { default: '<button>配置账户</button>' } })
    expect(wrapper.text()).toContain('没有权益快照'); expect(wrapper.text()).toContain('缺失数据不会填 0'); expect(wrapper.find('button').text()).toBe('配置账户')
  })
})
