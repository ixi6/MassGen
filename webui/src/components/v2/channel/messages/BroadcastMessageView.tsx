import type { BroadcastMessage } from '../../../../stores/v2/messageStore';

interface BroadcastMessageViewProps {
  message: BroadcastMessage;
}

export function BroadcastMessageView({ message }: BroadcastMessageViewProps) {
  const targetLabel = message.targets
    ? message.targets.join(', ')
    : 'all agents';

  return (
    <div className="v2-step-group py-0.5">
      <div className="v2-step-node" />
      <div className="flex items-center gap-2 rounded px-2 py-1.5 bg-purple-500/5 border border-purple-500/20">
        <span className="text-purple-400 shrink-0">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 4l6 4 6-4" strokeLinecap="round" strokeLinejoin="round" />
            <rect x="1" y="3" width="14" height="10" rx="1.5" />
          </svg>
        </span>
        <span className="text-xs font-medium text-purple-400 shrink-0">Broadcast</span>
        <span className="text-xs text-v2-text-muted shrink-0">
          to {targetLabel}
        </span>
        <span className="text-xs text-v2-text-secondary truncate ml-1">
          — {message.content}
        </span>
      </div>
    </div>
  );
}
