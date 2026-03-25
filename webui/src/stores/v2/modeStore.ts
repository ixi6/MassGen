/**
 * Mode Configuration Store
 *
 * Manages runtime mode overrides for coordination, agent mode, refinement,
 * personas, plan mode, agent count, per-agent provider/model/features, and docker toggle.
 * Mirrors TuiModeState from massgen/frontend/displays/tui_modes.py.
 */

import { create } from 'zustand';
import type { ProviderInfo, ProviderCapabilities, ReasoningEffort, ReasoningProfile } from '../wizardStore';

export type CoordinationMode = 'parallel' | 'decomposition' | 'checkpoint';
export type AgentMode = 'multi' | 'single';
export type PersonasMode = 'off' | 'perspective' | 'implementation' | 'methodology';
export type PlanMode = 'normal' | 'plan' | 'spec' | 'analyze';

export interface AgentConfigOverride {
  provider: string | null;
  model: string | null;
  reasoningEffort: ReasoningEffort | null;
  enableWebSearch: boolean | null;
  enableCodeExecution: boolean | null;
}

const defaultAgentConfig = (): AgentConfigOverride => ({
  provider: null,
  model: null,
  reasoningEffort: null,
  enableWebSearch: null,
  enableCodeExecution: null,
});

interface ModeState {
  // Mode toggles
  coordinationMode: CoordinationMode;
  agentMode: AgentMode;
  selectedSingleAgent: string | null;
  selectedMainAgent: string | null;  // Checkpoint mode: which agent orchestrates
  refinementEnabled: boolean;
  personasMode: PersonasMode;
  planMode: PlanMode;

  // Agent config overrides (null = use YAML config as-is)
  agentCount: number | null;
  agentConfigs: AgentConfigOverride[];
  dynamicModels: Record<string, string[]>;
  loadingModels: Record<string, boolean>;
  providerCapabilities: Record<string, ProviderCapabilities>;
  reasoningProfiles: Record<string, ReasoningProfile | null>;  // "provider/model" → profile
  maxAnswers: number | null;  // null = use config default (typically 5)
  dockerEnabled: boolean | null;
  dockerAvailable: boolean | null;  // null = unknown, fetched from /api/setup/status
  dockerStatus: string | null;      // "ready" | "not_installed" | "not_running"

  // Pre-collab toggles
  evalCriteriaEnabled: boolean;
  promptImproverEnabled: boolean;

  // Execution lock
  executionLocked: boolean;

  // Available providers (fetched from /api/providers)
  providers: ProviderInfo[];

  // Custom config persistence
  customConfigPath: string | null;
  needsFirstTimeSetup: boolean;

  // Agents parsed from the selected YAML config (read-only display)
  configAgents: { id: string; provider: string | null; model: string | null }[];
  configMaxAnswers: number | null;  // max_new_answers from the config file
  configPersonaMode: PersonasMode | null;  // persona mode from the config file
  configEvalCriteriaEnabled: boolean | null;  // eval criteria from the config file
  configPromptImproverEnabled: boolean | null;  // prompt improver from the config file
  configLocked: boolean;  // true when a non-custom config is selected (mode bar is read-only)
}

interface ModeActions {
  setCoordinationMode: (mode: CoordinationMode) => void;
  setAgentMode: (mode: AgentMode) => void;
  setSelectedSingleAgent: (agentId: string | null) => void;
  setSelectedMainAgent: (agentId: string | null) => void;
  setRefinementEnabled: (enabled: boolean) => void;
  setPersonasMode: (mode: PersonasMode) => void;
  setEvalCriteriaEnabled: (enabled: boolean) => void;
  setPromptImproverEnabled: (enabled: boolean) => void;
  setPlanMode: (mode: PlanMode) => void;
  setAgentCount: (count: number | null) => void;
  setAgentConfig: (index: number, updates: Partial<AgentConfigOverride>) => void;
  applyToAllAgents: (sourceIndex: number) => void;
  setMaxAnswers: (count: number | null) => void;
  setDockerEnabled: (enabled: boolean | null) => void;
  fetchDockerStatus: () => Promise<void>;
  lock: () => void;
  unlock: () => void;
  reset: () => void;
  fetchProviders: () => Promise<void>;
  fetchDynamicModels: (providerId: string) => Promise<string[]>;
  fetchProviderCapabilities: (providerId: string) => Promise<ProviderCapabilities | null>;
  fetchReasoningProfile: (providerId: string, model: string) => Promise<ReasoningProfile | null>;

  /** Produce overrides dict to send over WebSocket */
  getOverrides: () => Record<string, unknown>;

  /** Persist current state to backend (webui_config.yaml + webui_state.json) */
  persistState: () => Promise<void>;

  /** Restore state from backend on page load */
  restoreState: () => Promise<void>;

  /** Fetch agent definitions from a config file and store for display */
  syncFromConfig: (configPath: string) => Promise<void>;
}

const initialState: ModeState = {
  coordinationMode: 'parallel',
  agentMode: 'multi',
  selectedSingleAgent: null,
  selectedMainAgent: null,
  refinementEnabled: true,
  personasMode: 'off',
  evalCriteriaEnabled: false,
  promptImproverEnabled: false,
  planMode: 'normal',
  agentCount: null,
  agentConfigs: [],
  maxAnswers: null,
  dynamicModels: {},
  loadingModels: {},
  providerCapabilities: {},
  reasoningProfiles: {},
  dockerEnabled: null,
  dockerAvailable: null,
  dockerStatus: null,
  executionLocked: false,
  providers: [],
  customConfigPath: null,
  needsFirstTimeSetup: false,
  configAgents: [],
  configMaxAnswers: null,
  configPersonaMode: null,
  configEvalCriteriaEnabled: null,
  configPromptImproverEnabled: null,
  configLocked: false,
};

export const useModeStore = create<ModeState & ModeActions>()((set, get) => ({
  ...initialState,

  setCoordinationMode: (mode) => {
    const updates: Partial<ModeState> = { coordinationMode: mode };
    // When entering checkpoint mode, ensure a main agent is selected
    if (mode === 'checkpoint' && !get().selectedMainAgent) {
      const { configAgents, agentConfigs } = get();
      const firstId = configAgents.length > 0
        ? configAgents[0].id
        : agentConfigs.length > 0
          ? `agent_${String.fromCharCode(97)}`
          : null;
      if (firstId) {
        updates.selectedMainAgent = firstId;
        updates.selectedSingleAgent = firstId;
      }
    }
    set(updates);
  },
  setAgentMode: (mode) => {
    const { selectedMainAgent, selectedSingleAgent } = get();
    // When switching to single mode, default to the main agent if set
    if (mode === 'single' && selectedMainAgent && !selectedSingleAgent) {
      set({ agentMode: mode, selectedSingleAgent: selectedMainAgent });
    } else {
      set({ agentMode: mode });
    }
  },
  setSelectedSingleAgent: (agentId) => set({ selectedSingleAgent: agentId }),
  setSelectedMainAgent: (agentId) => {
    // Keep selectedSingleAgent in sync — the "main" agent is also
    // the one that runs in single-agent mode
    set({ selectedMainAgent: agentId, selectedSingleAgent: agentId });
  },
  setRefinementEnabled: (enabled) => set({ refinementEnabled: enabled }),
  setPersonasMode: (mode) => set({ personasMode: mode }),
  setEvalCriteriaEnabled: (enabled) => set({ evalCriteriaEnabled: enabled }),
  setPromptImproverEnabled: (enabled) => set({ promptImproverEnabled: enabled }),
  setPlanMode: (mode) => set({ planMode: mode }),

  setAgentCount: (count) => {
    const { agentConfigs } = get();
    if (count === null) {
      set({ agentCount: null, agentConfigs: [] });
    } else if (count > agentConfigs.length) {
      const newConfigs = [...agentConfigs];
      for (let i = agentConfigs.length; i < count; i++) {
        newConfigs.push(defaultAgentConfig());
      }
      set({ agentCount: count, agentConfigs: newConfigs });
    } else if (count < agentConfigs.length) {
      set({ agentCount: count, agentConfigs: agentConfigs.slice(0, count) });
    } else {
      set({ agentCount: count });
    }
  },

  setAgentConfig: (index, updates) => {
    const { agentConfigs } = get();
    if (index < 0 || index >= agentConfigs.length) return;
    const newConfigs = [...agentConfigs];
    newConfigs[index] = { ...newConfigs[index], ...updates };
    set({ agentConfigs: newConfigs });
  },

  applyToAllAgents: (sourceIndex) => {
    const { agentConfigs } = get();
    if (sourceIndex < 0 || sourceIndex >= agentConfigs.length) return;
    const source = agentConfigs[sourceIndex];
    const newConfigs = agentConfigs.map(() => ({ ...source }));
    set({ agentConfigs: newConfigs });
  },

  setMaxAnswers: (count) => set({ maxAnswers: count }),
  setDockerEnabled: (enabled) => set({ dockerEnabled: enabled }),

  fetchDockerStatus: async () => {
    try {
      const response = await fetch('/api/setup/status');
      if (!response.ok) return;
      const data = await response.json();
      set({
        dockerAvailable: data.docker_available ?? false,
        dockerStatus: data.docker_status ?? null,
      });
    } catch {
      // Silently ignore
    }
  },

  lock: () => set({ executionLocked: true }),
  unlock: () => set({ executionLocked: false }),
  reset: () => set(initialState),

  fetchProviders: async () => {
    try {
      const response = await fetch('/api/providers');
      if (!response.ok) return;
      const data = await response.json();
      set({ providers: data.providers || [] });
    } catch {
      // Silently ignore — providers are optional enhancement
    }
  },

  fetchDynamicModels: async (providerId: string) => {
    const { dynamicModels, loadingModels } = get();

    if (dynamicModels[providerId]) {
      return dynamicModels[providerId];
    }

    if (loadingModels[providerId]) {
      return [];
    }

    set({ loadingModels: { ...loadingModels, [providerId]: true } });

    try {
      const response = await fetch(`/api/providers/${providerId}/models`);
      if (!response.ok) {
        throw new Error('Failed to fetch models');
      }
      const data = await response.json();
      const models = data.models || [];

      set({
        dynamicModels: { ...get().dynamicModels, [providerId]: models },
        loadingModels: { ...get().loadingModels, [providerId]: false },
      });

      return models;
    } catch {
      set({ loadingModels: { ...get().loadingModels, [providerId]: false } });
      return [];
    }
  },

  fetchProviderCapabilities: async (providerId: string) => {
    const { providerCapabilities } = get();

    if (providerCapabilities[providerId]) {
      return providerCapabilities[providerId];
    }

    try {
      const response = await fetch(`/api/providers/${providerId}/capabilities`);
      if (!response.ok) {
        throw new Error('Failed to fetch capabilities');
      }
      const data = await response.json();

      set({
        providerCapabilities: { ...get().providerCapabilities, [providerId]: data },
      });

      return data as ProviderCapabilities;
    } catch {
      return null;
    }
  },

  fetchReasoningProfile: async (providerId: string, model: string) => {
    const key = `${providerId}/${model}`;
    const { reasoningProfiles } = get();

    if (key in reasoningProfiles) {
      return reasoningProfiles[key];
    }

    try {
      const response = await fetch(
        `/api/quickstart/reasoning-profile?provider_id=${encodeURIComponent(providerId)}&model=${encodeURIComponent(model)}`
      );
      if (!response.ok) {
        throw new Error('Failed to fetch reasoning profile');
      }
      const data = await response.json();
      const profile = data.profile as ReasoningProfile | null;

      set({
        reasoningProfiles: { ...get().reasoningProfiles, [key]: profile },
      });

      return profile;
    } catch {
      set({
        reasoningProfiles: { ...get().reasoningProfiles, [key]: null },
      });
      return null;
    }
  },

  getOverrides: () => {
    const state = get();
    const overrides: Record<string, unknown> = {};

    // --- Orchestrator overrides (ported from TuiModeState.get_orchestrator_overrides) ---

    // Coordination mode: decomposition requires multi-agent, checkpoint is special
    let effectiveCoordination = state.coordinationMode;
    if (state.agentMode === 'single' && effectiveCoordination === 'decomposition') {
      effectiveCoordination = 'parallel';
    }
    if (effectiveCoordination === 'checkpoint') {
      overrides.coordination_mode = 'voting';  // Checkpoint uses voting during delegation
      overrides.checkpoint_enabled = true;
      if (state.selectedMainAgent) {
        overrides.main_agent = state.selectedMainAgent;
      }
    } else {
      overrides.coordination_mode =
        effectiveCoordination === 'decomposition' ? 'decomposition' : 'voting';
    }

    // Refinement disabled = quick mode
    if (!state.refinementEnabled) {
      overrides.max_new_answers_per_agent = 1;
      overrides.skip_final_presentation = true;

      if (state.agentMode === 'single') {
        overrides.skip_voting = true;
      } else {
        overrides.disable_injection = true;
        overrides.defer_voting_until_all_answered = true;
        overrides.final_answer_strategy = 'synthesize';
      }
    } else if (state.maxAnswers !== null) {
      // Custom max rounds (only applies when refinement is on)
      overrides.max_new_answers_per_agent = state.maxAnswers;
    }

    // Persona overrides
    if (state.personasMode !== 'off') {
      overrides.persona_generator_enabled = true;
      overrides.persona_diversity_mode = state.personasMode;
    }

    // Eval criteria generator
    if (state.evalCriteriaEnabled) {
      overrides.evaluation_criteria_generator_enabled = true;
    }

    // Prompt improver
    if (state.promptImproverEnabled) {
      overrides.prompt_improver_enabled = true;
    }

    // Plan mode overrides
    if (state.planMode !== 'normal') {
      overrides.plan_mode = state.planMode;
      overrides.enable_agent_task_planning = true;
      overrides.task_planning_filesystem_mode = true;
    }

    // --- Agent config overrides ---

    if (state.agentCount !== null) {
      overrides.agent_count = state.agentCount;
    }

    // Per-agent overrides
    const hasOverrides = state.agentConfigs.some(
      (c) =>
        c.provider !== null ||
        c.model !== null ||
        c.reasoningEffort !== null ||
        c.enableWebSearch !== null ||
        c.enableCodeExecution !== null
    );
    if (hasOverrides) {
      overrides.agent_overrides = state.agentConfigs.map((c) => ({
        ...(c.provider && { backend_type: c.provider }),
        ...(c.model && { model: c.model }),
        ...(c.reasoningEffort && { reasoning_effort: c.reasoningEffort }),
        ...(c.enableWebSearch !== null && { enable_web_search: c.enableWebSearch }),
        ...(c.enableCodeExecution !== null && { enable_code_execution: c.enableCodeExecution }),
      }));
    }

    if (state.dockerEnabled !== null) {
      overrides.docker_override = state.dockerEnabled;
    }

    return overrides;
  },

  persistState: async () => {
    const state = get();

    // Build agent settings from current state
    const agents = state.agentConfigs.map((c, i) => ({
      id: `agent_${String.fromCharCode(97 + i)}`,
      provider: c.provider || 'openai',
      model: c.model || 'gpt-4o',
      ...(c.reasoningEffort && { reasoning_effort: c.reasoningEffort }),
      ...(c.enableWebSearch !== null && { enable_web_search: c.enableWebSearch }),
      ...(c.enableCodeExecution !== null && { enable_code_execution: c.enableCodeExecution }),
    }));

    const agentSettings = {
      agents: agents.length > 0 ? agents : [{ id: 'agent_a', provider: 'openai', model: 'gpt-4o' }],
      use_docker: state.dockerEnabled ?? false,
    };

    const uiState = {
      coordinationMode: state.coordinationMode,
      agentMode: state.agentMode,
      refinementEnabled: state.refinementEnabled,
      personasMode: state.personasMode,
      evalCriteriaEnabled: state.evalCriteriaEnabled,
      promptImproverEnabled: state.promptImproverEnabled,
      planMode: state.planMode,
      maxAnswers: state.maxAnswers,
      agentCount: state.agentCount,
      dockerEnabled: state.dockerEnabled,
      agentConfigs: state.agentConfigs,
    };

    try {
      const response = await fetch('/api/webui/save-state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_settings: agentSettings, ui_state: uiState }),
      });
      if (response.ok) {
        const data = await response.json();
        if (data.config_path) {
          set({ customConfigPath: data.config_path, needsFirstTimeSetup: false });
        }
      }
    } catch {
      // Silently ignore persistence errors
    }
  },

  restoreState: async () => {
    try {
      const response = await fetch('/api/webui/state');
      if (!response.ok) return;
      const data = await response.json();

      if (data.exists && data.config_path) {
        const updates: Partial<ModeState> = {
          customConfigPath: data.config_path,
          needsFirstTimeSetup: false,
        };

        // Restore UI state if available
        if (data.ui_state) {
          const ui = data.ui_state;
          if (ui.coordinationMode) updates.coordinationMode = ui.coordinationMode;
          if (ui.agentMode) updates.agentMode = ui.agentMode;
          if (ui.refinementEnabled !== undefined) updates.refinementEnabled = ui.refinementEnabled;
          if (ui.personasMode) updates.personasMode = ui.personasMode;
          if (ui.evalCriteriaEnabled !== undefined) updates.evalCriteriaEnabled = ui.evalCriteriaEnabled;
          if (ui.promptImproverEnabled !== undefined) updates.promptImproverEnabled = ui.promptImproverEnabled;
          if (ui.planMode) updates.planMode = ui.planMode;
          if (ui.maxAnswers !== undefined) updates.maxAnswers = ui.maxAnswers;
          if (ui.agentCount !== undefined) updates.agentCount = ui.agentCount;
          if (ui.dockerEnabled !== undefined) updates.dockerEnabled = ui.dockerEnabled;

          // Restore per-agent configs if saved, otherwise rebuild empty defaults
          if (ui.agentConfigs && Array.isArray(ui.agentConfigs)) {
            updates.agentConfigs = ui.agentConfigs.map((c: Partial<AgentConfigOverride>) => ({
              provider: c.provider ?? null,
              model: c.model ?? null,
              reasoningEffort: c.reasoningEffort ?? null,
              enableWebSearch: c.enableWebSearch ?? null,
              enableCodeExecution: c.enableCodeExecution ?? null,
            }));
          } else if (ui.agentCount !== null && ui.agentCount !== undefined) {
            const configs: AgentConfigOverride[] = [];
            for (let i = 0; i < ui.agentCount; i++) {
              configs.push(defaultAgentConfig());
            }
            updates.agentConfigs = configs;
          }
        }

        set(updates);
      } else {
        set({ customConfigPath: null, needsFirstTimeSetup: true, maxAnswers: 5 });
      }
    } catch {
      // Silently ignore
    }
  },

  syncFromConfig: async (configPath: string) => {
    // Check if this is the custom config — if so, unlock
    const { customConfigPath } = get();
    const isCustom = configPath === customConfigPath;

    if (isCustom) {
      set({ configAgents: [], configMaxAnswers: null, configPersonaMode: null, configEvalCriteriaEnabled: null, configPromptImproverEnabled: null, configLocked: false });
      return;
    }

    try {
      const res = await fetch(`/api/config/agents?path=${encodeURIComponent(configPath)}`);
      if (!res.ok) return;
      const data = await res.json();
      const updates: Partial<ModeState> = { configLocked: true };
      if (data.agents && Array.isArray(data.agents)) {
        updates.configAgents = data.agents;
        // Default main agent to first agent so checkpoint mode works immediately.
        // Also reset if current selection isn't in the new agent list (stale ID).
        if (data.agents.length > 0) {
          const currentMain = get().selectedMainAgent;
          const agentIds = data.agents.map((a: { id: string }) => a.id);
          if (!currentMain || !agentIds.includes(currentMain)) {
            updates.selectedMainAgent = data.agents[0].id;
            updates.selectedSingleAgent = data.agents[0].id;
          }
        }
      }
      if (data.max_answers !== undefined && data.max_answers !== null) {
        updates.configMaxAnswers = data.max_answers;
      } else {
        updates.configMaxAnswers = null;
      }
      updates.configPersonaMode = data.persona_mode ?? null;
      updates.configEvalCriteriaEnabled = data.eval_criteria_enabled ?? null;
      updates.configPromptImproverEnabled = data.prompt_improver_enabled ?? null;
      set(updates);
    } catch {
      // Silently ignore
    }
  },
}));

// Debounced auto-save subscription
let persistTimeout: ReturnType<typeof setTimeout> | null = null;

useModeStore.subscribe(
  (state, prevState) => {
    // Skip if execution is locked (running a coordination)
    if (state.executionLocked) return;

    // Check if any persisted fields changed
    const changed =
      state.agentCount !== prevState.agentCount ||
      state.agentConfigs !== prevState.agentConfigs ||
      state.dockerEnabled !== prevState.dockerEnabled ||
      state.coordinationMode !== prevState.coordinationMode ||
      state.agentMode !== prevState.agentMode ||
      state.refinementEnabled !== prevState.refinementEnabled ||
      state.personasMode !== prevState.personasMode ||
      state.evalCriteriaEnabled !== prevState.evalCriteriaEnabled ||
      state.promptImproverEnabled !== prevState.promptImproverEnabled ||
      state.planMode !== prevState.planMode ||
      state.maxAnswers !== prevState.maxAnswers;

    if (!changed) return;

    // Don't auto-save if we haven't done initial setup yet and have no config
    if (state.needsFirstTimeSetup && !state.customConfigPath) return;

    // Debounce 800ms
    if (persistTimeout) clearTimeout(persistTimeout);
    persistTimeout = setTimeout(() => {
      useModeStore.getState().persistState();
    }, 800);
  },
);
