import { useRef, useEffect, useMemo, useState } from 'react';
import { cn } from '../../../lib/utils';
import { useAgentStore } from '../../../stores/agentStore';
import { useMessageStore, type ChannelMessage, type ToolCallMessage, type ContentMessage } from '../../../stores/v2/messageStore';
import { useTileStore } from '../../../stores/v2/tileStore';
import { getAgentColor } from '../../../utils/agentColors';
import { MessageRenderer } from './messages/MessageRenderer';
import { ToolBatchView } from './messages/ToolBatchView';
import { ModeBar } from './ModeBar';
import { TaskPlanPanel } from './TaskPlanPanel';
import { StreamingIndicator } from './StreamingIndicator';
import { FinalAnswerSection } from './FinalAnswerSection';
import { TileDragHandle } from '../tiles/TileDragHandle';
import { useTileDrag } from '../tiles/TileDragContext';

interface AgentChannelProps {
  agentId: string;
}

export function AgentChannel({ agentId }: AgentChannelProps) {
  const agent = useAgentStore((s) => s.agents[agentId]);
  const agentOrder = useAgentStore((s) => s.agentOrder);
  const messages = useMessageStore((s) => s.messages[agentId] || []);
  const scrollRef = useRef<HTMLDivElement>(null);
  const isAutoScrollRef = useRef(true);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    const el = scrollRef.current;
    if (el && isAutoScrollRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages.length]);

  // Track if user has scrolled up (disable auto-scroll)
  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    isAutoScrollRef.current = atBottom;
  };

  // Inline status indicator — shows at bottom of message stream while agent is active
  const lastMsg = messages[messages.length - 1];
  const lastIsPending = lastMsg?.type === 'tool-call' && lastMsg.result === undefined;
  const isDone = agent?.status === 'completed' || agent?.status === 'failed';
  const statusLabel: Record<string, string> = {
    working: 'Generating',
    voting: 'Evaluating',
    waiting: 'Waiting',
  };
  const streamingLabel = statusLabel[agent?.status ?? ''] ?? '';
  // Show when not done and not on a pending tool call (tool spinner handles that)
  const showStreaming = !isDone && !lastIsPending && messages.length > 0;

  if (!agent) {
    return (
      <div className="flex items-center justify-center h-full text-v2-text-muted text-sm">
        Agent not found: {agentId}
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Channel header */}
      <ChannelHeader agentId={agentId} agent={agent} agentOrder={agentOrder} />

      {/* Mode bar */}
      <ModeBar />

      {/* Message stream + docked plan strip */}
      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* Messages */}
        <div className="flex-1 min-w-0">
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="h-full overflow-y-auto v2-scrollbar"
          >
            {messages.length === 0 ? (
              <div className="flex items-center justify-center h-full">
                <div className="text-center space-y-3 animate-v2-welcome-fade-in">
                  <div className="w-12 h-12 mx-auto rounded-full border-2 border-v2-accent/20 flex items-center justify-center">
                    {agent.status === 'working' ? (
                      <div className="w-8 h-8 rounded-full border-2 border-v2-border border-t-v2-accent animate-spin" />
                    ) : (
                      <div className="w-3 h-3 rounded-full bg-v2-accent/40 animate-pulse" />
                    )}
                  </div>
                  <p className="text-sm text-v2-text-secondary">
                    {agent.status === 'working' ? 'Preparing response...' : 'Connecting to agent...'}
                  </p>
                  <div className="flex justify-center gap-1">
                    <span className="w-1 h-1 rounded-full bg-v2-text-muted streaming-dot" style={{ animationDelay: '0s' }} />
                    <span className="w-1 h-1 rounded-full bg-v2-text-muted streaming-dot" style={{ animationDelay: '0.15s' }} />
                    <span className="w-1 h-1 rounded-full bg-v2-text-muted streaming-dot" style={{ animationDelay: '0.3s' }} />
                  </div>
                </div>
              </div>
            ) : (
              <div className="py-1 v2-timeline-spine">
                <GroupedMessages messages={messages} />
              </div>
            )}

            <StreamingIndicator visible={showStreaming} label={streamingLabel} />

            {/* Final answer rendered inline at bottom of stream */}
            <FinalAnswerSection />
          </div>
        </div>

        {/* Plan — docked right strip */}
        <TaskPlanPanel agentId={agentId} />
      </div>
    </div>
  );
}

// ============================================================================
// Channel Header
// ============================================================================

interface ChannelHeaderProps {
  agentId: string;
  agent: { status: string; modelName?: string };
  agentOrder: string[];
}

function ChannelHeader({ agentId, agent, agentOrder }: ChannelHeaderProps) {
  const setAutofitTiles = useTileStore((s) => s.setAutofitTiles);
  const isAutofit = useTileStore((s) => s.autofit);
  const { isDraggable } = useTileDrag();
  const agentColor = getAgentColor(agentId, agentOrder);
  const agentIndex = agentOrder.indexOf(agentId);

  const handleAutofit = () => {
    if (isAutofit) {
      // Toggle back to single view — set first agent
      useTileStore.getState().setTile({
        id: `channel-${agentOrder[0]}`,
        type: 'agent-channel',
        targetId: agentOrder[0],
        label: agentOrder[0],
      });
    } else {
      // Show all agents
      const allTiles = agentOrder.map((id) => ({
        id: `channel-${id}`,
        type: 'agent-channel' as const,
        targetId: id,
        label: id,
      }));
      setAutofitTiles(allTiles);
    }
  };

  return (
    <div
      className="flex items-center gap-3 px-4 py-2.5 border-b border-v2-border-subtle bg-v2-surface shrink-0"
      style={{ borderLeftWidth: '3px', borderLeftColor: agentColor.hex }}
    >
      {/* Drag handle — before numbered badge */}
      {isDraggable && <TileDragHandle />}

      {/* Numbered color badge */}
      <span
        className="flex items-center justify-center w-5 h-5 rounded text-[11px] font-bold text-white shrink-0"
        style={{ backgroundColor: agentColor.hex }}
      >
        {agentIndex + 1}
      </span>

      {/* Agent name */}
      <span className="font-medium text-sm text-v2-text">
        {agentId.replace(/_/g, ' ')}
      </span>

      {/* Model badge */}
      {agent.modelName && (
        <span className="text-[11px] text-v2-text-muted bg-v2-surface-raised px-1.5 py-0.5 rounded border border-v2-border-subtle">
          {agent.modelName}
        </span>
      )}

      {/* Status */}
      <StatusBadge status={agent.status} />

      <div className="flex-1" />

      {/* Autofit button */}
      {agentOrder.length > 1 && (
        <button
          onClick={handleAutofit}
          className={cn(
            'flex items-center gap-1.5 text-xs px-2 py-1 rounded',
            'text-v2-text-muted hover:text-v2-text hover:bg-v2-sidebar-hover',
            'transition-colors duration-150',
            isAutofit && 'bg-v2-accent/10 text-v2-accent'
          )}
          title={isAutofit ? 'Single agent view' : 'See all agents'}
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="2" y="2" width="5" height="12" rx="1" />
            <rect x="9" y="2" width="5" height="12" rx="1" />
          </svg>
          {isAutofit ? 'Single' : 'Autofit'}
        </button>
      )}
    </div>
  );
}

// ============================================================================
// Grouped Message Rendering — batches consecutive tool calls
// ============================================================================

/** Planning tools that should be hidden (shown in TaskPlanPanel instead) */
const PLAN_TOOLS = ['create_task_plan', 'update_task_status', 'add_task', 'edit_task'];

function isVisibleToolCall(msg: ChannelMessage): boolean {
  if (msg.type !== 'tool-call') return false;
  return !PLAN_TOOLS.some((pt) => (msg as ToolCallMessage).toolName.endsWith(pt));
}

type RenderItem =
  | { kind: 'message'; message: ChannelMessage }
  | { kind: 'batch'; tools: ToolCallMessage[] }
  | { kind: 'thinking-group'; messages: ContentMessage[] };

function isThinking(msg: ChannelMessage): msg is ContentMessage {
  return msg.type === 'content' && (msg as ContentMessage).contentType === 'thinking';
}

function GroupedMessages({ messages }: { messages: ChannelMessage[] }) {
  const items = useMemo(() => {
    const result: RenderItem[] = [];
    let toolBatch: ToolCallMessage[] = [];
    let thinkBatch: ContentMessage[] = [];

    const flushTools = () => {
      if (toolBatch.length === 0) return;
      if (toolBatch.length === 1) {
        result.push({ kind: 'message', message: toolBatch[0] });
      } else {
        result.push({ kind: 'batch', tools: [...toolBatch] });
      }
      toolBatch = [];
    };

    const flushThinking = () => {
      if (thinkBatch.length === 0) return;
      if (thinkBatch.length === 1) {
        result.push({ kind: 'message', message: thinkBatch[0] });
      } else {
        result.push({ kind: 'thinking-group', messages: [...thinkBatch] });
      }
      thinkBatch = [];
    };

    for (const msg of messages) {
      if (msg.type === 'tool-call' && !isVisibleToolCall(msg)) continue;

      if (msg.type === 'tool-call') {
        flushThinking();
        toolBatch.push(msg as ToolCallMessage);
      } else if (isThinking(msg)) {
        flushTools();
        thinkBatch.push(msg);
      } else {
        flushTools();
        flushThinking();
        result.push({ kind: 'message', message: msg });
      }
    }
    flushTools();
    flushThinking();

    return result;
  }, [messages]);

  return (
    <>
      {items.map((item) => {
        if (item.kind === 'batch') {
          return <ToolBatchView key={item.tools[0].id} tools={item.tools} />;
        }
        if (item.kind === 'thinking-group') {
          return <MergedThinkingView key={item.messages[0].id} messages={item.messages} />;
        }
        return <MessageRenderer key={item.message.id} message={item.message} />;
      })}
    </>
  );
}

/** Merged view for consecutive reasoning blocks */
function MergedThinkingView({ messages }: { messages: ContentMessage[] }) {
  const [expanded, setExpanded] = useState(false);
  const allContent = messages.map((m) => m.content.trim()).join('\n\n');
  const preview = messages[0].content.trim().split('\n')[0];
  const previewTruncated = preview.length > 80 ? preview.slice(0, 77) + '\u2026' : preview;

  return (
    <div
      className={cn('v2-reasoning-block cursor-pointer', expanded && 'v2-reasoning-expanded')}
      onClick={() => setExpanded(!expanded)}
    >
      <div className="v2-reasoning-node" />
      <div className={cn('v2-reasoning-row flex items-start gap-1.5')}>
        <svg
          className="v2-hover-chevron w-2.5 h-2.5 shrink-0 text-v2-text-muted"
          style={{ marginLeft: '-14px', marginRight: '-5px', marginTop: '4px' }}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M4 2l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {!expanded && (
          <span className="text-xs text-v2-text-muted italic opacity-70 truncate">
            {previewTruncated}
            <span className="text-v2-text-muted ml-1 not-italic">×{messages.length}</span>
          </span>
        )}
        {expanded && (
          <pre className="text-xs text-v2-text-muted italic opacity-70 whitespace-pre-wrap leading-relaxed animate-v2-fade-in flex-1 min-w-0 max-h-[300px] overflow-y-auto">
            {allContent}
          </pre>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Status Badge
// ============================================================================

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { color: string; label: string; pulse?: boolean }> = {
    working: { color: 'bg-v2-online', label: 'Working', pulse: true },
    voting: { color: 'bg-v2-idle', label: 'Voting', pulse: true },
    completed: { color: 'bg-v2-offline', label: 'Done' },
    failed: { color: 'bg-red-500', label: 'Failed' },
    waiting: { color: 'bg-v2-offline', label: 'Waiting' },
  };

  const { color, label, pulse } = config[status] || config.waiting;

  return (
    <div className="flex items-center gap-1.5">
      <span className={cn('w-2 h-2 rounded-full', color, pulse && 'animate-pulse')} />
      <span className="text-xs text-v2-text-muted">{label}</span>
      {pulse && (
        <span className="flex gap-0.5">
          <span className="w-1 h-1 rounded-full bg-v2-online streaming-dot" style={{ animationDelay: '0s' }} />
          <span className="w-1 h-1 rounded-full bg-v2-online streaming-dot" style={{ animationDelay: '0.15s' }} />
          <span className="w-1 h-1 rounded-full bg-v2-online streaming-dot" style={{ animationDelay: '0.3s' }} />
        </span>
      )}
    </div>
  );
}
