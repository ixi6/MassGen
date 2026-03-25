import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useMessageStore } from '../../../stores/v2/messageStore'
import { TaskPlanPanel } from './TaskPlanPanel'

const AGENT_ID = 'agent-alpha'

describe('TaskPlanPanel', () => {
  beforeEach(() => {
    useMessageStore.getState().reset()
    useMessageStore.setState({
      taskPlans: {
        [AGENT_ID]: [
          {
            id: 'task-1',
            description: 'Build the first artifact',
            status: 'in_progress',
            priority: 'high',
          },
          {
            id: 'task-2',
            description: 'Verify the result',
            status: 'pending',
          },
        ],
      },
    })
  })

  it('renders docked at default width and supports drag-resize', () => {
    render(<TaskPlanPanel agentId={AGENT_ID} />)

    const panel = screen.getByTestId('task-plan-panel')
    expect(panel).toHaveStyle({ width: '360px' })

    const handle = screen.getByTestId('task-plan-resize-handle')
    fireEvent.mouseDown(handle, { clientX: 100 })
    fireEvent.mouseMove(window, { clientX: 40 })
    fireEvent.mouseUp(window)

    expect(panel).toHaveStyle({ width: '420px' })
  })

  it('clicking a task expands its metadata', () => {
    render(<TaskPlanPanel agentId={AGENT_ID} />)

    // Click first task
    fireEvent.click(screen.getByText(/Build the first artifact/))

    // Should show metadata
    expect(screen.getByText('in progress')).toBeInTheDocument()
    expect(screen.getByText('high')).toBeInTheDocument()
    expect(screen.getByText('task-1')).toBeInTheDocument()
  })

  it('collapses to a vertical icon strip and re-expands', () => {
    render(<TaskPlanPanel agentId={AGENT_ID} />)

    // Find the collapse button (the chevron in header)
    const header = screen.getByTestId('task-plan-panel').querySelector('button:last-child')
    if (header) fireEvent.click(header)

    // Panel should be gone, collapsed strip visible
    expect(screen.queryByTestId('task-plan-panel')).toBeNull()
    expect(screen.getByText('0/2')).toBeInTheDocument()

    // Re-expand
    fireEvent.click(screen.getByTitle(/click to expand/))
    expect(screen.getByTestId('task-plan-panel')).toBeInTheDocument()
  })

  it('returns null when no task plan exists', () => {
    useMessageStore.setState({ taskPlans: {} })
    const { container } = render(<TaskPlanPanel agentId={AGENT_ID} />)
    expect(container.innerHTML).toBe('')
  })

  it('shows only the tasks for the given agent', () => {
    useMessageStore.setState({
      taskPlans: {
        [AGENT_ID]: [
          { id: 't1', description: 'Alpha task', status: 'pending' },
        ],
        'agent-beta': [
          { id: 't2', description: 'Beta task', status: 'pending' },
        ],
      },
    })
    render(<TaskPlanPanel agentId={AGENT_ID} />)
    expect(screen.getByText(/Alpha task/)).toBeInTheDocument()
    expect(screen.queryByText(/Beta task/)).toBeNull()
  })
})
