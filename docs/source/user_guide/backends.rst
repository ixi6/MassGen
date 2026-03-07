Backend Configuration
=====================

Backends connect MassGen agents to AI model providers. Each backend is configured in YAML and provides specific capabilities like web search, code execution, and file operations.

Overview
--------

Each agent in MassGen requires a backend configuration that specifies:

* **Provider**: Which AI service to use (OpenAI, Claude, Gemini, etc.)
* **Model**: Which specific model within that provider
* **Capabilities**: Which built-in tools are enabled
* **Parameters**: Model settings like temperature, max_tokens, etc.

Available Backends
------------------

Backend Types
~~~~~~~~~~~~~

MassGen supports these backend types (configured via ``type`` field in YAML):

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Backend Type
     - Provider
     - Models
   * - ``openai``
     - OpenAI
     - GPT-5, GPT-5-mini, GPT-5-nano, GPT-4, GPT-4o
   * - ``claude``
     - Anthropic
     - Claude Haiku 3.5, Claude Sonnet 4, Claude Opus 4
   * - ``claude_code``
     - Anthropic (SDK)
     - Claude Sonnet 4, Claude Opus 4 (with dev tools)
   * - ``codex``
     - OpenAI (CLI)
     - GPT-5.4, GPT-5.3-Codex, GPT-5.2-Codex, GPT-5.1-Codex
   * - ``gemini``
     - Google
     - Gemini 2.5 Flash, Gemini 2.5 Pro
   * - ``gemini_cli``
     - Google (CLI)
     - Gemini 3, Gemini 2.5 Models (via Gemini CLI)
   * - ``grok``
     - xAI
     - Grok-4, Grok-3, Grok-3-mini
   * - ``azure_openai``
     - Microsoft Azure
     - GPT-4, GPT-4o, GPT-5 (Azure deployments)
   * - ``zai``
     - ZhipuAI
     - GLM-4.5
   * - ``ag2``
     - AG2 Framework
     - Any AG2-compatible agent
   * - ``lmstudio``
     - LM Studio
     - Local open-source models
   * - ``copilot``
     - GitHub Copilot
     - GPT-5-mini, GPT-4, Claude Sonnet 4, Gemini 2.5 Pro
   * - ``chatcompletion``
     - Generic
     - Any OpenAI-compatible API

Backend Capabilities
~~~~~~~~~~~~~~~~~~~~

Different backends support different built-in tools:

.. list-table:: Backend Tool Support
   :header-rows: 1
   :widths: 15 10 10 10 10 12 12 12 10 10

   * - Backend
     - Web Search
     - Code Execution
     - Bash/Shell
     - Image
     - Audio
     - Video
     - MCP Support
     - Filesystem
     - Custom Tools
   * - ``openai``
     - ⭐
     - ⭐
     - ✅
     - ⭐ Both
     - ⭐ Both
     - ⭐ Generation
     - ✅
     - ✅
     - ✅
   * - ``claude``
     - ⭐
     - ⭐
     - ✅
     - 🔧
     - 🔧
     - 🔧
     - ✅
     - ✅
     - ✅
   * - ``claude_code``
     - ⭐
     - ❌
     - ⭐
     - 🔧
     - 🔧
     - 🔧
     - ✅
     - ⭐
     - ✅
   * - ``codex``
     - ⭐
     - ❌
     - ⭐
     - ⭐
     - ❌
     - ❌
     - ✅
     - ⭐
     - ✅
   * - ``copilot``
     - ⭐
     - ❌
     - ❌
     - 🔧
     - 🔧
     - 🔧
     - ✅
     - ❌
     - ❌
   * - ``gemini``
     - ⭐
     - ⭐
     - ✅
     - 🔧
     - 🔧
     - 🔧
     - ✅
     - ✅
     - ✅
   * - ``gemini_cli``
     - ⭐
     - ⭐
     - ⭐
     - 🔧
     - 🔧
     - 🔧
     - ✅
     - ⭐
     - ✅
   * - ``grok``
     - ⭐
     - ❌
     - ✅
     - 🔧
     - 🔧
     - 🔧
     - ✅
     - ✅
     - ✅
   * - ``azure_openai``
     - ⭐
     - ⭐
     - ✅
     - ⭐ Both
     - ❌
     - ❌
     - ✅
     - ✅
     - ❌
   * - ``chatcompletion``
     - ❌
     - ❌
     - ✅
     - 🔧
     - 🔧
     - 🔧
     - ✅
     - ✅
     - ✅
   * - ``lmstudio``
     - ❌
     - ❌
     - ✅
     - 🔧
     - 🔧
     - 🔧
     - ✅
     - ✅
     - ✅
   * - ``inference``
     - ❌
     - ❌
     - ✅
     - 🔧
     - 🔧
     - 🔧
     - ✅
     - ✅
     - ✅
   * - ``ag2``
     - ❌
     - ⭐
     - ❌
     - ❌
     - ❌
     - ❌
     - ❌
     - ❌
     - ❌

**Notes:**

* **Symbol Legend:**

  * ⭐ **Built-in** - Native backend feature (e.g., Anthropic's web search, OpenAI's native image API, Claude Code's Bash tool)
  * 🔧 **Via Custom Tools** - Available through custom tools (requires ``OPENAI_API_KEY`` for multimodal understanding)
  * ✅ **MCP-based or Available** - Feature available via MCP integration or standard capability
  * ❌ **Not available** - Feature not supported

* **Custom Tools:**

  * Custom tools allow you to give agents access to your own Python functions
  * Most backends support custom tools (OpenAI, Claude, Claude Code, Codex, Gemini, Grok, Chat Completions, LM Studio, Inference)
  * **Azure OpenAI** and **AG2** do not support custom tools as they inherit from the base backend class without the custom tools layer
  * Custom tools are essential for multimodal understanding features (``understand_image``, ``understand_video``, ``understand_audio``, ``understand_file``)
  * See :doc:`tools/custom_tools` for complete documentation on creating and using custom tools

* **Code Execution vs Bash/Shell:**

  .. warning::
     **Common Confusion**: ``enable_code_execution`` and ``enable_code_interpreter`` run code in the **provider's sandbox** (cloud environment) with **NO access to your local filesystem**. If you need agents to read/write files in your project, use MCP-based bash instead.

  * **Code Execution (⭐)**: Backend provider's native code execution tool (runs in provider sandbox - **no access to MassGen workspaces**)

    * ``openai``: OpenAI code interpreter for calculations and data analysis
    * ``claude``: Anthropic's code execution tool
    * ``gemini``: Google's code execution tool
    * ``azure_openai``: Azure OpenAI code interpreter
    * ``ag2``: AG2 framework code executors (Local, Docker, Jupyter, Cloud)
    * **When to use**: Quick calculations, data analysis, isolated code snippets that don't need filesystem access

  * **Bash/Shell**: MassGen-level feature with **direct workspace access**

    * ⭐ (``claude_code``, ``codex``): Native shell tools built into Claude Code and Codex
    * ✅ (all MCP-enabled backends): Universal bash/shell via ``enable_mcp_command_line: true``
    * **When to use**: Code that needs to interact with your project files, run tests, execute scripts
    * See :doc:`tools/code_execution` for detailed setup and comparison

  * **Recommendation**: Choose one approach based on your needs. Use **built-in code execution** for isolated computational tasks, and **MCP bash/shell** for operations that need to affect your workspace files.

* **Filesystem:**

  * ⭐ (``claude_code``, ``codex``): Native filesystem tools provided by the backend
  * ``claude_code``: Read, Write, Edit, Bash, Grep, Glob
  * ``codex``: shell, file_read, file_write, file_edit
  * ✅ (all backends with ``cwd`` parameter): Filesystem operations handled automatically through workspace configuration
  * See :doc:`files/file_operations` for detailed filesystem configuration

* **Multimodal Capabilities:**

  * **⭐ Native Multimodal Support**: The backend/model API directly handles multimodal content

    * **⭐ Both** (e.g., ``openai``, ``azure_openai``): Native API supports BOTH understanding (analyze) AND generation (create)
    * **⭐ Generation** (e.g., ``openai`` video): Can create videos via Sora-2 API but not analyze them

  * **🔧 Via Custom Tools**: Multimodal understanding through custom tools (``understand_image``, ``understand_video``, ``understand_audio``)

    * Works with any backend that supports custom tools
    * Requires ``OPENAI_API_KEY`` in ``.env`` file (tools use OpenAI's API for processing)
    * Examples: ``claude``, ``claude_code``, ``gemini``, ``grok``, ``chatcompletion``, ``lmstudio``, ``inference``
    * Does NOT work with ``azure_openai`` or ``ag2`` (these backends don't support custom tools)
    * See :doc:`advanced/multimodal` for complete setup instructions

  * **Understanding vs Generation**:

    * **Understanding**: Analyze existing content (images, audio, video)
    * **Generation**: Create new content from text prompts
    * **Both**: Supports both understanding AND generation

See :doc:`../reference/supported_models` for the complete backend capabilities reference.

Configuring Backends
--------------------

Basic Backend Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every agent needs a ``backend`` section in the YAML configuration:

.. code-block:: yaml

   agents:
     - id: "my_agent"
       backend:
         type: "openai"          # Backend type (required)
         model: "gpt-5-nano"     # Model name (required)

Backend-Specific Examples
-------------------------

OpenAI Backend
~~~~~~~~~~~~~~

**Basic Configuration:**

.. code-block:: yaml

   agents:
     - id: "gpt_agent"
       backend:
         type: "openai"
         model: "gpt-5-nano"
         enable_web_search: true
         enable_code_interpreter: true

**With Reasoning Parameters:**

.. code-block:: yaml

   agents:
     - id: "reasoning_agent"
       backend:
         type: "openai"
         model: "gpt-5-nano"
         text:
           verbosity: "medium"      # low, medium, high
         reasoning:
           effort: "high"            # low, medium, high
           summary: "auto"           # auto, concise, detailed

**Supported Models:** GPT-5, GPT-5-mini, GPT-5-nano, GPT-4, GPT-4o, GPT-4-turbo, GPT-3.5-turbo

Claude Backend
~~~~~~~~~~~~~~

**Basic Configuration:**

.. code-block:: yaml

   agents:
     - id: "claude_agent"
       backend:
         type: "claude"
         model: "claude-sonnet-4"
         enable_web_search: true
         enable_code_interpreter: true

**With MCP Integration:**

.. code-block:: yaml

   agents:
     - id: "claude_mcp"
       backend:
         type: "claude"
         model: "claude-sonnet-4"
         mcp_servers:
           - name: "weather"
             type: "stdio"
             command: "npx"
             args: ["-y", "@modelcontextprotocol/server-weather"]

**Supported Models:** claude-haiku-4-5-20251001, claude-sonnet-4-5-20250929, claude-opus-4-1-20250805, claude-sonnet-4-20250514, claude-3-5-sonnet-latest, claude-3-5-haiku-latest

Claude Code Backend
~~~~~~~~~~~~~~~~~~~

**With Workspace Configuration:**

.. code-block:: yaml

   agents:
     - id: "code_agent"
       backend:
         type: "claude_code"
         model: "claude-sonnet-4"
         cwd: "workspace"           # Working directory for file operations

   orchestrator:
     snapshot_storage: "snapshots"
     agent_temporary_workspace: "temp_workspaces"

**Authentication:**

The Claude Code backend supports flexible authentication:

* **API key**: Set ``CLAUDE_CODE_API_KEY`` or ``ANTHROPIC_API_KEY`` environment variable
* **Subscription**: If no API key is set, uses Claude subscription authentication

This allows you to use Claude Code with a subscription while using a separate
API key for standard Claude backend agents.

**Special Features:**

* Native file operations (Read, Write, Edit, Bash, Grep, Glob)
* Workspace isolation
* Snapshot sharing between agents
* Full development tool suite

Codex Backend
~~~~~~~~~~~~~

**Basic Configuration:**

.. code-block:: yaml

   agents:
     - id: "codex_agent"
       backend:
         type: "codex"
         model: "gpt-5.4"
         cwd: "workspace"

**Authentication:**

The Codex backend supports flexible authentication:

* **API key**: Set ``OPENAI_API_KEY`` environment variable
* **ChatGPT subscription**: If no API key, uses OAuth via ``codex login``

**Supported Models:** gpt-5.4 (default), gpt-5.3-codex, gpt-5.2-codex, gpt-5.1-codex, gpt-5-codex, gpt-4.1

**Reasoning Effort Configuration:**

.. code-block:: yaml

   agents:
     - id: "codex_reasoning"
       backend:
         type: "codex"
         model: "gpt-5.4"
         model_reasoning_effort: "xhigh"  # low | medium | high | xhigh
         # reasoning:
         #   effort: "xhigh"            # OpenAI-style alias (also supported)

If both ``model_reasoning_effort`` and ``reasoning.effort`` are provided,
``model_reasoning_effort`` takes precedence.

**Special Features:**

* Native shell and file operations via Codex CLI
* Web search capability
* Session persistence and resumption
* MCP server support via workspace config

.. warning::

   **Sandbox Limitation**: Codex uses OS-level sandboxing (Seatbelt/Landlock) which
   **only restricts writes, NOT reads**. Codex can read any file on the filesystem.
   For security-sensitive workloads, use Docker mode or consider Claude Code instead.
   See :ref:`Native Tool Backends <native-tool-backends>` for details.

**Recommended: Docker Mode for Security:**

.. code-block:: yaml

   agents:
     - id: "secure_codex"
       backend:
         type: "codex"
         model: "gpt-5.4"
         cwd: "workspace"
         enable_mcp_command_line: true
         command_line_execution_mode: "docker"
         command_line_docker_network_mode: "bridge"  # Required for Codex

Gemini CLI Backend
~~~~~~~~~~~~~~~~~~

The ``gemini_cli`` backend (alias: ``gemini-cli``) wraps Google's Gemini CLI (``@google/gemini-cli``) for local or Docker execution.

**Basic Configuration (Local):**

.. code-block:: yaml

   agents:
     - id: "gemini_cli_agent"
       backend:
         type: "gemini_cli"
         model: "gemini-2.5-pro"
         cwd: "workspace"

**Authentication:**

* **CLI login**: Run ``gemini`` interactively to login with Google (preferred)
* **API key**: Set ``GOOGLE_API_KEY`` or ``GEMINI_API_KEY`` environment variable

**Installation:** ``npm install -g @google/gemini-cli``

**Docker Mode:** Requires ``command_line_docker_network_mode: "bridge"``. Add ``@google/gemini-cli`` to
``command_line_docker_packages.preinstall.npm`` or use an image with Gemini CLI pre-installed.

**Supported Models:** gemini-2.5-pro (default), gemini-2.5-flash, gemini-2.5-flash-lite, gemini-3-flash-preview, gemini-3-pro-preview, gemini-3.1-pro-preview

**Example configs:** ``massgen/configs/providers/gemini/gemini_cli_local.yaml``, ``gemini_cli_docker.yaml``

GitHub Copilot Backend
~~~~~~~~~~~~~~~~~~~~~~

**Prerequisites:**

1. An active `GitHub Copilot subscription <https://github.com/features/copilot/plans>`_
2. Install the Copilot CLI:

   .. code-block:: bash

      # macOS / Linux
      brew install copilot-cli

      # npm (all platforms)
      npm install -g @github/copilot

      # Windows
      winget install GitHub.Copilot

3. Authenticate — run ``copilot`` and use the ``/login`` slash command, or set a
   ``GH_TOKEN`` / ``GITHUB_TOKEN`` environment variable with a
   `fine-grained PAT <https://github.com/settings/personal-access-tokens/new>`_
   that has the **Copilot Requests** permission.

**Basic Configuration:**

.. code-block:: yaml

   agents:
     - id: "copilot-assistant"
       backend:
         type: "copilot"
         model: "gpt-5-mini"

**Supported Models:** gpt-5-mini (default), gpt-4, claude-sonnet-4, gemini-2.5-pro

**Special Features:**

* No API key required — authentication is handled through your GitHub subscription
* Web search capability
* MCP server support
* Session persistence and resumption

Gemini Backend
~~~~~~~~~~~~~~

**Basic Configuration:**

.. code-block:: yaml

   agents:
     - id: "gemini_agent"
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
         enable_web_search: true
         enable_code_execution: true

**With Safety Settings:**

.. code-block:: yaml

   agents:
     - id: "safe_gemini"
       backend:
         type: "gemini"
         model: "gemini-2.5-pro"
         safety_settings:
           HARM_CATEGORY_HARASSMENT: "BLOCK_MEDIUM_AND_ABOVE"
           HARM_CATEGORY_HATE_SPEECH: "BLOCK_MEDIUM_AND_ABOVE"

**Supported Models:** gemini-2.5-flash, gemini-2.5-pro, gemini-2.5-flash-thinking

Grok Backend
~~~~~~~~~~~~

**Basic Configuration:**

.. code-block:: yaml

   agents:
     - id: "grok_agent"
       backend:
         type: "grok"
         model: "grok-3-mini"
         enable_web_search: true

**Supported Models:** grok-4, grok-4-fast, grok-3, grok-3-mini

Azure OpenAI Backend
~~~~~~~~~~~~~~~~~~~~

**Configuration:**

.. code-block:: yaml

   agents:
     - id: "azure_agent"
       backend:
         type: "azure_openai"
         model: "gpt-4"
         deployment_name: "my-gpt4-deployment"
         api_version: "2024-02-15-preview"

**Required Environment Variables:**

.. code-block:: bash

   AZURE_OPENAI_API_KEY=...
   AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
   AZURE_OPENAI_API_VERSION=YOUR-AZURE-OPENAI-API-VERSION

AG2 Backend
~~~~~~~~~~~

**Configuration:**

.. code-block:: yaml

   agents:
     - id: "ag2_agent"
       backend:
         type: "ag2"
         agent_type: "ConversableAgent"
         llm_config:
           config_list:
             - model: "gpt-4"
               api_key: "${OPENAI_API_KEY}"
         code_execution_config:
           executor: "local"
           work_dir: "coding"

See :doc:`integration/general_interoperability` for detailed AG2 configuration.

LM Studio Backend
~~~~~~~~~~~~~~~~~

**For Local Models:**

.. code-block:: yaml

   agents:
     - id: "local_agent"
       backend:
         type: "lmstudio"
         model: "lmstudio-community/Meta-Llama-3.1-8B-Instruct-GGUF"
         port: 1234

**Features:**

* Automatic LM Studio CLI installation
* Auto-download and loading of models
* Zero-cost usage
* Full privacy (local inference)

OpenRouter Backend
~~~~~~~~~~~~~~~~~~

OpenRouter provides unified access to multiple AI providers through a single API.
Use the ``chatcompletion`` backend type with OpenRouter's base URL.

**Basic Configuration:**

.. code-block:: yaml

   agents:
     - id: "openrouter_agent"
       backend:
         type: "chatcompletion"
         model: "openai/gpt-5-mini"
         base_url: "https://openrouter.ai/api/v1"

**With Reasoning Tokens:**

OpenRouter normalizes reasoning tokens across providers. Configure reasoning for
models that support it (OpenAI o-series, GPT-5, Claude 3.7+, Gemini 2.5+, DeepSeek R1, Grok):

.. code-block:: yaml

   agents:
     - id: "reasoning_agent"
       backend:
         type: "chatcompletion"
         model: "openai/gpt-5-mini"
         base_url: "https://openrouter.ai/api/v1"
         reasoning:
           effort: "medium"       # xhigh, high, medium, low, minimal, none
           max_tokens: 2000       # Optional: direct token limit (Anthropic-style)
           exclude: false         # Optional: set true to hide reasoning from response

**With Web Search:**

.. code-block:: yaml

   agents:
     - id: "search_agent"
       backend:
         type: "chatcompletion"
         model: "openai/gpt-5-mini"
         base_url: "https://openrouter.ai/api/v1"
         enable_web_search: true
         engine: "exa"            # exa (AI-native) or native (traditional)
         max_results: 10
         search_context_size: "high"  # low, medium, high

**Reasoning Effort Levels:**

* ``xhigh``: ~95% of max_tokens for reasoning
* ``high``: ~80% of max_tokens for reasoning
* ``medium``: ~50% of max_tokens for reasoning (default)
* ``low``: ~20% of max_tokens for reasoning
* ``minimal``: ~10% of max_tokens for reasoning
* ``none``: Disable reasoning entirely

**Environment Variable:**

.. code-block:: bash

   OPENROUTER_API_KEY=your-openrouter-api-key

.. note::

   Reasoning tokens are output tokens and billed accordingly. Models automatically
   include reasoning in responses when appropriate. Use ``exclude: true`` if you
   want the model to reason internally without returning the reasoning text.

Local Inference Backends (vLLM & SGLang)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Unified Inference Backend** (v0.0.24-v0.0.25)

MassGen supports high-performance local model serving through vLLM and SGLang with automatic server detection:

.. code-block:: yaml

   agents:
     - id: "local_vllm"
       backend:
         type: "chatcompletion"
         model: "meta-llama/Llama-3.1-8B-Instruct"
         base_url: "http://localhost:8000/v1"    # vLLM default port
         api_key: "EMPTY"

     - id: "local_sglang"
       backend:
         type: "chatcompletion"
         model: "meta-llama/Llama-3.1-8B-Instruct"
         base_url: "http://localhost:30000/v1"   # SGLang default port
         api_key: "${SGLANG_API_KEY}"

**Auto-Detection:**

* **vLLM**: Default port 8000
* **SGLang**: Default port 30000
* Automatically detects server type based on configuration
* Unified InferenceBackend class handles both

**SGLang-Specific Parameters:**

.. code-block:: yaml

   backend:
     type: "chatcompletion"
     model: "meta-llama/Llama-3.1-8B-Instruct"
     base_url: "http://localhost:30000/v1"
     separate_reasoning: true        # SGLang guided generation
     top_k: 50                        # Sampling parameter
     repetition_penalty: 1.1          # Prevent repetition

**Mixed Deployments:**

Run both vLLM and SGLang simultaneously:

.. code-block:: yaml

   agents:
     - id: "vllm_agent"
       backend:
         type: "chatcompletion"
         model: "Qwen/Qwen2.5-7B-Instruct"
         base_url: "http://localhost:8000/v1"
         api_key: "EMPTY"

     - id: "sglang_agent"
       backend:
         type: "chatcompletion"
         model: "Qwen/Qwen2.5-7B-Instruct"
         base_url: "http://localhost:30000/v1"
         api_key: "${SGLANG_API_KEY}"
         separate_reasoning: true

**Benefits of Local Inference:**

* **Cost Savings**: Zero API costs after initial setup
* **Privacy**: No data sent to external services
* **Control**: Full control over model selection and parameters
* **Performance**: Optimized for high-throughput inference
* **Customization**: Fine-tune models for specific use cases

**Setup vLLM Server:**

.. code-block:: bash

   # Install vLLM
   pip install vllm

   # Start vLLM server
   vllm serve meta-llama/Llama-3.1-8B-Instruct \
     --host 0.0.0.0 \
     --port 8000

**Setup SGLang Server:**

.. code-block:: bash

   # Install SGLang
   pip install "sglang[all]"

   # Start SGLang server
   python -m sglang.launch_server \
     --model-path meta-llama/Llama-3.1-8B-Instruct \
     --host 0.0.0.0 \
     --port 30000

**Configuration Example:**

See ``@examples/basic/multi/two_qwen_vllm_sglang.yaml`` for a complete mixed deployment example.

Common Backend Parameters
-------------------------

Model Parameters
~~~~~~~~~~~~~~~~

All backends support these common parameters:

.. code-block:: yaml

   backend:
     type: "openai"
     model: "gpt-5-nano"

     # Generation parameters
     temperature: 0.7           # Randomness (0.0-2.0, default 0.7)
     max_tokens: 4096           # Maximum response length
     top_p: 1.0                 # Nucleus sampling (0.0-1.0)

     # API configuration
     api_key: "${OPENAI_API_KEY}"  # Optional - uses env var by default
     timeout: 60                    # Request timeout in seconds

Tool Configuration
~~~~~~~~~~~~~~~~~~

Enable or disable built-in tools:

.. code-block:: yaml

   backend:
     type: "gemini"
     model: "gemini-2.5-flash"

     # Enable tools
     enable_web_search: true
     enable_code_execution: true

     # MCP servers (see MCP Integration guide)
     mcp_servers:
       - name: "server_name"
         type: "stdio"
         command: "npx"
         args: ["..."]

Multi-Backend Configurations
-----------------------------

Using Different Backends
~~~~~~~~~~~~~~~~~~~~~~~~

Each agent can use a different backend:

.. code-block:: yaml

   agents:
     - id: "fast_researcher"
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
         enable_web_search: true

     - id: "deep_analyst"
       backend:
         type: "openai"
         model: "gpt-5"
         reasoning:
           effort: "high"

     - id: "code_expert"
       backend:
         type: "claude_code"
         model: "claude-sonnet-4"
         cwd: "workspace"

This is the **recommended approach** - use each backend's strengths:

* **Gemini 2.5 Flash**: Fast research with web search
* **GPT-5**: Advanced reasoning and analysis
* **Claude Code**: Development with file operations

Backend Selection Guide
-----------------------

Choosing the Right Backend
~~~~~~~~~~~~~~~~~~~~~~~~~~

Consider these factors when selecting backends:

**For Research Tasks:**

* **Gemini 2.5 Flash**: Fast, cost-effective, excellent web search
* **GPT-5-nano**: Good reasoning with web search
* **Grok**: Real-time information access

**For Coding Tasks:**

* **Claude Code**: Best for file operations, full dev tools
* **GPT-5**: Advanced code generation with reasoning
* **Gemini 2.5 Pro**: Complex code analysis

**For Analysis Tasks:**

* **GPT-5**: Deep reasoning and complex analysis
* **Claude Sonnet 4**: Long context, detailed analysis
* **Gemini 2.5 Pro**: Comprehensive multimodal analysis

**For Cost-Sensitive Tasks:**

* **GPT-5-nano**: Low-cost OpenAI model
* **Grok-3-mini**: Fast and affordable
* **Gemini 2.5 Flash**: Very cost-effective
* **LM Studio**: Free (local inference)

**For Privacy-Sensitive Tasks:**

* **LM Studio**: Fully local, no data sharing
* **Azure OpenAI**: Enterprise security
* **Self-hosted vLLM**: Private cloud deployment

.. _native-tool-backends:

Native Tool Backends (Claude Code & Codex)
------------------------------------------

MassGen supports two "native tool" backends that wrap CLI/SDK tools rather than just API calls:
**Claude Code** (Anthropic's Claude Code SDK) and **Codex** (OpenAI's Codex CLI). These backends
come with their own built-in filesystem and shell tools, providing a more integrated development
experience but with different security characteristics than API-only backends.

Architecture Differences
~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table:: Native Tool Backends vs API Backends
   :header-rows: 1
   :widths: 25 35 40

   * - Aspect
     - Native Tool Backends (Claude Code, Codex)
     - API Backends (OpenAI, Claude, Gemini, etc.)
   * - Tool Execution
     - Native tools (Read, Write, Bash) run locally via CLI/SDK
     - Tools run via MassGen's MCP servers
   * - Permission Control
     - Backend's own sandbox + limited MassGen hooks
     - Full MassGen PathPermissionManager control
   * - Filesystem Access
     - Direct local filesystem access
     - Controlled through MCP filesystem tools
   * - State Management
     - Stateful (session persistence, conversation history)
     - Stateless (each call is independent)

Claude Code vs Codex Comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table:: Claude Code vs Codex
   :header-rows: 1
   :widths: 20 40 40

   * - Feature
     - Claude Code
     - Codex
   * - Provider
     - Anthropic (Claude Code SDK)
     - OpenAI (Codex CLI)
   * - Authentication
     - API key (ANTHROPIC_API_KEY) or subscription
     - API key (OPENAI_API_KEY) or ChatGPT subscription (OAuth)
   * - Models
     - Claude Sonnet 4, Claude Opus 4
     - GPT-5.4, GPT-5.3-Codex, GPT-5.2-Codex, GPT-5.1-Codex, GPT-5-Codex
   * - Native Tools
     - Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch
     - shell, apply_patch, web_search, image_view
   * - MCP Support
     - Yes (SDK-native)
     - Yes (via .codex/config.toml)
   * - Sandbox Type
     - SDK permission hooks
     - OS-level (Seatbelt on macOS, Landlock on Linux)
   * - **Read Restrictions**
     - **Yes** - SDK hooks block reads outside allowed paths
     - **No** - OS sandbox only restricts writes
   * - Write Restrictions
     - Yes - SDK hooks enforce write permissions
     - Yes - OS sandbox restricts writes to writable_roots

.. warning::

   **Codex Sandbox Limitation**: Codex uses OS-level sandboxing (Seatbelt on macOS,
   Landlock on Linux) which **only restricts writes, NOT reads**. This means Codex
   can read any file on the filesystem, including sensitive files outside the workspace
   and context_paths (SSH keys, credentials, environment files, etc.).

   MassGen's permission hooks **cannot intercept** Codex's native tool calls because
   they run directly through the Codex CLI's internal tools.

Security Recommendations
~~~~~~~~~~~~~~~~~~~~~~~~

**For security-sensitive workloads, prefer Docker mode** which provides full filesystem
isolation via container boundaries:

.. code-block:: yaml

   # Recommended: Docker mode for Codex with sensitive data
   agents:
     - id: "secure_codex"
       backend:
         type: "codex"
         model: "gpt-5.4"
         cwd: "workspace"
         enable_mcp_command_line: true
         command_line_execution_mode: "docker"
         command_line_docker_network_mode: "bridge"  # Required for Codex
         command_line_docker_enable_sudo: true

.. important::

   **Codex in Docker mode requires** ``command_line_docker_network_mode: "bridge"``.
   Without this setting, Codex will fail to execute. The validator will check for this.

In Docker mode:

* The container itself is the sandbox - Codex's native tools can only access what's mounted
* Host filesystem is fully isolated from the agent
* ``~/.codex/`` is mounted read-only for OAuth token access
* The Codex CLI runs with ``--sandbox danger-full-access`` since the container provides isolation

**When Docker is not available**, consider:

1. **Use Claude Code instead** - SDK permission hooks provide read/write restrictions
2. **Limit context_paths** - Only grant access to directories that need agent access
3. **Avoid sensitive data** - Don't run Codex in directories with credentials or secrets
4. **Use API-only backends** - For maximum control, use ``openai`` or ``claude`` backends with MCP tools

Backend Configuration Best Practices
-------------------------------------

1. **Start with defaults**: Test with default parameters before tuning
2. **Use environment variables**: Never hardcode API keys
3. **Match backend to task**: Use each backend's strengths
4. **Enable only needed tools**: Disable unused capabilities
5. **Set appropriate timeouts**: Longer timeouts for complex tasks
6. **Monitor costs**: Track API usage across backends
7. **Test configurations**: Verify settings before production use

Advanced Backend Configuration
-------------------------------

For detailed backend-specific parameters, see:

* `Backend Configuration Guide <https://github.com/Leezekun/MassGen/blob/main/@examples/BACKEND_CONFIGURATION.md>`_
* :doc:`../reference/yaml_schema` - Complete YAML schema

MCP Integration
~~~~~~~~~~~~~~~

See :doc:`tools/mcp_integration` for:

* Adding MCP servers to backends
* Tool filtering (allowed_tools, exclude_tools)
* Planning mode configuration (v0.0.29)
* HTTP-based MCP servers

File Operations
~~~~~~~~~~~~~~~

See :doc:`files/file_operations` for:

* Workspace configuration
* Snapshot storage
* Permission management
* Cross-agent file sharing

Troubleshooting
---------------

**Backend not found:**

Ensure the backend type is correct:

.. code-block:: bash

   # Correct backend types
   type: "openai"         # ✅
   type: "claude_code"    # ✅
   type: "copilot"        # ✅
   type: "gemini"         # ✅

   # Incorrect (common mistakes)
   type: "gpt"            # ❌ Use "openai"
   type: "claude"         # ✅ (but consider "claude_code" for dev tools)
   type: "google"         # ❌ Use "gemini"

**API key not found:**

Check your ``.env`` file has the correct variable name:

.. code-block:: bash

   # Backend type → Environment variable
   openai       → OPENAI_API_KEY
   claude       → ANTHROPIC_API_KEY
   claude_code  → CLAUDE_CODE_API_KEY (falls back to ANTHROPIC_API_KEY)
   copilot      → GH_TOKEN or GITHUB_TOKEN (or use /login in Copilot CLI)
   gemini       → GOOGLE_API_KEY
   grok         → XAI_API_KEY
   azure_openai → AZURE_OPENAI_API_KEY

.. note::

   **Separate API keys for Claude Code:** The ``claude_code`` backend checks
   ``CLAUDE_CODE_API_KEY`` first, then falls back to ``ANTHROPIC_API_KEY``.
   This allows you to use a Claude subscription (no API key needed) or a
   separate API key for Claude Code agents while using a different API key
   for standard Claude backend agents.

**Model not supported:**

Verify the model name matches the backend's supported models:

.. code-block:: yaml

   # Check supported models in README.md or use --model flag
   backend:
     type: "openai"
     model: "gpt-5-nano"  # ✅ Supported
     model: "gpt-6"       # ❌ Not yet available

Next Steps
----------

* :doc:`../quickstart/configuration` - Full configuration guide
* :doc:`tools/mcp_integration` - Add external tools via MCP
* :doc:`files/file_operations` - Enable file system operations
* :doc:`../reference/supported_models` - Complete model list
* :doc:`../examples/basic_examples` - See backends in action
