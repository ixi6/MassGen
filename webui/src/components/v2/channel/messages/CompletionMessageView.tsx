import { cn } from '../../../../lib/utils';
import type { CompletionMessage } from '../../../../stores/v2/messageStore';

interface CompletionMessageViewProps {
  message: CompletionMessage;
}

export function CompletionMessageView({ message }: CompletionMessageViewProps) {
  return (
    <div className="v2-step-group py-3">
      {/* Ring node instead of filled circle for completion markers */}
      <div
        className="absolute z-2"
        style={{
          left: '32px',
          top: '50%',
          width: '9px',
          height: '9px',
          borderRadius: '50%',
          border: '1.5px solid rgb(52, 211, 153)',
          opacity: 0.7,
          transform: 'translate(-50%, -50%)',
        }}
      />
      <div className="flex items-center gap-3">
        <div className="flex-1 h-px bg-emerald-500/30" />
        <div className="flex items-center gap-2 shrink-0">
          <svg
            className="w-4 h-4 text-emerald-400"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <path d="M4 8l3 3 5-5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className={cn(
            'text-[11px] font-medium uppercase tracking-wider text-emerald-400'
          )}>
            {message.label}
          </span>
          {message.selectedAgent && (
            <span className="text-[11px] text-v2-text-muted">
              — {message.selectedAgent}
            </span>
          )}
        </div>
        <div className="flex-1 h-px bg-emerald-500/30" />
      </div>
    </div>
  );
}
