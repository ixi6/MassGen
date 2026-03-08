/**
 * Setup Page Store
 *
 * Manages state for the standalone setup page that handles:
 * - API key configuration
 * - Docker setup and image pulling
 * - Skills management (basic toggle)
 */

import { create } from 'zustand';

// Docker status values from backend diagnostics
export type DockerStatusValue =
  | 'ready'
  | 'binary_not_installed'
  | 'pip_library_not_installed'
  | 'daemon_not_running'
  | 'permission_denied'
  | 'images_missing'
  | 'connection_timeout'
  | 'unknown_error';

// Docker diagnostics from API
export interface DockerDiagnostics {
  status: DockerStatusValue;
  is_available: boolean;
  binary_installed: boolean;
  pip_library_installed: boolean;
  daemon_running: boolean;
  has_permissions: boolean;
  images_available: Record<string, boolean>;
  docker_version: string | null;
  api_version: string | null;
  platform: string;
  error_message: string;
  resolution_steps: string[];
}

// Provider info for API key setup
export interface ProviderInfo {
  id: string;
  name: string;
  env_var: string | null;
  has_api_key: boolean;
}

// Skill info from API
export interface SkillInfo {
  name: string;
  description: string;
  location: 'builtin' | 'project';
  path: string;
  installed: boolean;
}

// Docker pull progress event
export interface DockerPullProgress {
  event: 'start' | 'progress' | 'complete' | 'error' | 'done';
  image?: string;
  status?: string;
  progress?: string;
  layer_id?: string;
  error?: string;
  success?: boolean;
  all_complete?: boolean;
}

// Setup step
export type SetupStep = 'apiKeys' | 'docker' | 'skills';

interface SetupState {
  // Current step
  currentStep: SetupStep;

  // Loading states
  isLoading: boolean;
  error: string | null;

  // Docker diagnostics
  dockerDiagnostics: DockerDiagnostics | null;
  dockerLoading: boolean;

  // Docker pull state
  isPulling: boolean;
  pullProgress: Record<string, { status: string; progress: string }>;
  pullJobId: string | null;
  pullError: string | null;
  pullComplete: boolean;

  // API keys
  providers: ProviderInfo[];
  apiKeyInputs: Record<string, string>;  // env_var -> value (in-memory only)
  apiKeySaveLocation: 'global' | 'local';
  savingApiKeys: boolean;
  apiKeySaveError: string | null;
  apiKeySaveSuccess: boolean;

  // Skills
  skills: SkillInfo[];
  skillsLoading: boolean;
  selectedSkills: string[];  // Skill names to enable

  // Actions
  setStep: (step: SetupStep) => void;
  nextStep: () => void;
  prevStep: () => void;

  // Docker actions
  fetchDockerDiagnostics: () => Promise<void>;
  startDockerPull: (images: string[]) => Promise<void>;
  cancelDockerPull: () => void;

  // API key actions
  fetchProviders: () => Promise<void>;
  setApiKeyInput: (envVar: string, value: string) => void;
  setApiKeySaveLocation: (location: 'global' | 'local') => void;
  saveApiKeys: () => Promise<boolean>;
  clearApiKeyInputs: () => void;

  // Skills actions
  fetchSkills: () => Promise<void>;
  toggleSkill: (skillName: string) => void;
  selectAllSkills: () => void;
  deselectAllSkills: () => void;

  // Reset
  reset: () => void;
}

const stepOrder: SetupStep[] = ['apiKeys', 'docker', 'skills'];

const initialState = {
  currentStep: 'apiKeys' as SetupStep,
  isLoading: false,
  error: null,

  dockerDiagnostics: null,
  dockerLoading: false,

  isPulling: false,
  pullProgress: {} as Record<string, { status: string; progress: string }>,
  pullJobId: null,
  pullError: null,
  pullComplete: false,

  providers: [] as ProviderInfo[],
  apiKeyInputs: {} as Record<string, string>,
  apiKeySaveLocation: 'global' as 'global' | 'local',
  savingApiKeys: false,
  apiKeySaveError: null,
  apiKeySaveSuccess: false,

  skills: [] as SkillInfo[],
  skillsLoading: false,
  selectedSkills: [] as string[],
};

export const useSetupStore = create<SetupState>()((set, get) => ({
  ...initialState,

  setStep: (step: SetupStep) => {
    set({ currentStep: step });
  },

  nextStep: () => {
    const { currentStep } = get();
    const currentIndex = stepOrder.indexOf(currentStep);
    if (currentIndex < stepOrder.length - 1) {
      set({ currentStep: stepOrder[currentIndex + 1] });
    }
  },

  prevStep: () => {
    const { currentStep } = get();
    const currentIndex = stepOrder.indexOf(currentStep);
    if (currentIndex > 0) {
      set({ currentStep: stepOrder[currentIndex - 1] });
    }
  },

  // Docker actions
  fetchDockerDiagnostics: async () => {
    set({ dockerLoading: true, error: null });
    try {
      const response = await fetch('/api/docker/diagnostics');
      if (!response.ok) {
        throw new Error('Failed to fetch Docker diagnostics');
      }
      const data: DockerDiagnostics = await response.json();
      set({ dockerDiagnostics: data });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Unknown error' });
    } finally {
      set({ dockerLoading: false });
    }
  },

  startDockerPull: async (images: string[]) => {
    set({
      isPulling: true,
      pullProgress: {},
      pullError: null,
      pullComplete: false,
    });

    try {
      // Start the pull job
      const response = await fetch('/api/docker/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ images }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to start Docker pull');
      }

      const { job_id } = await response.json();
      set({ pullJobId: job_id });

      // Connect to SSE stream
      const eventSource = new EventSource(`/api/docker/pull/${job_id}/stream`);

      eventSource.onmessage = (event) => {
        try {
          const data: DockerPullProgress = JSON.parse(event.data);
          const { pullProgress } = get();

          if (data.event === 'progress' && data.image) {
            set({
              pullProgress: {
                ...pullProgress,
                [data.image]: {
                  status: data.status || '',
                  progress: data.progress || '',
                },
              },
            });
          } else if (data.event === 'complete' && data.image) {
            set({
              pullProgress: {
                ...pullProgress,
                [data.image]: {
                  status: 'Complete',
                  progress: '100%',
                },
              },
            });
          } else if (data.event === 'error') {
            set({ pullError: data.error || 'Unknown error during pull' });
          } else if (data.event === 'done') {
            set({ pullComplete: true, isPulling: false });
            eventSource.close();
            // Refresh diagnostics after pull
            get().fetchDockerDiagnostics();
          }
        } catch {
          // Ignore parse errors
        }
      };

      eventSource.onerror = () => {
        eventSource.close();
        set({ isPulling: false });
      };

    } catch (err) {
      set({
        pullError: err instanceof Error ? err.message : 'Unknown error',
        isPulling: false,
      });
    }
  },

  cancelDockerPull: () => {
    set({
      isPulling: false,
      pullProgress: {},
      pullJobId: null,
    });
  },

  // API key actions
  fetchProviders: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await fetch('/api/providers');
      if (!response.ok) {
        throw new Error('Failed to fetch providers');
      }
      const data = await response.json();
      // Filter to only providers with env_var (need API keys) or special CLI-auth backends
      const providersWithKeys = data.providers.filter(
        (p: ProviderInfo) => p.env_var || p.id === 'claude_code' || p.id === 'copilot'
      );
      set({ providers: providersWithKeys });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Unknown error' });
    } finally {
      set({ isLoading: false });
    }
  },

  setApiKeyInput: (envVar: string, value: string) => {
    const { apiKeyInputs } = get();
    set({
      apiKeyInputs: { ...apiKeyInputs, [envVar]: value },
      apiKeySaveSuccess: false,
      apiKeySaveError: null,
    });
  },

  setApiKeySaveLocation: (location: 'global' | 'local') => {
    set({ apiKeySaveLocation: location });
  },

  saveApiKeys: async () => {
    const { apiKeyInputs, apiKeySaveLocation } = get();

    // Filter out empty values
    const keysToSave: Record<string, string> = {};
    for (const [key, value] of Object.entries(apiKeyInputs)) {
      if (value && value.trim()) {
        keysToSave[key] = value.trim();
      }
    }

    if (Object.keys(keysToSave).length === 0) {
      set({ apiKeySaveError: 'No API keys to save' });
      return false;
    }

    set({ savingApiKeys: true, apiKeySaveError: null, apiKeySaveSuccess: false });

    try {
      const response = await fetch('/api/setup/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          keys: keysToSave,
          save_location: apiKeySaveLocation,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to save API keys');
      }

      set({ apiKeySaveSuccess: true, savingApiKeys: false });
      return true;
    } catch (err) {
      set({
        apiKeySaveError: err instanceof Error ? err.message : 'Unknown error',
        savingApiKeys: false,
      });
      return false;
    }
  },

  clearApiKeyInputs: () => {
    set({ apiKeyInputs: {}, apiKeySaveSuccess: false, apiKeySaveError: null });
  },

  // Skills actions
  fetchSkills: async () => {
    set({ skillsLoading: true, error: null });
    try {
      const response = await fetch('/api/skills');
      if (!response.ok) {
        throw new Error('Failed to fetch skills');
      }
      const data = await response.json();
      set({
        skills: data.skills,
        // Select all built-in skills by default
        selectedSkills: data.skills
          .filter((s: SkillInfo) => s.location === 'builtin')
          .map((s: SkillInfo) => s.name),
      });
    } catch (err) {
      set({ error: err instanceof Error ? err.message : 'Unknown error' });
    } finally {
      set({ skillsLoading: false });
    }
  },

  toggleSkill: (skillName: string) => {
    const { selectedSkills } = get();
    if (selectedSkills.includes(skillName)) {
      set({ selectedSkills: selectedSkills.filter((s) => s !== skillName) });
    } else {
      set({ selectedSkills: [...selectedSkills, skillName] });
    }
  },

  selectAllSkills: () => {
    const { skills } = get();
    set({ selectedSkills: skills.map((s) => s.name) });
  },

  deselectAllSkills: () => {
    set({ selectedSkills: [] });
  },

  reset: () => {
    set(initialState);
  },
}));

// Selectors
export const selectCurrentStep = (state: SetupState) => state.currentStep;
export const selectIsLoading = (state: SetupState) => state.isLoading;
export const selectError = (state: SetupState) => state.error;
export const selectDockerDiagnostics = (state: SetupState) => state.dockerDiagnostics;
export const selectDockerLoading = (state: SetupState) => state.dockerLoading;
export const selectIsPulling = (state: SetupState) => state.isPulling;
export const selectPullProgress = (state: SetupState) => state.pullProgress;
export const selectPullComplete = (state: SetupState) => state.pullComplete;
export const selectProviders = (state: SetupState) => state.providers;
export const selectApiKeyInputs = (state: SetupState) => state.apiKeyInputs;
export const selectApiKeySaveLocation = (state: SetupState) => state.apiKeySaveLocation;
export const selectSavingApiKeys = (state: SetupState) => state.savingApiKeys;
export const selectApiKeySaveSuccess = (state: SetupState) => state.apiKeySaveSuccess;
export const selectApiKeySaveError = (state: SetupState) => state.apiKeySaveError;
export const selectSkills = (state: SetupState) => state.skills;
export const selectSelectedSkills = (state: SetupState) => state.selectedSkills;
