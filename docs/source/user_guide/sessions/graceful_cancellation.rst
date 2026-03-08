Graceful Cancellation
=====================

MassGen supports graceful cancellation, allowing you to interrupt a running session (Ctrl+C) while still preserving partial progress. This is useful when agents are going down the wrong path or taking too long.

How It Works
------------

When you press Ctrl+C during coordination:

1. MassGen captures the current state from all agents
2. Any answers that have been generated are saved
3. Agent workspaces are preserved
4. The session can be resumed later with ``--continue``

.. code-block:: bash

   # Running a session
   $ massgen --config my_config.yaml "Complex question..."

   🤖 Multi-Agent
   Agents: agent_a, agent_b
   Question: Complex question...

   [Agent coordination in progress...]

   ^C
   ⚠️  Cancellation requested - saving partial progress...
   ✅ Partial progress saved. Session can be resumed with --continue
   👋 Goodbye!

What Gets Saved
---------------

When you cancel mid-session, MassGen saves:

* **Partial answers** - Any answers that agents have submitted
* **Agent workspaces** - All files created or modified by each agent (separately)
* **Turn metadata** - Phase, timestamp, and task information
* **Voting state** - If voting was in progress

The partial turn is marked as "incomplete" in the session directory.

What the Next Turn Sees
-----------------------

When you resume a session with an incomplete turn, no information is lost:

**Conversation History**: All partial answers are combined into a single assistant message with clear attribution. Agents that were still working (have a workspace but no answer yet) get a placeholder:

.. code-block:: text

   [INCOMPLETE TURN - Session was cancelled before completion]
   [Phase when cancelled: coordinating]

   ## agent_a's answer (voted for: agent_b):
   First agent's partial answer...
   [Workspace available at: /path/to/workspace]

   ## agent_b:
   [No answer submitted - agent was still working]
   [View workspace for current progress: /path/to/workspace]

**Workspaces**: All agent workspaces from the incomplete turn are provided as read-only context paths, allowing agents to see what each other was working on. This includes:

- Agents that submitted partial answers
- Agents that were still working (created files but no answer yet)

This ensures no files or progress is lost, even from agents that hadn't finished their response.

Session Directory Structure
~~~~~~~~~~~~~~~~~~~~~~~~~~~

After cancellation, your session directory will contain:

.. code-block:: text

   .massgen/sessions/session_20251205_120000/
   ├── SESSION_SUMMARY.txt           # Updated with incomplete turn info
   ├── turn_1/                       # Complete previous turn (if any)
   │   ├── metadata.json
   │   ├── answer.txt
   │   └── workspace/
   └── turn_2/                       # Incomplete turn
       ├── metadata.json             # status: "incomplete"
       ├── partial_answers.json      # All agent answers
       ├── answer.txt                # Best available answer
       └── workspaces/               # Per-agent workspaces
           ├── agent_a/
           └── agent_b/

Resuming After Cancellation
---------------------------

Resume your session with the ``--continue`` flag:

.. code-block:: bash

   $ massgen --continue

   📚 Restored session with 2 previous turn(s)
      Starting turn 3

   ⚠️  Previous turn was incomplete (cancelled during coordinating phase)
      Task: Complex question...
      Partial answers saved from: agent_a, agent_b
      The incomplete turn's partial progress is saved in the session directory.

When resuming:

* MassGen shows you information about the incomplete turn
* You can ask the same question again or move on to a new one
* Previous complete turns provide context for agents
* Partial answers from the cancelled turn are available for review in the session directory

Viewing Partial Results
-----------------------

You can review the partial answers saved during cancellation:

.. code-block:: bash

   # View the partial answers
   cat .massgen/sessions/session_*/turn_*/partial_answers.json

   # View the best partial answer
   cat .massgen/sessions/session_*/turn_*/answer.txt

Force Exit
----------

If you need to exit immediately without saving:

* First Ctrl+C: Graceful cancellation (saves partial progress)
* Second Ctrl+C: Force exit (no saving)

Multi-Turn Mode Behavior
------------------------

In multi-turn (interactive) sessions, cancellation works slightly differently:

* **First Ctrl+C**: Saves partial progress and returns to the prompt
* **Second Ctrl+C**: Exits the session entirely
* **Queued runtime fallback prompts persist**: If pending runtime-injection text is promoted to a new turn prompt and that turn is cancelled, the prompt is retained in conversation history for subsequent turns

This allows you to cancel a long-running turn without losing your entire session:

.. code-block:: bash

   $ massgen --config my_config.yaml  # Interactive mode

   🤖 Multi-Agent Session

   > What is the meaning of life?

   [Agent coordination in progress...]

   ^C
   ⚠️  Cancellation requested - saving partial progress...
   ✅ Partial progress saved. Session can be resumed with --continue
   ⏸️  Turn cancelled. Partial progress saved.
   Enter your next question or /quit to exit.

   > Let's try a simpler question...

This behavior ensures you can:

- Cancel a turn that's taking too long without losing the session
- Review partial progress and decide how to proceed
- Continue with a different question if needed

Use Cases
---------

Graceful cancellation is helpful when:

1. **Wrong Direction** - Agents are pursuing an incorrect approach
2. **Too Long** - Coordination is taking longer than expected
3. **Debugging** - You want to inspect partial state
4. **Resource Management** - You need to free up API calls or compute

Configuration
-------------

Graceful cancellation is enabled by default. No configuration is required.

.. note::

   Partial progress is only saved if at least one agent has submitted an answer.
   If cancelled before any answers are generated, only the task metadata is saved.

Related Documentation
---------------------

* :doc:`multi_turn_mode` - Interactive multi-turn conversations
* :doc:`orchestration_restart` - How MassGen handles restarts
* :doc:`memory` - Memory and context management
