Code-Based Tools
================

MassGen supports code-based tool access following the `CodeAct <https://machinelearning.apple.com/research/codeact>`_ paradigm and other blog posts by `Anthropic <https://www.anthropic.com/engineering/code-execution-with-mcp>`_ and `Cloudflare <https://blog.cloudflare.com/code-mode/>`_. Instead of passing tool schemas to the model, MCP tools are presented as Python code in the workspace filesystem. Agents discover tools by reading files, import them like normal Python modules, and execute them via command-line.

This approach provides significant benefits:

* **Context reduction** - Load only needed tools instead of all schemas upfront
* **Transparent tool access** - Agents read source code and docstrings to understand tools
* **Native composition** - Combine multiple tools naturally using standard Python
* **Async-friendly workflows** - Write async scripts for parallel tool execution
* **Smart data filtering** - Process large datasets before returning to LLM

.. note::

   **Quick Setup Summary:**

   1. Enable ``enable_code_based_tools: true`` in your config
   2. Add ``enable_mcp_command_line: true`` for execution
   3. Optionally add ``exclude_file_operation_mcps: true`` to reduce redundancy
   4. Your MCP servers become Python code in ``workspace/servers/``
   5. For long-running tool calls, use the background lifecycle from :doc:`background_tools`

Quick Start: Try It Now
------------------------

MassGen includes a working example you can try immediately:

.. code-block:: bash

   # Explore available tools (demonstrates tool discovery)
   massgen --automation \
     --config massgen/configs/tools/filesystem/code_based/example_code_based_tools.yaml \
     "List all available tools by exploring the workspace filesystem. Show what MCP tools and custom tools are available."

   # Or create a website (demonstrates skills system)
   massgen \
     --config massgen/configs/tools/filesystem/code_based/example_code_based_tools.yaml \
     "Create a website about Bob Dylan, ensuring that it is visually appealing and user friendly"

The agent will:

1. Explore ``workspace/`` to discover available tools (MCP tools in ``servers/``, custom tools in ``custom_tools/``)
2. Read tool documentation from Python files and TOOL.md files
3. Import and use the tools as needed
4. Optionally create workflows in ``workspace/utils/`` for complex operations

How It Works
------------

When ``enable_code_based_tools: true`` is set, MassGen:

1. **Connects to your MCP servers** (weather, GitHub, etc.)
2. **Extracts tool schemas** from each connected server
3. **Generates Python wrapper code** for each tool
4. **Writes code to workspace** in an organized structure:

.. code-block:: text

   workspace/
   ├── servers/              # Auto-generated MCP wrappers
   │   ├── __init__.py      # Package marker (import from here)
   │   ├── weather/
   │   │   ├── __init__.py  # Exports: get_forecast, get_current
   │   │   ├── get_forecast.py
   │   │   └── get_current.py
   │   └── github/
   │       └── create_issue.py
   ├── custom_tools/         # Your custom Python tools (optional)
   ├── utils/               # Agent-created scripts (workflows, async, filtering)
   └── .mcp/                # Hidden MCP client (protocol handler)
       ├── client.py
       └── servers.json

**Directory purposes:**

* ``servers/`` - Auto-generated wrappers for MCP tools (read-only for agents)
* ``custom_tools/`` - Full Python implementations you provide (optional)
* ``utils/`` - Agent workspace for creating workflows and scripts
* ``.mcp/`` - Hidden infrastructure (agents don't see this)

TOOL.md Format & API Keys
--------------------------

Custom Tool Documentation
~~~~~~~~~~~~~~~~~~~~~~~~~~

Custom tools in ``massgen/tool/`` include ``TOOL.md`` files with YAML frontmatter for discoverability:

.. code-block:: yaml

   ---
   name: multimodal-tools
   description: Vision, audio, video, and file processing tools
   category: multimodal
   requires_api_keys: [OPENAI_API_KEY]
   tasks:
     - "Analyze and understand images with vision models"
     - "Understand and transcribe audio files"
     - "Process and understand various file formats (PDF, DOCX, etc.)"
   keywords: [vision, audio, video, multimodal, image-analysis]
   ---

   # Multimodal Tools

   [Detailed documentation follows...]

**YAML Fields:**

* ``name`` - Tool package identifier (matches directory name)
* ``description`` - One-line summary
* ``category`` - Primary category (text-processing, web-scraping, multimodal, automation, etc.)
* ``requires_api_keys`` - List of required API keys, or empty list ``[]`` if none needed
* ``tasks`` - Action-oriented task descriptions (searchable)
* ``keywords`` - Searchable terms

API Key Management
~~~~~~~~~~~~~~~~~~

MassGen uses ``.env`` files for API key management. Keys must be explicitly configured to be passed to Docker containers.

**1. Create .env file in project root:**

.. code-block:: bash

   # .env file
   OPENAI_API_KEY=sk-...
   ANTHROPIC_API_KEY=sk-ant-...
   GOOGLE_API_KEY=...
   GEMINI_API_KEY=...

See ``.env.example`` in the project root for a template of all supported API keys.

**2. Configure Docker to pass API keys:**

When using ``command_line_execution_mode: docker``, you **must** configure credentials to pass API keys:

.. code-block:: yaml

   backend:
     enable_code_based_tools: true
     enable_mcp_command_line: true
     command_line_execution_mode: "docker"

     # IMPORTANT: Pass API keys to Docker
     command_line_docker_credentials:
       env_file: ".env"  # Load from .env file
       env_vars_from_file:
         - "OPENAI_API_KEY"
         - "ANTHROPIC_API_KEY"
         - "GOOGLE_API_KEY"
         - "GEMINI_API_KEY"

**Without this configuration**, custom tools requiring API keys will fail inside Docker containers.

**Alternative approaches:**

.. code-block:: yaml

   # Option A: Load ALL variables from .env (simpler, less secure)
   command_line_docker_credentials:
     env_file: ".env"

   # Option B: Pass specific vars from host environment
   command_line_docker_credentials:
     env_vars:
       - "OPENAI_API_KEY"
       - "ANTHROPIC_API_KEY"

   # Option C: Dangerous - pass ALL host env vars (NOT RECOMMENDED)
   command_line_docker_credentials:
     pass_all_env: true

**3. Check which tools require which keys:**

.. code-block:: bash

   rg "^requires_api_keys:" massgen/tool/*/TOOL.md

**4. Filter tools by available API keys:**

.. code-block:: bash

   # Check what API keys you have
   env | grep "API_KEY"

   # Find tools that need OPENAI_API_KEY
   rg "^requires_api_keys:.*OPENAI_API_KEY" massgen/tool/*/TOOL.md -l

   # Find tools that need no API keys
   rg "^requires_api_keys: \[\]" massgen/tool/*/TOOL.md -l

.. note::

   **For local execution mode** (``command_line_execution_mode: local``), environment variables from your shell are automatically available. You only need to configure ``command_line_docker_credentials`` when using Docker.

**Automatic Tool Exclusion:**

MassGen automatically excludes tools based on unavailable API keys to prevent runtime failures:

* When you configure ``command_line_docker_credentials``, MassGen reads the ``requires_api_keys`` field from each tool's TOOL.md
* Tools requiring API keys not listed in your credentials configuration are automatically excluded
* Excluded tools won't be copied to your workspace and won't appear in tool listings
* Exclusion is logged during setup: ``"Excluding tool_name: missing API keys: KEY_NAME"``

**Example:**

.. code-block:: yaml

   # Only configure OpenAI key
   command_line_docker_credentials:
     env_file: ".env"
     env_vars_from_file:
       - "OPENAI_API_KEY"  # Only this key

**Result:**
- ``_multimodal_tools`` (requires ``OPENAI_API_KEY``) → ✅ **Available**
- ``_computer_use`` (requires ``OPENAI_API_KEY``) → ✅ **Available**
- ``_claude_computer_use`` (requires ``ANTHROPIC_API_KEY``) → ❌ **Excluded** (missing key)
- ``_gemini_computer_use`` (requires ``GOOGLE_API_KEY``) → ❌ **Excluded** (missing key)
- ``_web_tools`` (requires no API keys: ``[]``) → ✅ **Available**

You can override or supplement automatic exclusion with manual ``exclude_custom_tools`` configuration.

Configuration
-------------

Basic Setup
~~~~~~~~~~~

.. code-block:: yaml

   agents:
     - id: "my_agent"
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
         cwd: "workspace"

         # Enable code-based tools
         enable_code_based_tools: true
         enable_mcp_command_line: true      # Required for execution
         exclude_file_operation_mcps: true  # Recommended (use CLI for files)

         # Your MCP servers (will be converted to Python code)
         mcp_servers:
           - name: "weather"
             type: "stdio"
             command: "npx"
             args: ["-y", "@modelcontextprotocol/server-weather"]

With Custom Tools
~~~~~~~~~~~~~~~~~

If you have existing Python tools you want visible in the workspace:

.. code-block:: yaml

   backend:
     enable_code_based_tools: true
     custom_tools_path: "massgen/tool/_code_based_example"  # Copied to workspace/custom_tools/
     enable_mcp_command_line: true
     command_line_execution_mode: "docker"

     # IMPORTANT: Most custom tools require API keys
     command_line_docker_credentials:
       env_file: ".env"
       env_vars_from_file:
         - "OPENAI_API_KEY"
         - "ANTHROPIC_API_KEY"
         - "GOOGLE_API_KEY"

     mcp_servers:
       - name: "weather"
         # ... MCP config

Your custom tools directory will be copied into ``workspace/custom_tools/`` where agents can read and use them.

.. note::

   **Automatic Tool Filtering**: When using Docker execution mode, MassGen automatically excludes custom tools whose required API keys are not configured in ``command_line_docker_credentials``. For example, if you only configure ``OPENAI_API_KEY``, tools requiring ``ANTHROPIC_API_KEY`` will be automatically excluded and won't appear in your workspace.

   Use ``rg "^requires_api_keys:" massgen/tool/*/TOOL.md`` to check which tools need which API keys.

Direct MCP Servers
------------------

When using code-based tools, all user MCP servers are normally filtered out from direct protocol access and become accessible only via generated Python code. However, you may want certain MCP servers (like debugging or monitoring tools) to remain as direct native tools in the prompt.

Use ``direct_mcp_servers`` to specify which MCP servers should bypass code-based filtering:

.. code-block:: yaml

   backend:
     type: gemini
     model: gemini-3-flash-preview
     enable_code_based_tools: true
     auto_discover_custom_tools: true

     # Keep logfire as a native tool in the prompt
     direct_mcp_servers:
       - logfire

     mcp_servers:
       - name: logfire
         type: stdio
         command: uvx
         args: ["logfire-mcp@latest"]
         env:
           LOGFIRE_READ_TOKEN: ${LOGFIRE_READ_TOKEN}

       - name: weather
         # This MCP will be filtered to code-only access
         type: stdio
         command: uvx
         args: ["weather-mcp@latest"]

In this example:

- ``logfire`` tools appear directly in the prompt as callable functions
- ``weather`` tools are converted to Python code in the workspace

**When to Use Direct MCP Servers:**

- **Debugging/monitoring tools**: Keep tools like Logfire that you want immediate access to
- **Frequently-used MCPs**: Tools called often that benefit from direct invocation
- **Framework-adjacent MCPs**: Tools that feel like core capabilities rather than external services

.. note::

   Subagents automatically inherit ``direct_mcp_servers`` from their parent agent.

Agent Usage Patterns
--------------------

1. Tool Discovery
~~~~~~~~~~~~~~~~~

Agents discover tools through two mechanisms: **TOOL.md files** for custom tool packages and **filesystem exploration** for MCP tools.

**Custom Tool Packages (TOOL.md Discovery)**

Custom tools include TOOL.md files with searchable YAML frontmatter:

.. code-block:: bash

   # List all available custom tool packages
   rg "^name: " */TOOL.md

   # Search by task description
   rg "tasks:" -A 5 */TOOL.md | rg -i "scrape|image|automate"

   # Search by keyword
   rg "^keywords:.*web|vision" */TOOL.md -l

   # Search by category
   rg "^category: automation" */TOOL.md -l

   # Check API key requirements
   rg "^requires_api_keys:" */TOOL.md
   env | grep "API_KEY"  # Check which API keys you have

   # Semantic search (if available)
   search "process videos" . --glob "*/TOOL.md" --top-k 5

   # Read full documentation
   cat custom_tools/TOOL.md

.. important::

   **Docker Users**: If tools show ``requires_api_keys: [OPENAI_API_KEY]`` or similar, you must configure ``command_line_docker_credentials`` in your YAML to pass API keys to Docker containers. See the API Key Management section above for details.

**MCP Tools (Filesystem Discovery)**

MCP tools are discovered by exploring the servers/ directory:

.. code-block:: bash

   # Discover available MCP servers
   ls servers/

   # See tools in a server (each .py file is a tool)
   ls servers/weather/

   # Read tool documentation from docstring
   cat servers/weather/get_forecast.py

   # Search for functionality across all MCP tools
   rg "temperature|forecast" servers/ --type py

   # Semantic search within MCP tools
   search "get weather data" servers/ --type py

2. Direct Tool Usage
~~~~~~~~~~~~~~~~~~~~

Once discovered, agents import and use tools:

.. code-block:: python

   # Import tool
   from servers.weather import get_forecast

   # Call it
   forecast = get_forecast("San Francisco", days=3)
   print(forecast)

3. Creating Workflows (utils/)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Agents can write sophisticated scripts in ``utils/`` to compose multiple tools:

.. code-block:: python

   # utils/daily_weather_report.py
   from servers.weather import get_forecast, get_current

   def generate_report(city: str) -> str:
       """Generate a daily weather report for a city."""
       current = get_current(city)
       forecast = get_forecast(city, days=3)

       report = f"Current: {current['temp']}°F\n"
       report += f"3-day forecast: {forecast['summary']}"
       return report

   if __name__ == "__main__":
       print(generate_report("San Francisco"))

Then execute:

.. code-block:: bash

   python utils/daily_weather_report.py

4. Async Operations
~~~~~~~~~~~~~~~~~~~

For parallel tool calls, agents can use asyncio:

.. code-block:: python

   # utils/parallel_forecasts.py
   import asyncio
   from servers.weather import get_forecast

   async def get_forecasts(cities: list) -> dict:
       """Get forecasts for multiple cities in parallel."""
       tasks = [get_forecast(city) for city in cities]
       results = await asyncio.gather(*tasks)
       return dict(zip(cities, results))

   cities = ["San Francisco", "New York", "Los Angeles", "Chicago"]
   forecasts = asyncio.run(get_forecasts(cities))
   print(forecasts)

5. Data Filtering
~~~~~~~~~~~~~~~~~

Process large datasets in the execution environment before returning to the LLM:

.. code-block:: python

   # utils/qualified_leads.py
   from servers.salesforce import get_records

   def get_top_leads(limit: int = 50) -> list:
       """Get top qualified leads (filters 10k → 50 records)."""
       # Fetch large dataset
       all_records = get_records(object="Lead", limit=10000)

       # Filter in execution environment (not sent to LLM)
       qualified = [r for r in all_records if r["score"] > 80]

       # Return only top N (massive context reduction)
       return sorted(qualified, key=lambda x: x["score"], reverse=True)[:limit]

   # Agent only sees top 50, not all 10k records
   top_leads = get_top_leads()

Generated Code Example
----------------------

MassGen generates clean, documented Python wrappers. Here's an example:

**``servers/weather/get_forecast.py``:**

.. code-block:: python

   """
   get_forecast - MCP tool wrapper

   Auto-generated wrapper for the 'get_forecast' tool from the 'weather' MCP server.
   This wrapper handles MCP protocol communication transparently.
   """

   from typing import Any, Dict, Optional
   import sys
   import os
   from pathlib import Path

   # Add .mcp to path for MCP client
   _mcp_path = Path(__file__).parent.parent.parent / '.mcp'
   if str(_mcp_path) not in sys.path:
       sys.path.insert(0, str(_mcp_path))

   from client import call_mcp_tool


   def get_forecast(location: str, days: Optional[int] = 5) -> Any:
       """Get weather forecast for a location.

       Args:
           location (str): City name or coordinates
           days (int, optional): Number of days (default: 5, max: 10)

       Returns:
           Any: Tool execution result from MCP server
       """
       return call_mcp_tool(
           server="weather",
           tool="get_forecast",
           arguments={
               "location": location,
               "days": days
           }
       )


   if __name__ == "__main__":
       # CLI usage for testing
       import json

       if len(sys.argv) > 1:
           result = get_forecast(sys.argv[1])
       else:
           print("Usage: python get_forecast.py <location>")
           print(f"\nDocumentation:\n{get_forecast.__doc__}")
           sys.exit(1)

       print(json.dumps(result, indent=2))

Agents can read this file to understand the tool's interface, then import and use it.

Benefits
--------

Context Reduction
~~~~~~~~~~~~~~~~~

**Without code-based tools:**

* All tool schemas loaded upfront into model context
* 10 MCP tools × 200 tokens each = 2,000 tokens before any task
* Wasted context on unused tools

**With code-based tools:**

* Only tool names visible initially (``ls servers/``)
* Agent reads only needed tools

Transparency
~~~~~~~~~~~~

Agents can:

* Read source code to understand tool behavior
* See parameter types and defaults
* Read docstrings and examples
* Understand error handling

This is impossible with opaque tool schemas.

Composability
~~~~~~~~~~~~~

Standard Python enables natural tool composition:

.. code-block:: python

   # utils/weather_email.py
   from servers.weather import get_forecast
   from servers.gmail import send_email

   async def send_weather_alert(city: str, recipient: str):
       """Send weather forecast via email."""
       forecast = get_forecast(city, days=7)

       if forecast['max_temp'] > 100:
           await send_email(
               to=recipient,
               subject=f"Heat Alert: {city}",
               body=f"High temperature expected: {forecast['max_temp']}°F"
           )

Async Performance
~~~~~~~~~~~~~~~~~

Native async support enables parallel tool calls:

.. code-block:: python

   # Sequential: 3 seconds total
   forecast1 = get_forecast("SF")      # 1s
   forecast2 = get_forecast("NYC")     # 1s
   forecast3 = get_forecast("LA")      # 1s

   # Parallel: 1 second total
   results = await asyncio.gather(
       get_forecast("SF"),
       get_forecast("NYC"),
       get_forecast("LA")
   )  # All execute concurrently

Data Filtering Privacy
~~~~~~~~~~~~~~~~~~~~~~

Process sensitive data in execution environment:

.. code-block:: python

   # Fetch 10k customer records
   customers = get_records("Customer", limit=10000)

   # Filter to relevant subset (in execution env, not sent to LLM)
   active_customers = [c for c in customers if c["status"] == "active"]

   # Only return summary statistics
   return {
       "total": len(customers),
       "active": len(active_customers),
       "conversion_rate": len(active_customers) / len(customers)
   }

The LLM never sees the raw customer data.

Important Notes
---------------

Built-in MCPs Stay as MCPs
~~~~~~~~~~~~~~~~~~~~~~~~~~~

When ``enable_code_based_tools: true``:

**User MCP Servers (Converted to Code-Only)**
  * Weather, GitHub, Salesforce, etc. are **removed from MCP protocol**
  * **Only accessible via Python code** in ``servers/``
  * Agents cannot call them as protocol tools (must import and use)

**Framework MCPs (Remain as Protocol)**
  * ``command_line`` - Command execution (bash is implicitly available)
  * ``workspace_tools`` - File operations, media generation
  * ``filesystem`` - Filesystem operations
  * ``planning`` - Task planning MCP
  * ``memory`` - Memory management MCP

These framework MCPs are abstracted at the protocol level and not visible in the filesystem. For example, agents can run bash commands directly without needing an ``execute_command`` function - it's automatically available.

**Important**: User MCP tools are **completely filtered out** of the agent's MCP tool list. This forces agents to use the generated Python wrappers, achieving context reduction benefit.

Non-blocking Code Generation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If code generation fails, MCP setup continues normally. The agent falls back to protocol-based tool access.

Command-line Execution Required
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Code-based tools require command-line execution capability:

.. code-block:: yaml

   backend:
     enable_mcp_command_line: true  # Required

Without this, agents cannot execute Python scripts.

Recommended: Exclude File Operation MCPs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since agents have command-line access, file operations can use standard tools (``cat``, ``ls``, etc.):

.. code-block:: yaml

   backend:
     exclude_file_operation_mcps: true  # Use CLI for file operations

This reduces tool overhead and simplifies the environment.

.. important::

   **File Creation Tools Kept:** When ``exclude_file_operation_mcps: true`` is set, ``write_file`` and ``edit_file`` are **still available** as MCP tools. This is intentional:

   * **Avoids shell escaping nightmares** - Creating Python scripts with heredocs/echo leads to complex escaping issues
   * **Clean file creation** - Use ``write_file`` to create ``.py`` files, then execute via command-line
   * **Best of both worlds** - Write files via MCP, read/list via command-line

   Example of the problem this solves:

   .. code-block:: bash

      # Shell approach (FAILS with escaping issues):
      echo 'async def main():\n    result = await func("text with \"quotes\"")\n' > script.py

      # MCP approach (WORKS cleanly):
      mcp__filesystem__write_file(path="script.py", content="async def main():\n    ...")

   All other filesystem tools (read, list, search, etc.) are excluded and should use command-line equivalents.

Complete Example Config
------------------------

.. code-block:: yaml

   agents:
     - id: "research_agent"
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
         cwd: "research_workspace"

         # Code-based tools configuration
         enable_code_based_tools: true
         enable_mcp_command_line: true
         exclude_file_operation_mcps: true

         # Optional: Your custom tools
         custom_tools_path: "my_tools/"

         # MCP servers (converted to Python code)
         mcp_servers:
           - name: "weather"
             type: "stdio"
             command: "npx"
             args: ["-y", "@modelcontextprotocol/server-weather"]

           - name: "github"
             type: "stdio"
             command: "npx"
             args: ["-y", "@modelcontextprotocol/server-github"]
             env:
               GITHUB_TOKEN: "${GITHUB_TOKEN}"

       system_message: |
         You are a research assistant with access to weather and GitHub tools.
         Tools are available as Python modules in the workspace.

         Discover tools:
         - ls servers/
         - cat servers/weather/get_forecast.py

         Use tools:
         - from servers.weather import get_forecast
         - Create workflows in utils/ for complex tasks

   ui:
     display_type: "rich_terminal"

References
----------

This implementation is based on recent research and production systems:

* **CodeAct** (Apple Research) -
  https://machinelearning.apple.com/research/codeact

* **Cloudflare Code Mode** -
  https://blog.cloudflare.com/code-mode/

* **Anthropic MCP Code Execution** -
  https://www.anthropic.com/engineering/code-execution-with-mcp

See Also
--------

* :doc:`custom_tools` - Creating custom Python tools
* :doc:`background_tools` - Background lifecycle for long-running tool calls
* :doc:`mcp_integration` - MCP server setup and configuration
* :doc:`code_execution` - Command-line execution modes
* :doc:`../files/file_operations` - File operation configuration
