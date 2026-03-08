/**
 * Setup Page
 *
 * Standalone setup wizard for configuring MassGen:
 * - API keys
 * - Docker setup
 * - Skills selection (basic)
 */

import { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Key,
  Container,
  Puzzle,
  ChevronRight,
  ChevronLeft,
  Check,
  AlertCircle,
  Loader2,
  ExternalLink,
  Eye,
  EyeOff,
  RefreshCw,
} from 'lucide-react';
import { useState } from 'react';
import {
  useSetupStore,
  selectCurrentStep,
  selectDockerDiagnostics,
  selectDockerLoading,
  selectIsPulling,
  selectPullProgress,
  selectPullComplete,
  selectProviders,
  selectApiKeyInputs,
  selectApiKeySaveLocation,
  selectSavingApiKeys,
  selectApiKeySaveSuccess,
  selectApiKeySaveError,
  type SetupStep,
} from '../stores/setupStore';
import { useThemeStore } from '../stores/themeStore';

// Step configuration
const steps: { id: SetupStep; title: string; icon: typeof Key }[] = [
  { id: 'apiKeys', title: 'API Keys', icon: Key },
  { id: 'docker', title: 'Docker Setup', icon: Container },
  { id: 'skills', title: 'Skills', icon: Puzzle },
];

// API Keys Section Component
function ApiKeysSection() {
  const providers = useSetupStore(selectProviders);
  const apiKeyInputs = useSetupStore(selectApiKeyInputs);
  const apiKeySaveLocation = useSetupStore(selectApiKeySaveLocation);
  const apiKeySaveSuccess = useSetupStore(selectApiKeySaveSuccess);
  const apiKeySaveError = useSetupStore(selectApiKeySaveError);

  const setApiKeyInput = useSetupStore((s) => s.setApiKeyInput);
  const setApiKeySaveLocation = useSetupStore((s) => s.setApiKeySaveLocation);
  const fetchProviders = useSetupStore((s) => s.fetchProviders);

  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});

  useEffect(() => {
    fetchProviders();
  }, [fetchProviders]);

  const toggleShowPassword = (envVar: string) => {
    setShowPasswords((prev) => ({ ...prev, [envVar]: !prev[envVar] }));
  };

  // Sort providers: popular ones first, then alphabetically
  const popularProviderIds = ['openai', 'claude', 'gemini', 'grok'];
  // Separate CLI-auth providers from other providers (they have special auth)
  const claudeCodeProvider = providers.find((p) => p.id === 'claude_code');
  const copilotProvider = providers.find((p) => p.id === 'copilot');
  const otherProviders = providers.filter((p) => p.id !== 'claude_code' && p.id !== 'copilot');
  const configuredProviders = otherProviders.filter((p) => p.has_api_key);
  const unconfiguredProviders = otherProviders.filter((p) => !p.has_api_key);

  // Sort unconfigured: popular first, then rest alphabetically
  const sortedUnconfiguredProviders = [...unconfiguredProviders].sort((a, b) => {
    const aPopular = popularProviderIds.indexOf(a.id);
    const bPopular = popularProviderIds.indexOf(b.id);
    if (aPopular !== -1 && bPopular !== -1) return aPopular - bPopular;
    if (aPopular !== -1) return -1;
    if (bPopular !== -1) return 1;
    return a.name.localeCompare(b.name);
  });

  const [showConfiguredKeys, setShowConfiguredKeys] = useState(false);

  return (
    <div className="space-y-6">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Configure API Keys</h2>
        <p className="text-gray-600 dark:text-gray-400">
          Enter API keys for the providers you want to use. Keys are saved securely to your local
          environment.
        </p>
      </div>

      {/* Configured Keys Summary - Always visible at top */}
      {configuredProviders.length > 0 && (
        <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Check className="w-5 h-5 text-green-600" />
              <div>
                <span className="font-medium text-green-800 dark:text-green-200">
                  {configuredProviders.length} API Key{configuredProviders.length !== 1 ? 's' : ''} Configured
                </span>
                <p className="text-green-700 dark:text-green-300 text-sm">
                  {configuredProviders.map(p => p.name).join(', ')}
                </p>
              </div>
            </div>
            <button
              onClick={() => setShowConfiguredKeys(!showConfiguredKeys)}
              className="flex items-center gap-1 px-3 py-1.5 text-sm text-green-700 dark:text-green-300
                       bg-green-100 dark:bg-green-900/50 hover:bg-green-200 dark:hover:bg-green-900
                       rounded-lg transition-colors"
            >
              {showConfiguredKeys ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              {showConfiguredKeys ? 'Hide' : 'Show'}
            </button>
          </div>
          {showConfiguredKeys && (
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {configuredProviders.map((provider) => (
                <div
                  key={provider.id}
                  className="bg-white dark:bg-gray-800 border border-green-200 dark:border-green-800 rounded-lg p-3"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-gray-800 dark:text-gray-200">{provider.name}</span>
                    <span className="text-sm text-gray-500 dark:text-gray-400 font-mono">••••••••</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Claude Code Section */}
      {claudeCodeProvider && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-800 dark:text-gray-200">Claude Code</span>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                (available if logged in via <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">claude</code> CLI)
              </span>
            </div>
          </div>
          <div className="relative">
            <input
              type={showPasswords['CLAUDE_CODE_API_KEY'] ? 'text' : 'password'}
              value={apiKeyInputs['CLAUDE_CODE_API_KEY'] || ''}
              onChange={(e) => setApiKeyInput('CLAUDE_CODE_API_KEY', e.target.value)}
              placeholder="CLAUDE_CODE_API_KEY (optional)"
              className="w-full px-3 py-2 pr-10 border border-gray-300 dark:border-gray-600 rounded-lg
                       bg-white dark:bg-gray-700 text-gray-800 dark:text-gray-200
                       focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
            <button
              type="button"
              onClick={() => toggleShowPassword('CLAUDE_CODE_API_KEY')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700
                       dark:text-gray-400 dark:hover:text-gray-200"
            >
              {showPasswords['CLAUDE_CODE_API_KEY'] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>
      )}

      {/* GitHub Copilot Section */}
      {copilotProvider && (
        <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-800 dark:text-gray-200">GitHub Copilot</span>
              <span className="text-xs text-gray-500 dark:text-gray-400">
                (available if logged in via <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">copilot</code> CLI <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">/login</code> and <code className="bg-gray-100 dark:bg-gray-700 px-1 rounded">github-copilot-sdk</code> installed)
              </span>
            </div>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            No API key required. Uses Copilot CLI or GitHub token authentication.
          </p>
        </div>
      )}

      {/* All Unconfigured Providers */}
      {sortedUnconfiguredProviders.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Add API Keys</h3>
          <div className="grid gap-4 md:grid-cols-2">
            {sortedUnconfiguredProviders.map((provider) => (
              <div
                key={provider.id}
                className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-4"
              >
                <div className="flex items-center justify-between mb-2">
                  <label className="font-medium text-gray-800 dark:text-gray-200">{provider.name}</label>
                </div>
                <div className="relative">
                  <input
                    type={showPasswords[provider.env_var!] ? 'text' : 'password'}
                    value={apiKeyInputs[provider.env_var!] || ''}
                    onChange={(e) => setApiKeyInput(provider.env_var!, e.target.value)}
                    placeholder={provider.env_var || ''}
                    className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 pr-10 text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => toggleShowPassword(provider.env_var!)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                  >
                    {showPasswords[provider.env_var!] ? (
                      <EyeOff className="w-4 h-4" />
                    ) : (
                      <Eye className="w-4 h-4" />
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Status Messages */}
      {(apiKeySaveSuccess || apiKeySaveError) && (
        <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
          {apiKeySaveSuccess && (
            <span className="text-green-600 dark:text-green-400 flex items-center gap-2">
              <Check className="w-4 h-4" /> API keys saved successfully
            </span>
          )}
          {apiKeySaveError && (
            <span className="text-red-600 dark:text-red-400 flex items-center gap-2">
              <AlertCircle className="w-4 h-4" /> {apiKeySaveError}
            </span>
          )}
        </div>
      )}

      {/* Save location and auto-save note */}
      <div className="flex items-center justify-between text-sm text-gray-500 dark:text-gray-400">
        <div className="flex items-center gap-4">
          <span>Save to:</span>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              name="saveLocation"
              checked={apiKeySaveLocation === 'global'}
              onChange={() => setApiKeySaveLocation('global')}
              className="w-3.5 h-3.5 text-blue-600"
            />
            <span>~/.massgen/.env</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              name="saveLocation"
              checked={apiKeySaveLocation === 'local'}
              onChange={() => setApiKeySaveLocation('local')}
              className="w-3.5 h-3.5 text-blue-600"
            />
            <span>./.env</span>
          </label>
        </div>
        <span>(saved on Next)</span>
      </div>
    </div>
  );
}

// Docker Section Component
function DockerSection() {
  const dockerDiagnostics = useSetupStore(selectDockerDiagnostics);
  const dockerLoading = useSetupStore(selectDockerLoading);
  const isPulling = useSetupStore(selectIsPulling);
  const pullProgress = useSetupStore(selectPullProgress);
  const pullComplete = useSetupStore(selectPullComplete);

  const fetchDockerDiagnostics = useSetupStore((s) => s.fetchDockerDiagnostics);
  const startDockerPull = useSetupStore((s) => s.startDockerPull);

  const [selectedImages, setSelectedImages] = useState<string[]>([
    'ghcr.io/massgen/mcp-runtime-sudo:latest',
  ]);

  useEffect(() => {
    fetchDockerDiagnostics();
  }, [fetchDockerDiagnostics]);

  const availableImages = [
    {
      name: 'ghcr.io/massgen/mcp-runtime-sudo:latest',
      description: 'Sudo image (recommended - allows package installation)',
    },
    {
      name: 'ghcr.io/massgen/mcp-runtime:latest',
      description: 'Standard image (no sudo access)',
    },
  ];

  const toggleImage = (imageName: string) => {
    setSelectedImages((prev) =>
      prev.includes(imageName) ? prev.filter((i) => i !== imageName) : [...prev, imageName]
    );
  };

  const handlePull = () => {
    startDockerPull(selectedImages);
  };

  // Status indicator colors
  const getStatusColor = (ok: boolean) =>
    ok ? 'text-green-500' : 'text-red-500';
  const getStatusIcon = (ok: boolean) =>
    ok ? <Check className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />;

  return (
    <div className="space-y-6">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Docker Setup</h2>
        <p className="text-gray-600 dark:text-gray-400">
          Docker provides isolated execution environments for MassGen agents.
        </p>
      </div>

      {/* Docker Status */}
      <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-200">Docker Status</h3>
          <button
            onClick={fetchDockerDiagnostics}
            disabled={dockerLoading}
            className="p-2 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
          >
            <RefreshCw className={`w-4 h-4 ${dockerLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {dockerLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
          </div>
        ) : dockerDiagnostics ? (
          <div className="space-y-3">
            {/* Status Checklist */}
            <div className="grid gap-2">
              <div className="flex items-center gap-2">
                <span className={getStatusColor(dockerDiagnostics.binary_installed)}>
                  {getStatusIcon(dockerDiagnostics.binary_installed)}
                </span>
                <span className="text-gray-700 dark:text-gray-300">Docker binary installed</span>
                {dockerDiagnostics.docker_version && (
                  <span className="text-xs text-gray-500">({dockerDiagnostics.docker_version})</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className={getStatusColor(dockerDiagnostics.pip_library_installed)}>
                  {getStatusIcon(dockerDiagnostics.pip_library_installed)}
                </span>
                <span className="text-gray-700 dark:text-gray-300">Docker Python library</span>
              </div>
              <div className="flex items-center gap-2">
                <span className={getStatusColor(dockerDiagnostics.daemon_running)}>
                  {getStatusIcon(dockerDiagnostics.daemon_running)}
                </span>
                <span className="text-gray-700 dark:text-gray-300">Docker daemon running</span>
              </div>
              <div className="flex items-center gap-2">
                <span className={getStatusColor(dockerDiagnostics.has_permissions)}>
                  {getStatusIcon(dockerDiagnostics.has_permissions)}
                </span>
                <span className="text-gray-700 dark:text-gray-300">Permissions OK</span>
              </div>
            </div>

            {/* Error Message with Resolution Steps */}
            {!dockerDiagnostics.is_available && dockerDiagnostics.error_message && (
              <div className="mt-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-lg p-4">
                <div className="flex items-start gap-2 text-red-800 dark:text-red-200">
                  <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="font-medium">{dockerDiagnostics.error_message}</p>
                    {dockerDiagnostics.resolution_steps.length > 0 && (
                      <div className="mt-3">
                        <p className="font-medium mb-2">To fix this:</p>
                        <ol className="list-decimal list-inside space-y-1 text-sm">
                          {dockerDiagnostics.resolution_steps.map((step, i) => (
                            <li key={i} className={step.startsWith('  ') ? 'ml-4 list-none' : ''}>
                              {step}
                            </li>
                          ))}
                        </ol>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Images Status */}
            {dockerDiagnostics.is_available && (
              <div className="mt-4">
                <h4 className="font-medium text-gray-800 dark:text-gray-200 mb-2">Installed Images</h4>
                {Object.keys(dockerDiagnostics.images_available).length > 0 ? (
                  <div className="space-y-1">
                    {Object.entries(dockerDiagnostics.images_available).map(([image, available]) => (
                      <div key={image} className="flex items-center gap-2 text-sm">
                        <span className={getStatusColor(available)}>
                          {getStatusIcon(available)}
                        </span>
                        <span className="text-gray-600 dark:text-gray-400 font-mono text-xs">
                          {image}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-gray-500 text-sm">No MassGen images found</p>
                )}
              </div>
            )}
          </div>
        ) : (
          <p className="text-gray-500">Unable to check Docker status</p>
        )}
      </div>

      {/* Image Selection & Pull - Only show if not all images are installed */}
      {dockerDiagnostics?.daemon_running && (() => {
        // Check which images are NOT yet installed
        const missingImages = availableImages.filter(
          (img) => !dockerDiagnostics.images_available[img.name]
        );

        // If all images are installed, don't show pull section
        if (missingImages.length === 0) {
          return (
            <div className="bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg p-6">
              <div className="flex items-center gap-3">
                <Check className="w-6 h-6 text-green-600" />
                <div>
                  <h3 className="text-lg font-semibold text-green-800 dark:text-green-200">
                    All Docker Images Installed
                  </h3>
                  <p className="text-green-700 dark:text-green-300 text-sm">
                    Your Docker environment is fully configured and ready to use.
                  </p>
                </div>
              </div>
            </div>
          );
        }

        return (
          <div className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
            <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-200 mb-4">
              Pull Missing Docker Images
            </h3>

            <div className="space-y-3 mb-6">
              {missingImages.map((img) => (
                <label key={img.name} className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedImages.includes(img.name)}
                    onChange={() => toggleImage(img.name)}
                    disabled={isPulling}
                    className="mt-1 w-4 h-4 text-blue-600 rounded"
                  />
                  <div>
                    <span className="text-gray-800 dark:text-gray-200 font-mono text-sm">{img.name}</span>
                    <p className="text-gray-500 dark:text-gray-400 text-sm">{img.description}</p>
                  </div>
                </label>
              ))}
            </div>

            {/* Pull Progress */}
            {isPulling && Object.keys(pullProgress).length > 0 && (
              <div className="mb-4 space-y-2">
                {Object.entries(pullProgress).map(([image, progress]) => (
                  <div key={image} className="text-sm">
                    <div className="flex items-center justify-between text-gray-600 dark:text-gray-400">
                      <span className="font-mono text-xs truncate max-w-xs">{image}</span>
                      <span>{progress.status}</span>
                    </div>
                    {progress.progress && (
                      <p className="text-xs text-gray-500 font-mono">{progress.progress}</p>
                    )}
                  </div>
                ))}
              </div>
            )}

            {pullComplete && (
              <div className="mb-4 bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 rounded-lg p-3">
                <span className="text-green-800 dark:text-green-200 flex items-center gap-2">
                  <Check className="w-4 h-4" /> Images pulled successfully!
                </span>
              </div>
            )}

            <button
              onClick={handlePull}
              disabled={isPulling || selectedImages.length === 0}
              className="px-6 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-400 text-white rounded-lg transition-colors flex items-center gap-2"
            >
              {isPulling ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Pulling...
                </>
              ) : (
                <>Pull Selected Images</>
              )}
            </button>
          </div>
        );
      })()}

      {/* Skip Option */}
      <p className="text-center text-gray-500 dark:text-gray-400 text-sm">
        Docker is optional. You can skip this step if you prefer local execution mode.
      </p>
    </div>
  );
}

// Skill type from API
interface Skill {
  name: string;
  description: string;
  location: 'builtin' | 'user' | 'project';
  path: string;
  installed: boolean;
}

// Skill package type
interface SkillPackage {
  id: string;
  name: string;
  description: string;
  installed: boolean;
  skillCount?: number;
}

const DEFAULT_SKILL_PACKAGES: SkillPackage[] = [
  {
    id: 'anthropic',
    name: 'Anthropic Skills Collection',
    description: 'Official Anthropic skills including code analysis, research, and more.',
    installed: false,
  },
  {
    id: 'openai',
    name: 'OpenAI Skills Collection',
    description: 'Official OpenAI skill library with curated and experimental skill sets.',
    installed: false,
  },
  {
    id: 'vercel',
    name: 'Vercel Agent Skills',
    description: 'Vercel-maintained skill pack for modern full-stack and app workflows.',
    installed: false,
  },
  {
    id: 'agent_browser',
    name: 'Vercel Agent Browser Skill',
    description: 'Skill for browser-native automation via the agent-browser runtime.',
    installed: false,
  },
  {
    id: 'remotion',
    name: 'Remotion Skill',
    description: 'Video generation and editing skill powered by Remotion.',
    installed: false,
  },
  {
    id: 'crawl4ai',
    name: 'Crawl4AI',
    description: 'Web crawling and scraping skill for extracting content from websites.',
    installed: false,
  },
];

// Skills Section Component
function SkillsSection() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);
  const [showSkillsBrowser, setShowSkillsBrowser] = useState(false);

  // Skill packages that can be installed
  const [packages, setPackages] = useState<SkillPackage[]>(DEFAULT_SKILL_PACKAGES);

  const fetchSkills = async () => {
    try {
      const response = await fetch('/api/skills');
      if (!response.ok) {
        throw new Error('Failed to fetch skills');
      }
      const data = await response.json();
      const skillsList = data.skills || [];
      setSkills(skillsList);

      // Prefer server-side package status (authoritative) when available.
      const packageMap = data.packages;
      if (packageMap && typeof packageMap === 'object') {
        const packageList: SkillPackage[] = Object.entries(packageMap).map(([id, pkg]) => {
          const typedPkg = pkg as Record<string, unknown>;
          return {
            id,
            name: String(typedPkg['name'] || id),
            description: String(typedPkg['description'] || ''),
            installed: Boolean(typedPkg['installed']),
            skillCount: typeof typedPkg['skill_count'] === 'number'
              ? typedPkg['skill_count']
              : (typeof typedPkg['skillCount'] === 'number' ? typedPkg['skillCount'] : undefined),
          };
        });
        setPackages(packageList);
      } else {
        setPackages(DEFAULT_SKILL_PACKAGES);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load skills');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSkills();
  }, []);

  const handleInstallPackage = async (packageId: string) => {
    setInstalling(packageId);
    setInstallError(null);

    try {
      const response = await fetch('/api/skills/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ package: packageId }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Installation failed');
      }

      // Refresh skills list
      await fetchSkills();
    } catch (err) {
      setInstallError(err instanceof Error ? err.message : 'Installation failed');
    } finally {
      setInstalling(null);
    }
  };

  const builtinSkills = skills.filter((s) => s.location === 'builtin');
  const userSkills = skills.filter((s) => s.location === 'user');
  const projectSkills = skills.filter((s) => s.location === 'project');
  const installedSkills = [...userSkills, ...projectSkills];

  return (
    <div className="space-y-6">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">Skills</h2>
        <p className="text-gray-600 dark:text-gray-400">
          Skills extend agent capabilities with specialized knowledge, workflows, and tools.
          Install skill packages below, then enable them in your YAML config.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
        </div>
      ) : error ? (
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <div className="flex items-center gap-2 text-red-800 dark:text-red-200">
            <AlertCircle className="w-5 h-5" />
            <span>{error}</span>
          </div>
        </div>
      ) : (
        <>
          {/* Summary */}
          <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Check className="w-5 h-5 text-green-600" />
                <div>
                  <span className="font-medium text-green-800 dark:text-green-200">
                    {skills.length} Skill{skills.length !== 1 ? 's' : ''} Available
                  </span>
                  <p className="text-green-700 dark:text-green-300 text-sm">
                    {builtinSkills.length} built-in, {installedSkills.length} installed
                  </p>
                </div>
              </div>
              {skills.length > 0 && (
                <button
                  onClick={() => setShowSkillsBrowser(!showSkillsBrowser)}
                  className="text-sm text-green-700 dark:text-green-300 hover:underline"
                >
                  {showSkillsBrowser ? 'Hide Skills' : 'Browse Skills'}
                </button>
              )}
            </div>
          </div>

          {/* Install Error */}
          {installError && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
              <div className="flex items-center gap-2 text-red-800 dark:text-red-200">
                <AlertCircle className="w-5 h-5" />
                <span>{installError}</span>
              </div>
            </div>
          )}

          {/* Skill Packages */}
          <div className="space-y-3">
            <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-200">
              Skill Packages
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Install skill packages to add new capabilities. Requires CLI installation (run in terminal).
            </p>
            <div className="grid gap-4">
              {packages.map((pkg) => (
                <div
                  key={pkg.id}
                  className="bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-4"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-gray-800 dark:text-gray-200">
                          {pkg.name}
                        </span>
                        {pkg.installed ? (
                          <span className="px-2 py-0.5 text-xs bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300 rounded">
                            installed{pkg.skillCount ? ` (${pkg.skillCount} skills)` : ''}
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded">
                            not installed
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-600 dark:text-gray-400">
                        {pkg.description}
                      </p>
                    </div>
                    {pkg.installed ? (
                      <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                    ) : (
                      <button
                        onClick={() => handleInstallPackage(pkg.id)}
                        disabled={installing !== null}
                        className="px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-500 disabled:bg-gray-400
                                 text-white rounded-lg transition-colors flex items-center gap-2"
                      >
                        {installing === pkg.id ? (
                          <>
                            <Loader2 className="w-4 h-4 animate-spin" />
                            Installing...
                          </>
                        ) : (
                          'Install'
                        )}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Or install via CLI: <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">massgen --setup-skills</code>
            </p>
          </div>

          {/* Skills Browser (collapsible) */}
          {showSkillsBrowser && skills.length > 0 && (
            <div className="space-y-3 border-t border-gray-200 dark:border-gray-700 pt-4">
              <h3 className="text-lg font-semibold text-gray-800 dark:text-gray-200">
                Installed Skills
              </h3>

              {/* Built-in Skills */}
              {builtinSkills.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400">Built-in</h4>
                  <div className="grid gap-2 md:grid-cols-2">
                    {builtinSkills.map((skill) => (
                      <div
                        key={skill.name}
                        className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-lg p-3"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                            {skill.name}
                          </span>
                          <span className="px-1.5 py-0.5 text-xs bg-blue-100 dark:bg-blue-900/50 text-blue-600 dark:text-blue-400 rounded">
                            built-in
                          </span>
                        </div>
                        {skill.description && (
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-1">
                            {skill.description}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Installed Skills (user + project) */}
              {installedSkills.length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-medium text-gray-600 dark:text-gray-400">Installed</h4>
                  <div className="grid gap-2 md:grid-cols-2">
                    {installedSkills.map((skill) => (
                      <div
                        key={skill.name}
                        className="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700 rounded-lg p-3"
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                            {skill.name}
                          </span>
                          <span className="px-1.5 py-0.5 text-xs bg-purple-100 dark:bg-purple-900/50 text-purple-600 dark:text-purple-400 rounded">
                            {skill.location === 'user' ? 'user' : 'project'}
                          </span>
                        </div>
                        {skill.description && (
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-1">
                            {skill.description}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* No Skills Message */}
          {skills.length === 0 && (
            <div className="text-center py-4 text-gray-500 dark:text-gray-400">
              <p className="text-sm">No skills installed yet. Install a package above to get started.</p>
            </div>
          )}
        </>
      )}

      <p className="text-center text-gray-500 dark:text-gray-400 text-sm">
        Enable skills in your YAML config under{' '}
        <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">coordination.use_skills</code> and{' '}
        <code className="bg-gray-200 dark:bg-gray-700 px-1 rounded">coordination.massgen_skills</code>.
      </p>
    </div>
  );
}

// Main Setup Page Component
export function SetupPage() {
  const currentStep = useSetupStore(selectCurrentStep);
  const nextStep = useSetupStore((s) => s.nextStep);
  const prevStep = useSetupStore((s) => s.prevStep);
  const setStep = useSetupStore((s) => s.setStep);
  const saveApiKeys = useSetupStore((s) => s.saveApiKeys);
  const apiKeyInputs = useSetupStore(selectApiKeyInputs);
  const savingApiKeys = useSetupStore(selectSavingApiKeys);

  // Theme
  const getEffectiveTheme = useThemeStore((s) => s.getEffectiveTheme);
  const themeMode = useThemeStore((s) => s.mode);

  useEffect(() => {
    const effectiveTheme = getEffectiveTheme();
    const root = document.documentElement;
    if (effectiveTheme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
  }, [getEffectiveTheme, themeMode]);

  const currentStepIndex = steps.findIndex((s) => s.id === currentStep);
  const isFirstStep = currentStepIndex === 0;
  const isLastStep = currentStepIndex === steps.length - 1;

  // Check if there are any non-empty API keys to save
  const hasApiKeysToSave = Object.values(apiKeyInputs).some(v => v && v.trim());

  const handleNext = async () => {
    // Auto-save API keys when leaving the apiKeys step
    if (currentStep === 'apiKeys' && hasApiKeysToSave) {
      await saveApiKeys();
    }
    nextStep();
  };

  const handleFinish = () => {
    // Navigate to main app and auto-open quickstart wizard
    window.location.href = '/?wizard=open';
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
              MassGen Setup
            </h1>
          </div>
          <a
            href="/"
            className="text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 flex items-center gap-1 text-sm"
          >
            Skip to App <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      </header>

      {/* Progress Steps */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 px-6 py-4">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center justify-between">
            {steps.map((step, index) => {
              const StepIcon = step.icon;
              const isActive = step.id === currentStep;
              const isCompleted = index < currentStepIndex;

              return (
                <button
                  key={step.id}
                  onClick={() => setStep(step.id)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                    isActive
                      ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300'
                      : isCompleted
                      ? 'text-green-600 dark:text-green-400'
                      : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
                  }`}
                >
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center ${
                      isActive
                        ? 'bg-blue-600 text-white'
                        : isCompleted
                        ? 'bg-green-600 text-white'
                        : 'bg-gray-200 dark:bg-gray-700'
                    }`}
                  >
                    {isCompleted ? <Check className="w-4 h-4" /> : <StepIcon className="w-4 h-4" />}
                  </div>
                  <span className="font-medium">{step.title}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Main Content - pb-24 accounts for fixed footer */}
      <main className="px-6 py-8 pb-24">
        <div className="max-w-4xl mx-auto">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentStep}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
            >
              {currentStep === 'apiKeys' && <ApiKeysSection />}
              {currentStep === 'docker' && <DockerSection />}
              {currentStep === 'skills' && <SkillsSection />}
            </motion.div>
          </AnimatePresence>
        </div>
      </main>

      {/* Footer Navigation */}
      <footer className="fixed bottom-0 left-0 right-0 bg-white dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <button
            onClick={prevStep}
            disabled={isFirstStep}
            className="px-6 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <ChevronLeft className="w-4 h-4" /> Back
          </button>

          <div className="text-sm text-gray-500">
            Step {currentStepIndex + 1} of {steps.length}
          </div>

          {isLastStep ? (
            <button
              onClick={handleFinish}
              className="px-6 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg flex items-center gap-2"
            >
              Finish Setup <Check className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={handleNext}
              disabled={savingApiKeys}
              className="px-6 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-400 text-white rounded-lg flex items-center gap-2"
            >
              {savingApiKeys ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Saving...
                </>
              ) : (
                <>
                  Next <ChevronRight className="w-4 h-4" />
                </>
              )}
            </button>
          )}
        </div>
      </footer>
    </div>
  );
}

export default SetupPage;
