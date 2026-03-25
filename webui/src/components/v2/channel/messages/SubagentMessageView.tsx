import type { SubagentSpawnMessage, SubagentStartedMessage } from '../../../../stores/v2/messageStore';

interface SubagentSpawnViewProps {
  message: SubagentSpawnMessage;
}

export function SubagentSpawnView({ message }: SubagentSpawnViewProps) {
  return (
    <div className="v2-step-group py-0.5">
      <div className="v2-step-node" />
      <div className="flex items-center gap-2 rounded px-2 py-1.5 bg-cyan-500/5 border border-cyan-500/20">
        <span className="text-cyan-400 shrink-0">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M8 2v4M8 10v4M2 8h4M10 8h4" strokeLinecap="round" />
            <circle cx="8" cy="8" r="2" />
          </svg>
        </span>
        <span className="text-xs font-medium text-cyan-400">Spawning subagents</span>
        {message.subagentIds.length > 0 && (
          <span className="text-xs text-v2-text-muted">
            ({message.subagentIds.length})
          </span>
        )}
        {message.task && (
          <span className="text-xs text-v2-text-muted truncate ml-1">
            — {message.task}
          </span>
        )}
      </div>
    </div>
  );
}

interface SubagentStartedViewProps {
  message: SubagentStartedMessage;
}

export function SubagentStartedView({ message }: SubagentStartedViewProps) {
  return (
    <div className="v2-step-group py-0.5">
      <div className="v2-step-node" />
      <div className="flex items-center gap-2 rounded px-2 py-1.5 bg-teal-500/5 border border-teal-500/20">
        <span className="w-2 h-2 rounded-full bg-v2-online animate-pulse shrink-0" />
        <span className="text-xs font-medium text-teal-400 shrink-0">
          {message.subagentId}
        </span>
        {message.task && (
          <span className="text-xs text-v2-text-muted truncate">
            {message.task}
          </span>
        )}
      </div>
    </div>
  );
}
