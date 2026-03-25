import type { RoundDividerMessage } from '../../../../stores/v2/messageStore';

interface RoundDividerViewProps {
  message: RoundDividerMessage;
}

export function RoundDividerView({ message }: RoundDividerViewProps) {
  return (
    <div className="v2-step-group py-2">
      {/* Ring node instead of filled circle for dividers */}
      <div
        className="absolute z-2"
        style={{
          left: '32px',
          top: '50%',
          width: '9px',
          height: '9px',
          borderRadius: '50%',
          border: '1.5px solid var(--v2-text-muted, #6b6b82)',
          opacity: 0.5,
          transform: 'translate(-50%, -50%)',
        }}
      />
      <div className="flex items-center gap-3">
        <div className="flex-1 h-px bg-v2-border" />
        <span className="text-[11px] font-medium uppercase tracking-wider text-v2-text-muted shrink-0">
          {message.label}
        </span>
        <div className="flex-1 h-px bg-v2-border" />
      </div>
    </div>
  );
}
