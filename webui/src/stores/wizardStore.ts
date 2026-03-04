/**
 * Quickstart Wizard Store
 *
 * Manages state for the quickstart wizard flow.
 */

import { create } from 'zustand';

// Types for wizard state
export type WizardStep = 'context' | 'docker' | 'apiKeys' | 'agentCount' | 'setupMode' | 'agentConfig' | 'coordination' | 'preview';

export interface ContextPath {
  path: string;
  type: 'read' | 'write';
}

export interface ProviderInfo {
  id: string;
  name: string;
  models: string[];
  default_model: string;
  env_var: string | null;
  has_api_key: boolean;
  capabilities: string[];
  notes: string;
}

// Provider capabilities from the capabilities API
export interface ProviderCapabilities {
  provider_id: string;
  supports_web_search: boolean;
  supports_code_execution: boolean;
  supports_mcp: boolean;
  builtin_tools: string[];
  filesystem_support: string;
  all_capabilities: string[];
}

export interface AgentConfig {
  id: string;
  provider: string;
  model: string;
  // Per-agent tool settings
  enable_web_search?: boolean;
  enable_code_execution?: boolean;
  // Per-agent custom instruction
  system_message?: string;
}

// Subagent orchestrator configuration
export interface SubagentOrchestratorConfig {
  enabled: boolean;
  agents: Array<{
    backend: {
      type: string;
      model: string;
      base_url?: string;
    };
  }>;
}

// Persona generator configuration
export interface PersonaGeneratorConfig {
  enabled: boolean;
  diversity_mode?: 'perspective' | 'implementation';
}

// Coordination settings (shared across all agents)
export interface CoordinationSettings {
  voting_sensitivity: 'lenient' | 'balanced' | 'strict';
  answer_novelty_requirement: 'lenient' | 'balanced' | 'strict';
  max_new_answers_per_agent?: number;
  enable_subagents?: boolean;
  subagent_model_choice?: 'inherit' | 'custom';
  subagent_orchestrator?: SubagentOrchestratorConfig;
  persona_generator?: PersonaGeneratorConfig;
}

export interface SetupStatus {
  needs_setup: boolean;
  has_config: boolean;
  config_path: string;
  docker_available: boolean;
}

interface WizardState {
  // UI state
  isOpen: boolean;
  currentStep: WizardStep;
  isLoading: boolean;
  error: string | null;

  // Setup status
  setupStatus: SetupStatus | null;

  // Providers from API
  providers: ProviderInfo[];

  // Dynamic models cache (provider_id -> model list)
  dynamicModels: Record<string, string[]>;
  loadingModels: Record<string, boolean>;

  // Provider capabilities cache (provider_id -> capabilities)
  providerCapabilities: Record<string, ProviderCapabilities>;
  loadingCapabilities: Record<string, boolean>;

  // User selections
  contextPaths: ContextPath[];
  useDocker: boolean;
  agentCount: number;
  setupMode: 'same' | 'different';
  agents: AgentConfig[];

  // Coordination settings
  coordinationSettings: CoordinationSettings;

  // Generated config
  generatedConfig: Record<string, unknown> | null;
  generatedYaml: string | null;

  // Config filename for custom naming
  configFilename: string;

  // Saved config path for auto-selection
  savedConfigPath: string | null;

  // Actions
  openWizard: () => void;
  closeWizard: () => void;
  setStep: (step: WizardStep) => void;
  nextStep: () => void;
  prevStep: () => void;
  addContextPath: (path: string, type: 'read' | 'write') => void;
  removeContextPath: (index: number) => void;
  updateContextPath: (index: number, path: string, type: 'read' | 'write') => void;
  setUseDocker: (useDocker: boolean) => void;
  setAgentCount: (count: number) => void;
  setSetupMode: (mode: 'same' | 'different') => void;
  setAgentConfig: (index: number, provider: string, model: string, enableWebSearch?: boolean) => void;
  setAllAgentsConfig: (provider: string, model: string, enableWebSearch?: boolean) => void;
  setAgentWebSearch: (index: number, enableWebSearch: boolean) => void;
  setAgentCodeExecution: (index: number, enableCodeExecution: boolean) => void;
  setAgentSystemMessage: (index: number, systemMessage: string) => void;
  setCoordinationSettings: (settings: Partial<CoordinationSettings>) => void;
  setConfigFilename: (filename: string) => void;
  setGeneratedYaml: (yaml: string) => void;

  // API actions
  fetchSetupStatus: () => Promise<void>;
  fetchProviders: () => Promise<void>;
  fetchDynamicModels: (providerId: string) => Promise<string[]>;
  fetchProviderCapabilities: (providerId: string) => Promise<ProviderCapabilities | null>;
  generateConfig: () => Promise<void>;
  saveConfig: () => Promise<boolean>;
  reset: () => void;
}

const stepOrder: WizardStep[] = ['docker', 'apiKeys', 'agentCount', 'setupMode', 'agentConfig', 'coordination', 'context', 'preview'];

const defaultCoordinationSettings: CoordinationSettings = {
  voting_sensitivity: 'lenient',
  answer_novelty_requirement: 'lenient',
};

const initialState = {
  isOpen: false,
  currentStep: 'docker' as WizardStep,
  isLoading: false,
  error: null,
  setupStatus: null,
  providers: [],
  dynamicModels: {} as Record<string, string[]>,
  loadingModels: {} as Record<string, boolean>,
  providerCapabilities: {} as Record<string, ProviderCapabilities>,
  loadingCapabilities: {} as Record<string, boolean>,
  contextPaths: [] as ContextPath[],
  useDocker: true,
  agentCount: 3,
  setupMode: 'same' as const,
  agents: [],
  coordinationSettings: defaultCoordinationSettings,
  generatedConfig: null,
  generatedYaml: null,
  configFilename: 'config',
  savedConfigPath: null,
};

export const useWizardStore = create<WizardState>()((set, get) => ({
  ...initialState,

  openWizard: () => {
    set({ isOpen: true, currentStep: 'docker' });
    // Fetch setup status and providers when wizard opens
    get().fetchSetupStatus();
    get().fetchProviders();
  },

  closeWizard: () => {
    set({ isOpen: false });
  },

  addContextPath: (path: string, type: 'read' | 'write') => {
    const { contextPaths } = get();
    set({ contextPaths: [...contextPaths, { path, type }] });
  },

  removeContextPath: (index: number) => {
    const { contextPaths } = get();
    set({ contextPaths: contextPaths.filter((_, i) => i !== index) });
  },

  updateContextPath: (index: number, path: string, type: 'read' | 'write') => {
    const { contextPaths } = get();
    const newPaths = [...contextPaths];
    if (newPaths[index]) {
      newPaths[index] = { path, type };
      set({ contextPaths: newPaths });
    }
  },

  setStep: (step: WizardStep) => {
    set({ currentStep: step });
  },

  nextStep: () => {
    const { currentStep, agentCount, providers } = get();
    const currentIndex = stepOrder.indexOf(currentStep);

    // Skip apiKeys step if at least one provider has an API key configured
    if (currentStep === 'docker') {
      const hasAnyKey = providers.some((p) => p.has_api_key);
      if (hasAnyKey) {
        set({ currentStep: 'agentCount' });
        return;
      }
    }

    // Skip setupMode step if only 1 agent
    if (currentStep === 'agentCount' && agentCount === 1) {
      // Initialize single agent
      set({
        setupMode: 'same',
        agents: [{ id: 'agent_a', provider: '', model: '' }],
        currentStep: 'agentConfig',
      });
      return;
    }

    // After setupMode, initialize agents array
    if (currentStep === 'setupMode') {
      const newAgents: AgentConfig[] = [];
      for (let i = 0; i < agentCount; i++) {
        newAgents.push({
          id: `agent_${String.fromCharCode(97 + i)}`,
          provider: '',
          model: '',
        });
      }
      set({ agents: newAgents });
    }

    // When moving to preview, generate the config
    if (currentStep === 'context') {
      get().generateConfig();
    }

    if (currentIndex < stepOrder.length - 1) {
      set({ currentStep: stepOrder[currentIndex + 1] });
    }
  },

  prevStep: () => {
    const { currentStep, agentCount, providers } = get();
    const currentIndex = stepOrder.indexOf(currentStep);

    // Skip apiKeys step when going back if providers have keys
    if (currentStep === 'agentCount') {
      const hasAnyKey = providers.some((p) => p.has_api_key);
      if (hasAnyKey) {
        set({ currentStep: 'docker' });
        return;
      }
    }

    // Skip setupMode step when going back if only 1 agent
    if (currentStep === 'agentConfig' && agentCount === 1) {
      set({ currentStep: 'agentCount' });
      return;
    }

    if (currentIndex > 0) {
      set({ currentStep: stepOrder[currentIndex - 1] });
    }
  },

  setUseDocker: (useDocker: boolean) => {
    set({ useDocker });
  },

  setAgentCount: (count: number) => {
    set({ agentCount: count });
  },

  setSetupMode: (mode: 'same' | 'different') => {
    set({ setupMode: mode });
  },

  setAgentConfig: (index: number, provider: string, model: string, enableWebSearch?: boolean) => {
    const { agents } = get();
    const newAgents = [...agents];
    if (newAgents[index]) {
      newAgents[index] = {
        ...newAgents[index],
        provider,
        model,
        ...(enableWebSearch !== undefined && { enable_web_search: enableWebSearch }),
      };
      set({ agents: newAgents });
    }
  },

  setAllAgentsConfig: (provider: string, model: string, enableWebSearch?: boolean) => {
    const { agents } = get();
    const newAgents = agents.map((agent) => ({
      ...agent,
      provider,
      model,
      ...(enableWebSearch !== undefined && { enable_web_search: enableWebSearch }),
    }));
    set({ agents: newAgents });
  },

  setAgentWebSearch: (index: number, enableWebSearch: boolean) => {
    const { agents } = get();
    const newAgents = [...agents];
    if (newAgents[index]) {
      newAgents[index] = { ...newAgents[index], enable_web_search: enableWebSearch };
      set({ agents: newAgents });
    }
  },

  setAgentCodeExecution: (index: number, enableCodeExecution: boolean) => {
    const { agents } = get();
    const newAgents = [...agents];
    if (newAgents[index]) {
      newAgents[index] = { ...newAgents[index], enable_code_execution: enableCodeExecution };
      set({ agents: newAgents });
    }
  },

  setAgentSystemMessage: (index: number, systemMessage: string) => {
    const { agents } = get();
    const newAgents = [...agents];
    if (newAgents[index]) {
      newAgents[index] = { ...newAgents[index], system_message: systemMessage || undefined };
      set({ agents: newAgents });
    }
  },

  setCoordinationSettings: (settings: Partial<CoordinationSettings>) => {
    const { coordinationSettings } = get();
    set({ coordinationSettings: { ...coordinationSettings, ...settings } });
  },

  setConfigFilename: (filename: string) => {
    // Allow the raw input - we'll sanitize on save if needed
    // This allows users to type freely while seeing the preview
    set({ configFilename: filename });
  },

  setGeneratedYaml: (yaml: string) => {
    set({ generatedYaml: yaml });
  },

  fetchSetupStatus: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch('/api/setup/status');
      if (!response.ok) {
        throw new Error('Failed to fetch setup status');
      }
      const data = await response.json();
      set({ setupStatus: data, useDocker: data.docker_available });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Unknown error' });
    } finally {
      set({ isLoading: false });
    }
  },

  fetchProviders: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch('/api/providers');
      if (!response.ok) {
        throw new Error('Failed to fetch providers');
      }
      const data = await response.json();
      set({ providers: data.providers });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Unknown error' });
    } finally {
      set({ isLoading: false });
    }
  },

  fetchDynamicModels: async (providerId: string) => {
    const { dynamicModels, loadingModels } = get();

    // Return cached models if already loaded
    if (dynamicModels[providerId]) {
      return dynamicModels[providerId];
    }

    // Don't fetch if already loading
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
    } catch (err) {
      set({ loadingModels: { ...get().loadingModels, [providerId]: false } });
      return [];
    }
  },

  fetchProviderCapabilities: async (providerId: string) => {
    const { providerCapabilities, loadingCapabilities } = get();

    // Return cached capabilities if already loaded
    if (providerCapabilities[providerId]) {
      return providerCapabilities[providerId];
    }

    // Don't fetch if already loading
    if (loadingCapabilities[providerId]) {
      return null;
    }

    set({ loadingCapabilities: { ...loadingCapabilities, [providerId]: true } });

    try {
      const response = await fetch(`/api/providers/${providerId}/capabilities`);
      if (!response.ok) {
        throw new Error('Failed to fetch capabilities');
      }
      const data = await response.json();

      set({
        providerCapabilities: { ...get().providerCapabilities, [providerId]: data },
        loadingCapabilities: { ...get().loadingCapabilities, [providerId]: false },
      });

      return data as ProviderCapabilities;
    } catch (err) {
      set({ loadingCapabilities: { ...get().loadingCapabilities, [providerId]: false } });
      return null;
    }
  },

  generateConfig: async () => {
    const { agents, useDocker, coordinationSettings, contextPaths } = get();
    set({ isLoading: true, error: null });

    try {
      const response = await fetch('/api/config/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agents,
          use_docker: useDocker,
          coordination: coordinationSettings,
          context_paths: contextPaths,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to generate config');
      }

      const data = await response.json();
      set({
        generatedConfig: data.config,
        generatedYaml: data.yaml,
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Unknown error' });
    } finally {
      set({ isLoading: false });
    }
  },

  saveConfig: async () => {
    const { generatedConfig, generatedYaml, configFilename } = get();
    if (!generatedConfig && !generatedYaml) {
      set({ error: 'No config to save' });
      return false;
    }

    set({ isLoading: true, error: null });

    try {
      // Build filename with .yaml extension
      const filename = `${configFilename || 'config'}.yaml`;

      // Send yaml_content if we have edited YAML, otherwise send the config object
      const body: Record<string, unknown> = { filename };
      if (generatedYaml) {
        body.yaml_content = generatedYaml;
      }
      if (generatedConfig) {
        body.config = generatedConfig;
      }

      const response = await fetch('/api/config/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to save config');
      }

      const data = await response.json();
      set({ isLoading: false, savedConfigPath: data.path });
      return true;
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Unknown error', isLoading: false });
      return false;
    }
  },

  reset: () => {
    set(initialState);
  },
}));

// Selectors
export const selectIsWizardOpen = (state: WizardState) => state.isOpen;
export const selectCurrentStep = (state: WizardState) => state.currentStep;
export const selectIsLoading = (state: WizardState) => state.isLoading;
export const selectError = (state: WizardState) => state.error;
export const selectSetupStatus = (state: WizardState) => state.setupStatus;
export const selectProviders = (state: WizardState) => state.providers;
export const selectContextPaths = (state: WizardState) => state.contextPaths;
export const selectUseDocker = (state: WizardState) => state.useDocker;
export const selectAgentCount = (state: WizardState) => state.agentCount;
export const selectSetupMode = (state: WizardState) => state.setupMode;
export const selectAgents = (state: WizardState) => state.agents;
export const selectGeneratedYaml = (state: WizardState) => state.generatedYaml;
export const selectSavedConfigPath = (state: WizardState) => state.savedConfigPath;
export const selectDynamicModels = (state: WizardState) => state.dynamicModels;
export const selectLoadingModels = (state: WizardState) => state.loadingModels;
export const selectConfigFilename = (state: WizardState) => state.configFilename;
export const selectProviderCapabilities = (state: WizardState) => state.providerCapabilities;
export const selectLoadingCapabilities = (state: WizardState) => state.loadingCapabilities;
export const selectCoordinationSettings = (state: WizardState) => state.coordinationSettings;
