/**
 * v2 Message Store
 *
 * Builds chronological per-agent message streams from WebSocket events.
 * Runs in parallel with agentStore — both process the same WS events.
 * The v2 UI reads from this store for its chat-style message rendering.
 */

import { create } from 'zustand';
import type { WSEvent, HookExecutionInfo } from '../../types';

// ============================================================================
// Message Types
// ============================================================================

export type ChannelMessageType =
  | 'thinking'
  | 'content'
  | 'tool-call'
  | 'tool-result'
  | 'answer'
  | 'vote'
  | 'round-divider'
  | 'completion'
  | 'status'
  | 'error'
  | 'subagent-spawn'
  | 'subagent-started'
  | 'broadcast'
  | 'checkpoint';

interface BaseMessage {
  id: string;
  type: ChannelMessageType;
  agentId: string;
  timestamp: number;
}

export interface ThinkingMessage extends BaseMessage {
  type: 'thinking';
  content: string;
}

export interface ContentMessage extends BaseMessage {
  type: 'content';
  content: string;
  contentType: 'thinking' | 'text' | 'tool' | 'status';
}

export interface ToolCallMessage extends BaseMessage {
  type: 'tool-call';
  toolId?: string;
  toolName: string;
  args: Record<string, unknown>;
  result?: string;
  success?: boolean;
  elapsed?: number;
  preHooks?: HookExecutionInfo[];
  postHooks?: HookExecutionInfo[];
}

export interface ToolResultMessage extends BaseMessage {
  type: 'tool-result';
  toolId?: string;
  toolName: string;
  result: string;
  success: boolean;
}

export interface AnswerMessage extends BaseMessage {
  type: 'answer';
  answerLabel: string;
  answerNumber: number;
  contentPreview: string;
}

export interface VoteMessage extends BaseMessage {
  type: 'vote';
  targetId: string;
  targetName?: string;
  reason: string;
  voteLabel: string;
  voteRound: number;
}

export interface RoundDividerMessage extends BaseMessage {
  type: 'round-divider';
  roundNumber: number;
  label: string;
}

export interface StatusMessage extends BaseMessage {
  type: 'status';
  status: string;
  detail?: string;
}

export interface ErrorMessage extends BaseMessage {
  type: 'error';
  message: string;
}

export interface SubagentSpawnMessage extends BaseMessage {
  type: 'subagent-spawn';
  subagentIds: string[];
  task: string;
  callId: string;
}

export interface SubagentStartedMessage extends BaseMessage {
  type: 'subagent-started';
  subagentId: string;
  task: string;
  timeoutSeconds: number;
}

export interface BroadcastMessage extends BaseMessage {
  type: 'broadcast';
  content: string;
  targets: string[] | null;
}

export interface CheckpointMessage extends BaseMessage {
  type: 'checkpoint';
  checkpointNumber: number;
  task: string;
  status: 'started' | 'completed';
  consensus?: string;
  workspaceChanges?: { file: string; change: string }[];
}

export interface CompletionMessage extends BaseMessage {
  type: 'completion';
  label: string;
  selectedAgent?: string;
}

export type ChannelMessage =
  | ThinkingMessage
  | ContentMessage
  | ToolCallMessage
  | ToolResultMessage
  | AnswerMessage
  | VoteMessage
  | RoundDividerMessage
  | StatusMessage
  | ErrorMessage
  | SubagentSpawnMessage
  | SubagentStartedMessage
  | BroadcastMessage
  | CheckpointMessage
  | CompletionMessage;

// ============================================================================
// Thread (subagent) tracking
// ============================================================================

export interface ThreadInfo {
  id: string;
  parentAgentId: string;
  task: string;
  status: 'running' | 'completed';
  startTime: number;
}

export interface TaskItem {
  id: string;
  description: string;
  status: 'pending' | 'in_progress' | 'completed' | 'verified' | 'blocked';
  priority?: string;
  dependencies?: string[];
}

// ============================================================================
// Store
// ============================================================================

interface MessageStoreState {
  /** Per-agent chronological message arrays */
  messages: Record<string, ChannelMessage[]>;
  /** Agent order (mirrors agentStore) */
  agentOrder: string[];
  /** Agent models for display */
  agentModels: Record<string, string>;
  /** Current round number per agent */
  currentRound: Record<string, number>;
  /** Track pending tool calls (tool_call without result yet) */
  pendingToolCalls: Record<string, string | undefined>;
  /** Active subagent threads */
  threads: ThreadInfo[];
  /** Current coordination phase (from phase_change events) */
  currentPhase: string | null;
  /** Per-agent task plans extracted from planning tool results */
  taskPlans: Record<string, TaskItem[]>;
  /** Monotonic counter for message IDs */
  _counter: number;
}

interface MessageStoreActions {
  processWSEvent: (event: WSEvent) => void;
  getMessages: (agentId: string) => ChannelMessage[];
  reset: () => void;
}

const initialState: MessageStoreState = {
  messages: {},
  agentOrder: [],
  agentModels: {},
  currentRound: {},
  pendingToolCalls: {},
  threads: [],
  currentPhase: null,
  taskPlans: {},
  _counter: 0,
};

export const useMessageStore = create<MessageStoreState & MessageStoreActions>(
  (set, get) => ({
    ...initialState,

    getMessages: (agentId: string) => {
      return get().messages[agentId] || [];
    },

    reset: () => set(initialState),

    processWSEvent: (event: WSEvent) => {
      const state = get();

      switch (event.type) {
        case 'init': {
          if ('agents' in event && 'question' in event) {
            const msgs: Record<string, ChannelMessage[]> = {};
            const rounds: Record<string, number> = {};
            const models: Record<string, string> = {};

            (event.agents as string[]).forEach((id: string) => {
              // The backend emits round_start for each real round.
              // Keep init empty so startup does not fabricate a duplicate Round 1.
              msgs[id] = [];
              rounds[id] = 0;
            });

            if ('agent_models' in event && event.agent_models) {
              const agentModels = event.agent_models as Record<string, string>;
              Object.entries(agentModels).forEach(([id, model]) => {
                models[id] = model;
              });
            }

            set({
              messages: msgs,
              agentOrder: event.agents as string[],
              agentModels: models,
              currentRound: rounds,
              pendingToolCalls: {},
              currentPhase: null,
              taskPlans: {},
              _counter: 0,
            });
          }
          break;
        }

        // ================================================================
        // Structured events from EventEmitter (clean, typed, no MCP noise)
        // These replace agent_content/tool_call/tool_result for the v2 UI
        // ================================================================
        case 'structured_event' as string: {
          const se = event as unknown as {
            event_type: string;
            agent_id: string | null;
            round_number?: number;
            data: Record<string, unknown>;
            timestamp: number;
          };
          // Handle events that don't require an agent_id first
          if (se.event_type === 'phase_change') {
            const phase = (se.data.phase as string) || '';
            console.log('[v2 messageStore] phase_change:', phase, se.data);
            set({ currentPhase: phase || null });
            break;
          }

          // Checkpoint activation: dynamically create channels for participants
          if (se.event_type === 'checkpoint_activated') {
            const participants = (se.data.participants as Record<string, { real_agent_id: string; model: string }>) || {};
            const checkpointNumber = (se.data.checkpoint_number as number) || 1;
            const mainAgentId = (se.data.main_agent_id as string) || '';
            const newMessages = { ...state.messages };
            const newOrder = [...state.agentOrder];
            const newModels = { ...state.agentModels };
            const newRounds = { ...state.currentRound };

            for (const [displayId, info] of Object.entries(participants)) {
              if (!newMessages[displayId]) {
                newMessages[displayId] = [];
                newRounds[displayId] = 0;
                if (info.model) newModels[displayId] = info.model;
                // Insert after the real agent in the order
                const realIdx = newOrder.indexOf(info.real_agent_id);
                if (realIdx >= 0 && !newOrder.includes(displayId)) {
                  newOrder.splice(realIdx + 1, 0, displayId);
                } else if (!newOrder.includes(displayId)) {
                  newOrder.push(displayId);
                }
              }
            }

            // Add a delegation notice to the main agent's original channel
            if (mainAgentId && state.messages[mainAgentId]) {
              const task = (se.data.task as string) || '';
              const notice: ContentMessage = {
                id: `msg-${state._counter}`,
                type: 'content',
                agentId: mainAgentId,
                timestamp: se.timestamp,
                content: `📋 Checkpoint #${checkpointNumber} — delegated to team: ${task.slice(0, 120)}...`,
                contentType: 'text',
              };
              newMessages[mainAgentId] = [...(newMessages[mainAgentId] || []), notice];
            }

            set({
              messages: newMessages,
              agentOrder: newOrder,
              agentModels: newModels,
              currentRound: newRounds,
              _counter: state._counter + 1,
            });
            console.log('[v2 messageStore] checkpoint_activated: created channels for', Object.keys(participants));
            break;
          }

          // Checkpoint completed: add summary to main agent's channel
          if (se.event_type === 'checkpoint_completed') {
            const mainAgentId = (se.data.main_agent_id as string) || '';
            const consensus = (se.data.consensus as string) || '';
            const checkpointNumber = (se.data.checkpoint_number as number) || 1;
            if (mainAgentId && state.messages[mainAgentId]) {
              const notice: ContentMessage = {
                id: `msg-${state._counter}`,
                type: 'content',
                agentId: mainAgentId,
                timestamp: se.timestamp,
                content: `✅ Checkpoint #${checkpointNumber} completed. ${consensus ? 'Consensus: ' + consensus.slice(0, 200) + '...' : ''}`,
                contentType: 'text',
              };
              set({
                messages: { ...state.messages, [mainAgentId]: [...(state.messages[mainAgentId] || []), notice] },
                _counter: state._counter + 1,
              });
            }
            break;
          }

          if (!se.agent_id || !state.messages[se.agent_id]) break;
          const agentId = se.agent_id;
          const existing = state.messages[agentId] || [];

          switch (se.event_type) {
            case 'text': {
              const content = (se.data.content as string) || '';
              if (!content) break;
              // Coalesce consecutive text messages
              const lastMsg = existing[existing.length - 1];
              if (lastMsg && lastMsg.type === 'content' && (lastMsg as ContentMessage).contentType === 'text') {
                const updated = [...existing];
                updated[updated.length - 1] = {
                  ...lastMsg,
                  content: (lastMsg as ContentMessage).content + '\n' + content,
                } as ContentMessage;
                set({ messages: { ...state.messages, [agentId]: updated } });
              } else {
                const msg: ContentMessage = {
                  id: `msg-${state._counter}`,
                  type: 'content',
                  agentId,
                  timestamp: se.timestamp,
                  content,
                  contentType: 'text',
                };
                set({
                  messages: { ...state.messages, [agentId]: [...existing, msg] },
                  _counter: state._counter + 1,
                });
              }
              break;
            }

            case 'thinking': {
              const content = (se.data.content as string) || '';
              if (!content) break;
              const msg: ContentMessage = {
                id: `msg-${state._counter}`,
                type: 'content',
                agentId,
                timestamp: se.timestamp,
                content,
                contentType: 'thinking',
              };
              set({
                messages: { ...state.messages, [agentId]: [...existing, msg] },
                _counter: state._counter + 1,
              });
              break;
            }

            case 'tool_start': {
              const toolId = (se.data.tool_id as string) || undefined;
              const toolName = (se.data.tool_name as string) || 'unknown';
              const args = (se.data.args as Record<string, unknown>) || {};
              const msg: ToolCallMessage = {
                id: `msg-${state._counter}`,
                type: 'tool-call',
                agentId,
                timestamp: se.timestamp,
                toolId,
                toolName,
                args,
              };
              set({
                messages: { ...state.messages, [agentId]: [...existing, msg] },
                pendingToolCalls: { ...state.pendingToolCalls, [agentId]: toolId },
                _counter: state._counter + 1,
              });
              break;
            }

            case 'tool_complete': {
              const toolId = (se.data.tool_id as string) || undefined;
              const toolName = (se.data.tool_name as string) || '';
              const result = (se.data.result as string) || '';
              const elapsed = se.data.elapsed_seconds as number | undefined;
              const updated = [...existing];
              for (let i = updated.length - 1; i >= 0; i--) {
                const msg = updated[i];
                if (msg.type === 'tool-call') {
                  const tc = msg as ToolCallMessage;
                  if ((toolId && tc.toolId === toolId) || (!toolId && tc.result === undefined)) {
                    updated[i] = {
                      ...tc,
                      result,
                      success: true,
                      elapsed: elapsed ? elapsed * 1000 : undefined,
                    };
                    break;
                  }
                }
              }

              // Extract task plan from planning tool results
              const isCreatePlan = toolName.endsWith('create_task_plan');
              const isUpdateStatus = toolName.endsWith('update_task_status');
              const isEditTask = toolName.endsWith('edit_task') || toolName.endsWith('add_task');
              let newTaskPlan: TaskItem[] | undefined;
              if ((isCreatePlan || isUpdateStatus || isEditTask) && result) {
                try {
                  const resultData = JSON.parse(result);
                  if (isCreatePlan && resultData.tasks && Array.isArray(resultData.tasks)) {
                    // create_task_plan: full tasks array in result
                    newTaskPlan = resultData.tasks.map((t: Record<string, unknown>) => ({
                      id: String(t.id || ''),
                      description: String(t.description || ''),
                      status: String(t.status || 'pending') as TaskItem['status'],
                      priority: t.priority ? String(t.priority) : undefined,
                      dependencies: Array.isArray(t.dependencies) ? t.dependencies.map(String) : undefined,
                    }));
                  } else if (isUpdateStatus && resultData.task) {
                    // update_task_status: patch existing plan with updated task
                    const updatedTask = resultData.task as Record<string, unknown>;
                    const taskId = String(updatedTask.id || '');
                    const existingPlan = [...(state.taskPlans[agentId] || [])];
                    const idx = existingPlan.findIndex((t) => t.id === taskId);
                    if (idx >= 0) {
                      existingPlan[idx] = {
                        ...existingPlan[idx],
                        status: String(updatedTask.status || existingPlan[idx].status) as TaskItem['status'],
                        description: updatedTask.description ? String(updatedTask.description) : existingPlan[idx].description,
                      };
                      newTaskPlan = existingPlan;
                    }
                  } else if (isEditTask && resultData.tasks && Array.isArray(resultData.tasks)) {
                    // add_task/edit_task: full tasks array
                    newTaskPlan = resultData.tasks.map((t: Record<string, unknown>) => ({
                      id: String(t.id || ''),
                      description: String(t.description || ''),
                      status: String(t.status || 'pending') as TaskItem['status'],
                      priority: t.priority ? String(t.priority) : undefined,
                      dependencies: Array.isArray(t.dependencies) ? t.dependencies.map(String) : undefined,
                    }));
                  }
                } catch (e) {
                  console.warn('[v2 messageStore] Failed to parse planning tool result:', e, result?.slice(0, 200));
                }
              }

              set({
                messages: { ...state.messages, [agentId]: updated },
                ...(newTaskPlan !== undefined ? { taskPlans: { ...state.taskPlans, [agentId]: newTaskPlan } } : {}),
              });
              break;
            }

            case 'round_start': {
              const roundNum = se.round_number !== undefined
                ? se.round_number + 1
                : (state.currentRound[agentId] || 0) + 1;
              if (roundNum <= (state.currentRound[agentId] || 0)) break;
              const divider: RoundDividerMessage = {
                id: `msg-${state._counter}`,
                type: 'round-divider',
                agentId,
                timestamp: se.timestamp,
                roundNumber: roundNum,
                label: `Round ${roundNum}`,
              };
              set({
                messages: { ...state.messages, [agentId]: [...existing, divider] },
                currentRound: { ...state.currentRound, [agentId]: roundNum },
                _counter: state._counter + 1,
              });
              break;
            }

            case 'answer_submitted': {
              const rawAnswerLabel = (se.data.answer_label as string) || '';
              const answerNumber = (se.data.answer_number as number) || 1;
              const content = (se.data.content as string) || '';
              const contentPreview = content.slice(0, 200);
              const agentIndex = state.agentOrder.indexOf(agentId) + 1;
              const answerLabel = rawAnswerLabel || `answer${agentIndex}.${answerNumber}`;
              const alreadyRecorded = existing.some(
                (message) =>
                  message.type === 'answer' &&
                  (
                    (message as AnswerMessage).answerLabel === answerLabel ||
                    (
                      (message as AnswerMessage).answerNumber === answerNumber &&
                      (message as AnswerMessage).contentPreview === contentPreview
                    )
                  )
              );
              if (alreadyRecorded) break;
              const msg: AnswerMessage = {
                id: `msg-${state._counter}`,
                type: 'answer',
                agentId,
                timestamp: se.timestamp,
                answerLabel,
                answerNumber,
                contentPreview,
              };
              set({
                messages: { ...state.messages, [agentId]: [...existing, msg] },
                _counter: state._counter + 1,
              });
              break;
            }

            case 'vote': {
              const targetId = (se.data.target_id as string) || (se.data.voted_for as string) || '';
              const reason = ((se.data.reason as string) || '').trim();
              const targetModel = state.agentModels[targetId];
              const voteRound = state.currentRound[agentId] || se.round_number || 0;
              const alreadyRecorded = existing.some(
                (message) =>
                  message.type === 'vote' &&
                  (message as VoteMessage).voteRound === voteRound &&
                  (message as VoteMessage).targetId === targetId &&
                  (message as VoteMessage).reason === reason
              );
              if (alreadyRecorded) break;
              const existingVotes = existing.filter((m) => m.type === 'vote').length;
              const agentIndex = state.agentOrder.indexOf(agentId) + 1;
              const voteLabel = `vote${agentIndex}.${existingVotes + 1}`;
              const msg: VoteMessage = {
                id: `msg-${state._counter}`,
                type: 'vote',
                agentId,
                timestamp: se.timestamp,
                targetId,
                targetName: targetModel ? `${targetId} (${targetModel})` : targetId,
                reason,
                voteLabel,
                voteRound,
              };
              set({
                messages: { ...state.messages, [agentId]: [...existing, msg] },
                _counter: state._counter + 1,
              });
              break;
            }

            case 'error': {
              const message = (se.data.message as string) || (se.data.error as string) || 'Unknown error';
              const msg: ErrorMessage = {
                id: `msg-${state._counter}`,
                type: 'error',
                agentId,
                timestamp: se.timestamp,
                message,
              };
              set({
                messages: { ...state.messages, [agentId]: [...existing, msg] },
                _counter: state._counter + 1,
              });
              break;
            }

            // Ignore structured events we don't need to render
            default:
              break;
          }
          break;
        }

        // ================================================================
        // Legacy display events (kept for backward compat / v1 UI)
        // The v2 UI prefers structured_event above, but falls back to
        // these if the EventEmitter bridge isn't active
        // ================================================================
        case 'agent_content': {
          // Skip if we're getting structured_events (they're cleaner)
          // We detect this by checking if we've seen any structured text/tool events
          if ('agent_id' in event && 'content' in event) {
            const agentId = event.agent_id as string;
            const existing = state.messages[agentId] || [];
            // If we already have structured messages, skip agent_content
            if (existing.some(m => m.type === 'tool-call' || (m.type === 'content' && !(m as ContentMessage).content.includes('MCP:')))) {
              break;
            }
            const content = event.content as string;
            const contentType = ('content_type' in event ? event.content_type : 'thinking') as string;

            // Coalesce consecutive content messages of the same type
            const lastMsg = existing[existing.length - 1];
            if (lastMsg && lastMsg.type === 'content' && (lastMsg as ContentMessage).contentType === contentType) {
              const updated = [...existing];
              updated[updated.length - 1] = {
                ...lastMsg,
                content: (lastMsg as ContentMessage).content + content,
              } as ContentMessage;
              set({
                messages: { ...state.messages, [agentId]: updated },
              });
            } else {
              const msg: ContentMessage = {
                id: `msg-${state._counter}`,
                type: 'content',
                agentId,
                timestamp: event.timestamp,
                content,
                contentType: contentType as 'thinking' | 'tool' | 'status',
              };
              set({
                messages: { ...state.messages, [agentId]: [...existing, msg] },
                _counter: state._counter + 1,
              });
            }
          }
          break;
        }

        // Legacy tool_call/tool_result — ignored when structured_event is active
        case 'tool_call':
        case 'tool_result':
          break;

        case 'hook_execution': {
          const hookEv = event as unknown as {
            agent_id: string;
            tool_call_id?: string;
            hook_info: HookExecutionInfo;
          };
          if (!hookEv.agent_id || !state.messages[hookEv.agent_id]) break;
          const hookAgentId = hookEv.agent_id;
          const hookExisting = [...(state.messages[hookAgentId] || [])];
          const hookInfo = hookEv.hook_info;
          const toolCallId = hookEv.tool_call_id;

          // Find the matching tool call — scan backwards
          let found = false;
          for (let i = hookExisting.length - 1; i >= 0; i--) {
            const msg = hookExisting[i];
            if (msg.type !== 'tool-call') continue;
            const tc = msg as ToolCallMessage;
            if (toolCallId && tc.toolId === toolCallId) {
              // Exact match by tool_call_id
              const arrKey = hookInfo.hook_type === 'pre' ? 'preHooks' : 'postHooks';
              hookExisting[i] = {
                ...tc,
                [arrKey]: [...(tc[arrKey] || []), hookInfo],
              };
              found = true;
              break;
            } else if (!toolCallId) {
              // No tool_call_id — attach to most recent tool call
              const arrKey = hookInfo.hook_type === 'pre' ? 'preHooks' : 'postHooks';
              hookExisting[i] = {
                ...tc,
                [arrKey]: [...(tc[arrKey] || []), hookInfo],
              };
              found = true;
              break;
            }
          }

          if (found) {
            set({ messages: { ...state.messages, [hookAgentId]: hookExisting } });
          }
          break;
        }

        case 'new_answer': {
          if ('agent_id' in event && 'content' in event) {
            const agentId = event.agent_id as string;
            const answerNumber = ('answer_number' in event ? event.answer_number : 1) as number;
            const answerLabel = ('answer_label' in event ? event.answer_label : undefined) as string | undefined;
            const agentIndex = state.agentOrder.indexOf(agentId) + 1;
            const label = answerLabel || `answer${agentIndex}.${answerNumber}`;
            const content = event.content as string;
            const contentPreview = content.slice(0, 200);

            const existing = state.messages[agentId] || [];
            const alreadyRecorded = existing.some(
              (message) =>
                message.type === 'answer' &&
                (
                  (message as AnswerMessage).answerLabel === label ||
                  (
                    (message as AnswerMessage).answerNumber === answerNumber &&
                    (message as AnswerMessage).contentPreview === contentPreview
                  )
                )
            );
            if (alreadyRecorded) {
              break;
            }
            const msg: AnswerMessage = {
              id: `msg-${state._counter}`,
              type: 'answer',
              agentId,
              timestamp: event.timestamp < 1e12 ? event.timestamp * 1000 : event.timestamp,
              answerLabel: label,
              answerNumber,
              contentPreview,
            };
            set({
              messages: { ...state.messages, [agentId]: [...existing, msg] },
              _counter: state._counter + 1,
            });
          }
          break;
        }

        case 'vote_cast': {
          if ('voter_id' in event && 'target_id' in event) {
            const voterId = event.voter_id as string;
            const targetId = event.target_id as string;
            const reason = (('reason' in event ? event.reason : '') as string).trim();
            const agentIndex = state.agentOrder.indexOf(voterId) + 1;
            const existing = state.messages[voterId] || [];
            const voteRound = state.currentRound[voterId] || 0;
            const alreadyRecorded = existing.some(
              (message) =>
                message.type === 'vote' &&
                (message as VoteMessage).voteRound === voteRound &&
                (message as VoteMessage).targetId === targetId &&
                (message as VoteMessage).reason === reason
            );
            if (alreadyRecorded) {
              break;
            }

            // Count existing votes for this agent to determine vote number
            const existingVotes = existing.filter((m) => m.type === 'vote').length;
            const voteLabel = `vote${agentIndex}.${existingVotes + 1}`;

            const targetModel = state.agentModels[targetId];
            const msg: VoteMessage = {
              id: `msg-${state._counter}`,
              type: 'vote',
              agentId: voterId,
              timestamp: event.timestamp,
              targetId,
              targetName: targetModel ? `${targetId} (${targetModel})` : targetId,
              reason,
              voteLabel,
              voteRound,
            };
            set({
              messages: { ...state.messages, [voterId]: [...existing, msg] },
              _counter: state._counter + 1,
            });
          }
          break;
        }

        case 'restart': {
          // restart is a session-level banner; the backend's round_start events
          // are the source of truth for per-agent round dividers.
          break;
        }

        case 'agent_status': {
          if ('agent_id' in event && 'status' in event) {
            const agentId = event.agent_id as string;
            const status = event.status as string;
            const existing = state.messages[agentId] || [];
            const msg: StatusMessage = {
              id: `msg-${state._counter}`,
              type: 'status',
              agentId,
              timestamp: event.timestamp,
              status,
            };
            set({
              messages: { ...state.messages, [agentId]: [...existing, msg] },
              _counter: state._counter + 1,
            });
          }
          break;
        }

        case 'error': {
          if ('message' in event) {
            const agentId = ('agent_id' in event ? event.agent_id : '__global__') as string;
            const existing = state.messages[agentId] || [];
            const msg: ErrorMessage = {
              id: `msg-${state._counter}`,
              type: 'error',
              agentId,
              timestamp: event.timestamp,
              message: event.message as string,
            };
            set({
              messages: { ...state.messages, [agentId]: [...existing, msg] },
              _counter: state._counter + 1,
            });
          }
          break;
        }

        // Subagent events
        case 'subagent_spawn' as string: {
          const ev = event as { agent_id: string; subagent_ids?: string[]; task?: string; call_id?: string };
          if (ev.agent_id) {
            const agentId = ev.agent_id;
            const existing = state.messages[agentId] || [];
            const msg: SubagentSpawnMessage = {
              id: `msg-${state._counter}`,
              type: 'subagent-spawn',
              agentId,
              timestamp: event.timestamp,
              subagentIds: ev.subagent_ids || [],
              task: ev.task || '',
              callId: ev.call_id || '',
            };
            const newThreads = (ev.subagent_ids || []).map((sid: string) => ({
              id: sid,
              parentAgentId: agentId,
              task: ev.task || '',
              status: 'running' as const,
              startTime: event.timestamp,
            }));
            // Initialize message arrays for subagent IDs so their
            // structured_event messages are stored instead of dropped
            const newMessages = { ...state.messages, [agentId]: [...existing, msg] };
            for (const sid of ev.subagent_ids || []) {
              if (!newMessages[sid]) {
                newMessages[sid] = [];
              }
            }
            set({
              messages: newMessages,
              threads: [...state.threads, ...newThreads],
              _counter: state._counter + 1,
            });
          }
          break;
        }

        case 'subagent_started' as string: {
          const ev = event as unknown as { agent_id: string; subagent_id: string; task?: string; timeout_seconds?: number; timestamp: number };
          if (ev.agent_id && ev.subagent_id) {
            const agentId = ev.agent_id;
            const existing = state.messages[agentId] || [];
            const msg: SubagentStartedMessage = {
              id: `msg-${state._counter}`,
              type: 'subagent-started',
              agentId,
              timestamp: event.timestamp,
              subagentId: ev.subagent_id,
              task: ev.task || '',
              timeoutSeconds: ev.timeout_seconds || 300,
            };
            // Add thread if not already tracked
            const existingThread = state.threads.find((t) => t.id === ev.subagent_id);
            const newThreads = existingThread ? state.threads : [
              ...state.threads,
              {
                id: ev.subagent_id,
                parentAgentId: agentId,
                task: ev.task || '',
                status: 'running' as const,
                startTime: event.timestamp,
              },
            ];
            // Initialize message array for subagent ID
            const newMessages = { ...state.messages, [agentId]: [...existing, msg] };
            if (!newMessages[ev.subagent_id]) {
              newMessages[ev.subagent_id] = [];
            }
            set({
              messages: newMessages,
              threads: newThreads,
              _counter: state._counter + 1,
            });
          }
          break;
        }

        case 'final_answer':
        case 'coordination_complete': {
          // Insert a completion marker into all agent channels
          const newMsgs = { ...state.messages };
          let ctr = state._counter;
          const selectedId = 'selected_agent' in event
            ? (event as unknown as Record<string, unknown>).selected_agent as string
            : undefined;

          state.agentOrder.forEach((aid) => {
            const msgs = newMsgs[aid] || [];
            // Avoid duplicate completion markers
            if (msgs.length > 0 && msgs[msgs.length - 1].type === 'completion') return;
            const msg: CompletionMessage = {
              id: `msg-${ctr++}`,
              type: 'completion',
              agentId: aid,
              timestamp: event.timestamp || Date.now(),
              label: 'Complete',
              selectedAgent: selectedId,
            };
            newMsgs[aid] = [...msgs, msg];
          });
          set({ messages: newMsgs, _counter: ctr });
          break;
        }

        case 'broadcast_sent' as string: {
          const broadcastMsg = (event as unknown as { message: string }).message || '';
          const broadcastTargets = (event as unknown as { targets: string[] | null }).targets;
          const now = Date.now();
          const newMsgs = { ...state.messages };
          let ctr = state._counter;

          // Determine which agents receive the broadcast message
          const targetAgents = broadcastTargets
            ? broadcastTargets.filter((t) => state.messages[t] !== undefined)
            : state.agentOrder;

          for (const aid of targetAgents) {
            const msgs = newMsgs[aid] || [];
            const msg: BroadcastMessage = {
              id: `msg-${ctr++}`,
              type: 'broadcast',
              agentId: aid,
              timestamp: now,
              content: broadcastMsg,
              targets: broadcastTargets,
            };
            newMsgs[aid] = [...msgs, msg];
          }

          set({ messages: newMsgs, _counter: ctr });
          break;
        }

        // Events handled by agentStore only (no message for channel view)
        case 'state_snapshot': {
          const snapshot = event as {
            current_phase?: string;
          };
          set({ currentPhase: snapshot.current_phase || null });
          break;
        }

        case 'consensus_reached':
        case 'done':
        case 'init_status':
        case 'preparation_status':
        case 'vote_distribution':
        case 'orchestrator_event':
        case 'timeout_status':
        case 'file_change':
          // These don't produce channel messages
          break;

        default:
          break;
      }
    },
  })
);
