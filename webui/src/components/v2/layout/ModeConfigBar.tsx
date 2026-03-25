import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { cn } from '../../../lib/utils';
import { useModeStore } from '../../../stores/v2/modeStore';
import type {
  CoordinationMode,
  AgentMode,
  PlanMode,
  PersonasMode,
  AgentConfigOverride,
} from '../../../stores/v2/modeStore';
import type { ReasoningEffort } from '../../../stores/wizardStore';

// ────────────────────────────────────────────────────────────────
// ToggleButton — compact two-state toggle
// ────────────────────────────────────────────────────────────────

function ToggleButton<T extends string>({
  options,
  value,
  onChange,
  testId,
}: {
  options: [{ label: string; value: T }, { label: string; value: T }];
  value: T;
  onChange: (v: T) => void;
  testId?: string;
}) {
  const activeOpt = options.find((o) => o.value === value) ?? options[0];
  const inactiveOpt = options.find((o) => o.value !== value) ?? options[1];
  const isNonDefault = value !== options[0].value;

  return (
    <div
      data-testid={testId}
      className="group inline-flex items-center shrink-0 rounded-v2-input bg-[var(--v2-input-bg)] border border-v2-border overflow-hidden"
    >
      {/* Active label — always visible */}
      <span
        className={cn(
          'px-2.5 py-1.5 text-xs font-semibold whitespace-nowrap select-none',
          isNonDefault ? 'bg-v2-accent text-white' : 'text-v2-text'
        )}
      >
        {activeOpt.label}
      </span>
      {/* Small gap hint — shows there's more */}
      <span
        aria-hidden="true"
        data-testid={testId ? `${testId}-peek` : undefined}
        className="w-2 shrink-0"
      />
      {/* Inactive label — collapsed, revealed on hover */}
      <button
        type="button"
        aria-label={`Switch to ${inactiveOpt.label}`}
        data-testid={testId ? `${testId}-inactive-label` : undefined}
        onClick={() => onChange(inactiveOpt.value)}
        className={cn(
          'text-xs font-medium whitespace-nowrap transition-all duration-150 ease-in-out overflow-hidden',
          'max-w-0 py-1.5 opacity-0',
          'group-hover:max-w-[80px] group-hover:px-2.5 group-hover:opacity-100',
          'text-v2-text-muted hover:text-v2-text hover:bg-[var(--v2-channel-hover)]'
        )}
      >
        {inactiveOpt.label}
      </button>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// DropdownToken — compact dropdown for Mode / Personas
// ────────────────────────────────────────────────────────────────

interface DropdownItem<T> {
  label: string;
  value: T;
  description?: string;
}

function DropdownToken<T extends string>({
  label,
  items,
  value,
  defaultValue,
  onChange,
  testId,
}: {
  label?: string;
  items: DropdownItem<T>[];
  value: T;
  defaultValue: T;
  onChange: (v: T) => void;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuPos, setMenuPos] = useState<{ left: number; bottom: number } | null>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (ref.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    if (open && ref.current) {
      const rect = ref.current.getBoundingClientRect();
      setMenuPos({ left: rect.left, bottom: window.innerHeight - rect.top + 6 });
    }
  }, [open]);

  const isActive = value !== defaultValue;
  const currentItem = items.find((i) => i.value === value) ?? items[0];

  return (
    <div ref={ref} className="relative shrink-0" data-testid={testId}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          'inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-v2-input',
          'text-xs font-medium cursor-pointer border transition-all duration-150',
          'whitespace-nowrap select-none',
          isActive
            ? 'border-v2-accent bg-v2-accent/15'
            : 'border-v2-border bg-[var(--v2-input-bg)]',
          'hover:border-v2-accent'
        )}
      >
        {label && (
          <span className="text-[10px] font-semibold uppercase tracking-wider text-v2-text-muted">
            {label}
          </span>
        )}
        <span className={cn(isActive ? 'text-v2-accent font-semibold' : 'text-v2-text')}>
          {currentItem.label}
        </span>
        <span className="text-[8px] text-v2-text-muted ml-0.5">{'\u25BE'}</span>
      </button>

      {open && menuPos && createPortal(
        <div
          ref={menuRef}
          data-testid={testId ? `${testId}-menu` : undefined}
          className={cn(
            'fixed z-[9999]',
            'bg-v2-surface-raised border border-v2-border rounded-lg',
            'shadow-lg min-w-[160px] p-1'
          )}
          style={{ left: menuPos.left, bottom: menuPos.bottom }}
        >
          {items.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => {
                onChange(item.value);
                setOpen(false);
              }}
              className={cn(
                'w-full text-left flex items-start gap-2 px-2.5 py-2 rounded-v2-input',
                'text-xs transition-colors',
                value === item.value
                  ? 'text-v2-accent font-semibold'
                  : 'text-v2-text-secondary hover:bg-[var(--v2-channel-hover)] hover:text-v2-text'
              )}
            >
              <span className="w-4 flex-shrink-0 text-center text-xs pt-px">
                {value === item.value ? '\u2713' : ''}
              </span>
              <div className="flex flex-col gap-px">
                <span>{item.label}</span>
                {item.description && (
                  <span className="text-[10px] text-v2-text-muted font-normal">
                    {item.description}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>,
        document.body
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// AgentCountStepper — [ - ] N [ + ]
// ────────────────────────────────────────────────────────────────

function AgentCountStepper({ onIncrement }: { onIncrement?: () => void }) {
  const agentCount = useModeStore((s) => s.agentCount);
  const setAgentCount = useModeStore((s) => s.setAgentCount);

  const decrement = () => {
    if (agentCount === null || agentCount <= 1) {
      setAgentCount(null);
    } else {
      setAgentCount(agentCount - 1);
    }
  };

  const increment = () => {
    if (agentCount === null) {
      setAgentCount(1);
    } else if (agentCount < 8) {
      setAgentCount(agentCount + 1);
    }
    onIncrement?.();
  };

  return (
    <div
      data-testid="agent-count-stepper"
      className="inline-flex items-center shrink-0 rounded-v2-input bg-[var(--v2-input-bg)] border border-v2-border overflow-hidden"
    >
      <button
        type="button"
        data-testid="agent-count-decrement"
        onClick={decrement}
        className="w-7 h-[30px] flex items-center justify-center text-sm text-v2-text-muted hover:text-v2-text hover:bg-[var(--v2-channel-hover)] transition-colors"
      >
        {'\u2212'}
      </button>
      <span
        data-testid="agent-count-value"
        className="min-w-[24px] text-center text-[13px] font-semibold text-v2-text px-0.5"
      >
        {agentCount ?? 'Config'}
      </span>
      <button
        type="button"
        data-testid="agent-count-increment"
        onClick={increment}
        className="w-7 h-[30px] flex items-center justify-center text-sm text-v2-text-muted hover:text-v2-text hover:bg-[var(--v2-channel-hover)] transition-colors"
      >
        +
      </button>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// AgentSummaryButton — colored provider/model chips per agent
// ────────────────────────────────────────────────────────────────

const providerChipColors: Record<string, { bg: string; text: string }> = {
  anthropic: { bg: 'rgba(204, 120, 50, 0.12)', text: '#e8915a' },
  openai: { bg: 'rgba(16, 163, 127, 0.12)', text: '#34d399' },
  google: { bg: 'rgba(66, 133, 244, 0.12)', text: '#60a5fa' },
  gemini: { bg: 'rgba(66, 133, 244, 0.12)', text: '#60a5fa' },
  xai: { bg: 'rgba(240, 178, 50, 0.12)', text: '#f0b232' },
};
const defaultChipColor = { bg: 'rgba(128, 132, 142, 0.12)', text: 'var(--v2-text-muted)' };

function ModelChip({
  index,
  config,
  isSelected,
  isMainAgent,
  onClick,
}: {
  index: number;
  config: AgentConfigOverride;
  isSelected?: boolean;
  isMainAgent?: boolean;
  onClick?: () => void;
}) {
  const letter = String.fromCharCode(65 + index);
  const colors = (config.provider && providerChipColors[config.provider]) || defaultChipColor;

  const providerShort = config.provider ?? '';
  const modelShort = config.model
    ? config.model.length > 14
      ? config.model.slice(0, 12) + '\u2026'
      : config.model
    : '';
  const hasConfig = config.provider || config.model;

  return (
    <span
      role={onClick ? 'button' : undefined}
      onClick={onClick ? (e) => { e.stopPropagation(); onClick(); } : undefined}
      className={cn(
        'inline-flex items-center px-2 py-1 rounded text-[11px] font-medium transition-all whitespace-nowrap',
        onClick && 'cursor-pointer hover:ring-1 hover:ring-v2-accent/40',
        isSelected && 'ring-2 ring-v2-accent ring-offset-1 ring-offset-[var(--v2-input-bg)]',
        isMainAgent && 'ring-1 ring-amber-400/50'
      )}
      style={{ background: hasConfig ? colors.bg : defaultChipColor.bg, color: hasConfig ? colors.text : defaultChipColor.text }}
    >
      {isMainAgent && <span className="text-amber-400 mr-1" title="Main agent">&#9733;</span>}
      <span className="font-bold mr-1.5 opacity-70">{letter}</span>
      {hasConfig ? (
        <>
          {providerShort && <span className="opacity-60">{providerShort}</span>}
          {providerShort && modelShort && <span className="opacity-35 mx-px">/</span>}
          {modelShort && <span className="font-semibold">{modelShort}</span>}
          {!modelShort && <span className="opacity-50 italic">set model</span>}
        </>
      ) : (
        <span className="opacity-50 text-amber-400/80">not set</span>
      )}
    </span>
  );
}

function AgentSummaryButton({ onClick }: { onClick: () => void }) {
  const agentCount = useModeStore((s) => s.agentCount);
  const agentConfigs = useModeStore((s) => s.agentConfigs);
  const configAgents = useModeStore((s) => s.configAgents);
  const configLockedVal = useModeStore((s) => s.configLocked);
  const agentMode = useModeStore((s) => s.agentMode);
  const coordinationMode = useModeStore((s) => s.coordinationMode);
  const selectedMainAgent = useModeStore((s) => s.selectedMainAgent);
  const selectedSingleAgent = useModeStore((s) => s.selectedSingleAgent);
  const setSelectedSingleAgent = useModeStore((s) => s.setSelectedSingleAgent);

  const isSingleMode = agentMode === 'single';
  const isCheckpointMode = coordinationMode === 'checkpoint';

  // When config is locked or agentCount is null, show agents from the parsed YAML
  const useConfigAgents = (configLockedVal || agentCount === null) && configAgents.length > 0;
  const effectiveConfigs: AgentConfigOverride[] = useConfigAgents
    ? configAgents.map((a) => ({
        provider: a.provider,
        model: a.model,
        reasoningEffort: null,
        enableWebSearch: null,
        enableCodeExecution: null,
      }))
    : agentConfigs;

  if (!useConfigAgents && agentCount === null) {
    return (
      <button
        type="button"
        data-testid="agent-summary-btn"
        onClick={onClick}
        className={cn(
          'inline-flex items-center shrink-0 gap-1.5 px-2 py-1.5 rounded-v2-input',
          'text-xs border border-v2-border bg-[var(--v2-input-bg)]',
          'text-v2-text-muted hover:border-v2-accent hover:text-v2-text transition-all'
        )}
      >
        <span>from config</span>
        <span className="text-sm leading-none">{'\u2699'}</span>
      </button>
    );
  }

  const chipCount = useConfigAgents ? effectiveConfigs.length : agentCount ?? 0;

  // In single mode, determine which agent is selected (default = first = index 0)
  const selectedIndex = isSingleMode
    ? (selectedSingleAgent
        ? effectiveConfigs.findIndex((_, i) => `agent_${String.fromCharCode(97 + i)}` === selectedSingleAgent)
        : 0)
    : -1;

  const handleChipClick = (index: number) => {
    if (isSingleMode) {
      const agentId = `agent_${String.fromCharCode(97 + index)}`;
      setSelectedSingleAgent(agentId);
    }
  };

  return (
    <div
      role="button"
      data-testid="agent-summary-btn"
      onClick={onClick}
      className={cn(
        'inline-flex items-center shrink-0 gap-1.5 px-1 py-1 pr-2 rounded-v2-input cursor-pointer',
        'text-xs border border-v2-border bg-[var(--v2-input-bg)]',
        'text-v2-text-secondary hover:border-v2-accent transition-all'
      )}
    >
      <div className="flex gap-1 items-center">
        {effectiveConfigs.slice(0, chipCount || effectiveConfigs.length).map((config, i) => {
          const chipAgentId = useConfigAgents && configAgents[i]
            ? configAgents[i].id
            : `agent_${String.fromCharCode(97 + i)}`;
          const isMain = isCheckpointMode && (
            selectedMainAgent ? selectedMainAgent === chipAgentId : i === 0
          );
          return (
            <ModelChip
              key={i}
              index={i}
              config={config}
              isSelected={isSingleMode && (selectedIndex === -1 ? i === 0 : i === selectedIndex)}
              isMainAgent={isMain}
              onClick={isSingleMode ? () => handleChipClick(i) : undefined}
            />
          );
        })}
      </div>
      <span
        className="text-sm text-v2-text-muted leading-none hover:text-v2-text transition-colors"
      >
        {'\u2699'}
      </span>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// AgentConfigDrawer — bottom sheet with per-agent config cards
// ────────────────────────────────────────────────────────────────

// ────────────────────────────────────────────────────────────────
// SearchableSelect — filterable dropdown with search input
// ────────────────────────────────────────────────────────────────

function SearchableSelect({
  value,
  options,
  onChange,
  disabled,
  placeholder,
  loading,
  testId,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  disabled?: boolean;
  placeholder?: string;
  loading?: boolean;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch('');
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
    }
  }, [open]);

  const filtered = search
    ? options.filter((o) => o.toLowerCase().includes(search.toLowerCase()))
    : options;

  const displayValue = value || placeholder || '';

  if (disabled) {
    return (
      <div
        data-testid={testId}
        className={cn(
          'w-full px-2.5 py-[7px] rounded-v2-input text-xs',
          'bg-[var(--v2-input-bg)] border border-v2-border text-v2-text-muted',
          'opacity-50 cursor-not-allowed'
        )}
      >
        {placeholder || 'Select provider first'}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative" data-testid={testId}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          'w-full px-2.5 py-[7px] rounded-v2-input text-xs text-left',
          'bg-[var(--v2-input-bg)] border border-v2-border text-v2-text',
          'cursor-pointer flex items-center justify-between',
          'hover:border-v2-accent focus:outline-none focus:border-v2-accent focus:ring-1 focus:ring-v2-accent/30'
        )}
      >
        <span className={cn(!value && 'text-v2-text-muted')}>
          {loading ? 'Loading...' : displayValue}
        </span>
        <span className="text-[8px] text-v2-text-muted">{'\u25BE'}</span>
      </button>

      {open && (
        <div
          className={cn(
            'absolute top-full mt-1 left-0 right-0 z-60',
            'bg-v2-surface-raised border border-v2-border rounded-lg',
            'shadow-lg overflow-hidden'
          )}
        >
          {/* Search input */}
          <div className="p-1.5 border-b border-v2-border">
            <input
              ref={inputRef}
              data-testid={testId ? `${testId}-search` : undefined}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search models..."
              className={cn(
                'w-full px-2 py-1.5 rounded text-xs',
                'bg-[var(--v2-input-bg)] border border-v2-border text-v2-text',
                'placeholder:text-v2-text-muted/60',
                'focus:outline-none focus:border-v2-accent focus:ring-1 focus:ring-v2-accent/30'
              )}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  setOpen(false);
                  setSearch('');
                } else if (e.key === 'Enter' && filtered.length === 1) {
                  onChange(filtered[0]);
                  setOpen(false);
                  setSearch('');
                }
              }}
            />
          </div>

          {/* Options list */}
          <div className="max-h-[200px] overflow-y-auto v2-scrollbar p-1">
            {filtered.length === 0 ? (
              <div className="px-2.5 py-2 text-xs text-v2-text-muted">No matches</div>
            ) : (
              filtered.map((opt) => (
                <button
                  key={opt}
                  type="button"
                  onClick={() => {
                    onChange(opt);
                    setOpen(false);
                    setSearch('');
                  }}
                  className={cn(
                    'w-full text-left px-2.5 py-1.5 rounded text-xs transition-colors',
                    opt === value
                      ? 'text-v2-accent font-semibold bg-v2-accent/10'
                      : 'text-v2-text-secondary hover:bg-[var(--v2-channel-hover)] hover:text-v2-text'
                  )}
                >
                  {opt}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Shared select styling */
const selectCn = cn(
  'w-full px-2.5 py-[7px] rounded-v2-input text-xs',
  'bg-[var(--v2-input-bg)] border border-v2-border text-v2-text',
  'cursor-pointer appearance-none',
  'hover:border-v2-accent focus:outline-none focus:border-v2-accent focus:ring-1 focus:ring-v2-accent/30'
);

function AgentCard({ index }: { index: number }) {
  const agentConfigs = useModeStore((s) => s.agentConfigs);
  const configAgents = useModeStore((s) => s.configAgents);
  const configLockedCard = useModeStore((s) => s.configLocked);
  const providers = useModeStore((s) => s.providers);
  const dynamicModels = useModeStore((s) => s.dynamicModels);
  const loadingModels = useModeStore((s) => s.loadingModels);
  const providerCapabilities = useModeStore((s) => s.providerCapabilities);
  const reasoningProfiles = useModeStore((s) => s.reasoningProfiles);
  const setAgentConfig = useModeStore((s) => s.setAgentConfig);
  const applyToAllAgents = useModeStore((s) => s.applyToAllAgents);
  const fetchDynamicModels = useModeStore((s) => s.fetchDynamicModels);
  const fetchProviderCapabilities = useModeStore((s) => s.fetchProviderCapabilities);
  const fetchReasoningProfile = useModeStore((s) => s.fetchReasoningProfile);
  const coordinationMode = useModeStore((s) => s.coordinationMode);
  const selectedMainAgent = useModeStore((s) => s.selectedMainAgent);
  const setSelectedMainAgent = useModeStore((s) => s.setSelectedMainAgent);

  // When config is locked, show config agent data instead of override data
  const configAgent = configLockedCard ? configAgents[index] : null;
  const config = configLockedCard
    ? { provider: configAgent?.provider ?? null, model: configAgent?.model ?? null, reasoningEffort: null as ReasoningEffort | null, enableWebSearch: null as boolean | null, enableCodeExecution: null as boolean | null }
    : agentConfigs[index];
  const letter = String.fromCharCode(65 + index);
  const agentId = configAgent?.id ?? `agent_${String.fromCharCode(97 + index)}`;
  const showMainToggle = coordinationMode === 'checkpoint';
  // Default first agent to main if none selected in checkpoint mode
  const isMainAgent = selectedMainAgent
    ? selectedMainAgent === agentId
    : (showMainToggle && index === 0);

  const selectedProvider = config?.provider ?? '';
  const providerInfo = providers.find((p) => p.id === selectedProvider);
  const models = selectedProvider ? (dynamicModels[selectedProvider] ?? []) : [];
  const isLoadingModels = selectedProvider ? (loadingModels[selectedProvider] ?? false) : false;
  const capabilities = selectedProvider
    ? (providerCapabilities[selectedProvider] ?? null)
    : null;

  // Effective model: what the user selected, or the provider default
  const effectiveModel = config?.model ?? providerInfo?.default_model ?? '';

  // Reasoning profile for the current provider+model combo
  const reasoningKey = selectedProvider && effectiveModel
    ? `${selectedProvider}/${effectiveModel}`
    : '';
  const reasoningProfile = reasoningKey ? (reasoningProfiles[reasoningKey] ?? null) : null;
  const supportsReasoning = reasoningProfile !== null && reasoningProfile !== undefined;

  // Fetch reasoning profile when model or provider changes
  useEffect(() => {
    if (selectedProvider && effectiveModel && !(reasoningKey in reasoningProfiles)) {
      fetchReasoningProfile(selectedProvider, effectiveModel);
    }
  }, [selectedProvider, effectiveModel]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleProviderChange = async (providerId: string) => {
    if (!providerId) {
      setAgentConfig(index, { provider: null, model: null, reasoningEffort: null });
      return;
    }
    // Look up the provider's default model and set it immediately
    const pInfo = providers.find((p) => p.id === providerId);
    const defaultModel = pInfo?.default_model ?? null;
    setAgentConfig(index, { provider: providerId, model: defaultModel, reasoningEffort: null });
    await fetchDynamicModels(providerId);
    await fetchProviderCapabilities(providerId);
    // Reasoning profile will be fetched by the useEffect above
  };

  const handleModelChange = (model: string) => {
    setAgentConfig(index, { model: model || null, reasoningEffort: null });
  };

  const supportsSearch = capabilities?.supports_web_search ?? true;

  // Valid reasoning effort values for this model
  const reasoningEfforts = reasoningProfile
    ? reasoningProfile.choices.map(([, value]) => value)
    : [];
  const defaultReasoningLabel = reasoningProfile
    ? `${reasoningProfile.default_effort} (default)`
    : 'auto';

  return (
    <div
      data-testid={`agent-card-${index}`}
      className={cn(
        'w-[280px] flex-shrink-0 rounded-lg border bg-v2-main',
        'p-3.5 flex flex-col gap-2.5 transition-colors',
        isMainAgent
          ? 'border-v2-accent/60 ring-1 ring-v2-accent/20'
          : 'border-v2-border hover:border-v2-accent/40'
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-semibold flex items-center gap-2">
          <span className={cn(
            'w-6 h-6 rounded-full inline-flex items-center justify-center text-[11px] font-bold',
            isMainAgent ? 'bg-v2-accent text-white' : 'bg-v2-accent/15 text-v2-accent'
          )}>
            {letter}
          </span>
          Agent {letter}
          {isMainAgent && (
            <span className="text-[9px] font-bold uppercase tracking-wider text-v2-accent">
              Main
            </span>
          )}
        </span>
        <div className="flex items-center gap-1.5">
          {showMainToggle && (
            <button
              type="button"
              data-testid={`agent-card-${index}-main-toggle`}
              onClick={(e) => {
                e.stopPropagation();
                setSelectedMainAgent(isMainAgent ? null : agentId);
              }}
              className={cn(
                'text-[10px] px-2 py-1 rounded border transition-colors',
                isMainAgent
                  ? 'bg-v2-accent/15 text-v2-accent border-v2-accent/30 font-semibold'
                  : 'text-v2-text-muted border-v2-border hover:border-v2-accent/40 hover:text-v2-accent'
              )}
            >
              {isMainAgent ? 'Main' : 'Set Main'}
            </button>
          )}
          {!configLockedCard && (
            <button
              type="button"
              data-testid={`agent-card-${index}-apply-all`}
              onClick={() => applyToAllAgents(index)}
              className="text-[10px] text-v2-accent hover:bg-v2-accent/15 px-2 py-1 rounded transition-colors"
            >
              Apply to all
            </button>
          )}
          {configLockedCard && !showMainToggle && (
            <span className="text-[10px] text-v2-text-muted italic">from config</span>
          )}
        </div>
      </div>

      {/* Provider */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-v2-text-muted">
          Provider
        </label>
        {configLockedCard ? (
          <div className={cn(selectCn, 'opacity-70 cursor-default')}>
            {selectedProvider || 'Not set'}
          </div>
        ) : (
          <select
            data-testid={`agent-card-${index}-provider`}
            value={selectedProvider}
            onChange={(e) => handleProviderChange(e.target.value)}
            className={selectCn}
          >
            <option value="">Select provider...</option>
            {providers.map((p) => (
              <option key={p.id} value={p.id} disabled={!p.has_api_key}>
                {p.name}{!p.has_api_key ? ' (no key)' : ''}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Model */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-v2-text-muted">
          Model
        </label>
        {configLockedCard ? (
          <div className={cn(selectCn, 'opacity-70 cursor-default')}>
            {config?.model || 'Not set'}
          </div>
        ) : (
          <SearchableSelect
            testId={`agent-card-${index}-model`}
            value={config?.model ?? ''}
            options={models}
            onChange={handleModelChange}
            disabled={!selectedProvider}
            placeholder="Select provider first"
            loading={isLoadingModels}
          />
        )}
      </div>

      {/* Reasoning — only shown when the model supports it */}
      {supportsReasoning && (
        <div className="flex flex-col gap-1">
          <label className="text-[10px] font-semibold uppercase tracking-wider text-v2-text-muted">
            Reasoning
          </label>
          {configLockedCard ? (
            <div className={cn(selectCn, 'opacity-70 cursor-default')}>
              {defaultReasoningLabel}
            </div>
          ) : (
            <select
              data-testid={`agent-card-${index}-reasoning`}
              value={config?.reasoningEffort ?? ''}
              onChange={(e) =>
                setAgentConfig(index, {
                  reasoningEffort: (e.target.value || null) as ReasoningEffort | null,
                })
              }
              className={selectCn}
            >
              <option value="">{defaultReasoningLabel}</option>
              {reasoningEfforts
                .filter((r) => r !== reasoningProfile?.default_effort)
                .map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
            </select>
          )}
        </div>
      )}

      {/* Web Search toggle */}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] font-semibold uppercase tracking-wider text-v2-text-muted">
          Web Search
        </label>
        {configLockedCard ? (
          <div className={cn(selectCn, 'opacity-70 cursor-default text-center')}>
            {config?.enableWebSearch === true ? 'Enabled' : 'Disabled'}
          </div>
        ) : (
          <button
            type="button"
            data-testid={`agent-card-${index}-search`}
            disabled={!supportsSearch}
            onClick={() =>
              setAgentConfig(index, {
                enableWebSearch: config?.enableWebSearch === true ? false : true,
              })
            }
            className={cn(
              'w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5',
              'rounded text-[11px] border transition-all',
              !supportsSearch
                ? 'border-v2-border/50 text-v2-text-muted/40 cursor-not-allowed opacity-50'
                : config?.enableWebSearch === true
                  ? 'border-v2-accent text-v2-accent bg-v2-accent/15'
                  : 'border-v2-border text-v2-text-muted hover:border-v2-text-muted hover:text-v2-text-secondary'
            )}
            title={!supportsSearch ? 'Not available for this provider' : undefined}
          >
            {config?.enableWebSearch === true ? 'Enabled' : 'Disabled'}
          </button>
        )}
      </div>
    </div>
  );
}

function ConfigPreviewPanel({ configPath, onClose }: { configPath: string; onClose: () => void }) {
  const [yaml, setYaml] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const getOverrides = useModeStore((s) => s.getOverrides);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadPreview = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const overrides = getOverrides();
      const response = await fetch('/api/config/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config_path: configPath, mode_overrides: overrides }),
      });
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to preview');
      }
      const data = await response.json();
      setYaml(data.resolved_yaml);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load preview');
    } finally {
      setLoading(false);
    }
  }, [configPath, getOverrides]);

  // Subscribe to override-relevant state so we re-render on changes
  const overridesKey = useModeStore((s) => JSON.stringify(s.getOverrides()));

  // Re-fetch when overrides or configPath change (debounced 300ms)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      loadPreview();
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [overridesKey, configPath]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      data-testid="config-preview-panel"
      className="absolute bottom-full left-0 right-0 z-50 border-b border-v2-border bg-v2-surface px-4 py-2 shadow-lg rounded-t-lg"
    >
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-v2-text-muted">
            Resolved Config
          </span>
          <button
            type="button"
            onClick={loadPreview}
            disabled={loading}
            className="text-[10px] text-v2-accent hover:underline disabled:opacity-50"
          >
            {loading ? 'Loading...' : 'Refresh'}
          </button>
          {error && <span className="text-[10px] text-red-400">{error}</span>}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-v2-text-muted hover:text-v2-text text-sm transition-colors"
        >
          {'\u00D7'}
        </button>
      </div>
      {yaml && (
        <pre className="text-[11px] text-v2-text-secondary bg-[var(--v2-input-bg)] rounded-lg p-3 max-h-[30vh] overflow-auto v2-scrollbar font-mono leading-relaxed">
          {yaml}
        </pre>
      )}
    </div>
  );
}

function AgentConfigDrawer({
  open,
  onClose,
  showSaveButton,
  onSave,
}: {
  open: boolean;
  onClose: () => void;
  showSaveButton?: boolean;
  onSave?: () => void;
}) {
  const agentCount = useModeStore((s) => s.agentCount);
  const configAgents = useModeStore((s) => s.configAgents);
  const configLockedDrawer = useModeStore((s) => s.configLocked);
  const coordinationMode = useModeStore((s) => s.coordinationMode);
  const selectedMainAgent = useModeStore((s) => s.selectedMainAgent);
  const setSelectedMainAgent = useModeStore((s) => s.setSelectedMainAgent);

  // Auto-select first agent as main when drawer opens in checkpoint mode
  useEffect(() => {
    if (!open || coordinationMode !== 'checkpoint') return;
    const firstId = configLockedDrawer && configAgents.length > 0
      ? configAgents[0].id
      : agentCount && agentCount > 0
        ? `agent_${String.fromCharCode(97)}`
        : null;
    if (firstId && !selectedMainAgent) {
      setSelectedMainAgent(firstId);
    }
  }, [open, coordinationMode, configAgents, configLockedDrawer, agentCount, selectedMainAgent, setSelectedMainAgent]);

  const cardCount = configLockedDrawer ? configAgents.length : agentCount;
  if (!open || cardCount === null || cardCount === 0) return null;

  return (
    <div
      data-testid="agent-drawer"
      className="fixed inset-0 bg-black/50 z-50 flex items-end"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={cn(
          'w-full max-h-[75vh] bg-v2-surface',
          'rounded-t-xl border-t border-v2-border',
          'flex flex-col animate-in slide-in-from-bottom duration-250'
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Handle */}
        <div className="flex justify-center py-2.5 pb-1.5 cursor-grab">
          <span className="w-9 h-1 rounded-full bg-v2-border" />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-5 pb-3">
          <h3 className="text-[15px] font-semibold">Configure Agents</h3>
          <button
            type="button"
            onClick={onClose}
            className="w-7 h-7 rounded flex items-center justify-center text-v2-text-muted hover:bg-[var(--v2-channel-hover)] hover:text-v2-text transition-colors text-lg"
          >
            {'\u00D7'}
          </button>
        </div>

        {/* Body — styled scrollbar, cards never stretch */}
        <div className="px-5 pb-5 overflow-x-auto agent-cards-scroll flex-1">
          <div className="inline-flex gap-3 pb-2">
            {Array.from({ length: cardCount }, (_, i) => (
              <AgentCard key={i} index={i} />
            ))}
          </div>
        </div>

        {/* Save & Start button for first-time setup */}
        {showSaveButton && (
          <div className="px-5 pb-4 pt-2 border-t border-v2-border">
            <button
              type="button"
              data-testid="save-and-start-btn"
              onClick={onSave}
              className={cn(
                'w-full py-2.5 rounded-v2-input text-sm font-semibold',
                'bg-v2-accent text-white hover:bg-v2-accent-hover',
                'transition-colors duration-150'
              )}
            >
              Save & Start
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// MaxRoundsSelector — compact dropdown for max rounds
// ────────────────────────────────────────────────────────────────

const DEFAULT_MAX_ROUNDS = 5;
const MAX_ROUNDS_OPTIONS = [
  ...Array.from({ length: 10 }, (_, i) => ({
    label: String(i + 1),
    value: String(i + 1),
  })),
];

function MaxRoundsSelector() {
  const maxAnswers = useModeStore((s) => s.maxAnswers);
  const setMaxAnswers = useModeStore((s) => s.setMaxAnswers);

  // Display the effective value: user-set or default
  const effectiveValue = maxAnswers ?? DEFAULT_MAX_ROUNDS;

  return (
    <div
      data-testid="max-rounds-selector"
      className="inline-flex items-center shrink-0 gap-1 px-2 py-1.5 rounded-v2-input bg-[var(--v2-input-bg)] border border-v2-border text-xs"
    >
      <span className="text-[10px] font-semibold uppercase tracking-wider text-v2-text-muted">
        Rounds
      </span>
      <select
        data-testid="max-rounds-select"
        value={String(effectiveValue)}
        onChange={(e) => {
          const v = Number(e.target.value);
          setMaxAnswers(v === DEFAULT_MAX_ROUNDS ? null : v);
        }}
        className={cn(
          'bg-transparent text-xs font-medium cursor-pointer',
          'focus:outline-none',
          maxAnswers !== null ? 'text-v2-accent font-semibold' : 'text-v2-text'
        )}
      >
        {MAX_ROUNDS_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// ModeConfigBar — main export
// ────────────────────────────────────────────────────────────────

const PLAN_MODE_ITEMS: DropdownItem<PlanMode>[] = [
  { label: 'Normal', value: 'normal', description: 'Standard multi-agent run' },
  { label: 'Plan', value: 'plan', description: 'Create plan, approve, execute' },
  { label: 'Spec', value: 'spec', description: 'Generate requirements spec' },
  { label: 'Analyze', value: 'analyze', description: 'Deep structured analysis' },
];

const PERSONAS_ITEMS: DropdownItem<PersonasMode>[] = [
  { label: 'No Personas', value: 'off' },
  { label: 'Perspective', value: 'perspective' },
  { label: 'Implementation', value: 'implementation' },
  { label: 'Methodology', value: 'methodology' },
];

// ────────────────────────────────────────────────────────────────
// PreCollabDropdown — combined Personas + Eval Criteria + Prompt Improver
// ────────────────────────────────────────────────────────────────

function PreCollabDropdown() {
  const personasMode = useModeStore((s) => s.personasMode);
  const evalCriteriaEnabled = useModeStore((s) => s.evalCriteriaEnabled);
  const promptImproverEnabled = useModeStore((s) => s.promptImproverEnabled);
  const configPersonaMode = useModeStore((s) => s.configPersonaMode);
  const configEvalCriteriaEnabled = useModeStore((s) => s.configEvalCriteriaEnabled);
  const configPromptImproverEnabled = useModeStore((s) => s.configPromptImproverEnabled);
  const configLocked = useModeStore((s) => s.configLocked);
  const setPersonasMode = useModeStore((s) => s.setPersonasMode);
  const setEvalCriteriaEnabled = useModeStore((s) => s.setEvalCriteriaEnabled);
  const setPromptImproverEnabled = useModeStore((s) => s.setPromptImproverEnabled);

  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [menuPos, setMenuPos] = useState<{ left: number; bottom: number } | null>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (ref.current?.contains(target)) return;
      if (menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  useEffect(() => {
    if (open && ref.current) {
      const rect = ref.current.getBoundingClientRect();
      setMenuPos({ left: rect.left, bottom: window.innerHeight - rect.top + 6 });
    }
  }, [open]);

  // Effective values (respect config lock)
  const effPersonas = configLocked ? (configPersonaMode ?? personasMode) : personasMode;
  const effEval = configLocked ? !!configEvalCriteriaEnabled : evalCriteriaEnabled;
  const effImprove = configLocked ? !!configPromptImproverEnabled : promptImproverEnabled;

  // Summary label
  const activeCount =
    (effPersonas !== 'off' ? 1 : 0) + (effEval ? 1 : 0) + (effImprove ? 1 : 0);
  const summaryLabel = activeCount === 0
    ? 'Off'
    : activeCount === 1
      ? (effPersonas !== 'off' ? 'Personas' : effEval ? 'Eval' : 'Improve')
      : `${activeCount} active`;

  const isActive = activeCount > 0;

  return (
    <div ref={ref} className="relative shrink-0" data-testid="dropdown-precollab">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={cn(
          'inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-v2-input',
          'text-xs font-medium cursor-pointer border transition-all duration-150',
          'whitespace-nowrap select-none',
          isActive
            ? 'border-v2-accent bg-v2-accent/15'
            : 'border-v2-border bg-[var(--v2-input-bg)]',
          'hover:border-v2-accent'
        )}
      >
        <span className="text-[10px] font-semibold uppercase tracking-wider text-v2-text-muted">
          Pre-Collab
        </span>
        <span className={cn(isActive ? 'text-v2-accent font-semibold' : 'text-v2-text')}>
          {summaryLabel}
        </span>
        <span className="text-[8px] text-v2-text-muted ml-0.5">{'\u25BE'}</span>
      </button>

      {open && menuPos && createPortal(
        <div
          ref={menuRef}
          data-testid="dropdown-precollab-menu"
          className={cn(
            'fixed z-[9999]',
            'bg-v2-surface-raised border border-v2-border rounded-lg',
            'shadow-lg min-w-[200px] p-1'
          )}
          style={{ left: menuPos.left, bottom: menuPos.bottom }}
        >
          {/* Personas section */}
          <div className="px-2 pt-1.5 pb-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-v2-text-muted">
              Personas
            </span>
          </div>
          {PERSONAS_ITEMS.map((item) => (
            <button
              key={item.value}
              type="button"
              data-testid={`precollab-persona-${item.value}`}
              onClick={() => setPersonasMode(item.value)}
              className={cn(
                'w-full text-left flex items-center gap-2 px-2.5 py-1.5 rounded-v2-input',
                'text-xs transition-colors',
                effPersonas === item.value
                  ? 'text-v2-accent font-semibold'
                  : 'text-v2-text-secondary hover:bg-[var(--v2-channel-hover)] hover:text-v2-text'
              )}
            >
              <span className="w-4 text-center text-xs">{effPersonas === item.value ? '\u2713' : ''}</span>
              {item.label}
            </button>
          ))}

          {/* Divider */}
          <div className="mx-2 my-1 border-t border-v2-border" />

          {/* Eval Criteria toggle */}
          <button
            type="button"
            data-testid="precollab-eval-criteria"
            onClick={() => setEvalCriteriaEnabled(!effEval)}
            className={cn(
              'w-full text-left flex items-center gap-2 px-2.5 py-1.5 rounded-v2-input',
              'text-xs transition-colors',
              effEval
                ? 'text-v2-accent font-semibold'
                : 'text-v2-text-secondary hover:bg-[var(--v2-channel-hover)] hover:text-v2-text'
            )}
          >
            <span className="w-4 text-center text-xs">{effEval ? '\u2713' : ''}</span>
            Eval Criteria
          </button>

          {/* Prompt Improver toggle */}
          <button
            type="button"
            data-testid="precollab-prompt-improver"
            onClick={() => setPromptImproverEnabled(!effImprove)}
            className={cn(
              'w-full text-left flex items-center gap-2 px-2.5 py-1.5 rounded-v2-input',
              'text-xs transition-colors',
              effImprove
                ? 'text-v2-accent font-semibold'
                : 'text-v2-text-secondary hover:bg-[var(--v2-channel-hover)] hover:text-v2-text'
            )}
          >
            <span className="w-4 text-center text-xs">{effImprove ? '\u2713' : ''}</span>
            Improve Prompt
          </button>
        </div>,
        document.body
      )}
    </div>
  );
}

export function ModeConfigBar({ configPath }: { configPath?: string } = {}) {
  const coordinationMode = useModeStore((s) => s.coordinationMode);
  const agentMode = useModeStore((s) => s.agentMode);
  const refinementEnabled = useModeStore((s) => s.refinementEnabled);
  const planMode = useModeStore((s) => s.planMode);
  const dockerEnabled = useModeStore((s) => s.dockerEnabled);
  const dockerAvailable = useModeStore((s) => s.dockerAvailable);
  const dockerStatus = useModeStore((s) => s.dockerStatus);
  const executionLocked = useModeStore((s) => s.executionLocked);
  const providers = useModeStore((s) => s.providers);

  const selectedMainAgent = useModeStore((s) => s.selectedMainAgent);
  const configAgents = useModeStore((s) => s.configAgents);
  const setCoordinationMode = useModeStore((s) => s.setCoordinationMode);
  const setSelectedMainAgent = useModeStore((s) => s.setSelectedMainAgent);
  const setAgentMode = useModeStore((s) => s.setAgentMode);
  const setRefinementEnabled = useModeStore((s) => s.setRefinementEnabled);
  const setPlanMode = useModeStore((s) => s.setPlanMode);
  const setDockerEnabled = useModeStore((s) => s.setDockerEnabled);
  const fetchProviders = useModeStore((s) => s.fetchProviders);
  const fetchDockerStatus = useModeStore((s) => s.fetchDockerStatus);
  const needsFirstTimeSetup = useModeStore((s) => s.needsFirstTimeSetup);
  const persistState = useModeStore((s) => s.persistState);
  const configLocked = useModeStore((s) => s.configLocked);

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  // Fetch providers + docker status on mount
  useEffect(() => {
    if (providers.length === 0) fetchProviders();
    fetchDockerStatus();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="relative">
      {/* Config preview panel — floats above the mode bar */}
      {previewOpen && configPath && (
        <ConfigPreviewPanel configPath={configPath} onClose={() => setPreviewOpen(false)} />
      )}

      <div
        data-testid="mode-config-bar"
        className={cn(
          'border-t border-v2-border bg-v2-surface px-4 py-[7px]',
          'flex items-center gap-1.5 flex-nowrap overflow-x-auto v2-scrollbar',
          executionLocked && 'opacity-50 pointer-events-none'
        )}
      >
        {/* Mode controls — locked when using a config file */}
        <div className={cn(
          'contents',
          configLocked && 'opacity-50 pointer-events-none'
        )}>
          {/* Mode dropdown */}
          <DropdownToken<PlanMode>
            label="Mode"
            items={PLAN_MODE_ITEMS}
            value={planMode}
            defaultValue="normal"
            onChange={setPlanMode}
            testId="dropdown-plan-mode"
          />

          {/* Coordination mode dropdown */}
          <DropdownToken<CoordinationMode>
            label="Coord"
            items={[
              { label: 'Parallel', value: 'parallel', description: 'All agents work simultaneously' },
              { label: 'Decomp', value: 'decomposition', description: 'Task decomposition with owned subtasks' },
              { label: 'Checkpoint', value: 'checkpoint', description: 'Main agent delegates via checkpoint()' },
            ]}
            value={coordinationMode}
            defaultValue="parallel"
            onChange={setCoordinationMode}
            testId="dropdown-coordination"
          />

          {/* Main agent selector (checkpoint mode only) */}
          {coordinationMode === 'checkpoint' && configAgents.length > 0 && (
            <DropdownToken<string>
              label="Main"
              items={configAgents.map((a) => ({
                label: a.id,
                value: a.id,
                description: a.model ? `${a.provider ?? ''}/${a.model}` : undefined,
              }))}
              value={selectedMainAgent ?? configAgents[0]?.id ?? ''}
              defaultValue={configAgents[0]?.id ?? ''}
              onChange={setSelectedMainAgent}
              testId="dropdown-main-agent"
            />
          )}

          {/* Agent mode toggle */}
          <ToggleButton<AgentMode>
            options={[
              { label: 'Multi', value: 'multi' },
              { label: 'Single', value: 'single' },
            ]}
            value={agentMode}
            onChange={setAgentMode}
            testId="toggle-agent-mode"
          />

          {/* Refinement toggle */}
          <ToggleButton<string>
            options={[
              { label: 'Refine', value: 'on' },
              { label: 'Quick', value: 'off' },
            ]}
            value={refinementEnabled ? 'on' : 'off'}
            onChange={(v) => setRefinementEnabled(v === 'on')}
            testId="toggle-refinement"
          />

          {/* Pre-Collab dropdown (Personas + Eval Criteria + Prompt Improver) */}
          <PreCollabDropdown />

          {/* Max rounds selector — right of Personas, only visible when Refine is active */}
          {refinementEnabled && (
            <MaxRoundsSelector />
          )}

          {/* Separator dot */}
          <div className="w-[3px] h-[3px] rounded-full bg-v2-border flex-shrink-0" />

          {/* Agent count stepper */}
          <AgentCountStepper onIncrement={() => setDrawerOpen(true)} />
        </div>

        {/* Agent summary button — always clickable to view models */}
        <AgentSummaryButton onClick={() => setDrawerOpen(true)} />

        {/* Docker toggle — pushed right, availability-aware */}
        <button
          type="button"
          data-testid="docker-toggle"
          disabled={dockerAvailable === false}
          onClick={() => {
            if (dockerAvailable === false) return;
            setDockerEnabled(dockerEnabled === true ? false : true);
          }}
          title={
            dockerAvailable === false
              ? dockerStatus === 'not_installed'
                ? 'Docker not installed. Run: massgen --setup-docker'
                : dockerStatus === 'not_running'
                  ? 'Docker not running. Start Docker Desktop first.'
                  : 'Docker unavailable'
              : dockerEnabled === true
                ? 'Docker isolation enabled'
                : 'Click to enable Docker isolation'
          }
          className={cn(
            'inline-flex items-center shrink-0 gap-1.5 px-2.5 py-1.5 rounded-v2-input',
            'text-xs font-medium border transition-colors duration-100 ml-auto whitespace-nowrap',
            dockerAvailable === false
              ? 'bg-[var(--v2-input-bg)] text-v2-text-muted/40 border-v2-border/50 cursor-not-allowed'
              : dockerEnabled === true
                ? 'bg-v2-online/15 text-v2-online border-v2-online/30'
                : 'bg-[var(--v2-input-bg)] text-v2-text-muted border-v2-border hover:text-v2-text-secondary hover:border-v2-accent'
          )}
        >
          <span
            className={cn(
              'w-1.5 h-1.5 rounded-full',
              dockerAvailable === false
                ? 'bg-red-400/60'
                : dockerEnabled === true
                  ? 'bg-v2-online'
                  : 'bg-current opacity-60'
            )}
          />
          Docker
        </button>

        {/* Preview config toggle */}
        <button
          type="button"
          data-testid="config-preview-toggle"
          onClick={() => setPreviewOpen(!previewOpen)}
          disabled={!configPath}
          title={!configPath ? 'Select a config first' : 'Preview resolved config'}
          className={cn(
            'inline-flex items-center shrink-0 gap-1 px-2 py-1.5 rounded-v2-input',
            'text-xs font-medium border transition-colors duration-100',
            previewOpen
              ? 'bg-v2-accent/15 text-v2-accent border-v2-accent/30'
              : 'bg-[var(--v2-input-bg)] text-v2-text-muted border-v2-border hover:text-v2-text-secondary hover:border-v2-accent',
            !configPath && 'opacity-40 cursor-not-allowed'
          )}
        >
          YAML
        </button>
      </div>
      </div>

      {/* Agent config drawer */}
      <AgentConfigDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        showSaveButton={needsFirstTimeSetup}
        onSave={async () => {
          await persistState();
          setDrawerOpen(false);
        }}
      />
    </>
  );
}
