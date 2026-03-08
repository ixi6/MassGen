Background Tool Execution
=========================

MassGen supports non-blocking tool execution for long-running work. This lets agents continue useful foreground tasks while a tool runs in the background.

Use this guide for the generic background lifecycle used by custom tools and MCP targets.

.. note::

   This page covers **tool-level background jobs** (custom tools + MCP tools).
   For running an entire MassGen CLI command in the background, see :doc:`../integration/automation` (BackgroundShellManager).

When to Use Background Tools
----------------------------

Use background mode when a tool call is expected to take noticeable time and you can continue meaningful work without waiting.

Common examples:

* Large test suites and benchmark runs
* Long data processing tasks
* Media generation and heavy file processing
* Slow MCP/API calls

Foreground mode is usually better for short checks where immediate output is needed.

Lifecycle Overview
------------------

MassGen exposes a consistent lifecycle:

1. Start a background job with ``custom_tool__start_background_tool``
2. Check progress with ``custom_tool__get_background_tool_status``
3. Get final output with ``custom_tool__get_background_tool_result``
4. Optionally wait for the next completion with ``custom_tool__wait_for_background_tool``
5. Cancel with ``custom_tool__cancel_background_tool`` if no longer needed
6. Inspect all jobs with ``custom_tool__list_background_tools``

.. important::

   Lifecycle tools use ``job_id`` (background job identifier), not tool-specific IDs such as ``subagent_id``.

You can request background execution in two ways:

* Preferred for normal custom tool calls: include ``background: true`` (or ``mode: background``) on the original tool call
* Explicit management flow: call ``custom_tool__start_background_tool`` with target ``tool_name`` and ``arguments``

How Waiting Works
-----------------

``custom_tool__wait_for_background_tool`` blocks until the **next unseen** background job reaches a terminal state (``completed``, ``error``, or ``cancelled``), or until timeout.

Timeout behavior:

* Default timeout is 30 seconds
* Maximum timeout is 600 seconds
* Timeout returns a success payload with ``ready: false`` and ``timed_out: true``

Wait Interruption by Runtime Input
----------------------------------

``custom_tool__wait_for_background_tool`` can return early when runtime-injection content becomes available.

Interruption payload shape:

.. code-block:: json

   {
     "success": true,
     "ready": false,
     "interrupted": true,
     "interrupt_reason": "runtime_injection_available",
     "injected_content": "...",
     "waited_seconds": 4.231
   }

Notes:

* ``interrupt_reason`` may be ``runtime_injection_available`` (new context ready) or ``turn_cancelled``.
* ``injected_content`` contains the runtime context to incorporate before proceeding.
* Runtime input delivered this way is persisted for that agent within the current turn, so if the agent round restarts, the same instruction context is still present.
* If runtime input is queued just before the wait call starts, MassGen now signals an interrupt immediately after wait activation so the input is not stranded in queue.
* After handling injected context, you can continue foreground work or call wait again.

Result Delivery and Polling
---------------------------

In many runs, completed background results are automatically injected back into agent context by the hook framework. When results are not auto-injected (or when deterministic control is needed), poll status and fetch results explicitly.

Recommended pattern:

1. Start job(s)
2. Continue foreground work
3. When blocked, use ``custom_tool__wait_for_background_tool``
4. Fetch final payload with ``custom_tool__get_background_tool_result`` as needed

Subagents + Background Lifecycle
--------------------------------

For subagent work, keep these roles separate:

* ``spawn_subagents``: starts subagent work
* ``list_subagents``: discovery/index of subagent metadata (status, workspace, session pointers)
* ``custom_tool__*background*`` lifecycle tools: status/result/wait/cancel management for background jobs

When cancelling a background subagent flow, call ``custom_tool__cancel_background_tool(job_id)`` with the
background job ID returned by the lifecycle system.

Backend Notes
-------------

* This lifecycle is available across the primary MassGen tool-capable backends.
* Codex custom-tool sessions include these lifecycle tools via the ``massgen_custom_tools`` MCP wrapper.
* For Codex/Claude Code MCP targets, background-capable MCP server configs are derived from normal ``mcp_servers`` and filtered to avoid recursive/internal servers.

UI Notes (TUI)
--------------

When using the textual UI, background jobs are surfaced in status/ribbon indicators and a background-jobs modal. This makes it easier to monitor asynchronous progress without manual log inspection.

See Also
--------

* :doc:`custom_tools` - Custom tool authoring and registration
* :doc:`code_based_tools` - CodeAct-style MCP wrappers and tool usage
* :doc:`code_execution` - Command execution tools (including background shell commands)
* :doc:`../integration/automation` - BackgroundShellManager for full CLI process automation
