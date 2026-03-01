Configuration
=============

MassGen is configured using environment variables for API keys and YAML files for agent definitions and orchestrator settings. This guide shows you how to set up your configuration.

.. tip::

   MassGen offers multiple usage modes: **CLI** with YAML configuration, **Python API** (``massgen.run()``), and **LiteLLM integration** for OpenAI-compatible interfaces. This guide focuses on CLI configuration. For Python integration, see :doc:`../user_guide/integration/python_api`.

Configuration Methods
=====================

MassGen offers three ways to configure your agents:

1. **Interactive Setup Wizard** (Recommended for beginners)
2. **YAML Configuration Files** (For advanced customization)
3. **CLI Flags** (For quick one-off queries)

Interactive Setup Wizard
-------------------------

The easiest way to configure MassGen is through the interactive wizard:

.. code-block:: bash

   # First run automatically triggers the wizard
   uv run massgen

   # Or manually launch it
   uv run massgen --init

**The Config Builder Interface:**

.. code-block:: text

   ╭──────────────────────────────────────────────────────────────────────────────╮
   │                                                                              │
   │       ███╗   ███╗ █████╗ ███████╗███████╗ ██████╗ ███████╗███╗   ██╗         │
   │       ████╗ ████║██╔══██╗██╔════╝██╔════╝██╔════╝ ██╔════╝████╗  ██║         │
   │       ██╔████╔██║███████║███████╗███████╗██║  ███╗█████╗  ██╔██╗ ██║         │
   │       ██║╚██╔╝██║██╔══██║╚════██║╚════██║██║   ██║██╔══╝  ██║╚██╗██║         │
   │       ██║ ╚═╝ ██║██║  ██║███████║███████║╚██████╔╝███████╗██║ ╚████║         │
   │       ╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝         │
   │                                                                              │
   │            🤖 🤖 🤖  →  💬 collaborate  →  🎯 winner  →  📢 final            │
   │                                                                              │
   │  Interactive Configuration Builder                                           │
   │  Create custom multi-agent configurations in minutes!                        │
   ╰──────────────────────────────────────────────────────────────────────────────╯

The wizard guides you through 4 simple steps:

1. **Select Your Use Case**: Choose from pre-built templates (Research, Coding, Q&A, etc.)
2. **Configure Agents**: Select providers and models (wizard detects available API keys)
3. **Configure Tools**: Enable web search, code execution, file operations, etc.
4. **Review & Save**: Save to ``~/.config/massgen/config.yaml`` (Windows: ``%USERPROFILE%\.config\massgen\config.yaml``)

After completing the wizard, your configuration is ready to use:

.. code-block:: bash

   uv run massgen "Your question"  # Uses default config automatically

Configuration Directory Structure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

MassGen uses two directories for configuration:

**User Configuration** (``~/.config/massgen/``):

.. code-block:: text

   ~/.config/massgen/                        # Windows: %USERPROFILE%\.config\massgen\
   ├── config.yaml              # Default configuration (from wizard)
   ├── agents/                  # Your custom named configurations
   │   ├── research-team.yaml
   │   └── coding-agents.yaml
   └── .env                     # API keys (optional)

**Project Workspace** (``.massgen/`` in your project):

MassGen also creates a ``.massgen/`` directory in your project for sessions, workspaces, and snapshots. See :doc:`../user_guide/concepts` for details.

**Creating Named Configurations:**

.. code-block:: bash

   # Run the wizard in named config mode
   uv run massgen --init

   # Choose to save to ~/.config/massgen/agents/ (Windows: %USERPROFILE%\.config\massgen\agents\)
   # Then use it:
   uv run massgen --config research-team "Your question"

Quickstart Output Filenames
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Quickstart supports explicit config filenames without manually editing paths:

.. code-block:: bash

   # Uses quickstart defaults and saves to .massgen/team-config.yaml
   uv run massgen --quickstart --config team-config

   # Extension is optional; .yaml is added when omitted
   uv run massgen --quickstart --config team-config.yaml

In the TUI/Web quickstart wizard, use the "Save Location" step to:

* choose project (``.massgen/``) or global (``~/.config/massgen/``) save location
* enter a custom filename

Environment Variables
---------------------

API keys are configured through environment variables or a ``.env`` file. After pip install, the setup wizard can create ``~/.config/massgen/.env`` (Windows: ``%USERPROFILE%\.config\massgen\.env``) for you.

OpenRouter (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~

**Use one API key to access all models** - OpenRouter provides a unified API for OpenAI, Anthropic, Google, xAI, and 200+ other models:

.. code-block:: bash

   # Single key for all models
   export OPENROUTER_API_KEY=sk-or-v1-...

Then use OpenRouter models in your multi-agent configurations

Get your key: `OpenRouter <https://openrouter.ai/keys>`_

Individual Provider Keys
~~~~~~~~~~~~~~~~~~~~~~~~

Alternatively, use provider-specific keys:

.. code-block:: bash

   # OpenAI (for GPT-5, GPT-4, etc.)
   OPENAI_API_KEY=sk-...

   # Anthropic Claude (for claude backend)
   ANTHROPIC_API_KEY=sk-ant-...

   # Claude Code (optional - for claude_code backend only)
   # If set, claude_code uses this instead of ANTHROPIC_API_KEY
   # CLAUDE_CODE_API_KEY=sk-ant-...

   # Google Gemini
   GOOGLE_API_KEY=...

   # xAI Grok
   XAI_API_KEY=...

.. note::

   **Separate API keys for Claude Code:** The ``claude_code`` backend checks
   ``CLAUDE_CODE_API_KEY`` first, then falls back to ``ANTHROPIC_API_KEY``.
   This allows you to use a Claude subscription (no API key) or a separate
   API key for Claude Code agents while using a different API key for standard
   Claude backend agents.

**Getting API Keys:**

* `OpenRouter <https://openrouter.ai/keys>`_ (recommended - single key for all models)
* `OpenAI <https://platform.openai.com/api-keys>`_
* `Anthropic Claude <https://docs.anthropic.com/en/api/overview>`_
* `Google Gemini <https://ai.google.dev/gemini-api/docs>`_
* `xAI Grok <https://docs.x.ai/docs/overview>`_

YAML Configuration Files
-------------------------

MassGen uses YAML files to define agents, their backends, and orchestrator settings. Configuration files are stored in ``@examples/`` and can be referenced using the ``--config`` flag.

Basic Configuration Structure
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A minimal MassGen configuration has these top-level keys:

.. code-block:: yaml

   agents:              # List of agents (required)
     - id: "agent_id"   # Agent definitions
       backend: ...     # Backend configuration
       system_message: ...  # Optional system prompt

   orchestrator:        # Orchestrator settings (optional, required for file ops)
     snapshot_storage: "snapshots"
     agent_temporary_workspace: "temp_workspaces"
     context_paths: ...

   ui:                  # UI settings (optional)
     display_type: "rich_terminal"
     logging_enabled: true

Single Agent Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~

For a single agent, use the ``agents`` field (plural) with one entry:

.. code-block:: yaml

   # @examples/basic/single/single_gpt5nano
   agents:                # Note: plural 'agents' even for single agent
     - id: "gpt-5-nano"
       backend:
         type: "openai"
         model: "gpt-5-nano"
         enable_web_search: true
         enable_code_interpreter: true

   ui:
     display_type: "rich_terminal"
     logging_enabled: true

.. warning::

   **Common Mistake**: When converting a single-agent config to multi-agent, remember to keep ``agents:`` (plural).

   While ``agent:`` (singular) is supported for single-agent configs, always use ``agents:`` (plural) for consistency - this prevents errors when adding more agents later.

**Run this configuration:**

.. code-block:: bash

   uv run massgen \
     --config @examples/basic/single/single_gpt5nano \
     "What is machine learning?"

Multi-Agent Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~

For multiple agents, add more entries to the ``agents`` list:

.. code-block:: yaml

   # @examples/basic/multi/three_agents_default
   agents:
     - id: "gemini2.5flash"
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
         enable_web_search: true

     - id: "gpt5nano"
       backend:
         type: "openai"
         model: "gpt-5-nano"
         enable_web_search: true
         enable_code_interpreter: true

     - id: "grok3mini"
       backend:
         type: "grok"
         model: "grok-3-mini"
         enable_web_search: true

   ui:
     display_type: "rich_terminal"
     logging_enabled: true

**Run this configuration:**

.. code-block:: bash

   uv run massgen \
     --config @examples/basic/multi/three_agents_default \
     "Analyze the pros and cons of renewable energy"

Backend Configuration
---------------------

Each agent requires a ``backend`` configuration that specifies the model provider and settings.

.. important::
   **Choosing the right backend?** Different backends support different features (web search, code execution, file operations, etc.). Check the **Backend Capabilities Matrix** in :doc:`../user_guide/backends` to see which features are available for each backend type.

Supported Providers
~~~~~~~~~~~~~~~~~~~

MassGen supports many LLM providers. Use the **slash format** (``provider/model``) for the Python API and LiteLLM:

.. list-table:: Provider Reference
   :header-rows: 1
   :widths: 15 20 30 20

   * - Provider
     - Backend Type
     - Example Models
     - Slash Format Example
   * - OpenAI
     - ``openai``
     - ``gpt-5``, ``gpt-5-nano``, ``gpt-5.1``
     - ``openai/gpt-5``
   * - Anthropic
     - ``claude``
     - ``claude-sonnet-4-5-20250929``, ``claude-opus-4-5-20251101``
     - ``claude/claude-sonnet-4-5-20250929``
   * - Google
     - ``gemini``
     - ``gemini-2.5-flash``, ``gemini-2.5-pro``, ``gemini-3-pro-preview``
     - ``gemini/gemini-2.5-flash``
   * - xAI
     - ``grok``
     - ``grok-4``, ``grok-4-1-fast-reasoning``, ``grok-3-mini``
     - ``grok/grok-4``
   * - Groq
     - ``groq``
     - ``llama-3.3-70b-versatile``, ``mixtral-8x7b-32768``
     - ``groq/llama-3.3-70b-versatile``
   * - Cerebras
     - ``cerebras``
     - ``llama-3.3-70b``, ``llama-3.1-8b``
     - ``cerebras/llama-3.3-70b``
   * - Together
     - ``together``
     - ``meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo``
     - ``together/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo``
   * - Fireworks
     - ``fireworks``
     - ``accounts/fireworks/models/llama-v3p3-70b-instruct``
     - ``fireworks/accounts/fireworks/models/llama-v3p3-70b-instruct``
   * - OpenRouter
     - ``openrouter``
     - 200+ models (e.g., ``x-ai/grok-4.1-mini``)
     - ``openrouter/x-ai/grok-4.1-mini``
   * - Qwen
     - ``qwen``
     - ``qwen-max``, ``qwen-plus``, ``qwen-turbo``
     - ``qwen/qwen-max``
   * - Moonshot
     - ``moonshot``
     - ``moonshot-v1-128k``, ``moonshot-v1-32k``
     - ``moonshot/moonshot-v1-128k``
   * - Nebius
     - ``nebius``
     - ``Qwen/Qwen3-4B-fast``
     - ``nebius/Qwen/Qwen3-4B-fast``
   * - Claude Code
     - ``claude_code``
     - ``claude-sonnet-4-5-20250929``
     - (YAML only)
   * - Azure OpenAI
     - ``azure_openai``
     - ``gpt-4o`` (deployment name)
     - (YAML only)

.. tip::
   **Nested slashes are supported!** For providers like OpenRouter, Together, and Fireworks where model names contain slashes, the format still works:

   - ``openrouter/x-ai/grok-4.1-mini`` → provider=openrouter, model=x-ai/grok-4.1-mini
   - ``together/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo`` → provider=together, model=meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo

**Using slash format in Python:**

.. code-block:: python

   import massgen

   # Build config with slash format
   config = massgen.build_config(models=[
       "openai/gpt-5",
       "groq/llama-3.3-70b-versatile",
       "openrouter/x-ai/grok-4.1-mini"
   ])

   # Or with LiteLLM (using OpenRouter)
   from dotenv import load_dotenv
   load_dotenv()  # Load OPENROUTER_API_KEY from .env

   import litellm
   from massgen import register_with_litellm

   register_with_litellm()
   response = litellm.completion(
       model="massgen/build",
       messages=[{"role": "user", "content": "Your question"}],
       optional_params={"models": ["openrouter/openai/gpt-5", "openrouter/anthropic/claude-sonnet-4.5"]}
   )
   print(response.choices[0].message.content)

Backend Types (YAML)
~~~~~~~~~~~~~~~~~~~~

For YAML configuration files, use the ``type`` field:

* ``openai`` - OpenAI models (GPT-5, GPT-4, etc.)
* ``claude`` - Anthropic Claude models
* ``claude_code`` - Claude Code SDK with dev tools
* ``gemini`` - Google Gemini models
* ``grok`` - xAI Grok models
* ``groq`` - Groq inference (ultra-fast)
* ``cerebras`` - Cerebras AI
* ``together`` - Together AI
* ``fireworks`` - Fireworks AI
* ``openrouter`` - OpenRouter (200+ models)
* ``qwen`` - Alibaba Qwen models
* ``moonshot`` - Kimi/Moonshot AI
* ``nebius`` - Nebius AI Studio
* ``azure_openai`` - Azure OpenAI deployment
* ``zai`` - ZhipuAI GLM models
* ``ag2`` - AG2 framework integration
* ``lmstudio`` - Local models via LM Studio
* ``chatcompletion`` - Generic OpenAI-compatible API

Basic Backend Structure
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   backend:
     type: "openai"           # Backend type (required)
     model: "gpt-5-nano"      # Model name (required)
     api_key: "..."           # Optional - uses env var by default
     temperature: 0.7         # Optional - model parameters
     max_tokens: 4096         # Optional - response length

Backend-Specific Features
~~~~~~~~~~~~~~~~~~~~~~~~~

Different backends support different built-in tools:

.. code-block:: yaml

   # OpenAI with tools
   backend:
     type: "openai"
     model: "gpt-5-nano"
     enable_web_search: true
     enable_code_interpreter: true

   # Gemini with tools
   backend:
     type: "gemini"
     model: "gemini-2.5-flash"
     enable_web_search: true
     enable_code_execution: true

   # Claude Code with workspace
   backend:
     type: "claude_code"
     model: "claude-sonnet-4"
     cwd: "workspace"          # Working directory for file operations

.. note::
   Always use ``cwd: "workspace"`` rather than numbered names like ``workspace1``. MassGen automatically adds a unique suffix per agent at runtime to prevent identity leakage during voting.

See :doc:`../reference/yaml_schema` for complete backend options.

System Messages
---------------

Customize agent behavior with system messages:

.. code-block:: yaml

   agents:
     - id: "research_agent"
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
       system_message: |
         You are a research specialist. When answering questions:
         1. Always search for current information
         2. Cite your sources
         3. Provide comprehensive analysis

     - id: "code_agent"
       backend:
         type: "openai"
         model: "gpt-5-nano"
       system_message: |
         You are a coding expert. When solving problems:
         1. Write clean, well-documented code
         2. Use code execution to test solutions
         3. Explain your approach clearly

Orchestrator Configuration
--------------------------

Control workspace sharing and project integration:

.. code-block:: yaml

   orchestrator:
     snapshot_storage: "snapshots"              # Workspace snapshots for sharing
     agent_temporary_workspace: "temp_workspaces"  # Temporary workspaces
     context_paths:                             # Project integration
       - path: "/absolute/path/to/project"
         permission: "read"                     # read or write

Decomposition Mode Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use decomposition mode when agents own subtasks and one presenter synthesizes:

.. code-block:: yaml

   agents:
     - id: "frontend"
       subtask: "Implement UI and client behavior"
       backend:
         type: "openai"
         model: "gpt-5-nano"

     - id: "backend"
       subtask: "Implement API and persistence"
       backend:
         type: "openai"
         model: "gpt-5-nano"

     - id: "integrator"
       subtask: "Integrate and present final output"
       backend:
         type: "openai"
         model: "gpt-5-nano"

   orchestrator:
     coordination_mode: "decomposition"
     presenter_agent: "integrator"
     # Recommended decomposition defaults:
     max_new_answers_per_agent: 2  # Recommended range: 2-3
     max_new_answers_global: 9     # Team-wide cumulative cap across all agents
     answer_novelty_requirement: "balanced"

Sensible defaults guidance:

* By default, use ``max_new_answers_per_agent: 2-3`` in decomposition mode.
* Usually this is lower than fully parallel voting mode settings.
* Add ``max_new_answers_global`` for deterministic total coordination budget.
* Keep other answer-control parameters at defaults unless you need stricter behavior.
* Keep fairness defaults enabled (``fairness_enabled: true``, ``fairness_lead_cap_answers: 2``, ``max_midstream_injections_per_round: 2``) to prevent fast agents from repeatedly lapping slower peers and causing restart churn.

Quickstart note:

* The Quickstart flows (``uv run massgen --quickstart`` and the Web/TUI quickstart wizard) expose decomposition mode, presenter selection, and these defaults directly.
* For GPT-5x models, Quickstart also exposes ``reasoning.effort`` selection.
  OpenAI GPT-5 models support ``low|medium|high`` and Codex GPT-5 models include ``xhigh``.

Example:

.. code-block:: yaml

   agents:
     - id: "agent_a"
       backend:
         type: "codex"
         model: "gpt-5.3-codex"
         reasoning:
           effort: "xhigh"
           summary: "auto"

Advanced Configuration
----------------------

MCP Integration
~~~~~~~~~~~~~~~

Add MCP (Model Context Protocol) servers for external tools:

.. code-block:: yaml

   agents:
     - id: "agent_with_mcp"
       backend:
         type: "openai"
         model: "gpt-5-nano"
         mcp_servers:
           - name: "weather"
             type: "stdio"
             command: "npx"
             args: ["-y", "@fak111/weather-mcp"]

See :doc:`../user_guide/tools/mcp_integration` for details.

File Operations
~~~~~~~~~~~~~~~

Enable file system access for agents:

.. code-block:: yaml

   agents:
     - id: "file_agent"
       backend:
         type: "claude_code"
         model: "claude-sonnet-4"
         cwd: "workspace"       # Agent's working directory

   orchestrator:
     snapshot_storage: "snapshots"
     agent_temporary_workspace: "temp_workspaces"

See :doc:`../user_guide/files/file_operations` for details.

Project Integration
~~~~~~~~~~~~~~~~~~~

Share directories with agents (read or write access):

.. code-block:: yaml

   agents:
     - id: "project_agent"
       backend:
         type: "claude_code"
         cwd: "workspace"

   orchestrator:
     context_paths:
       - path: "/absolute/path/to/project/src"
         permission: "read"      # Agents can analyze code
       - path: "/absolute/path/to/project/docs"
         permission: "write"     # Agents can update docs

See :doc:`../user_guide/files/project_integration` for details.

Protected Paths
~~~~~~~~~~~~~~~

Make specific files read-only within writable context paths:

.. code-block:: yaml

   orchestrator:
     context_paths:
       - path: "/project"
         permission: "write"
         protected_paths:
           - "config.json"        # Read-only
           - "template.html"      # Read-only
           # Other files remain writable

**Use Case**: Allow agents to modify most files while protecting critical configurations or templates.

See :doc:`../user_guide/files/protected_paths` for complete documentation.

Planning Mode
~~~~~~~~~~~~~

Prevent irreversible actions during multi-agent coordination:

.. code-block:: yaml

   orchestrator:
     coordination:
       enable_planning_mode: true
       planning_mode_instruction: |
         PLANNING MODE: Describe your intended actions without executing.
         Save execution for the final presentation phase.

**Use Case**: File operations, API calls, or any task with irreversible consequences.

See :doc:`../user_guide/advanced/planning_mode` for complete documentation.

Subagents
~~~~~~~~~

Enable agents to spawn parallel child processes for independent tasks:

.. code-block:: yaml

   orchestrator:
     coordination:
       enable_subagents: true
       subagent_default_timeout: 300  # 5 minutes per subagent
       subagent_max_concurrent: 3     # Max parallel subagents

**Example usage:**

.. code-block:: bash

   uv run massgen \
     --config @massgen/configs/features/subagent_demo.yaml \
     "Build a website with frontend, backend, and documentation"

The agent can spawn subagents to work on each component simultaneously. Subagents:

* Run in isolated workspaces
* Inherit parent agent configurations by default
* Execute concurrently for parallel task completion
* Return structured results with workspace paths

**Use Case**: Complex tasks with independent, parallelizable components (e.g., multi-part research, website building, documentation generation).

See :doc:`../user_guide/advanced/subagents` for complete documentation.

Timeout Configuration
~~~~~~~~~~~~~~~~~~~~~

Control maximum coordination time:

.. code-block:: yaml

   timeout_settings:
     orchestrator_timeout_seconds: 1800  # 30 minutes (default)

**CLI Override**:

.. code-block:: bash

   uv run massgen --orchestrator-timeout 600 --config config.yaml

See :doc:`../reference/timeouts` for complete timeout documentation.

For the complete list of CLI parameters, see :doc:`../reference/cli`

Configuration Best Practices
-----------------------------

1. **Start Simple**: Use single agent configs for testing, then scale to multi-agent
2. **Use Environment Variables**: Never commit API keys to version control
3. **Organize Configs**: Group related configurations in directories
4. **Comment Your YAML**: Add comments to explain agent roles and settings
5. **Test Incrementally**: Verify each agent works before combining them
6. **Version Your Configs**: Track configuration changes in version control

Example Configuration Templates
-------------------------------

All configuration examples are in ``@examples/``:

* ``@examples/basic/single/single_gpt5nano`` - Single agent configuration
* ``@examples/basic/multi/three_agents_default`` - Multi-agent collaboration
* ``@examples/basic/multi/decomposition_quickstart`` - Decomposition mode with recommended defaults
* ``@examples/basic/multi/decomposition_example`` - Decomposition mode with richer role setup
* ``@examples/tools/mcp/*`` - MCP integration examples
* ``@examples/tools/filesystem/*`` - File operation examples
* ``@examples/ag2/*`` - AG2 framework integration

See the `Configuration Guide <https://github.com/Leezekun/MassGen/blob/main/@examples/README.md>`_ for the complete catalog.

Next Steps
----------

**Excellent! You understand configuration basics. Here's your path forward:**

✅ **You are here:** You know how to configure agents in YAML

⬜ **Put it to use:** :doc:`../examples/basic_examples` - Copy ready-made configurations

⬜ **Go deeper:** :doc:`../user_guide/concepts` - Understand how multi-agent coordination works

⬜ **Add capabilities:** :doc:`../user_guide/tools/mcp_integration` - Integrate external tools

**Need a reference?** The complete configuration schema is at :doc:`../reference/yaml_schema`

Troubleshooting
---------------

**Configuration not found:**

Ensure the path is correct relative to the MassGen directory:

.. code-block:: bash

   # Correct - relative to MassGen root
   uv run massgen --config @examples/basic/multi/three_agents_default

   # Incorrect - missing massgen/ prefix
   uv run massgen --config configs/basic/multi/three_agents_default.yaml

**API key not found:**

Check that your ``.env`` file exists and contains the correct key:

.. code-block:: bash

   # Verify .env file exists
   ls -la .env

   # Check for the required key
   grep "OPENAI_API_KEY" .env

**YAML syntax error:**

Validate your YAML syntax:

.. code-block:: bash

   python -c "import yaml; yaml.safe_load(open('your-config.yaml'))"
