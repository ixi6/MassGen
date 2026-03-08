Change Documents
================

Change Documents (changedocs) are decision journals that agents write alongside their answers during coordination. They capture **why** each decision was made, **what alternatives** were considered, and **where in the code** each decision lives --- creating a traceable record from reasoning to implementation.

.. note::

   Change documents are enabled by default. To disable them, set ``enable_changedoc: false`` in coordination config.

Why Change Documents?
---------------------

When AI agents produce code, the reasoning behind their decisions is usually lost. You see *what* was built but not *why*. Change documents solve this by recording decisions in real-time as agents work:

* **Decision provenance** --- every significant choice is documented with rationale
* **Code traceability** --- each decision points to specific files, functions, and line numbers
* **Multi-agent attribution** --- track which agent introduced each idea, and which ideas were genuinely new
* **Deliberation history** --- see how decisions evolved as agents observed and refined each other's work

Quick Start
-----------

Change documents are enabled by default. Agents automatically write ``tasks/changedoc.md`` in their workspace:

.. code-block:: yaml

   # Default behavior --- changedoc is on
   orchestrator:
     coordination:
       enable_changedoc: true   # This is the default

To disable:

.. code-block:: yaml

   orchestrator:
     coordination:
       enable_changedoc: false

How It Works
------------

Agent Workflow
~~~~~~~~~~~~~~

Each agent follows this workflow during coordination:

1. **Create** ``tasks/changedoc.md`` as their first action
2. **Log decisions** in real-time as they make them (not after the fact)
3. **Reference code** with file paths, symbol names, and line numbers
4. **Submit answer** --- the changedoc is already up to date

When agents build on prior answers, they **inherit** the previous agent's changedoc and extend it with their own decisions.

Self-Reference Placeholder
~~~~~~~~~~~~~~~~~~~~~~~~~~

When writing a changedoc, agents use ``[SELF]`` wherever they would reference their own work. The orchestrator automatically replaces ``[SELF]`` with the agent's real answer label (e.g., ``agent1.2``) when the answer is submitted. This means:

* Agents don't need to know their own label in advance
* Other agents always see real labels, never placeholders
* The provenance chain is consistent and machine-readable

.. code-block:: markdown

   # What the agent writes:
   **Origin:** [SELF] --- NEW

   # What the next agent sees:
   **Origin:** agent1.2 --- NEW

Observation Flow
~~~~~~~~~~~~~~~~

The orchestrator automatically includes changedoc content when agents observe each other's work:

.. code-block:: text

   Agent A writes changedoc with DEC-001, DEC-002
       |
       v
   Orchestrator reads tasks/changedoc.md from Agent A's workspace
       |
       v
   Agent B sees Agent A's answer + changedoc in <changedoc> tags
       |
       v
   Agent B inherits changedoc, modifies decisions, adds new ones
       |
       v
   Final presenter consolidates into definitive changedoc

Final Consolidation
~~~~~~~~~~~~~~~~~~~

The final presenter (winning agent) produces a consolidated changedoc that:

* Finalizes the decision list (removes superseded decisions)
* Updates all code references to point to the delivered files
* Preserves the deliberation trail showing how decisions evolved
* Marks which ideas were genuinely new contributions

Changedoc Structure
-------------------

A changedoc has four sections:

Header
~~~~~~

.. code-block:: markdown

   # Change Document

   **Based on:** agent1.1

The ``Based on`` field tracks which answer this changedoc inherits from, using MassGen's answer labels (e.g., ``agent1.1`` = agent 1's first answer, ``agent2.3`` = agent 2's third answer).

Decisions
~~~~~~~~~

Each decision has an Origin, Choice, Rationale, Alternatives, and Implementation:

.. code-block:: markdown

   ### DEC-001: Use connection pooling for response time
   **Origin:** agent1.1 --- NEW
   **Choice:** Connection pooling with pgbouncer
   **Why:** Reduces query overhead from ~180ms to ~40ms
   **Alternatives considered:**
   - Caching: Doesn't handle cache misses within 200ms
   - Read replicas: Adds operational complexity
   **Implementation:**
   - `src/db/pool.py:L15-42` -> `ConnectionPool.__init__()` --- configures pool size and timeout
   - `src/db/pool.py:L44-68` -> `ConnectionPool.acquire()` --- checkout with retry logic

Key fields:

* **Origin** --- who first introduced this decision, using answer labels
* **NEW** marker --- flags genuinely novel ideas not present in any prior answer
* **Implementation** --- relative file paths, symbol names, and line numbers

When a decision is modified by a later agent:

.. code-block:: markdown

   ### DEC-002: Authentication approach
   **Origin:** agent1.1, modified by agent2.1
   **Choice:** JWT with refresh tokens
   **Why:** agent1.1 used session cookies, but JWT scales better for API clients
   **Implementation:**
   - `src/auth/jwt.py:L10-35` -> `create_token()` --- signs payload with RS256

Code References
~~~~~~~~~~~~~~~

All code references use relative paths within the workspace with both symbol names and line numbers:

.. code-block:: text

   Format: `relative/path/file.py:L10-25` -> `ClassName.method()` --- brief description

Line numbers are stable references because each agent's code is frozen once they submit their answer. When another agent reads the changedoc, the line numbers point to an immutable snapshot.

Deliberation Trail
~~~~~~~~~~~~~~~~~~

The trail records what changed between agents and why:

.. code-block:: markdown

   ## Deliberation Trail

   ### agent2.1 (based on agent1.1):
   - DEC-001: Kept --- connection pooling approach is sound
   - DEC-002: Modified --- switched from session cookies to JWT (see rationale above)
   - DEC-003: NEW --- added rate limiting, not present in agent1.1's answer

   ### agent1.2 (based on agent2.1):
   - DEC-001: Kept
   - DEC-002: Kept agent2.1's JWT approach
   - DEC-003: Kept rate limiting, increased threshold from 100 to 500 req/min

The trail uses answer labels (``agent1.1``, ``agent2.1``) for precise provenance. You can trace any decision back through the chain to see who introduced it, who modified it, and why.

Decision Provenance
-------------------

Every decision tracks its origin through the refinement chain:

.. code-block:: text

   agent1.1 --- NEW            Original idea, introduced by agent 1
   agent1.1, modified by agent2.1   Agent 2 changed it, attributed to agent 1
   agent2.1 --- NEW            Genuinely new idea from agent 2

This lets you answer:

* **Where did this idea come from?** Check the Origin field.
* **Who contributed new thinking?** Look for ``NEW`` markers.
* **Did two agents build on the same source?** Compare ``Based on:`` headers --- if both say ``agent1.1``, they forked from the same point.
* **How did a decision evolve?** Read the Deliberation Trail entries for that DEC number.

Reading Changedocs in Logs
--------------------------

Changedocs are saved in the log directory alongside answers:

.. code-block:: text

   .massgen/massgen_logs/log_YYYYMMDD_HHMMSS/
   └── turn_1/
       └── attempt_1/
           ├── agent_a/
           │   └── YYYYMMDD_HHMMSS_NNNNNN/
           │       ├── answer.txt
           │       ├── changedoc.md            # Changedoc snapshot at this step
           │       └── workspace/
           │           └── tasks/
           │               └── changedoc.md    # Raw file from workspace
           ├── final/
           │   └── agent_a/
           │       └── changedoc.md            # Final consolidated changedoc
           └── ...

Each agent snapshot captures the changedoc at that point in time. The ``final/`` directory contains the presenter's consolidated version.

Configuration
-------------

.. code-block:: yaml

   orchestrator:
     coordination:
       enable_changedoc: true    # Default: true

Change documents work with all coordination modes and all backends. They are independent of planning mode --- you get decision journals whether or not ``enable_planning_mode`` is set.

.. seealso::

   When combined with planning mode, changedocs become even more powerful --- agents document their *intended* approach during coordination, then the winning agent executes and updates code references to the final implementation.

   :doc:`planning_mode` --- Planning mode configuration and workflow

Example Output
--------------

Here is an example changedoc from a two-agent run creating a Python fun-facts terminal application:

.. code-block:: markdown

   # Change Document

   **Based on:** agent1.1

   ## Summary
   Interactive Python script with 35 fun facts across 5 categories,
   using Rich library for terminal formatting with validated input via Prompt.ask().

   ## Decisions

   ### DEC-001: Use Rich library for terminal formatting
   **Origin:** agent1.1 --- NEW
   **Choice:** Use the `rich` library for all terminal output
   **Why:** Professional terminal output with minimal code --- panels, tables, syntax
   highlighting, progress bars. Well-maintained and widely used.
   **Alternatives considered:**
   - ANSI escape codes: Too low-level and harder to maintain
   - Colorama: More low-level, requires more code for similar effects
   **Implementation:**
   - `fun_facts.py:L1-5` -> imports --- `from rich.console import Console`
   - `fun_facts.py:L45-80` -> `display_fact()` --- renders fact in styled Panel

   ### DEC-002: Validated input with Prompt.ask()
   **Origin:** agent1.1 --- NEW
   **Choice:** Use `Prompt.ask(choices=[...])` for all user input
   **Why:** Eliminates invalid input entirely, provides autocomplete UX
   **Alternatives considered:**
   - Basic `input()`: More error-prone (agent2.1 used this, switched away)
   **Implementation:**
   - `fun_facts.py:L82-95` -> `main()` --- menu loop with `Prompt.ask(choices=["1","2","3","4","5"])`

   ### DEC-003: Statistics view
   **Origin:** agent1.2 --- NEW
   **Choice:** Add collection statistics showing facts per category
   **Why:** Helps users understand collection scope, showcases Rich tables
   **Implementation:**
   - `fun_facts.py:L120-145` -> `show_statistics()` --- Rich Table with category counts

   ## Deliberation Trail

   ### agent1.1 (original):
   - Created DEC-001, DEC-002 with 35 facts across 5 categories

   ### agent2.1 (original, parallel):
   - Also chose Rich (DEC-001 convergence), but used basic `input()` and 20 facts

   ### agent1.2 (based on agent2.1):
   - DEC-001: Kept
   - DEC-002: Kept Prompt.ask() --- agent2.1's `input()` approach is more error-prone
   - DEC-003: NEW --- statistics view not in any prior answer

Next Steps
----------

* :doc:`planning_mode` --- Combine changedocs with planning mode for safe execution
* :doc:`../../user_guide/logging` --- Understanding the full log directory structure
* :doc:`agent_communication` --- How agents observe and respond to each other
