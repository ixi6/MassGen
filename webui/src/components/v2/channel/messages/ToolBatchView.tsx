import { useState } from 'react';
import { cn } from '../../../../lib/utils';
import type { ToolCallMessage } from '../../../../stores/v2/messageStore';
import { HookList } from './ToolCallMessageView';

/** Number of tools visible when tree is open but not fully expanded */
const COLLAPSED_VISIBLE = 3;

interface ToolBatchViewProps {
  tools: ToolCallMessage[];
}

export function ToolBatchView({ tools }: ToolBatchViewProps) {
  const [treeOpen, setTreeOpen] = useState(true);
  const [allExpanded, setAllExpanded] = useState(false);
  const [expandedToolId, setExpandedToolId] = useState<string | null>(null);

  const anyPending = tools.some((t) => t.result === undefined);
  const anyFailed = tools.some((t) => t.success === false);

  const totalElapsed = tools.reduce((sum, t) => sum + (t.elapsed || 0), 0);
  const elapsedStr = totalElapsed > 0
    ? totalElapsed > 1000
      ? `${(totalElapsed / 1000).toFixed(1)}s`
      : `${Math.round(totalElapsed)}ms`
    : null;

  const serverName = getServerName(tools);

  const visibleTools = allExpanded
    ? tools
    : tools.slice(-COLLAPSED_VISIBLE);
  const hiddenCount = allExpanded ? 0 : Math.max(0, tools.length - COLLAPSED_VISIBLE);

  return (
    <div className="v2-step-group">
      {/* Batch header — inline trace, no card */}
      <div
        className={cn(
          'v2-tool-row flex items-center gap-[7px] py-[3px] cursor-pointer rounded-sm',
          'hover:bg-[var(--v2-channel-hover)] transition-colors duration-100',
          treeOpen && 'v2-tool-row-expanded'
        )}
        data-testid="batch-header"
        onClick={() => setTreeOpen(!treeOpen)}
      >
        <svg
          className="v2-hover-chevron w-3 h-3 shrink-0 text-v2-text-muted"
          style={{ marginLeft: '-14px', marginRight: '-5px' }}
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <path d="M4 2l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>

        <span className={cn(
          'w-1.5 h-1.5 rounded-full shrink-0',
          anyPending ? 'bg-blue-400 animate-pulse' : anyFailed ? 'bg-red-400' : 'bg-v2-online'
        )} />

        <span className="font-mono text-xs font-medium text-v2-text-muted opacity-80 shrink-0">
          {serverName}
        </span>

        <span className="text-xs text-v2-text-muted">
          ×{tools.length}
        </span>

        <div className="flex-1" />

        {elapsedStr && (
          <span className="text-xs font-mono text-v2-text-muted shrink-0">
            {elapsedStr}
          </span>
        )}
      </div>

      {/* Sub-call tree */}
      {treeOpen && (
        <div
          data-testid="batch-tool-tree"
          className="ml-1.5 border-l border-v2-border-subtle pl-2.5 mt-0.5 animate-v2-fade-in"
        >
          {hiddenCount > 0 && (
            <button
              onClick={(e) => { e.stopPropagation(); setAllExpanded(true); }}
              className="text-xs text-v2-text-muted hover:text-v2-text transition-colors py-0.5"
            >
              (+{hiddenCount} earlier)
            </button>
          )}

          {visibleTools.map((tool) => {
            const isPending = tool.result === undefined;
            const toolExpanded = expandedToolId === tool.id;

            return (
              <div key={tool.id}>
                <div
                  className={cn(
                    'v2-sub-row flex items-center gap-1.5 py-[3px] cursor-pointer rounded-sm',
                    'hover:bg-[var(--v2-channel-hover)] transition-colors duration-100 text-xs',
                    toolExpanded && 'v2-sub-row-expanded'
                  )}
                  onClick={() => setExpandedToolId(toolExpanded ? null : tool.id)}
                >
                  <svg
                    className="v2-sub-chevron w-2.5 h-2.5 shrink-0 text-v2-text-muted"
                    style={{ marginLeft: '-12px', marginRight: '-1px' }}
                    viewBox="0 0 12 12"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                  >
                    <path d="M4 2l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>

                  <span className={cn(
                    'w-1.5 h-1.5 rounded-full shrink-0',
                    isPending ? 'bg-blue-400 animate-pulse' : tool.success ? 'bg-v2-online' : 'bg-red-400'
                  )} />

                  <span className="font-mono text-v2-text-muted truncate flex-1">
                    {extractArgHint(tool.args) || tool.toolName}
                  </span>

                  {tool.elapsed != null && (
                    <span className="text-v2-text-muted shrink-0">
                      {tool.elapsed > 1000
                        ? `${(tool.elapsed / 1000).toFixed(1)}s`
                        : `${Math.round(tool.elapsed)}ms`}
                    </span>
                  )}
                </div>

                {toolExpanded && <ToolDetail tool={tool} />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ToolDetail({ tool }: { tool: ToolCallMessage }) {
  return (
    <div className="ml-1.5 mb-1 space-y-1.5 animate-v2-fade-in border-l border-v2-border-subtle pl-2.5">
      {Object.keys(tool.args).length > 0 && (
        <div className="rounded bg-v2-main p-2 border border-v2-border-subtle">
          <div className="text-[11px] uppercase tracking-wider text-v2-text-muted mb-1">Args</div>
          <pre className="text-xs font-mono whitespace-pre-wrap break-all text-v2-text-secondary">
            {formatArgs(tool.args)}
          </pre>
        </div>
      )}
      {tool.result !== undefined && (
        <div className="rounded bg-v2-main p-2 border border-v2-border-subtle">
          <div className="text-[11px] uppercase tracking-wider text-v2-text-muted mb-1">Result</div>
          <pre className="text-xs font-mono text-v2-text-secondary whitespace-pre-wrap break-all max-h-[200px] overflow-y-auto v2-scrollbar">
            {tool.result}
          </pre>
        </div>
      )}
      <HookList label="Pre-hooks" hooks={tool.preHooks} />
      <HookList label="Post-hooks" hooks={tool.postHooks} />
    </div>
  );
}

function getServerName(tools: ToolCallMessage[]): string {
  const names = tools.map((t) => t.toolName);
  if (names.every((n) => n === names[0])) return names[0];
  const first = names[0];
  for (let len = first.length; len > 0; len--) {
    const prefix = first.slice(0, len);
    if (names.every((n) => n.startsWith(prefix))) {
      return prefix.replace(/[_\s]+$/, '') || first;
    }
  }
  return first;
}

function extractArgHint(args: Record<string, unknown>): string {
  for (const key of ['path', 'file_path', 'filename', 'file', 'target', 'command']) {
    if (typeof args[key] === 'string') {
      return args[key] as string;
    }
  }
  return '';
}

function formatArgs(args: Record<string, unknown>): string {
  return JSON.stringify(args, null, 2);
}
