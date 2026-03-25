import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAgentStore } from '../../../stores/agentStore'
import { useMessageStore } from '../../../stores/v2/messageStore'
import { GlobalInputBar } from './GlobalInputBar'

vi.mock('./ConfigViewerModal', () => ({
  ConfigViewerModal: () => null,
}))

describe('GlobalInputBar launch state', () => {
  beforeEach(() => {
    useAgentStore.getState().reset()
    useMessageStore.getState().reset()
    vi.restoreAllMocks()
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        json: async () => ({ configs: [] }),
      })
    )
  })

  it('seeds launch state immediately when starting a new run', async () => {
    useMessageStore.setState({
      messages: {
        stale_agent: [
          {
            id: 'msg-1',
            type: 'status',
            agentId: 'stale_agent',
            timestamp: 1,
            status: 'working',
          },
        ],
      },
      agentOrder: ['stale_agent'],
      agentModels: {},
      currentRound: { stale_agent: 1 },
      pendingToolCalls: {},
      threads: [],
      currentPhase: null,
      taskPlans: {},
      _counter: 1,
    })

    const startCoordination = vi.fn()
    const user = userEvent.setup()

    render(
      <GlobalInputBar
        wsStatus="connected"
        startCoordination={startCoordination}
        continueConversation={() => undefined}
        cancelCoordination={() => undefined}
        selectedConfig="configs/basic/demo.yaml"
        onConfigChange={() => undefined}
        hasActiveSession={false}
        isComplete={false}
        isLaunching={false}
      />
    )

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith('/api/configs')
    })

    await user.type(screen.getByRole('textbox'), 'Build the thing{Enter}')

    expect(startCoordination).toHaveBeenCalledWith('Build the thing', 'configs/basic/demo.yaml')
    expect(useAgentStore.getState().question).toBe('Build the thing')
    expect(useAgentStore.getState().initStatus).toEqual({
      message: 'Submitting prompt...',
      step: 'request',
      progress: 3,
    })
    expect(useMessageStore.getState().messages).toEqual({})
  })
})
