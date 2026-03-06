## ADDED Requirements

### Requirement: TUI Mode State
The system SHALL maintain a centralized mode state in the Textual TUI that tracks plan mode, agent mode, refinement mode, and override state.

#### Scenario: Mode state initialization
- **WHEN** the TUI starts
- **THEN** mode state initializes with defaults: normal plan mode, multi-agent mode, refinement enabled

#### Scenario: Mode state generates orchestrator overrides
- **WHEN** a turn is submitted
- **THEN** mode state generates appropriate config overrides based on current settings

### Requirement: Mode Bar Widget
The system SHALL display a Mode Bar widget above the input area containing toggles for plan mode, agent mode, and refinement mode.

#### Scenario: Mode bar visibility
- **WHEN** the TUI is running
- **THEN** the Mode Bar is visible above the input area with clickable toggles

#### Scenario: Mode bar disabled during execution
- **WHEN** agents are executing
- **THEN** mode toggles are disabled to prevent inconsistent state

### Requirement: Plan Mode
The system SHALL support a plan mode where queries create plans for approval before execution.

#### Scenario: Enter plan mode
- **WHEN** user presses Shift+Tab
- **THEN** plan mode is activated and Mode Bar indicates plan mode is on

#### Scenario: Plan mode submission
- **WHEN** user submits a query in plan mode
- **THEN** the system runs planning phase (--plan internally)
- **AND** displays a plan approval modal with plan preview

#### Scenario: Plan approval with additions
- **WHEN** user approves plan with additional instructions
- **THEN** the system transitions to execute mode
- **AND** runs execute-plan with the approved plan and additions

#### Scenario: Plan execution display
- **WHEN** executing an approved plan
- **THEN** the TUI shows plan directory and "Executing Plan" status

### Requirement: Agent Mode Toggle
The system SHALL support switching between single-agent and multi-agent modes via the Mode Bar.

#### Scenario: Single-agent mode activation
- **WHEN** user switches to single-agent mode
- **THEN** one agent is active based on tab bar selection
- **AND** other agent tabs are greyed out (disabled visual)

#### Scenario: Tab bar agent selection
- **WHEN** user clicks a tab in single-agent mode
- **THEN** that agent becomes the active single agent
- **AND** other tabs remain greyed out

#### Scenario: Context preservation across agent switches
- **WHEN** user switches active agent between turns in single-agent mode
- **THEN** the new agent has access to full conversation history

### Requirement: Refinement Mode Toggle
The system SHALL support enabling/disabling refinement via the Mode Bar.

#### Scenario: Refinement off with single agent
- **WHEN** refinement is disabled and agent mode is single
- **THEN** voting is skipped entirely (skip_voting=True)
- **AND** agent goes directly from answer to presentation

#### Scenario: Refinement off with multi-agent
- **WHEN** refinement is disabled and agent mode is multi
- **THEN** max_new_answers_per_agent is set to 1
- **AND** disable_injection is set to True (agents work independently)
- **AND** defer_voting_until_all_answered is set to True
- **AND** final_answer_strategy is set to `synthesize`

### Requirement: Final Answer Strategy
The orchestrator SHALL support selecting how the final answer is produced after coordination completes.

#### Scenario: Winner reuse strategy
- **WHEN** `final_answer_strategy` is `winner_reuse`
- **THEN** the selected winner's existing answer is used directly when final presentation can be skipped
- **AND** no additional synthesis LLM call is required

#### Scenario: Winner present strategy
- **WHEN** `final_answer_strategy` is `winner_present`
- **THEN** the selected winner performs the normal final presentation pass
- **AND** the final answer is derived from that presentation output

#### Scenario: Synthesize strategy
- **WHEN** `final_answer_strategy` is `synthesize`
- **THEN** the selected presenter receives all completed agent answers in final presentation context
- **AND** the presenter combines the strongest relevant parts into a single final answer
- **AND** synthesis does not depend on write-context-path detection

#### Scenario: Multi-agent quick mode defaults to synthesis
- **WHEN** refinement is disabled and agent mode is multi
- **THEN** `final_answer_strategy` defaults to `synthesize`
- **AND** the system does not default to reusing the voted winner answer verbatim

### Requirement: Independent Agent Execution
The orchestrator SHALL support disabling injection to allow agents to work independently.

#### Scenario: Injection disabled
- **WHEN** disable_injection is True
- **THEN** agents do not receive injection content about other agents' progress
- **AND** agents do not trigger restart signals to other agents
- **AND** each agent works only on the original task without seeing other agents' answers

### Requirement: Deferred Voting
The orchestrator SHALL support deferring voting until all agents have submitted answers. (for multi-agent + refinement OFF)

#### Scenario: Deferred voting enabled
- **WHEN** defer_voting_until_all_answered is True
- **THEN** agents that finish early wait until all agents have submitted at least one answer
- **AND** voting phase begins only after all agents have answered
- **AND** this avoids wasteful restarts (agent voting on own answer then being restarted)

#### Scenario: Single agent with refinement on
- **WHEN** refinement is enabled and agent mode is single
- **THEN** voting is available (vote = "I'm done refining")
- **AND** agent can choose between new_answer or vote

### Requirement: Human Override
The system SHALL allow users to override the voted winner after voting completes but before final presentation.

#### Scenario: Override availability
- **WHEN** voting completes
- **THEN** TUI shows "Press Ctrl+O to override, Enter to continue" notification

#### Scenario: Override modal display
- **WHEN** user presses Ctrl+O after voting
- **THEN** OverrideModal displays all agents' recent answers with previews

#### Scenario: Override selection
- **WHEN** user selects a different agent in OverrideModal
- **THEN** that agent is set as the presenter
- **AND** that agent does the final presentation

### Requirement: Skip Voting Configuration
The orchestrator SHALL support a skip_voting config flag to bypass vote tool injection.

#### Scenario: Skip voting enabled
- **WHEN** skip_voting is True
- **THEN** vote tool is not injected into agent tools
- **AND** enforcement does not require vote tool call
- **AND** agent proceeds directly to presentation after new_answer

### Requirement: Context Path Write Access in Quick Mode
The system SHALL enable context path write access appropriately when refinement mode is OFF.

#### Scenario: Single agent with refinement OFF and write context paths
- **WHEN** refinement is disabled
- **AND** agent mode is single
- **AND** context paths with write permission exist
- **THEN** write access is enabled for those context paths
- **AND** no final presentation LLM call is made
- **AND** the agent can write directly to context paths during coordination

#### Scenario: Multi-agent with refinement OFF and write context paths
- **WHEN** refinement is disabled
- **AND** agent mode is multi
- **AND** context paths with write permission exist
- **AND** `final_answer_strategy` is `winner_present` or `synthesize`
- **THEN** final presentation is executed
- **AND** write access is enabled during final presentation

#### Scenario: Multi-agent with refinement OFF and no write context paths
- **WHEN** refinement is disabled
- **AND** agent mode is multi
- **AND** no context paths with write permission exist
- **AND** `final_answer_strategy` is `winner_reuse`
- **THEN** final presentation is skipped
- **AND** existing answer is used directly

#### Scenario: Multi-agent synthesis without write context paths
- **WHEN** refinement is disabled
- **AND** agent mode is multi
- **AND** no context paths with write permission exist
- **AND** `final_answer_strategy` is `synthesize`
- **THEN** final presentation still runs to produce a synthesized answer

### Requirement: Docker Container Recreation for Write Access
The system SHALL recreate Docker containers with write-enabled mounts for final presentation.

#### Scenario: Recreate container before final presentation
- **WHEN** final presentation is about to begin
- **AND** the agent uses Docker execution mode
- **AND** context paths with write permission exist
- **THEN** the existing Docker container is removed
- **AND** a new container is created with write-enabled mounts for writable context paths
- **AND** the agent can use shell commands to write to context paths

#### Scenario: Why container recreation is needed
- **NOTE** Docker containers are created at coordination start with context paths mounted as read-only (to prevent race conditions between parallel agents)
- **NOTE** Docker mount modes cannot be changed after container creation
- **NOTE** MCP filesystem tools bypass Docker mounts (run on host), but shell commands run inside the container
- **NOTE** Without recreation, shell commands (rm, cp, mv, etc.) would fail with "Read-only file system"

### Requirement: Context Path Write Tracking
The system SHALL track and display files written to context paths using snapshot-based mtime comparison.

#### Scenario: Snapshot context paths before writes are enabled
- **WHEN** context write access is about to be enabled
- **AND** context paths with write permission exist
- **THEN** a snapshot of all files in writable context paths is taken
- **AND** the snapshot stores file paths and modification times (mtime) only (no content)
- **NOTE** For single-agent + refinement OFF: snapshot taken at start of coordination
- **NOTE** For multi-agent or refinement ON: snapshot taken before final presentation

#### Scenario: Detect written files after execution completes
- **WHEN** execution completes (coordination or final presentation)
- **THEN** the system compares current context path state against the snapshot
- **AND** files with newer mtime than snapshot are recorded as "modified"
- **AND** files not present in snapshot are recorded as "new"
- **AND** both modified and new files are included in the write tracking list

#### Scenario: Display written files in final answer (few files)
- **WHEN** final answer is displayed
- **AND** 5 or fewer files were written to context paths
- **THEN** a footer section shows "Files written to context paths:"
- **AND** lists each file path inline

#### Scenario: Display written files in final answer (many files)
- **WHEN** final answer is displayed
- **AND** more than 5 files were written to context paths
- **THEN** a footer section shows "{count} files written to context paths"
- **AND** full list is written to `{log_dir}/context_path_writes.txt`
- **AND** footer shows path to view details

#### Scenario: No footer when no writes
- **WHEN** final answer is displayed
- **AND** no files were written to context paths
- **THEN** no footer section is displayed
