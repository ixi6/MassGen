Core Concepts
=============

Understanding MassGen's core concepts is essential for using the system effectively.

What is MassGen?
-----------------

MassGen is a **multi-agent coordination system** that assigns tasks to multiple AI agents who work in parallel, share observations, vote for solutions, and converge on the best answer through natural consensus.

Think of it as a "parallel study group" for AI - agents learn from each other to produce better results than any single agent could achieve alone.

Configuration-Driven Architecture
----------------------------------

MassGen uses **YAML files** to configure everything, not Python code.

.. code-block:: yaml

   agents:
     - id: "researcher"
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
       system_message: "You are a researcher"

     - id: "analyst"
       backend:
         type: "openai"
         model: "gpt-5-nano"
       system_message: "You are an analyst"

Run via command line:

.. code-block:: bash

   massgen --config config.yaml "Your question"

This design makes MassGen:

* **Declarative** - Describe what you want, not how to do it
* **Version-controllable** - Config files in Git
* **Shareable** - Easy to share and reproduce setups
* **Language-agnostic** - No Python required for most users

.. seealso::
   :doc:`../quickstart/configuration` - Complete configuration guide with all options and examples

CLI-Based Execution
-------------------

MassGen is currently run via command line (a Python library API is planned for future releases):

**Quick single agent:**

.. code-block:: bash

   massgen --model claude-3-5-sonnet-latest "Question"

**Multi-agent with config:**

.. code-block:: bash

   massgen --config my_agents.yaml "Question"

**Interactive mode:**

.. code-block:: bash

   # Omit question for interactive chat
   massgen --config my_agents.yaml

See :doc:`../reference/cli` for complete CLI reference.

Execution Hierarchy
-------------------

Understanding MassGen's execution hierarchy helps navigate logs and debug issues.

.. code-block:: text

   Session (multi-turn conversation)
   └── Turn 1 (first user question)
   │   └── Attempt 1 (orchestration execution)
   │       ├── Round 1: Agent A processes → new_answer
   │       ├── Round 2: Agent B processes → new_answer
   │       ├── Round 3: Agent A processes → vote for B
   │       └── Round 4: Agent B processes → vote for self → CONSENSUS
   │
   └── Turn 2 (second user question)
       └── Attempt 1
           ├── Round 1: Agent A → new_answer
           └── Round 2: Agent B → vote → CONSENSUS

**Definitions:**

.. list-table::
   :header-rows: 1
   :widths: 15 50 35

   * - Term
     - Definition
     - Log Path
   * - **Session**
     - Multi-turn conversation. Spans multiple user interactions.
     - ``.massgen/sessions/``
   * - **Turn**
     - Single user question/task. Triggers full coordination.
     - ``log_TIMESTAMP/turn_N/``
   * - **Attempt**
     - One orchestration execution. Restarts create new attempts.
     - ``turn_N/attempt_N/``
   * - **Round**
     - Single agent LLM call cycle: context → streaming → output.
     - Recorded in ``llm_calls/``

**Key Insight:** Coordination ends when all agents vote (no ``new_answer`` calls). Each ``new_answer`` extends coordination; each ``vote`` moves toward consensus.

Multi-Agent Coordination
-------------------------

How Coordination Works
~~~~~~~~~~~~~~~~~~~~~~

MassGen's coordination follows a natural collaborative flow where agents observe each other's work and converge on the best solution:

**At each step, agents can:**

1. **See recent answers** - Agents view the most recent answers from other agents
2. **Decide their action** - Each agent chooses to either:

   * **Provide a new answer** if they have a better approach or refinement
   * **Vote for an existing answer** they believe is best

3. **Share context through workspace snapshots** (if file operations are enabled) - When agents provide answers, their workspace state is captured, allowing other agents to see their work

**Coordination completes when:**

* All agents have voted for solutions
* The agent with most votes becomes the final presenter

**Final presentation:**

* The winning agent delivers the coordinated final answer, using read/write permissions (if using filesystem operations and configured with context paths)

Coordination Flow Diagram
~~~~~~~~~~~~~~~~~~~~~~~~~~

Here's how agents asynchronously evaluate and respond during coordination:

.. code-block:: text

   ┌─────────────────────────────────────────────────────────────┐
   │              ASYNCHRONOUS COORDINATION LOOP                  │
   └─────────────────────────────────────────────────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
                ┌───▼──┐     ┌───▼──┐     ┌───▼──┐
                │Agent │     │Agent │     │Agent │
                │  A   │     │  B   │     │  C   │
                └───┬──┘     └───┬──┘     └───┬──┘
                    │            │            │
        ┌───────────▼────────────▼────────────▼───────────┐
        │     View ANONYMIZED Answers (Context)           │
        │     - ORIGINAL MESSAGE                          │
        │     - CURRENT ANSWERs (anonymized)          │
        └───────────┬────────────┬────────────┬───────────┘
                    │            │            │
        ┌───────────▼────────────▼────────────▼───────────┐
        │  "Does the best CURRENT ANSWER address the      │
        │   ORIGINAL MESSAGE well?"                       │
        └───────────┬────────────┬────────────┬───────────┘
                    │            │            │
            ┌───────▼──────┐     │     ┌──────▼───────┐
            │    YES       │     │     │     NO       │
            │              │     │     │              │
        ┌───▼──────────┐   │     │     │    ┌─────────▼──────────┐
        │Use `vote`    │   │     │     │    │Digest existing     │
        │tool          │   │     │     │    │answers, combine    │
        │              │   │     │     │    │strengths, address  │
        │              │   │     │     │    │weaknesses, then use│
        │              │   │     │     │    │`new_answer` tool   │
        └───┬──────────┘   │     │     │    └─────────┬──────────┘
            │              │     │     │              │
            │              │     │     │              │
            └──────────────┴─────┴─────┴──────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  All agents voted?       │
                    │  (No new_answer calls)   │
                    └────┬──────────────┬──────┘
                         │              │
                     YES │              │ NO
                         │              │
              ┌──────────▼───────┐      │
              │  Select Winner   │      │
              │  (Most votes)    │      │
              └──────────┬───────┘      │
                         │              │
              ┌──────────▼───────┐      │
              │ Final Presentation│     │
              │ (Winner delivers)│      │
              └───────────────────┘     │
                                        │
                             ┌──────────▼───────────────┐
                             │ Agent provided new_answer│
                             │ ↓                        │
                             │ INJECT update to others: │
                             │ ALL agents receive update│
                             │ and continue with new    │
                             │ answer in context        │
                             │ (loop back to top)       │
                             └──────────────────────────┘

**Key Insights:**

* **Asynchronous evaluation** - Agents evaluate continuously and independently (no synchronized rounds)
* **Anonymized answers** - Agents don't know who provided which answer, reducing bias
* **Actual agent prompt** - Agents evaluate "Does best CURRENT ANSWER address ORIGINAL MESSAGE well?"
* **Inject-and-continue** - When any agent uses ``new_answer``, other agents receive an update appended to their conversation and continue (preserving their conversation history, though a new API call is made). Agents that haven't produced their first answer yet are protected from interruption (see :ref:`first-answer-protection` below).
* **Natural consensus** - Coordination ends only when all agents vote (no ``new_answer`` calls)
* **Democratic selection** - Winner determined by peer voting

Streaming Architecture
~~~~~~~~~~~~~~~~~~~~~~~

Each agent :term:`round` involves streaming LLM responses with potential tool execution:

.. code-block:: text

   ┌─────────────────────────────────────────────────────────────────┐
   │                    SINGLE AGENT ROUND                           │
   └─────────────────────────────────────────────────────────────────┘

   ┌──────────────┐     ┌──────────────────────────────────────────┐
   │  1. CONTEXT  │────▶│  2. LLM API CALL (streaming)             │
   │              │     │                                          │
   │ • Messages   │     │  ┌────────────────────────────────────┐  │
   │ • Tools      │     │  │ Stream Chunks:                     │  │
   │ • Prev Ans   │     │  │   content → content → content →    │  │
   └──────────────┘     │  │   tool_calls → done                │  │
                        │  └────────────────────────────────────┘  │
                        └──────────────────┬───────────────────────┘
                                           │
                              ┌────────────▼────────────┐
                              │  3. TOOL EXECUTION?     │
                              │     (if tool_calls)     │
                              └────────────┬────────────┘
                                           │
                      ┌────────────────────┴────────────────────┐
                      │                                         │
               ┌──────▼──────┐                          ┌───────▼──────┐
               │  Yes: MCP   │                          │  No: Done    │
               │  or Custom  │                          │              │
               │  Tool Call  │                          │  Output:     │
               └──────┬──────┘                          │  new_answer  │
                      │                                 │  or vote     │
                      ▼                                 └──────────────┘
               ┌─────────────┐
               │ Execute &   │
               │ Add Result  │
               │ to Messages │
               └──────┬──────┘
                      │
                      ▼
               ┌─────────────┐
               │ RECURSE:    │
               │ New LLM     │──────▶ (back to step 2)
               │ Call        │
               └─────────────┘

**Streaming Flow:**

1. **Context Assembly** - Messages, tools, and previous answers prepared
2. **LLM Streaming** - Response chunks arrive: ``content``, ``tool_calls``, ``reasoning``, ``done``
3. **Tool Detection** - If ``tool_calls`` chunk received, execute tools
4. **Recursive Call** - Tool results added to messages, new LLM call made
5. **Completion** - When ``done`` received without tools, round complete

Context Management & Injection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each agent maintains an **AgentConversationBuffer** - a unified store that captures all streaming content and supports context injection from other agents.

**Why a Unified Buffer?**

During streaming, agents accumulate content, tool calls, reasoning, and tool results. When one agent provides a ``new_answer``, other agents need to receive that update mid-work. The buffer ensures:

* **Complete context** - All streaming content is captured and persisted
* **Working injection** - Updates from other agents are immediately visible
* **Single source of truth** - No fragmented storage locations

**Data Flow During Streaming:**

.. code-block:: text

   Backend yields chunks:
       │
       ├── content chunk ──────► buffer.add_content("I'll analyze...")
       │                              └── Accumulates in pending content
       │
       ├── reasoning chunk ────► buffer.add_reasoning("Let me think...")
       │                              └── Accumulates in pending reasoning
       │
       ├── tool_call chunk ────► buffer.add_tool_call("read_file", {path: "x"})
       │                              └── Added to pending tool calls
       │
       ├── tool_result chunk ──► buffer.add_tool_result("read_file", "call_1", "...")
       │                              └── Updates matching pending tool call
       │
       └── done chunk ─────────► buffer.flush_turn()
                                     │
                                     ├── Creates permanent entries from pending data
                                     └── Clears all pending accumulators

**Data Flow During Injection:**

When Agent A provides a ``new_answer``, other agents receive an injection:

.. code-block:: text

   Agent A provides new_answer
            │
            ▼
   Orchestrator detects new_answer, sets restart_pending[B] = True
            │
            ▼
   Agent B reaches safe point (between LLM calls)
            │
            ▼
   Orchestrator injects into Agent B's buffer:
       buffer_b.inject_update({"<anonymized>": "Here's my answer..."})
            │
            ├── Formats injection message with <NEW_ANSWERS> tags
            └── Creates INJECTION entry in buffer
            │
            ▼
   Agent B's next LLM call:
       messages = buffer_b.to_messages()  ← Includes injection entry
            │
            ▼
       agent.chat(messages)  ← Agent sees the injected update!

**Key Insight:** The buffer ensures that when Agent B receives an injection, it sees:

1. **Original context** - The initial user question and system messages
2. **Own previous work** - All content, tool calls, and results from its streaming
3. **New injection** - The update from Agent A, formatted as a new user message

This allows agents to seamlessly continue their work with full awareness of what other agents have discovered.

.. _first-answer-protection:

First-Answer Protection
~~~~~~~~~~~~~~~~~~~~~~~~

When an agent submits a ``new_answer``, MassGen signals all other agents to restart
or receive a mid-stream injection with the new context. However, agents that have not
yet produced their **first answer** are protected from these interruptions.

**Why?** Independent first answers are critical for diversity. If Agent A finishes
quickly and Agent B is immediately restarted before completing its first round,
Agent B never contributes an independent perspective -- it only ever sees Agent A's
work. This undermines the parallel exploration that makes multi-agent coordination
valuable.

**How it works:**

1. When any agent submits ``new_answer``, all agents are flagged with ``restart_pending``
2. Before acting on the flag, MassGen checks whether the target agent has produced
   at least one answer
3. If the agent has **no answer yet**, the flag is cleared and the agent continues
   working undisturbed
4. If the agent **already has an answer**, the restart or injection proceeds normally

This guard applies to all injection paths: full restarts, mid-stream hook injection,
and no-hook enforcement fallbacks. It does **not** apply to fairness gate restarts,
which correctly prevent agents from voting before they have sufficient context.

.. note::
   The ``restart_pending`` flag will be re-set if additional answers arrive while
   the agent is still working on its first round. The protection only defers the
   action -- it does not permanently suppress updates.

What Agents See
~~~~~~~~~~~~~~~

**Answer Context:**

Each agent sees the most recent answers from other agents **anonymously**. Answers are presented without attribution to reduce bias.

**Key Points:**

* **Anonymized evaluation** - Agents don't know which agent provided which answer
* **Focus on content** - Decisions based on answer quality, not agent identity
* **Bias reduction** - Prevents agents from favoring certain models or deferring to "authority"
* **Original message** - All agents always see the initial user query
* **Best current answer** - Agents evaluate if the best available answer is sufficient

This anonymous evaluation lets agents:

* Compare different approaches objectively
* Build on good insights regardless of source
* Catch potential errors without bias
* Decide whether to vote or provide a better answer based purely on merit

.. note::
   **Workspace Naming**: Always use ``cwd: "workspace"`` in your configs rather than numbered names like ``workspace1`` or ``workspace2``. MassGen automatically adds unique random suffixes per agent at runtime (e.g., ``workspace_f7a3b2c1``). This prevents agents from inferring their identity from workspace paths, which would undermine the anonymous voting design.

**Workspace Snapshots (for file operations):**

When an agent with filesystem capabilities provides an answer:

* Their workspace is saved as a snapshot
* Other agents can see this snapshot in their temporary workspace
* This enables code review, file analysis, and iterative refinement

Example: If Agent A writes code and provides answer "agent_a.1", Agent B can review that code in ``.massgen/temp_workspaces/agent_a/`` before deciding to vote or provide improvements.

Voting Mechanism
~~~~~~~~~~~~~~~~

:term:`Agents<Agent>` participate in democratic decision-making by evaluating solutions and voting for the best answer:

**Voting Process:**

1. Each agent reviews answers from other agents
2. Agent decides: "Is there a better answer than mine?"
3. If YES → Vote for the better answer
4. If NO → Continue with their own answer or refine it

**Natural Consensus:**

The system reaches :term:`consensus` when all agents have voted. No forced agreement - agents vote for what they genuinely believe is best based on their evaluation criteria.

**Example Scenario:**

* **Agent A** (Researcher) - Provides detailed research → Votes for Agent C's synthesis
* **Agent B** (Analyst) - Provides data analysis → Votes for Agent C's synthesis
* **Agent C** (Synthesizer) - Combines insights → Votes for self (believes synthesis is best)

**Result:** Agent C wins with 3 votes (including self-vote) and presents the final answer.

Benefits of Multi-Agent Approach
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Diverse Perspectives** - Different models, different insights
* **Error Correction** - Agents catch each other's mistakes
* **Collaborative Refinement** - Ideas build on each other
* **Quality Convergence** - Natural selection of best solutions
* **Robustness** - System works even if some agents fail

Coordination Termination
~~~~~~~~~~~~~~~~~~~~~~~~~

Coordination ends when one of these conditions is met:

**Normal Completion:**

* ✅ **All agents have voted** - Consensus reached naturally
* ✅ **Winner selected** - Agent with most votes presents final answer

**Timeout:**

* ⏰ **Orchestrator timeout reached** (default: 30 minutes)
* System saves current state and terminates gracefully
* Partial results preserved

**Typical Duration:**

* Simple tasks: 1-5 minutes (2-3 :term:`rounds<Round>` total across all agents)
* Standard tasks: 5-15 minutes (3-5 rounds)
* Complex tasks: 15-30 minutes (5-10 rounds)

**Configuration:**

.. code-block:: yaml

   timeout_settings:
     orchestrator_timeout_seconds: 1800  # 30 minutes (default)

**CLI Override:**

.. code-block:: bash

   massgen --orchestrator-timeout 600 --config config.yaml

See :doc:`../reference/timeouts` for complete timeout documentation.

Agents & Backends
-----------------

Agent Definition
~~~~~~~~~~~~~~~~

Each :term:`agent` has:

* **ID**: Unique identifier
* **Backend**: :term:`LLM provider<Backend>` (Claude, Gemini, GPT, etc.)
* **Model**: Specific model version
* **System Message**: Role and instructions (:term:`system prompt<System Message>`)
* **Tools**: Optional :term:`MCP servers<MCP Server>` or native capabilities

Example:

.. code-block:: yaml

   agents:
     - id: "code_expert"
       backend:
         type: "claude_code"
         model: "sonnet"
         cwd: "workspace"
       system_message: "You are a coding expert with file operations"

Backend Types
~~~~~~~~~~~~~

MassGen supports multiple :term:`backend` providers:

* **API-based**: Claude, Gemini, GPT, Grok, Azure OpenAI, Z AI
* **Local**: LM Studio, vLLM, SGLang
* **External Frameworks**: AG2

Each backend type has different capabilities. See :doc:`../reference/supported_models` for details.

Workspace Isolation
-------------------

Each :term:`agent` gets an isolated :term:`workspace` for file operations, preventing interference during :term:`coordination phase`.

**What is a Workspace?**

A workspace is an agent's private directory where it can:

* Read, write, and edit files freely
* Execute code and scripts
* Create directory structures
* Perform file operations without affecting other agents

All workspaces are stored under ``.massgen/workspaces/`` in your project directory.

**Example:**

.. code-block:: yaml

   agents:
     - id: "writer"
       backend:
         type: "claude_code"
         cwd: "writer_workspace"    # Isolated workspace: .massgen/workspaces/writer_workspace/

     - id: "reviewer"
       backend:
         type: "gemini"
         cwd: "reviewer_workspace"  # Separate workspace: .massgen/workspaces/reviewer_workspace/

**Benefits of Isolation:**

* **No conflicts** - Agents can't accidentally overwrite each other's files
* **Parallel work** - Multiple agents modify files simultaneously
* **Clean state** - Each agent starts with a fresh workspace
* **Workspace sharing** - Agents can review each other's workspaces via :term:`snapshots<Snapshot>`

.. seealso::
   :doc:`files/file_operations` - Complete workspace management guide including directory structure, snapshots, and safety features

MCP Tool Integration
--------------------

MassGen integrates tools via :term:`Model Context Protocol (MCP)<MCP (Model Context Protocol)>`, enabling access to web search, weather, :term:`file operations<File Operation>`, and many other external services.

**Example:**

.. code-block:: yaml

   backend:
     type: "gemini"
     model: "gemini-2.5-flash"
     mcp_servers:
       - name: "search"
         type: "stdio"
         command: "npx"
         args: ["-y", "@modelcontextprotocol/server-brave-search"]

.. seealso::
   :doc:`tools/mcp_integration` - Complete MCP guide including common servers, tool filtering, planning mode, and security considerations

Project Integration
-------------------

Work directly with your existing codebase using :term:`context paths<Context Path>` with granular read/write permissions.

**What is a Context Path?**

A context path is a shared directory that agents can access during collaboration. Unlike isolated :term:`workspaces<Workspace>`, context paths allow agents to:

* **Read** your existing project files for analysis
* **Write** to your project (only the :term:`final agent` during presentation)
* **Reference** code, documentation, or data from your real project

**Key Features:**

* **Permission control** - Specify ``read`` or ``write`` access per path
* **Coordination safety** - All paths are read-only during coordination
* **Final agent writes** - Only the winning agent can write during final presentation
* **Protected paths** - Mark specific files as read-only even within writable paths

**Example:**

.. code-block:: yaml

   orchestrator:
     context_paths:
       - path: "/Users/me/project/src"
         permission: "read"       # All agents can analyze code
       - path: "/Users/me/project/docs"
         permission: "write"      # Final agent can update docs
         protected_paths:
           - "README.md"          # Keep README read-only

All MassGen state organized under ``.massgen/`` directory in your project root.

.. seealso::
   * :doc:`files/project_integration` - Complete project integration guide
   * :doc:`files/protected_paths` - Protect specific files within writable paths
   * :doc:`files/file_operations` - File operation safety features

Interactive Multi-Turn Mode
----------------------------

Start MassGen without a question for interactive chat with context preservation across turns.

.. code-block:: bash

   # Single agent interactive
   massgen --model gemini-2.5-flash

   # Multi-agent interactive
   massgen --config my_agents.yaml

**Key Features:**

* **Context preservation** - :term:`Sessions<Session>` are automatically saved and restored
* **Multi-turn coordination** - Full coordination process runs for each turn
* **Workspace persistence** - File operations persist across turns
* **Tool integration** - :term:`MCP tools<MCP Server>` work seamlessly across turns
* **Session management** - Resume previous conversations or start fresh

**Tool Running in Multi-Turn:**

When using MCP tools or file operations in :term:`multi-turn mode`:

* Tools execute during each turn's coordination
* Workspace state is preserved in ``.massgen/sessions/``
* Subsequent turns can access previous turn's files and data
* Planning mode can be enabled to prevent premature tool execution

**Example Session:**

.. code-block:: bash

   Turn 1: "Create a website about Python"
   # Agents coordinate, winner creates files in workspace
   # Workspace saved to .massgen/sessions/session_abc123/

   Turn 2: "Add a dark mode toggle"
   # Agents see previous workspace, coordinate on improvements
   # Winner modifies existing files

.. seealso::
   * :doc:`sessions/multi_turn_mode` - Complete interactive mode guide including commands, session management, and debugging
   * :doc:`tools/mcp_integration` - Using MCP tools in multi-turn sessions
   * :doc:`advanced/planning_mode` - Prevent premature tool execution during coordination

External Framework Integration
-------------------------------

AG2 Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Integrate :term:`AG2` framework as a custom tool:

.. code-block:: yaml

   agents:
     - id: "ag2_assistant"
       backend:
         type: "openai"
         model: "gpt-4o"
         custom_tools:
           - name: ["ag2_lesson_planner"]
             category: "education"
             path: "massgen/tool/_extraframework_agents/ag2_lesson_planner_tool.py"
             function: ["ag2_lesson_planner"]
       system_message: |
         You have access to an AG2-powered tool that uses
         nested chats and group collaboration.

AG2's multi-agent orchestration patterns are wrapped as tools that MassGen agents can invoke.

See :doc:`integration/general_interoperability` for details.

File Operation Safety
---------------------

Read-Before-Delete Enforcement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

MassGen prevents accidental file deletion:

* Agents must read a file before deleting it
* Exception: Agent-created files can be deleted
* Clear error messages when operations blocked

Directory Validation
~~~~~~~~~~~~~~~~~~~~

* All paths validated at startup
* Context paths must be directories, not files
* Absolute paths required

Permissions
~~~~~~~~~~~

* **During coordination**: All context paths are READ-ONLY
* **Final presentation**: Winning agent gets configured permission (read/write)

See :doc:`files/file_operations` for safety features.

System Architecture
-------------------

Execution Flow
~~~~~~~~~~~~~~

1. **Load Configuration**

   Parse :term:`YAML configuration`, validate paths, initialize :term:`agents<Agent>`

2. **Coordination**

   * Agents work in parallel, each seeing recent answers from others
   * Each agent decides: provide new answer or vote for existing answer
   * When agent provides answer, :term:`workspace` :term:`snapshot` is captured
   * Other agents see snapshots in their :term:`temporary workspace`
   * Continues until all agents have voted

3. **Winner Selection**

   Agent with most votes is selected as :term:`final agent`

4. **Final Presentation**

   * Winning agent delivers the coordinated final answer
   * If using :term:`context paths<Context Path>` with write permission, winning agent can update project files

5. **Output**

   Results displayed, logged, and workspace snapshots saved

Real-Time Visualization
~~~~~~~~~~~~~~~~~~~~~~~

MassGen provides rich terminal UI showing:

* Agent coordination table
* Voting progress
* Consensus detection
* Streaming responses
* Phase transitions

Disable with ``--no-display`` for simple text output.

State Management & .massgen Directory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

MassGen organizes all working files under the :term:`.massgen Directory` in your project root. This keeps MassGen state separate from your project files.

**Directory Structure:**

.. code-block:: text

   .massgen/
   ├── workspaces/              # Agent workspaces
   │   ├── agent1_workspace/    # Agent 1's isolated workspace
   │   └── agent2_workspace/    # Agent 2's isolated workspace
   ├── snapshots/               # Workspace snapshots for sharing
   │   └── agent1_snapshot_1/   # Agent 1's snapshot from coordination round 1
   ├── temp_workspaces/         # Temporary workspaces for viewing others' work
   │   └── agent1/              # Agent 2 can see Agent 1's work here
   ├── sessions/                # Multi-turn session history
   │   └── session_abc123/      # Saved session state
   └── logs/                    # Execution logs

**Key Features:**

* **Workspace isolation** - Each agent has private workspace under ``workspaces/``
* **Snapshot sharing** - Agents share work via ``snapshots/`` during coordination
* **Session persistence** - Multi-turn conversations saved in ``sessions/``
* **Clean separation** - All MassGen files kept separate from your project
* **Git-friendly** - Add ``.massgen/`` to ``.gitignore`` to exclude from version control

**How State Persists:**

1. **During coordination**: Agent workspaces and snapshots are created/updated
2. **Between turns**: Session state saved to ``sessions/`` directory
3. **On restart**: Sessions can be resumed from saved state
4. **Final presentation**: Winner's workspace contains the final output

See :doc:`files/project_integration` for using ``.massgen`` with your existing codebase.

Common Patterns
---------------

Research Tasks
~~~~~~~~~~~~~~

.. code-block:: yaml

   agents:
     - id: "gemini"  # Fast web search
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
     - id: "gpt5"   # Deep analysis
       backend:
         type: "openai"
         model: "gpt-5-nano"

Coding Tasks
~~~~~~~~~~~~

.. code-block:: yaml

   agents:
     - id: "coder"  # Code execution
       backend:
         type: "claude_code"
         cwd: "workspace"
     - id: "reviewer"  # Code review
       backend:
         type: "gemini"

Hybrid Teams
~~~~~~~~~~~~

.. code-block:: yaml

   agents:
     - id: "ag2_executor"  # AG2 framework tool
       backend:
         custom_tools:
           - name: ["ag2_lesson_planner"]
             # ... AG2 tool config
         type: "openai"
         # ... backend config
     - id: "claude_analyst"  # File operations
       backend:
         type: "claude_code"
         # ... MCP config
     - id: "gemini_researcher"  # Web search
       backend:
         type: "gemini"

Best Practices
--------------

1. **Start Simple** - Begin with 2-3 agents, add more as needed
2. **Diverse Models** - Mix different providers for varied perspectives
3. **Clear Roles** - Give each agent specific system messages
4. **Use MCP** - Leverage tools for enhanced capabilities
5. **Enable Planning Mode** - For tasks with irreversible actions
6. **Context Paths** - Work with existing projects safely
7. **Interactive Mode** - For iterative development

Next Steps
----------

* :doc:`../quickstart/running-massgen` - Practical examples
* :doc:`../reference/yaml_schema` - Complete configuration reference
* :doc:`tools/mcp_integration` - Add tools to agents
* :doc:`sessions/multi_turn_mode` - Interactive conversations
* :doc:`files/project_integration` - Work with your codebase
* :doc:`integration/general_interoperability` - External framework integration
