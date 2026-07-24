import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import WorkbenchPage from './WorkbenchPage.vue'
import { workbenchApi } from './api'

// Mock vue-router
vi.mock('vue-router', () => ({
  useRoute: () => ({
    params: { projectId: 'proj-test-123' }
  }),
  useRouter: () => ({
    push: vi.fn()
  })
}))

// Mock project store
vi.mock('@/shared/stores/project', () => ({
  useProjectStore: () => ({
    hasPermission: () => true
  })
}))

// Mock workbenchApi
vi.mock('./api', () => ({
  workbenchApi: {
    getSummary: vi.fn(),
    getTodos: vi.fn(),
    getInProgressTasks: vi.fn(),
    getAgentRuns: vi.fn(),
    getRemainingRequirements: vi.fn(),
    getRecentVisits: vi.fn()
  }
}))

describe('WorkbenchPage.vue Component', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()

    vi.mocked(workbenchApi.getSummary).mockResolvedValue({
      remaining_requirements_count: 5,
      my_todos_count: 3,
      in_progress_tasks_count: 2,
      waiting_human_count: 1,
      generated_at: new Date().toISOString()
    } as any)

    vi.mocked(workbenchApi.getTodos).mockResolvedValue({
      items: [
        {
          id: 'REQUIREMENT:1',
          type: 'REQUIREMENT_DESIGN',
          title: '需求需进行测试设计: REQ-10017 个人工作台',
          priority: 'HIGH',
          created_at: new Date().toISOString(),
          urgency: 'NORMAL',
          sub_item_count: 1,
          target_type: 'REQUIREMENT',
          target_id: 'req-1',
          target_route: '/projects/proj-test-123/requirements/req-1'
        }
      ],
      total: 1,
      limit: 50,
      offset: 0
    } as any)

    vi.mocked(workbenchApi.getInProgressTasks).mockResolvedValue({
      items: [],
      total: 0,
      limit: 10,
      offset: 0
    } as any)

    vi.mocked(workbenchApi.getAgentRuns).mockResolvedValue({
      items: [],
      total: 0,
      limit: 10,
      offset: 0
    } as any)

    vi.mocked(workbenchApi.getRemainingRequirements).mockResolvedValue({
      items: [],
      total: 0,
      limit: 10,
      offset: 0
    } as any)

    vi.mocked(workbenchApi.getRecentVisits).mockResolvedValue({
      items: [],
      total: 0,
      limit: 10,
      offset: 0
    } as any)
  })

  it('renders workbench title and summary cards correctly', async () => {
    const wrapper = mount(WorkbenchPage, {
      global: {
        stubs: ['router-link']
      }
    })

    expect(wrapper.text()).toContain('工作台')
    expect(workbenchApi.getSummary).toHaveBeenCalledWith('proj-test-123', expect.anything())

    // 验证 API 挂载后概要数字渲染
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('5')
    expect(wrapper.text()).toContain('3')
  })
})
