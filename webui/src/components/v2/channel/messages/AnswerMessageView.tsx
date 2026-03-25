import { useState } from 'react';
import { cn } from '../../../../lib/utils';
import type { AnswerMessage } from '../../../../stores/v2/messageStore';

interface AnswerMessageViewProps {
  message: AnswerMessage;
}

export function AnswerMessageView({ message }: AnswerMessageViewProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="v2-step-group py-1">
      <div className="v2-step-node" />
      <div
        data-testid="answer-card"
        onClick={() => setExpanded(!expanded)}
        className={cn(
          'flex items-start gap-3 rounded-v2-card bg-yellow-500/5 border border-yellow-500/20 px-3 py-2.5',
          'cursor-pointer hover:bg-yellow-500/10 transition-colors duration-150'
        )}
      >
        {/* Star icon */}
        <span className="text-yellow-400 mt-0.5 shrink-0">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 1l2.1 4.2L15 6l-3.5 3.4.8 4.8L8 12l-4.3 2.2.8-4.8L1 6l4.9-.8L8 1z" />
          </svg>
        </span>

        <div className="flex-1 min-w-0">
          {/* Label */}
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-400">
              {message.answerLabel}
            </span>
            <span className="text-xs text-v2-text-muted">submitted</span>
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

          {/* Preview (collapsed) — 3-line clamp */}
          {!expanded && message.contentPreview && (
            <p className="text-sm text-v2-text-secondary line-clamp-3">
              {message.contentPreview}
            </p>
          )}

          {/* Full content (expanded) */}
          {expanded && (
            <div data-testid="answer-expanded" className="animate-v2-fade-in">
              <p className="text-sm text-v2-text whitespace-pre-wrap break-words">
                {message.contentPreview}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
