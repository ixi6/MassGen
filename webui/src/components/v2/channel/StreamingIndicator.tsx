interface StreamingIndicatorProps {
  visible: boolean;
  label?: string;
}

export function StreamingIndicator({ visible, label = 'Generating' }: StreamingIndicatorProps) {
  if (!visible) return null;

  const isWaiting = label === 'Waiting';
  const dotColor = isWaiting ? 'bg-v2-text-muted' : 'bg-v2-online';
  const dotClass = isWaiting ? 'waiting-dot' : 'typing-dot';

  return (
    <div className="px-4 py-2 animate-v2-fade-in">
      <div className="inline-flex items-center gap-2">
        <span className="flex gap-1" aria-hidden="true">
          <span className={`${dotClass} h-1.5 w-1.5 rounded-full ${dotColor}`} />
          <span className={`${dotClass} h-1.5 w-1.5 rounded-full ${dotColor}`} />
          <span className={`${dotClass} h-1.5 w-1.5 rounded-full ${dotColor}`} />
        </span>
        <span className="text-xs text-v2-text-muted">{label}</span>
      </div>
    </div>
  );
}
