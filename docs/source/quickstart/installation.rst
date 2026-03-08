============
Installation
============

Prerequisites
=============

MassGen requires **Python 3.11 or higher**.

A guide to install python can be found `here <https://realpython.com/installing-python/>`_

.. code-block:: bash

   python --version  # Should be 3.11+

Quick Install
=============

.. tabs::

   .. tab:: CLI

      .. code-block:: bash

         pip install uv          # if uv is not installed, the fastest way to check if uv is installed is to run "uv venv"
         # if the above command fails, run "curl -LsSf https://astral.sh/uv/install.sh | sh" for macOS and Linux to install uv
         # or run "powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" for Windows
         uv venv && source .venv/bin/activate
         uv pip install massgen

   .. tab:: LiteLLM Integration

      .. code-block:: bash

         pip install uv          # if uv is not installed, the fastest way to check if uv is installed is to run "uv venv"
         # if the above command fails, run "curl -LsSf https://astral.sh/uv/install.sh | sh" for macOS and Linux to install uv
         # or run "powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" for Windows
         uv venv && source .venv/bin/activate
         uv pip install massgen litellm python-dotenv

      Then in Python:

      .. code-block:: python

         from dotenv import load_dotenv
         load_dotenv()  # Load OPENROUTER_API_KEY from .env

         import litellm
         from massgen import register_with_litellm

         register_with_litellm()

         response = litellm.completion(
             model="massgen/build",
             messages=[{"role": "user", "content": "Hello!"}],
             optional_params={"models": ["openrouter/openai/gpt-5"]}
         )
         print(response.choices[0].message.content)

For programmatic Python usage, see the :doc:`../user_guide/integration/python_api`.

First Run Setup
===============

On first run, MassGen guides you through setup. Choose your preferred interface:

.. tabs::

   .. tab:: WebUI (Recommended)

      .. code-block:: bash

         uv run massgen --web

      The browser-based setup wizard will:

      1. **Configure API keys** - Enter keys for OpenAI, Anthropic, Google, etc.
      2. **Setup Docker** (optional) - For isolated code execution
      3. **Review Skills** - See available agent capabilities
      4. **Create your agent team** - Quickstart wizard for configuration

      This is the easiest way to get started - everything in one visual interface.

   .. tab:: CLI

      .. code-block:: bash

         uv run massgen

      The terminal wizard will:

      1. **Configure API keys** (OpenRouter recommended, or individual providers)
      2. **Create your agent team** (choose from templates or examples)
      3. **Launch interactive TUI mode** immediately

      The Textual TUI (default) provides real-time visualization with:

      - 📊 Timeline view of all agent activities
      - 🎯 Individual agent status cards
      - 🗳️ Vote visualization and consensus tracking
      - 💬 Multi-turn conversation management

By default, setup creates ``~/.config/massgen/config.yaml``.
Quickstart also supports custom filenames:

* In the TUI/Web Quickstart "Save Location" step, choose project (``.massgen/``) or global
  (``~/.config/massgen/``) and enter a filename.
* In CLI quickstart, ``--config`` can be used as the output filename:

.. code-block:: bash

   # Saves to .massgen/team-config.yaml
   uv run massgen --quickstart --config team-config

API Keys
--------
API keys can be configured through webui or cli setup. However, they can also be setup through the terminal:

**OpenRouter (recommended):** Single API key for all models

.. code-block:: bash

   export OPENROUTER_API_KEY=sk-or-v1-...

**Or use individual providers:** OpenAI, Anthropic, Google Gemini, xAI (Grok), Azure OpenAI, Groq, Together AI, Fireworks, Cerebras

**Manual setup** (optional - wizard handles this):

.. code-block:: bash

   # Create .env file
   mkdir -p ~/.config/massgen
   echo "OPENROUTER_API_KEY=sk-or-v1-..." >> ~/.config/massgen/.env

Re-run Setup
------------

Re-configure anytime:

.. code-block:: bash

   uv run massgen --web         # WebUI setup page (visit /setup)
   uv run massgen --init        # CLI full configuration wizard
   uv run massgen --setup       # CLI just API keys
   uv run massgen --quickstart  # CLI quick 3-agent setup

Verify Installation
===================

.. code-block:: bash

   # Check CLI is available
   uv run massgen --help

   # List example configurations
   uv run massgen --list-examples

   # Run multi-agent collaboration
   uv run massgen --config @examples/basic/multi/three_agents_default "What is machine learning?"

Optional: Observability
=======================

For structured logging and tracing with Logfire:

.. code-block:: bash

   # Install with observability support
   pip install "massgen[observability]"

   # Or with uv
   uv pip install "massgen[observability]"

   # Authenticate with Logfire
   uv run logfire auth

   # Run with observability enabled
   uv run massgen --logfire --config your_config.yaml "Your question"

See :doc:`../user_guide/logging` for detailed Logfire configuration.

Optional: Docker & Skills
=========================

For advanced features like isolated code execution:

.. code-block:: bash

   # Install Docker images
   uv run massgen --setup-docker

   # Install skills (semantic search, web scraping)
   uv run massgen --setup-skills

These are optional - basic MassGen works without them.

.. note::

   In ``uv run massgen --quickstart``, when Docker mode is selected the wizard includes
   a Skills step where you can select package(s) and install them immediately with
   on-page status updates (Anthropic/OpenAI/Vercel collections, Agent Browser skill,
   Remotion, and Crawl4AI). Use ``--setup-skills`` to retry or pre-install manually.

Development Installation
========================

For contributors or source code access:

.. code-block:: bash

   git clone https://github.com/Leezekun/MassGen.git
   cd MassGen
   pip install -e .

   # Or with full dev setup (Unix/macOS)
   ./scripts/init.sh

Next Steps
==========

.. grid:: 2
   :gutter: 3

   .. grid-item-card:: ▶️ Run MassGen

      See all usage modes

      :doc:`running-massgen`

   .. grid-item-card:: ⚙️ Configuration

      Create custom agent teams

      :doc:`configuration`

   .. grid-item-card:: 📚 Examples

      Ready-to-use configs

      :doc:`../examples/basic_examples`

   .. grid-item-card:: 🐍 Python API

      Programmatic integration

      :doc:`../user_guide/integration/python_api`

Troubleshooting
===============

**Python version error:**

.. code-block:: bash

   python --version  # Need 3.11+
   pip install --upgrade massgen

**API key not found:**

Check ``~/.config/massgen/.env`` exists with correct keys, or re-run ``massgen --init``.

**Setup wizard not appearing:**

Run ``massgen --init`` to manually trigger it.

For more help: `GitHub Issues <https://github.com/Leezekun/MassGen/issues>`_
