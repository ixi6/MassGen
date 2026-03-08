Architecture
============

MassGen's architecture is designed for scalability, flexibility, and extensibility.

System Overview
---------------

.. code-block:: text

   ┌─────────────────────────────────────────┐
   │           User Application              │
   └─────────────┬───────────────────────────┘
                 │
   ┌─────────────▼───────────────────────────┐
   │          Orchestrator Layer             │
   │  ┌─────────────┬──────────────────┐    │
   │  │  Strategy   │  Consensus       │    │
   │  │  Manager    │  Engine           │    │
   │  └─────────────┴──────────────────┘    │
   └─────────────┬───────────────────────────┘
                 │
   ┌─────────────▼───────────────────────────┐
   │           Agent Layer                   │
   │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
   │  │Agent1│ │Agent2│ │Agent3│ │AgentN│ │
   │  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ │
   └─────┼────────┼────────┼────────┼──────┘
         │        │        │        │
   ┌─────▼────────▼────────▼────────▼──────┐
   │         Backend Abstraction            │
   │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
   │  │OpenAI│ │Claude│ │Gemini│ │ Grok │ │
   │  └──────┘ └──────┘ └──────┘ └──────┘ │
   └─────────────────────────────────────────┘

Core Components
---------------

Orchestrator
~~~~~~~~~~~~

The orchestrator manages agent coordination:

* Task distribution
* Strategy execution
* Consensus building
* Result aggregation

Agent
~~~~~

Agents are autonomous units with:

* Unique identity and role
* Backend connection
* Tool access
* Memory management

Backend
~~~~~~~

Backends provide LLM capabilities:

* API abstraction
* Model management
* Response handling
* Error recovery

Design Principles
-----------------

1. **Modularity**: Components are loosely coupled
2. **Extensibility**: Easy to add new agents, backends, tools
3. **Scalability**: Supports horizontal scaling
4. **Resilience**: Fault-tolerant design
5. **Flexibility**: Multiple orchestration strategies

Coordination Protocol
---------------------

MassGen uses a coordination protocol built around redundancy and iterative refinement, with cycles of restarts and voting-based consensus to validate quality.

Vote-Based Consensus
~~~~~~~~~~~~~~~~~~~~

The coordination process follows these steps:

1. **Parallel Execution**: All agents receive the same query and work simultaneously
2. **Answer Observation**: Agents can see recent answers from other agents
3. **Decision Making**: Each agent chooses to either:

   - Provide a new/refined answer (``new_answer`` tool)
   - Vote for an existing answer they think is best (``vote`` tool)

4. **Dynamic Updates**: When an agent provides ``new_answer``:

   - Other agents receive update injection mid-work
   - Agents continue with preserved context (inject-and-continue)
   - All existing votes are cleared (new answer invalidates votes)

5. **Consensus Detection**: Coordination continues until all agents have voted
6. **Winner Selection**: The agent with the most votes is selected
7. **Final Presentation**: The winning agent delivers the final answer

**Key Features:**

* **Natural Convergence**: No forced consensus, agents naturally agree on best answer
* **Iterative Refinement**: Agents can refine their answers after seeing others' work
* **Workspace Sharing**: When agents answer, their workspace is snapshotted for others to review
* **Tie Resolution**: Deterministic tie-breaking based on answer order

Inject-and-Continue (Preempt-Not-Restart)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When an agent provides a ``new_answer`` while other agents are working, MassGen uses an **inject-and-continue** approach instead of restarting agents from scratch.

**Traditional Approach (Restart):**

.. code-block:: text

   Agent A: Working on solution... [deep in analysis]
   Agent B: Provides new_answer
            ↓
   Agent A: KILL stream → Clear context → Restart from zero
            ❌ Lost all partial work and thinking

**MassGen Approach (Inject-and-Continue):**

.. code-block:: text

   Agent A: Working on solution... [completes response]
   Agent B: Provides new_answer
            ↓
   Agent A: Receive UPDATE → Append to conversation → New API call
            ✅ Preserved conversation history
            ✅ Can now build on Agent B's answer

**How It Works:**

When Agent B provides a ``new_answer``, the orchestrator appends an UPDATE message to Agent A's
conversation history containing Agent B's answer. Agent A then makes a **new API call** with
this extended context. This preserves the conversation history but requires a fresh inference call.

.. note::

   **Future Enhancement**: True mid-stream injection within tool responses is planned, which would
   allow updates to be injected while an agent is actively streaming, preserving in-progress thinking.
   Currently, updates are only processed between API calls.

**Benefits:**

1. **Conversation Preservation**: Agents keep their full conversation history
2. **Collaboration**: Agents can synthesize and build on each other's work
3. **No Full Restart**: Agents don't lose their accumulated context

**Update Injection Points**:

Updates are injected at **safe points** during agent execution:

* Between iteration loops (after completing a response)
* When agent checks for new context
* Between API calls (not mid-stream)

**Race Condition**: If an agent is deep in its first response when a new answer arrives, it won't see the injection until completing that response. By then, it may already have full context from the orchestrator's normal flow. This is acceptable - the agent still gets all answers, just via different mechanism (full context on next spawn vs. injection mid-work).

Implementation: ``massgen/orchestrator.py:_inject_update_and_continue()``

Answer Labeling
~~~~~~~~~~~~~~~

Each answer gets a unique identifier: ``agent{N}.{attempt}``

* ``agent1.1`` = Agent 1's first answer
* ``agent2.1`` = Agent 2's first answer
* ``agent1.2`` = Agent 1's second answer (after restart)
* ``agent1.final`` = Agent 1's final answer (if winner)

This labeling system enables:

* Clear vote tracking
* Answer evolution visualization
* Transparent decision history

Implementation: ``massgen/orchestrator.py``

Workspace Management
--------------------

Each agent gets an isolated workspace for safe file operations.

Directory Structure
~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   .massgen/
   ├── workspaces/           # Agent working directories
   │   ├── agent1/          # Agent 1's isolated workspace
   │   └── agent2/          # Agent 2's isolated workspace
   ├── snapshots/           # Workspace snapshots for coordination
   │   ├── agent1_20250113_143022/  # Snapshot of agent1's work
   │   └── agent2_20250113_143025/  # Snapshot of agent2's work
   ├── temp_workspaces/     # Previous turn results for multi-turn
   │   ├── agent1_turn_1/   # Agent 1's turn 1 results
   │   └── agent2_turn_1/   # Agent 2's turn 1 results
   ├── sessions/            # Multi-turn conversation history
   │   └── session_20250113_143000/
   │       ├── turn_1/
   │       └── turn_2/
   └── massgen_logs/        # All logging output
       └── log_20250113_143000/

Snapshot System
~~~~~~~~~~~~~~~

When an agent provides an answer during coordination:

1. **Capture**: Their workspace is copied to ``snapshots/``
2. **Share**: Other agents receive read-only access to the snapshot
3. **Review**: Agents can examine files, code, and outputs
4. **Build**: Agents build on insights from other agents' work

This enables agents to:

* See concrete work, not just descriptions
* Catch errors in code or logic
* Build incrementally on each other's contributions
* Provide informed votes based on actual outputs

Implementation: ``massgen/filesystem_manager/``

Multi-Turn Conversations
-------------------------

MassGen supports interactive multi-turn conversations with full context preservation.

Session Management
~~~~~~~~~~~~~~~~~~

Each multi-turn session maintains:

* **Session ID**: Unique identifier (e.g., ``session_20250113_143000``)
* **Turn History**: Numbered turns (``turn_1``, ``turn_2``, ...)
* **Workspace Persistence**: Each turn's workspace is preserved
* **Context Paths**: Previous turns become read-only context for next turns

Turn Lifecycle
~~~~~~~~~~~~~~

1. **Turn Start**: Increment turn counter, create turn directory
2. **Context Loading**: Previous turn's workspace becomes read-only context
3. **Execution**: Agents work with fresh writeable workspace + previous context
4. **Persistence**: Winning agent's workspace is saved to turn directory
5. **Summary Update**: SESSION_SUMMARY.txt is updated with turn details

This allows agents to:

* Compare "what I changed" vs "what was originally there"
* Build incrementally across multiple turns
* Reference previous results explicitly
* Maintain project continuity

Implementation: ``massgen/cli.py`` (multi-turn mode)

MCP Integration
---------------

MassGen integrates Model Context Protocol (MCP) for external tool access.

Architecture
~~~~~~~~~~~~

.. code-block:: text

   Backend → MCP Client → MCP Server → External Tools
      ↓
   Tools List → Agent → Tool Calls → Tool Results

Supported Backends:

* **Claude**: Native MCP support via ``claude_messages`` API
* **Gemini**: MCP support via function calling
* **Others**: Via tool conversion layer

Planning Mode
~~~~~~~~~~~~~

Special coordination mode for MCP tools:

* **During Coordination**: Agents can *plan* tool usage without execution
* **After Consensus**: Winner executes tools in their final answer
* **Safety**: Prevents irreversible actions during collaboration

This is critical for:

* File operations (create, delete, modify)
* API calls with side effects
* Database operations
* External service integrations

Implementation: ``massgen/backend/gemini.py``, ``massgen/backend/claude.py``

Backend Abstraction
-------------------

All LLM interactions go through a unified backend interface.

Backend Interface
~~~~~~~~~~~~~~~~~

Each backend implements:

.. code-block:: python

   class Backend:
       async def chat(messages, stream=True):
           """Stream responses with tool calls"""

       async def get_available_tools():
           """Return tools for this backend"""

       def format_messages(messages):
           """Convert to backend-specific format"""

Supported Backends:

* **API-based**: OpenAI, Claude, Gemini, Grok, Azure OpenAI
* **Local**: LM Studio, vLLM, SGLang
* **External**: AG2 framework agents
* **Custom**: Claude Code CLI with filesystem access

Implementation: ``massgen/backend/``

File Permission System
----------------------

MassGen enforces granular file permissions for safe project integration.

Context Paths
~~~~~~~~~~~~~

Agents can access specific directories with permissions:

.. code-block:: yaml

   orchestrator:
     context_paths:
       - path: "/path/to/project"
         permission: "write"
         protected_paths:
           - ".git"
           - "node_modules"

Permission Types:

* ``read``: View files only
* ``write``: Read, create, modify, delete files (except protected)

Protected Paths:

* Immune from modification/deletion
* Relative to context path
* Supports files and directories

Safety Features:

* **Read-Before-Delete**: Agents must read files before deletion
* **Permission Validation**: All file operations are checked
* **Audit Trail**: All operations logged to massgen.log

Implementation: ``massgen/filesystem_manager/_path_permission_manager.py``

Code Organization
-----------------

.. code-block:: text

   massgen/
   ├── orchestrator.py           # Coordination engine
   ├── chat_agent.py             # Agent implementations
   ├── cli.py                    # Command-line interface
   ├── config_builder.py         # Interactive config wizard
   ├── agent_config.py           # Configuration models
   ├── backend/                  # LLM backend implementations
   │   ├── claude.py            # Anthropic Claude
   │   ├── gemini.py            # Google Gemini
   │   ├── response.py          # OpenAI
   │   ├── grok.py              # xAI Grok
   │   ├── claude_code.py       # Claude Code CLI
   │   ├── external.py          # External frameworks (AG2)
   │   └── ...
   ├── frontend/                 # UI components
   │   └── coordination_ui.py   # Terminal UI
   ├── filesystem_manager/       # File operations & permissions
   │   ├── _path_permission_manager.py
   │   ├── _workspace_tools_server.py
   │   └── ...
   ├── logger_config.py          # Logging configuration
   └── adapters/                 # External framework adapters
       └── ag2/                 # AG2 adapter

Key Modules:

* **orchestrator.py**: Vote tracking, consensus detection, workspace snapshots
* **chat_agent.py**: Agent lifecycle, message handling, tool execution
* **backend/**: LLM-specific implementations with unified interface
* **filesystem_manager/**: Permission system, workspace isolation
* **frontend/**: Real-time coordination display with Rich

Extension Points
----------------

Adding New Backends
~~~~~~~~~~~~~~~~~~~

1. Subclass ``Backend`` base class
2. Implement ``chat()`` and ``format_messages()``
3. Register in ``cli.py``'s ``create_backend()``
4. Add to ``AgentConfig`` factory methods

Example: ``massgen/backend/grok.py``

Adding MCP Servers
~~~~~~~~~~~~~~~~~~

1. Configure in YAML:

   .. code-block:: yaml

      backend:
        type: "claude"
        mcp_servers:
          - name: "weather"
            command: "npx"
            args: ["-y", "@modelcontextprotocol/server-weather"]

2. Servers auto-start when backend initializes
3. Tools automatically discovered and presented to agent

Example: All MCP configs in ``massgen/configs/tools/mcp/``

Adding External Frameworks
~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Create adapter in ``massgen/adapters/{framework}/``
2. Implement ``ExternalAgentAdapter`` interface
3. Register in ``adapters/__init__.py``
4. Agents work seamlessly with native MassGen agents

Example: ``massgen/adapters/ag2/``

Context Management
------------------

MassGen implements several strategies to manage LLM context windows efficiently.

Reactive Compression
~~~~~~~~~~~~~~~~~~~~

When the LLM provider returns a context length error, MassGen automatically:

1. Captures the streaming buffer content (tool calls, reasoning, partial work)
2. Generates a summary of completed work
3. Compresses older messages while preserving recent context
4. Retries the request with the compressed context

See :doc:`../user_guide/sessions/memory` for user-facing documentation.

Implementation: ``massgen/backend/_compression_utils.py``

Streaming Buffer
~~~~~~~~~~~~~~~~

The ``StreamingBufferMixin`` captures streamed content during API calls, enabling
compression recovery to preserve partial work when context limits are exceeded.

**How it works:**

1. As chunks stream from the API, content is accumulated in ``_streaming_buffer``
2. If a context length error occurs mid-stream, the buffer contains partial work
3. The buffer content is passed to compression, which summarizes it
4. The summary is injected as an assistant message for retry

**Buffer content flow:**

.. code-block:: text

   API Stream → _append_to_streaming_buffer() → _streaming_buffer accumulates
                                              ↓
                              Context error detected
                                              ↓
                              buffer_content passed to compress_messages_for_recovery()
                                              ↓
                              Summarized into: "[Tool execution results]\n{buffer}"
                                              ↓
                              Injected as assistant message in compressed result

**Backend Support:**

.. list-table:: Streaming Buffer Support by Backend
   :header-rows: 1
   :widths: 30 20 50

   * - Backend
     - Buffer Support
     - Notes
   * - ``ChatCompletionsBackend``
     - ✅ Yes
     - Base for OpenAI-compatible APIs
   * - ``ClaudeBackend``
     - ✅ Yes
     - Anthropic Messages API
   * - ``GeminiBackend``
     - ✅ Yes
     - Google Gemini SDK
   * - ``ResponseBackend``
     - ✅ Yes
     - OpenAI Responses API
   * - ``GrokBackend``
     - ✅ Yes
     - Inherits from ChatCompletionsBackend
   * - ``LMStudioBackend``
     - ✅ Yes
     - Inherits from ChatCompletionsBackend
   * - ``InferenceBackend``
     - ✅ Yes
     - Inherits from ChatCompletionsBackend
   * - ``AzureOpenAIBackend``
     - ❌ No
     - Extends LLMBackend directly
   * - ``ClaudeCodeBackend``
     - ❌ No
     - Streaming handled internally
   * - ``ExternalAgentBackend``
     - ❌ No
     - Wrapper for external agents

**Implementation:**

- ``massgen/backend/_streaming_buffer_mixin.py`` - Mixin class providing buffer methods
- Buffer methods: ``_clear_streaming_buffer()``, ``_append_to_streaming_buffer()``
- Buffer respects ``_compression_retry`` flag to avoid clearing during retry

**Adding buffer support to a backend:**

.. code-block:: python

   from ._streaming_buffer_mixin import StreamingBufferMixin

   class MyBackend(StreamingBufferMixin, CustomToolAndMCPBackend):
       # StreamingBufferMixin MUST come first in MRO
       pass

**Note:** The mixin must appear before other base classes in the inheritance list
to ensure proper method resolution order (MRO).

MCP Tool Result Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

MCP ``CallToolResult`` objects contain both structured and text representations.
MassGen extracts only the clean text content to minimize context usage:

.. code-block:: text

   Raw CallToolResult (sent to context):
   ❌ "meta=None content=[TextContent(type='text', text='file contents...')]
       structuredContent={'content': 'file contents...'}"  ← Duplicated, bloated

   Optimized extraction (sent to context):
   ✅ "file contents..."  ← Clean, minimal

This optimization typically reduces tool result size by 4-10x, significantly
extending how many tool calls can fit within the context window.

**Extraction Logic:**

1. Check if result has ``.content`` attribute (MCP CallToolResult)
2. Extract text from ``TextContent`` objects in the content list
3. Fall back to ``.text`` attribute or ``str(result)`` for other result types

Implementation: ``_extract_text_from_content()`` in each backend's
``_append_tool_result_message()`` method.

Large Tool Result Eviction
~~~~~~~~~~~~~~~~~~~~~~~~~~

Tool results exceeding a token threshold are automatically evicted to files,
preventing context window saturation. Inspired by `LangChain DeepAgents Harness
<https://docs.langchain.com/oss/python/deepagents/harness>`_.

**How it works:**

1. After tool execution, the result is checked against the token threshold
2. If exceeding 20,000 tokens, the result is written to a file in the agent's workspace
3. The result is replaced with a reference message containing:

   - Token and character counts
   - File path for retrieval
   - Character position for chunked reading
   - A 2,000 token preview of the content

**Example reference message:**

.. code-block:: text

   [Tool Result Evicted - Too Large for Context]

   The result from read_file was 50,000 tokens / 200,000 chars (limit: 20,000 tokens).
   Full result saved to: .tool_results/read_file_20241225_143052_a1b2c3d4.txt

   To read more: start at char 6,500, read in chunks.

   Preview (chars 0-6,500 of 200,000):
   {"data": [{"id": 1, "name": "Alice"...

Note: The preview character count varies based on content (approximately 2,000 tokens).

**Configuration:**

Currently uses hardcoded thresholds defined in constants:

- ``TOOL_RESULT_EVICTION_THRESHOLD_TOKENS = 20,000`` - Eviction trigger
- ``TOOL_RESULT_EVICTION_PREVIEW_TOKENS = 2,000`` - Preview size
- ``EVICTED_RESULTS_DIR = ".tool_results"`` - Storage directory

**Implementation files:**

- ``massgen/filesystem_manager/_constants.py`` - Threshold constants
- ``massgen/backend/base_with_custom_tool_and_mcp.py`` - Eviction logic:

  - ``_truncate_to_token_limit()`` - Binary search for token-based truncation
  - ``_maybe_evict_large_tool_result()`` - Main eviction logic
  - Integration in ``_execute_tool_with_logging()``

**Testing:** ``massgen/tests/test_tool_result_eviction.py``

Performance Considerations
--------------------------

* **Parallel Execution**: All agents run concurrently
* **Streaming**: All responses stream in real-time
* **Workspace Isolation**: Copy-on-write for efficiency
* **Async I/O**: All file operations are non-blocking
* **Token Management**: Per-backend rate limiting

See Also
--------

* :doc:`contributing` - How to contribute code
* :doc:`writing_configs` - Configuration authoring guide
* ``massgen/orchestrator.py`` - Core coordination logic
* ``massgen/backend/`` - Backend implementations
* ``massgen/filesystem_manager/`` - Permission system