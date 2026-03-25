import { cn } from '../../../../lib/utils';
import type { StatusMessage, ErrorMessage } from '../../../../stores/v2/messageStore';

interface StatusMessageViewProps {
  message: StatusMessage;
}

export function StatusMessageView({ message }: StatusMessageViewProps) {
  return (
    <div className="v2-step-group">
      <div className="v2-step-node" style={{ width: '5px', height: '5px', top: '10px', opacity: 0.4 }} />
      <div className="flex items-center gap-2 text-xs text-v2-text-muted">
        <StatusDot status={message.status} />
        <span className="capitalize">{message.status}</span>
        {message.detail && (
          <span className="text-v2-text-muted/60">- {message.detail}</span>
        )}
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const color = {
    working: 'bg-v2-online',
    voting: 'bg-v2-idle',
    completed: 'bg-v2-offline',
    failed: 'bg-red-500',
    waiting: 'bg-v2-offline',
  }[status] || 'bg-v2-offline';

  return <span className={cn('w-1.5 h-1.5 rounded-full', color)} />;
}

interface ErrorMessageViewProps {
  message: ErrorMessage;
}

export function ErrorMessageView({ message }: ErrorMessageViewProps) {
  return (
    <div className="v2-step-group py-1">
      <div className="v2-step-node" style={{ background: 'rgb(248, 113, 113)' }} />
      <div className="flex items-start gap-2 rounded-v2-card bg-red-500/10 border border-red-500/20 px-3 py-2">
        <svg className="w-4 h-4 text-red-400 mt-0.5 shrink-0" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="8" cy="8" r="6" />
          <path d="M8 5v4M8 11v0" strokeLinecap="round" />
        </svg>
        <span className="text-sm text-red-300">{message.message}</span>
      </div>
    </div>
  );
}
