import { useEffect, useRef, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { cn } from '../../../lib/utils';
import { useMessageStore } from '../../../stores/v2/messageStore';

const EMPTY_PLAN: never[] = [];
const DEFAULT_WIDTH = 360;
const MIN_WIDTH = 200;
const MAX_WIDTH = 560;

const STATUS_ICONS: Record<string, string> = {
  pending: '\u00B7',
  in_progress: '\u2192',
  completed: '\u2713',
  verified: '\u2713',
  blocked: '\u25CB',
};

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-v2-text-muted',
  in_progress: 'text-v2-accent',
  completed: 'text-v2-online',
  verified: 'text-v2-online',
  blocked: 'text-red-400',
};

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-red-400',
  medium: 'bg-v2-idle',
  low: 'bg-v2-text-muted',
};

interface TaskMeta {
  id: string;
  description: string;
  status: string;
  priority?: string;
  dependencies?: string[];
}

export function TaskPlanPanel({ agentId }: { agentId: string }) {
  const [collapsed, setCollapsed] = useState(false);
  const [panelWidth, setPanelWidth] = useState(DEFAULT_WIDTH);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const taskPlan = useMessageStore((s) => s.taskPlans[agentId] ?? EMPTY_PLAN);
  const resizeRef = useRef<{ startX: number; startWidth: number } | null>(null);

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!resizeRef.current) return;
      const delta = resizeRef.current.startX - e.clientX;
      setPanelWidth(Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, resizeRef.current.startWidth + delta)));
    };
    const onMouseUp = () => {
      resizeRef.current = null;
      document.body.style.removeProperty('cursor');
      document.body.style.removeProperty('user-select');
    };
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      document.body.style.removeProperty('cursor');
      document.body.style.removeProperty('user-select');
    };
  }, []);

  const startResize = (e: ReactMouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    resizeRef.current = { startX: e.clientX, startWidth: panelWidth };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  if (!taskPlan || taskPlan.length === 0) return null;

  const completedCount = taskPlan.filter(
    (t) => t.status === 'completed' || t.status === 'verified'
  ).length;
  const totalCount = taskPlan.length;
  const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  // Collapsed: vertical strip with progress bar + icon
  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className={cn(
          'flex flex-col items-center py-3 gap-2',
          'border-l border-v2-border bg-v2-surface',
          'text-v2-text-muted hover:text-v2-text hover:bg-v2-sidebar-hover',
          'transition-colors duration-150 shrink-0'
        )}
        style={{ width: 32 }}
        title={`Plan ${completedCount}/${totalCount} — click to expand`}
      >
        {/* Clipboard icon */}
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="3" y="2" width="10" height="12" rx="1.5" />
          <path d="M6 2V1h4v1" strokeLinecap="round" />
          <path d="M6 6h4M6 9h3" strokeLinecap="round" />
        </svg>
        {/* Vertical progress bar */}
        <div className="w-[3px] flex-1 rounded-full bg-v2-border-subtle overflow-hidden">
          <div
            className="w-full bg-v2-online rounded-full transition-all duration-500"
            style={{ height: `${progressPct}%` }}
          />
        </div>
        {/* Count */}
        <span className="text-[9px] font-mono font-medium">
          {completedCount}/{totalCount}
        </span>
      </button>
    );
  }

  return (
    <div
      data-testid="task-plan-panel"
      className="shrink-0 border-l border-v2-border bg-v2-surface flex flex-col relative"
      style={{ width: panelWidth }}
    >
      {/* Drag handle */}
      <div
        data-testid="task-plan-resize-handle"
        onMouseDown={startResize}
        className="absolute left-0 top-0 h-full w-2 -translate-x-1/2 z-10 cursor-col-resize group"
      >
        <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-transparent group-hover:bg-v2-accent transition-colors" />
      </div>

      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-v2-border-subtle">
        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-v2-text-muted shrink-0" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="2" width="10" height="12" rx="1.5" />
            <path d="M6 2V1h4v1" strokeLinecap="round" />
            <path d="M6 6h4M6 9h3" strokeLinecap="round" />
          </svg>
          <span className="text-xs font-semibold text-v2-text">Plan</span>
          <span className="text-xs text-v2-accent font-medium">
            {completedCount}/{totalCount}
          </span>
        </div>
        <button
          onClick={() => setCollapsed(true)}
          className={cn(
            'flex items-center justify-center w-5 h-5 rounded',
            'text-v2-text-muted hover:text-v2-text hover:bg-v2-sidebar-hover',
            'transition-colors duration-150'
          )}
        >
          <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M8 2l-4 4 4 4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {/* Progress bar */}
      <div className="px-3 pt-2 pb-1">
        <div className="h-1 rounded-full bg-v2-border-subtle overflow-hidden">
          <div
            className="h-full bg-v2-online rounded-full transition-all duration-500 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto v2-scrollbar py-1">
        {taskPlan.map((task, idx) => (
          <TaskRow
            key={task.id}
            task={task}
            index={idx}
            isExpanded={expandedTaskId === task.id}
            onToggle={() => setExpandedTaskId(expandedTaskId === task.id ? null : task.id)}
          />
        ))}
      </div>
    </div>
  );
}

function TaskRow({
  task,
  index,
  isExpanded,
  onToggle,
}: {
  task: TaskMeta;
  index: number;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        task.status === 'in_progress' && 'bg-v2-accent/5 border-l-2 border-v2-accent',
        task.status !== 'in_progress' && 'border-l-2 border-transparent'
      )}
    >
      <button
        onClick={onToggle}
        className={cn(
          'flex items-start gap-2 w-full text-left px-3 py-1.5',
          'hover:bg-[var(--v2-channel-hover)] transition-colors duration-100'
        )}
      >
        <span
          className={cn(
            'text-xs font-mono w-3 shrink-0 text-center mt-px',
            STATUS_COLORS[task.status] || 'text-v2-text-muted'
          )}
        >
          {STATUS_ICONS[task.status] || '\u00B7'}
        </span>

        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-1">
            {task.priority && (
              <span
                className={cn(
                  'w-1.5 h-1.5 rounded-full shrink-0 mt-1',
                  PRIORITY_COLORS[task.priority] || 'bg-v2-text-muted'
                )}
                title={`${task.priority} priority`}
              />
            )}
            <span
              className={cn(
                'text-xs leading-relaxed',
                task.status === 'completed' || task.status === 'verified'
                  ? 'text-v2-text-muted line-through'
                  : task.status === 'in_progress'
                    ? 'text-v2-text font-medium'
                    : task.status === 'blocked'
                      ? 'text-red-400/70'
                      : 'text-v2-text-secondary'
              )}
            >
              {index + 1}. {task.description}
            </span>
          </div>
        </div>
      </button>

      {/* Expanded metadata */}
      {isExpanded && (
        <div className="px-3 pb-2 ml-5 space-y-1 animate-v2-fade-in">
          <div className="text-[11px] text-v2-text-muted">
            <span className="text-v2-text-secondary">Status:</span>{' '}
            {task.status.replace('_', ' ')}
          </div>
          {task.priority && (
            <div className="text-[11px] text-v2-text-muted">
              <span className="text-v2-text-secondary">Priority:</span>{' '}
              {task.priority}
            </div>
          )}
          {task.dependencies && task.dependencies.length > 0 && (
            <div className="text-[11px] text-v2-text-muted">
              <span className="text-v2-text-secondary">Depends on:</span>{' '}
              {task.dependencies.join(', ')}
            </div>
          )}
          <div className="text-[11px] text-v2-text-muted">
            <span className="text-v2-text-secondary">ID:</span>{' '}
            <span className="font-mono">{task.id}</span>
          </div>
        </div>
      )}
    </div>
  );
}
