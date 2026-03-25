import { useState } from 'react';
import { cn } from '../../../../lib/utils';
import type { ContentMessage } from '../../../../stores/v2/messageStore';

interface ContentMessageViewProps {
  message: ContentMessage;
}

export function ContentMessageView({ message }: ContentMessageViewProps) {
  const isThinking = message.contentType === 'thinking';
  const [expanded, setExpanded] = useState(!isThinking);

  const content = message.content.trim();
  if (!content) return null;

  const lines = content.split('\n');
  const hasMore = lines.length > 3 || content.length > 300;
  const preview = lines.slice(0, 2).join('\n');
  const previewTruncated = preview.length > 200 ? preview.slice(0, 200) + '\u2026' : preview;

  // Thinking/reasoning — unlabeled italic text with hover-reveal chevron
  if (isThinking) {
    const firstLine = lines[0];
    const previewLine = firstLine.length > 80 ? firstLine.slice(0, 77) + '\u2026' : firstLine;

    return (
      <div
        className={cn('v2-reasoning-block cursor-pointer', expanded && 'v2-reasoning-expanded')}
        onClick={() => setExpanded(!expanded)}
      >
        <div className="v2-reasoning-node" />
        <div className="v2-reasoning-row flex items-start gap-1.5">
          <svg
            className="v2-hover-chevron w-2.5 h-2.5 shrink-0 text-v2-text-muted"
            style={{ marginLeft: '-14px', marginRight: '-5px', marginTop: '4px' }}
            viewBox="0 0 12 12"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="M4 2l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {!expanded && (
            <span className="text-[13px] text-v2-text-muted italic opacity-70 truncate leading-relaxed">
              {previewLine}
            </span>
          )}
          {expanded && (
            <pre className="text-[13px] text-v2-text-muted italic opacity-70 whitespace-pre-wrap leading-relaxed break-words animate-v2-fade-in flex-1 min-w-0 max-h-[300px] overflow-y-auto v2-scrollbar">
              {content}
            </pre>
          )}
        </div>
      </div>
    );
  }

  // Regular content — plain text with spine node, no border
  if (!hasMore) {
    return (
      <div className="v2-step-group">
        <div className="v2-step-node" />
        <div className="py-1.5">
          <p className="text-sm text-v2-text leading-relaxed">
            {content}
          </p>
        </div>
      </div>
    );
  }

  // Longer content: collapsible
  return (
    <div className="v2-step-group">
      <div className="v2-step-node" />
      <div className="py-1.5 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        {expanded ? (
          <div className="animate-v2-fade-in">
            <pre className="whitespace-pre-wrap text-sm text-v2-text leading-relaxed break-words">
              {content}
            </pre>
            <button className="text-xs text-v2-text-muted mt-1 hover:text-v2-text transition-colors">
              Show less
            </button>
          </div>
        ) : (
          <p className="text-sm text-v2-text leading-relaxed">
            {previewTruncated}
            {hasMore && (
              <span className="text-v2-text-muted ml-1">
                (+{lines.length - 2} lines)
              </span>
            )}
          </p>
        )}
      </div>
    </div>
  );
}
