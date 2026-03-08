Running MassGen
===============

This guide shows you how to run MassGen using different modes and configurations.

Choosing Your Mode
------------------

MassGen offers four ways to run multi-agent workflows:

.. list-table::
   :header-rows: 1
   :widths: 15 35 50

   * - Mode
     - Best For
     - Key Features
   * - **CLI**
     - Interactive exploration, quick experiments
     - Rich terminal UI, YAML configs, real-time visualization
   * - **WebUI**
     - Visual monitoring, team demos, workspace browsing
     - Browser-based UI, real-time streaming, file explorer, vote visualization
   * - **LiteLLM**
     - Application integration, LangChain, existing LiteLLM users
     - Standard OpenAI interface, drop-in replacement
   * - **HTTP Server**
     - Integrating via HTTP, OpenAI-compatible clients, proxies/gateways
     - OpenAI-compatible endpoints (``/v1/chat/completions``), SSE streaming, tool calling

For advanced programmatic control, see the :doc:`../user_guide/integration/python_api` (async-first, headless execution).

Quick Start Examples
--------------------

.. tabs::

   .. tab:: CLI

      .. code-block:: bash

         # Multi-agent collaboration (recommended)
         uv run massgen --config @examples/basic/multi/three_agents_default "Analyze renewable energy"

         # Interactive mode (multi-turn)
         uv run massgen

      Textual TUI (default) with timeline view, agent cards, vote visualization, and multi-turn conversations.

   .. tab:: WebUI

      .. code-block:: bash

         # Start the web interface
         uv run massgen --web

         # Open http://localhost:8000 in your browser

      Browser-based UI with real-time agent streaming, vote visualization, and workspace browsing.

   .. tab:: LiteLLM

      .. code-block:: python

         from dotenv import load_dotenv
         load_dotenv()  # Load OPENROUTER_API_KEY from .env

         import litellm
         from massgen import register_with_litellm

         register_with_litellm()

         # Multi-agent with multiple models (using OpenRouter)
         response = litellm.completion(
             model="massgen/build",
             messages=[{"role": "user", "content": "Analyze renewable energy"}],
             optional_params={"models": ["openrouter/openai/gpt-5", "openrouter/anthropic/claude-sonnet-4.5"]}
         )
         print(response.choices[0].message.content)

      Standard OpenAI-compatible interface for seamless integration with existing applications.

   .. tab:: HTTP Server

      .. code-block:: bash

         # Start an OpenAI-compatible HTTP server (defaults: 0.0.0.0:4000)
         uv run massgen serve

         # With a specific config
         uv run massgen serve --config @examples/basic/multi/three_agents_default

         # Health check
         curl http://localhost:4000/health

         # OpenAI-compatible Chat Completions
         curl http://localhost:4000/v1/chat/completions \
           -H "Content-Type: application/json" \
           -d '{"model":"massgen","messages":[{"role":"user","content":"Analyze renewable energy"}]}'

      OpenAI-compatible HTTP API for integrating MassGen into existing clients and server workflows.

      .. note::

         **Config Selection:** Use the ``model`` parameter to select configs:

         - ``model="massgen"`` - Use the default config (from ``--config`` or auto-discovered)
         - ``model="massgen/basic_multi"`` - Use a built-in example config
         - ``model="massgen/path:/path/to/config.yaml"`` - Use a specific config file

         **Full Parity:** The HTTP server uses ``massgen.run()`` internally, providing identical behavior
         to CLI, WebUI, and LiteLLM modes - including logging to ``.massgen/massgen_logs/``, metrics,
         and session management. The ``massgen_metadata`` field in responses contains the same data
         as ``massgen.run()`` returns.

CLI Usage
---------

Basic Command Structure
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   uv run massgen [OPTIONS] ["<your question>"]

For the complete list of CLI options, see :doc:`../reference/cli`.

Multi-Agent Collaboration
~~~~~~~~~~~~~~~~~~~~~~~~~

MassGen is designed for multi-agent collaboration - multiple agents working together on complex tasks:

.. code-block:: bash

   # Three agents collaborate
   uv run massgen --config @examples/basic/multi/three_agents_default "Analyze the pros and cons of renewable energy"

The agents work in parallel, share observations, vote for solutions, and converge on the best answer.

Decomposition Mode
~~~~~~~~~~~~~~~~~~

Use decomposition mode when each agent owns a subtask and one presenter combines results:

.. code-block:: bash

   uv run massgen \
     --config @examples/basic/multi/decomposition_quickstart \
     "Build a small full-stack todo app"

Recommended decomposition defaults:

* ``max_new_answers_per_agent: 2-3`` (consecutive cap; resets after unseen external updates are injected)
* ``max_new_answers_global`` set to an overall budget (for example ``9`` with three agents)
* If a decomposition agent hits its cap, it should stop instead of running a wasteful extra round
* With GPT-5x models, quickstart lets you pick ``reasoning.effort`` (Codex GPT-5 models include ``xhigh``)

Unless you need different behavior, keep these defaults.

Interactive Multi-Turn Mode
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Start without a question to enter interactive chat mode:

.. code-block:: bash

   # Interactive with multi-agent team
   uv run massgen --config @examples/basic/multi/three_agents_default

Features:

* Conversation context preserved across turns
* Session history saved in ``.massgen/sessions/``
* Real-time agent coordination visualization
* Optional CWD context shortcut via ``--cwd-context ro|rw``

CWD Context Shortcut
~~~~~~~~~~~~~~~~~~~~

Use ``--cwd-context`` when you want quick access to your current directory without editing YAML:

.. code-block:: bash

   # Read-only current directory context
   uv run massgen --config @examples/basic/multi/three_agents_default --cwd-context ro "Review this repository"

   # Writable current directory context
   uv run massgen --config @examples/basic/multi/three_agents_default --cwd-context rw "Implement the requested changes"

In Textual TUI sessions, this initializes the same state as pressing ``Ctrl+P``.
During Execute mode, ``Ctrl+P`` is blocked so context scope cannot change mid-execution.

See :doc:`../user_guide/sessions/multi_turn_mode` for the complete guide.

.. note::

   For programmatic Python access with async support and full control, see the :doc:`../user_guide/integration/python_api`.

WebUI
-----

The WebUI provides a browser-based interface for visual monitoring of multi-agent coordination.

Starting the WebUI
~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Basic: Start on localhost:8000
   uv run massgen --web

   # With custom host/port
   uv run massgen --web --web-host 0.0.0.0 --web-port 3000

   # With a default config
   uv run massgen --web --config @examples/basic/multi/three_agents_default

Then open http://localhost:8000 in your browser.

First-Time Setup
~~~~~~~~~~~~~~~~

On first launch, the WebUI automatically guides you through setup:

1. **Setup Page** - Configure API keys, Docker, and skills
2. **Quickstart Wizard** - Create your first agent configuration, including decomposition mode, presenter selection, GPT-5x reasoning selection, and recommended answer-control defaults

This makes ``uv run massgen --web`` the easiest way to get started with MassGen.

Key Features
~~~~~~~~~~~~

* **Real-time Agent Streaming** - Watch agents think, use tools, and generate answers live
* **Vote Visualization** - See voting distribution and consensus-building with animated charts
* **Coordination Timeline** - Visual swimlane diagram showing answer flow and dependencies
* **Answer Browser** - Browse all agent answers with version history
* **Workspace Explorer** - View and examine files created by agents during execution
* **Multi-Turn Conversations** - Continue sessions with follow-up questions
* **Quickstart Wizard** - Guided setup for configuring agents without manual YAML editing, including decomposition controls

See :doc:`../user_guide/webui` for the complete WebUI guide.

LiteLLM Integration
-------------------

MassGen integrates with LiteLLM for a familiar OpenAI-compatible interface. Use OpenRouter to access multiple models with a single API key.

Setup
~~~~~

.. code-block:: python

   from dotenv import load_dotenv
   load_dotenv()  # Load OPENROUTER_API_KEY from .env

   import litellm
   from massgen import register_with_litellm

   # Register once at startup
   register_with_litellm()

Model String Formats
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # Dynamic multi-agent with OpenRouter (recommended - single API key)
   response = litellm.completion(
       model="massgen/build",
       messages=[{"role": "user", "content": "Your question"}],
       optional_params={"models": ["openrouter/openai/gpt-5", "openrouter/anthropic/claude-sonnet-4.5"]}
   )
   print(response.choices[0].message.content)

   # Use example config
   response = litellm.completion(
       model="massgen/basic_multi",
       messages=[{"role": "user", "content": "Your question"}]
   )
   print(response.choices[0].message.content)

Access MassGen Metadata
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   # MassGen-specific metadata
   metadata = response._hidden_params
   print(metadata.get("massgen_vote_results"))
   print(metadata.get("massgen_answers"))

See :doc:`../user_guide/integration/python_api` for complete LiteLLM documentation.

Adding Tools
------------

MCP Integration
~~~~~~~~~~~~~~~

Add external tools via Model Context Protocol:

.. tabs::

   .. tab:: CLI

      .. code-block:: bash

         uv run massgen --config @examples/tools/mcp/gpt5_nano_mcp_example.yaml \
           "What's the weather in New York?"

   .. tab:: YAML Config

      .. code-block:: yaml

         agents:
           - id: "agent_with_tools"
             backend:
               type: "openai"
               model: "openrouter/openai/gpt-5"
             mcp_servers:
               - command: "npx"
                 args: ["-y", "@modelcontextprotocol/server-weather"]

See :doc:`../user_guide/tools/mcp_integration` for details.

File Operations
~~~~~~~~~~~~~~~

Agents can work with files in isolated workspaces:

.. tabs::

   .. tab:: CLI

      .. code-block:: bash

         uv run massgen --config @examples/tools/filesystem/claude_code_single.yaml \
           "Create a Python web scraper and save results to CSV"

   .. tab:: YAML Config

      .. code-block:: yaml

         orchestrator:
           file_system:
             enabled: true
             use_docker: false

See :doc:`../user_guide/files/file_operations` for details.

Configuration Paths
-------------------

MassGen supports multiple ways to specify configurations:

.. code-block:: bash

   # Built-in examples (works from any directory)
   uv run massgen --config @examples/basic/multi/three_agents_default "Question"

   # List all examples
   uv run massgen --list-examples

   # Custom file (relative or absolute path)
   uv run massgen --config ./my-config.yaml "Question"

   # User config directory
   uv run massgen --config my-saved-config "Question"
   # Looks for ~/.config/massgen/agents/my-saved-config.yaml

   # Quickstart with explicit output filename
   uv run massgen --quickstart --config team-config
   # Saves generated config to .massgen/team-config.yaml

Viewing Results
---------------

By default, MassGen shows a rich terminal UI. Control the display:

.. code-block:: bash

   # Disable UI (quiet mode)
   uv run massgen --no-display --config config.yaml "Question"

   # Enable debug logging
   uv run massgen --debug --config config.yaml "Question"

After execution completes, an interactive Agent Selector menu appears, allowing you to:

* View each agent's original output and reasoning
* See the orchestrator's system status and voting process
* Display the coordination table with full agent interaction history
* Browse workspace files created during execution
* Press ``q`` to exit

Analyzing and Sharing Sessions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After running a session, use these commands to analyze and share your results:

.. code-block:: bash

   # View summary of the most recent run
   massgen logs

   # List recent runs with costs and questions
   massgen logs list

   # Share a session (creates shareable URL)
   massgen export

The ``massgen export`` command uploads your session to GitHub Gist and returns a shareable URL that anyone can view without login. This is useful for collaboration, debugging, or showcasing results.

See :doc:`../user_guide/logging` for the complete logging and sharing guide.

Next Steps
----------

.. grid:: 2
   :gutter: 3

   .. grid-item-card:: ⚙️ Configuration

      Create custom agent teams

      :doc:`configuration`

   .. grid-item-card:: 📚 Core Concepts

      Understand multi-agent coordination

      :doc:`../user_guide/concepts`

   .. grid-item-card:: 🐍 Python API

      Full programmatic control

      :doc:`../user_guide/integration/python_api`

   .. grid-item-card:: 🔌 Tools & MCP

      Add capabilities to agents

      :doc:`../user_guide/tools/index`
