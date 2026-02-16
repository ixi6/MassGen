Subagents
=========

Subagents enable agents to spawn independent child processes of a MassGen orchestrator for parallel task execution. Each subagent runs in its own isolated workspace, allowing complex workflows to be broken into concurrent, independent pieces.

Quick Start
-----------

**Enable subagents and run a parallel task:**

.. code-block:: bash

   massgen \
     --config @massgen/configs/features/subagent_demo.yaml \
     "Build a web app with frontend, backend, and documentation"

Here, the agent can spawn subagents to work on frontend, backend, and docs simultaneously.

*NOTE: Currently, you may want to mention subagents in the prompt to ensure the agent uses them effectively.*

What are Subagents?
-------------------

Subagents are independent MassGen processes spawned by a parent agent to handle parallelizable work:

.. code-block:: text

   Parent Agent
   ├── spawn_subagents([
   │     {task: "Build frontend", subagent_id: "frontend"},
   │     {task: "Build backend", subagent_id: "backend"},
   │     {task: "Write docs", subagent_id: "docs"}
   │   ])
   │
   ├─→ Subagent: frontend (isolated workspace)
   ├─→ Subagent: backend (isolated workspace)
   └─→ Subagent: docs (isolated workspace)

   ← All complete → Parent continues with results

Key characteristics:

* **Process isolation**: Each subagent is a separate MassGen subprocess, meaning it can use as little as one agent but up to multiple agents, all with MassGen's full capabilities.
* **Independent workspaces**: No interference between subagents
* **Parallel execution**: All subagents run concurrently
* **Automatic inheritance**: Subagents use the same model/backend as parent by default
* **Result aggregation**: Parent receives structured results with workspace paths

When to Use Subagents
---------------------

Use subagents when you have:

* **Independent parallel tasks**: Research topic A while researching topic B
* **Large deliverables**: Break a website into frontend, backend, assets
* **Context isolation**: Keep each task's files separate and organized
* **Time-consuming work**: Run multiple long tasks simultaneously

Do NOT use subagents for:

* **Sequential dependencies**: Task B needs output from Task A
* **Simple tasks**: Overhead isn't worth it for quick operations
* **Shared state requirements**: Tasks that need to coordinate in real-time

Configuration
-------------

Basic Configuration
~~~~~~~~~~~~~~~~~~~

Enable subagents in your YAML config:

.. code-block:: yaml

   orchestrator:
     coordination:
       enable_subagents: true
       subagent_default_timeout: 300  # 5 minutes per subagent (default)
       subagent_min_timeout: 60       # Minimum 1 minute (prevents too-short timeouts)
       subagent_max_timeout: 600      # Maximum 10 minutes (prevents runaway subagents)
       subagent_max_concurrent: 3     # Max 3 subagents at once

       # Optional: per-round timeouts for subagents (inherits parent if omitted)
       subagent_round_timeouts:
         initial_round_timeout_seconds: 600
         subsequent_round_timeout_seconds: 300
         round_timeout_grace_seconds: 120

.. note::

   Timeouts are clamped to the ``[subagent_min_timeout, subagent_max_timeout]`` range. This prevents models from accidentally setting unreasonably short or long timeouts.

Full Example
~~~~~~~~~~~~

.. code-block:: yaml

   agents:
     - id: "orchestrator_agent"
       backend:
         type: "openai"
         model: "gpt-4o"
         cwd: "workspace"
         enable_mcp_command_line: true
       system_message: |
         You are a task orchestrator. For complex tasks with independent
         parts, use spawn_subagents to parallelize the work.

   orchestrator:
     coordination:
       enable_subagents: true
       subagent_default_timeout: 300
       subagent_max_concurrent: 3
       enable_agent_task_planning: true  # Recommended for complex orchestration

   ui:
     display_type: "rich_terminal"
     logging_enabled: true

Custom Subagent Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, subagents inherit all parent agent configurations. To customize:

.. code-block:: yaml

   orchestrator:
     coordination:
       enable_subagents: true
       subagent_orchestrator:
         enabled: true
         agents:
           - id: "subagent_worker"
             backend:
               type: "openai"
               model: "gpt-5-mini"  # Use cheaper model for subagents
           - id: "subagent_worker_2"
             backend:
               type: "gemini"
               model: "gemini-3-flash-preview"

How Agents Use Subagents
------------------------

When subagents are enabled, agents have access to the ``spawn_subagents`` tool:

.. code-block:: json

   {
     "tool": "spawn_subagents",
     "arguments": {
       "tasks": [
         {
           "task": "Research Bob Dylan's biography and write to bio.md",
           "subagent_id": "biography"
         },
         {
           "task": "Create discography table in discography.md",
           "subagent_id": "discography"
         },
         {
           "task": "List 20 famous songs with years in songs.md",
           "subagent_id": "songs"
         }
       ],
      "refine": true
    }
  }

Critical Rules for Calling Subagent Tool
~~~~~~~~~~~~~~

1. **Tasks run in PARALLEL**: All tasks start simultaneously. Do NOT create tasks where one depends on another's output.

2. **Context is REQUIRED**: Subagents need project context to understand their work.

3. **Maximum tasks per call**: Limited by ``subagent_max_concurrent`` (default 3).

4. **No nesting**: Subagents cannot spawn their own subagents.

5. **Read-only context files**: Use ``context_files`` to share files, but subagents can only read them.
6. **Refine mode**: Use ``refine: false`` to return the first answer without multi-round refinement.

Result Structure
~~~~~~~~~~~~~~~~

The ``spawn_subagents`` tool returns:

.. code-block:: json

   {
     "success": true,
     "results": [
       {
         "subagent_id": "biography",
         "status": "completed",
         "success": true,
         "answer": "Created bio.md with comprehensive biography...",
         "workspace": "/path/to/subagents/biography/workspace",
         "execution_time_seconds": 45.2,
         "token_usage": {"input_tokens": 5000, "output_tokens": 2000}
       },
       {
         "subagent_id": "discography",
         "status": "completed",
         "success": true,
         "answer": "Created discography.md with album table...",
         "workspace": "/path/to/subagents/discography/workspace",
         "execution_time_seconds": 38.7
       }
     ],
     "summary": {
       "total": 3,
       "completed": 3,
       "failed": 0,
       "timeout": 0
     }
   }

Refinement Control
~~~~~~~~~~~~~~~~~~

Use ``refine: false`` to disable multi-round refinement for faster, single-pass answers:

.. code-block:: json

   {
     "tool": "spawn_subagents",
     "arguments": {
       "tasks": [
         {"task": "Summarize the repo structure in README.md", "subagent_id": "summary"}
       ],
       "refine": false
     }
   }

Status Values
~~~~~~~~~~~~~

Subagents can return several status values, each indicating a different outcome:

.. list-table::
   :header-rows: 1
   :widths: 25 10 65

   * - Status
     - success
     - Description
   * - ``completed``
     - ``true``
     - Normal completion. Use the answer directly.
   * - ``completed_but_timeout``
     - ``true``
     - **Timed out but full answer recovered.** The subagent finished its work before being interrupted. Use the answer normally.
   * - ``partial``
     - ``false``
     - Timed out with partial work. Some work was done but no final answer was selected. Check the ``workspace`` for useful files.
   * - ``timeout``
     - ``false``
     - Timed out with no recoverable work. Check the ``workspace`` anyway for any partial files.
   * - ``error``
     - ``false``
     - An exception occurred. Check the ``error`` field for details.

.. note::

   The ``completed_but_timeout`` status indicates the subagent completed its task successfully—it just took longer than the configured timeout. The answer is complete and should be used normally. This is a success case with ``success: true``.

Sharing Files with Subagents
----------------------------

Pass files to subagents using ``context_files``:

.. code-block:: json

   {
     "tasks": [
       {
         "task": "Refactor the utils module",
         "subagent_id": "refactor",
         "context_files": [
           "/path/to/project/utils.py",
           "/path/to/project/config.py"
         ]
       }
     ],
   }

.. warning::

   Context files are **read-only**. Subagents cannot modify files passed via ``context_files``. If you need the parent to use subagent output, copy files from the subagent's workspace after completion.

Handling Timeouts and Failures
------------------------------

MassGen automatically attempts to recover work from timed-out subagents. When a subagent times out, the system checks the subagent's internal state to recover any completed work, answers, and cost metrics.

Timeout Recovery Behavior
~~~~~~~~~~~~~~~~~~~~~~~~~

When a subagent times out:

1. The system reads the subagent's internal ``status.json`` to check progress
2. If a complete answer was produced (the subagent finished but the timeout fired during cleanup), the answer and costs are recovered
3. The status is set to ``completed_but_timeout`` (success=true) if recovery succeeded
4. If partial work exists but no final answer, status is ``partial``
5. If no recoverable work exists, status is ``timeout``

**Example with recovery:**

.. code-block:: json

   {
     "subagent_id": "research",
     "status": "completed_but_timeout",
     "success": true,
     "answer": "Research completed. Created movies.md with...",
     "completion_percentage": 100,
     "token_usage": {"input_tokens": 50000, "output_tokens": 3000, "estimated_cost": 0.05}
   }

The ``completion_percentage`` field indicates progress (0-100) based on how many agents
have submitted answers and cast votes. With N agents, each answer contributes ~(50/N)%
and each vote contributes ~(50/N)%. Approximate phase milestones:

* **0%**: Just started
* **~50%**: All initial answers submitted, waiting for voting
* **100%**: Task completed (may still timeout during final presentation)

Handling Different Status Values
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**For** ``completed_but_timeout`` **(success=true):**

Use the answer normally—the subagent completed its work successfully.

**For** ``partial`` **(success=false):**

.. code-block:: text

   The subagent did work but didn't reach a final answer.

   1. Check the workspace path for created files
   2. Review completion_percentage to understand progress
   3. Either use partial files or retry with a simpler task

**For** ``timeout`` **(success=false):**

.. code-block:: text

   The subagent made no recoverable progress.

   1. Check the workspace anyway for any files
   2. Consider if the task was too complex
   3. Break into smaller subtasks or increase timeout

**For** ``error`` **(success=false):**

.. code-block:: text

   An exception occurred during execution.

   1. Read the error message for details
   2. Check if it's recoverable (missing file, permission issue)
   3. Fix the issue and retry

Example: Mixed Results Handling
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When spawn_subagents returns mixed results:

.. code-block:: json

   {
     "success": false,
     "results": [
       {
         "subagent_id": "research",
         "status": "completed",
         "answer": "Research findings...",
         "workspace": "/path/to/subagents/research/workspace",
         "execution_time_seconds": 45.2,
         "token_usage": {"input_tokens": 5000, "output_tokens": 1200}
       },
       {
         "subagent_id": "analysis",
         "status": "completed_but_timeout",
         "answer": "Analysis results...",
         "workspace": "/path/to/subagents/analysis/workspace",
         "execution_time_seconds": 300.0,
         "completion_percentage": 100,
         "token_usage": {"input_tokens": 8000, "output_tokens": 2000}
       },
       {
         "subagent_id": "synthesis",
         "status": "timeout",
         "answer": null,
         "workspace": "/path/to/subagents/synthesis/workspace",
         "execution_time_seconds": 300.0,
         "completion_percentage": 45
       }
     ],
     "summary": {"total": 3, "completed": 2, "timeout": 1}
   }

The parent agent should:

1. Use the answers from ``research`` and ``analysis`` (both have valid answers)
2. Check ``synthesis``'s workspace for any partial files
3. Either complete the synthesis work itself or retry with a longer timeout

Logging and Debugging
---------------------

Directory Structure
~~~~~~~~~~~~~~~~~~~

Subagents create two directory structures:

**1. Log Directory (persisted):**

.. code-block:: text

   .massgen/massgen_logs/log_YYYYMMDD_HHMMSS/
   └── turn_1/
       └── attempt_1/
           ├── subagents/
           │   └── biography/
           │       ├── conversation.jsonl       # Subagent conversation history
           │       ├── workspace/               # Copy/symlink of runtime workspace
           │       └── full_logs/
           │           ├── status.json          # ◄ Single source of truth (Orchestrator writes)
           │           ├── biography_agent_1/
           │           │   └── 20260102_103045/
           │           │       ├── answer.txt   # Agent's answer snapshot
           │           │       └── workspace/   # Agent's workspace snapshot
           │           └── biography_agent_2/
           │               └── ...
           ├── metrics_summary.json             # Includes aggregated subagent costs
           └── status.json

**2. Runtime Workspace (may be cleaned up):**

.. code-block:: text

   .massgen/workspaces/workspace1_{hash}/
   └── subagents/
       └── biography/
           └── workspace/
               ├── agent_1_{hash}/     # Agent 1's working directory
               ├── agent_2_{hash}/     # Agent 2's working directory
               ├── snapshots/          # Answer snapshots
               └── temp/               # Temporary files

The ``full_logs/status.json`` is the single source of truth for subagent status. It's written by the subagent's Orchestrator and contains detailed coordination state including costs, votes, and historical workspaces.

Status File
~~~~~~~~~~~

The ``full_logs/status.json`` contains rich information:

.. code-block:: json

   {
     "meta": {
       "elapsed_seconds": 192.5,
       "start_time": 1767419307.4
     },
     "costs": {
       "total_input_tokens": 50000,
       "total_output_tokens": 3000,
       "total_estimated_cost": 0.05
     },
     "coordination": {
       "phase": "presentation",
       "completion_percentage": 100
     },
     "agents": {
       "biography_agent_1": {"status": "answered", "token_usage": {...}},
       "biography_agent_2": {"status": "answered", "token_usage": {...}}
     },
     "results": {
       "winner": "biography_agent_1",
       "votes": {"agent1.1": 2}
     },
     "historical_workspaces": [
       {"agentId": "biography_agent_1", "answerLabel": "agent1.1", "timestamp": "20260102_103045", ...}
     ]
   }

When you query status via ``check_subagent_status``, this is transformed into a simplified view:

.. code-block:: json

   {
     "subagent_id": "biography",
     "status": "running",
     "phase": "enforcement",
     "completion_percentage": 75,
     "task": "Write a biography of Bob Dylan...",
     "workspace": "/path/to/subagents/biography/workspace",
     "started_at": "2026-01-02T10:30:45",
     "elapsed_seconds": 145.3,
     "token_usage": {"input_tokens": 50000, "output_tokens": 3000, "estimated_cost": 0.05}
   }

Cost Tracking
-------------

Subagent costs are automatically aggregated in the parent's metrics:

.. code-block:: json

   {
     "totals": {
       "estimated_cost": 0.083,
       "agent_cost": 0.046,
       "subagent_cost": 0.037
     },
     "subagents": {
       "total_subagents": 3,
       "total_input_tokens": 15000,
       "total_output_tokens": 6000,
       "total_estimated_cost": 0.037
     }
   }

Async Subagent Execution
------------------------

By default, ``spawn_subagents`` blocks until all subagents complete. For long-running tasks,
you can use async mode to spawn subagents in the background while the parent agent continues working.

Enabling Async Mode
~~~~~~~~~~~~~~~~~~~

Pass ``async_=True`` to spawn subagents in the background:

.. code-block:: json

   {
     "tool": "spawn_subagents",
     "arguments": {
       "tasks": [
         {"task": "Research OAuth 2.0 best practices", "subagent_id": "oauth-research"}
       ],
       "async_": true
     }
   }

The tool returns immediately with running status:

.. code-block:: json

   {
     "success": true,
     "mode": "async",
     "subagents": [
       {
         "subagent_id": "oauth-research",
         "status": "running",
         "workspace": "/path/to/subagents/oauth-research/workspace",
         "status_file": "/path/to/logs/oauth-research/full_logs/status.json"
       }
     ],
    "note": "Poll for subagent completion to retrieve results when ready."
   }


Configuration
~~~~~~~~~~~~~

Configure async subagent behavior in your YAML config:

.. code-block:: yaml

   orchestrator:
     coordination:
       enable_subagents: true
       async_subagents:
         enabled: true  # Allow async spawning (default: true)


When to Use Async Mode
~~~~~~~~~~~~~~~~~~~~~~

Use async mode when:

* **Long-running research tasks**: Spawn research while continuing other work
* **Independent background work**: Tasks that don't block the main workflow
* **Parallel exploration**: Start multiple research directions simultaneously

Do NOT use async mode when:

* **Results needed immediately**: If you need the result before proceeding
* **Sequential dependencies**: If subsequent work depends on the subagent output
* **Critical path tasks**: If the subagent task is on the critical path

Example: Async Research
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   Parent Agent Workflow:
   1. Spawn async subagent for OAuth research
   2. Continue working on database schema
   3. (Subagent completes in background)
   4. On next tool call, OAuth research results injected
   5. Use research to inform authentication implementation

Evaluation Delegation Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A key use case for async subagents is **delegating procedural evaluation work** so the main
agent can focus on implementation. Without this, agents often spend their entire token budget
on evaluation (serving websites, running tests, taking screenshots, writing reports) and run
out of budget before implementing improvements.

**The pattern:** Spawn an async subagent with ``async_=True, refine=False`` to handle
procedural evaluation, then continue building while it runs.

.. list-table::
   :header-rows: 1
   :widths: 50 50

   * - Subagent handles (procedural)
     - Main agent handles (analytical)
   * - Serve website, take screenshots, run Playwright tests
     - Analyze previous answers and peer approaches
   * - Execute test suites, linters, validation scripts
     - Make quality judgments and prioritize improvements
   * - Run benchmarks, profiling, performance measurements
     - Synthesize insights into a coherent strategy
   * - Check file integrity, link resolution, cross-references
     - Decide what to build or fix next
   * - Compare output against specs with automated tools
     - Weigh tradeoffs and make architectural decisions

The subagent returns a **descriptive report** — what it measured, what passed, what failed,
what it observed. The main agent trusts these observations but makes its own quality judgments,
since it has full context and the subagent may run on a simpler or cheaper model.

.. code-block:: text

   Parent Agent Workflow:
   1. Implement website features
   2. Spawn async subagent: "Serve index.html, take full-page screenshots,
      run Playwright accessibility checks, report all findings"
   3. Continue implementing next feature while subagent evaluates
   4. Subagent results arrive → read descriptive report
   5. Use findings to fix issues, then spawn another eval subagent

.. note::

   For backends without automatic result injection (hook support), agents can manually
   poll for async subagent completion using ``check_subagent_status`` and
   ``get_subagent_result``.

Best Practices
--------------

1. **Design for independence**: Each subagent task should be completable without other subagents' output.

2. **Provide clear context**: The ``context`` parameter helps subagents understand the bigger picture.

3. **Use meaningful IDs**: ``subagent_id`` values appear in logs and help with debugging.

4. **Set appropriate timeouts**: Complex tasks may need longer than the default 5 minutes.

5. **Check workspaces on failure**: Subagent workspaces persist even on timeout/error.

6. **Start small**: Test with 2-3 subagents before scaling up.

Example Workflows
-----------------

Website Builder
~~~~~~~~~~~~~~~

.. code-block:: text

   Task: "Build a Bob Dylan tribute website"

   Parent agent spawns:
   ├── "research" subagent → Creates bio.md, timeline.md, quotes.md
   ├── "frontend" subagent → Creates HTML templates, CSS, JS
   └── "assets" subagent → Creates image metadata, placeholders

   Parent then:
   1. Copies files from each workspace
   2. Integrates content into templates
   3. Delivers final website

Documentation Generator
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   Task: "Generate API documentation for all modules"

   Parent agent spawns:
   ├── "auth_docs" subagent → Documents auth module
   ├── "db_docs" subagent → Documents database module
   └── "api_docs" subagent → Documents API endpoints

   Parent then:
   1. Collects all generated docs
   2. Creates index and cross-references
   3. Builds final documentation site

Docker Support
--------------

Subagents fully support Docker execution mode. When the parent agent is configured to run commands in Docker, subagents automatically inherit all Docker settings:

.. code-block:: yaml

   agents:
     - id: "orchestrator_agent"
       backend:
         type: "gemini"
         model: "gemini-2.0-flash"
         cwd: "workspace"
         enable_mcp_command_line: true
         command_line_execution_mode: docker
         command_line_docker_image: ghcr.io/massgen/mcp-runtime-sudo:latest
         command_line_docker_network_mode: bridge
         command_line_docker_enable_sudo: true
         enable_code_based_tools: true
         auto_discover_custom_tools: true

   orchestrator:
     coordination:
       enable_subagents: true

With this configuration:

* Subagents inherit Docker settings (image, network mode, sudo, credentials)
* Subagents inherit code-based tools settings
* Each subagent's ``execute_command`` calls run in isolated Docker containers

**Architecture:**

.. code-block:: text

   Host Machine
   └── MassGen parent process (runs on host)
        ├── execute_command → Docker container
        └── spawn_subagents → subprocess on host
             └── MassGen subagent process (runs on host)
                  └── execute_command → Docker container

.. important::

   **Limitation**: MassGen itself must run on the host, not inside Docker. The subagent system spawns new MassGen processes as subprocesses, which requires host access. Docker mode only applies to command execution (``execute_command`` tool), not to the MassGen orchestration layer.

   This means:

   * ✅ Running ``massgen`` on your host with ``command_line_execution_mode: docker`` works
   * ✅ Subagents will also run their commands in Docker
   * ❌ Running the entire MassGen process inside Docker with subagents enabled is not supported

Troubleshooting
---------------

Subagent Not Spawning
~~~~~~~~~~~~~~~~~~~~~

**Problem**: ``spawn_subagents`` tool not available.

**Solution**: Ensure ``enable_subagents: true`` is set in orchestrator config.

All Subagents Timing Out
~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Subagents consistently hit timeout.

**Solutions**:

1. Increase timeout: ``subagent_default_timeout: 600``
2. Simplify tasks: Break into smaller pieces
3. Check model: Some models are slower than others

Subagent Can't Access Files
~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Subagent reports file not found.

**Solutions**:

1. Use absolute paths in ``context_files``
2. Verify file exists before spawning
3. Remember: context files are read-only

Parent Can't Find Subagent Output
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Parent agent can't locate subagent's created files.

**Solutions**:

1. Check the ``workspace`` path in the result
2. Instruct subagents to list created files in their answer
3. Use ``copy_files_batch`` tool to copy from subagent workspace

Related Documentation
---------------------

* :doc:`agent_task_planning` - Plan tasks before spawning subagents
* :doc:`planning_mode` - Coordinate before executing
* :doc:`../tools/index` - Tools available to agents
* :doc:`../../reference/yaml_schema` - Complete configuration reference
