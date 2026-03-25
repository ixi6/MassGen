import { useState } from 'react';
import { cn } from '../../../../lib/utils';
import type { VoteMessage } from '../../../../stores/v2/messageStore';

interface VoteMessageViewProps {
  message: VoteMessage;
}

export function VoteMessageView({ message }: VoteMessageViewProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="v2-step-group py-1">
      <div className="v2-step-node" />
      <div
        data-testid="vote-card"
        onClick={() => setExpanded(!expanded)}
        className={cn(
          'flex items-start gap-3 rounded-v2-card bg-violet-500/5 border border-violet-500/20 px-3 py-2.5',
          'cursor-pointer hover:bg-violet-500/10 transition-colors duration-150'
        )}
      >
        {/* Ballot icon */}
        <span className="text-violet-400 mt-0.5 shrink-0">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="2" y="3" width="12" height="10" rx="1.5" />
            <path d="M2 7h12" />
            <path d="M5.5 9.5l1.5 1.5 3-3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-400">
              {message.voteLabel}
            </span>
            <span className="text-sm text-v2-text-secondary">
              Voted for <span className="font-medium text-v2-text">{message.targetName || message.targetId}</span>
            </span>
            <div className="flex-1" />
            {/* Expand indicator */}
            <svg
              className={cn(
                'w-3 h-3 text-v2-text-muted transition-transform duration-150 shrink-0',
                expanded && 'rotate-90'
              )}
              viewBox="0 0 12 12"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M4 2l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>

          {/* Reason preview (collapsed) — 2-line clamp */}
          {!expanded && message.reason && (
            <p className="text-xs text-v2-text-muted mt-1 italic line-clamp-2">
              {message.reason}
            </p>
          )}

          {/* Full reason (expanded) */}
          {expanded && message.reason && (
            <div data-testid="vote-expanded" className="mt-1 animate-v2-fade-in">
              <p className="text-sm text-v2-text-secondary italic whitespace-pre-wrap break-words">
                {message.reason}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
