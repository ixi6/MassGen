# Change: Add TUI Mode System for Native Multi-Agent Integration

## Why
The Textual TUI currently lacks native mode toggles for common multi-agent workflows. Users must use CLI flags or restart sessions to switch between planning/execution, single/multi-agent, or enable/disable refinement. This creates friction for interactive workflows and prevents seamless integration of multi-agent capabilities into a simple coding agent setup.

## What Changes

### Plan Mode (Shift+Tab)
- Add keyboard binding (Shift+Tab) to toggle plan mode
- In plan mode, submitted queries run planning phase (`--plan` internally)
- After planning completes, show approval modal with plan preview
- User can add additional instructions before approving
- On approval, auto-transition to execute mode (`--execute-plan`)
- Display shows plan directory and "Executing Plan" status during execution

### Agent Mode Toggle (Single vs Multi)
- Add mode toggle in new Mode Bar widget above input area
- Single-agent mode: one agent from config is active, others greyed out in tab bar
- Tab bar becomes agent selector in single-agent mode
- Context preserved across agent switches between turns
- Single agent keeps voting when refinement is ON (vote = "I'm done refining")

### Refinement Mode Toggle (On/Off)
- Add toggle in Mode Bar to enable/disable refinement
- Default: On (normal vote/new_answer patterns)
- Off + Single agent: skip coordination rounds entirely, direct answer
- Off + Multi-agent: set max_new_answers_per_agent=1 so each agent produces one independent answer
- Off + Multi-agent: default final answer behavior to synthesis, combining the strongest parts of completed answers instead of reusing the voted winner verbatim

### Human Override (Ctrl+O)
- Add keyboard binding (Ctrl+O) to trigger override modal
- Available AFTER voting completes but BEFORE final presentation
- Browse all agents' most recent answers
- Select different agent to do final presentation
- Chosen agent then does final presentation (writes to workspace normally)
- **Post-completion redo deferred to future spec**

### Mode Bar Widget
- New horizontal widget positioned above input area
- Contains: Plan mode indicator, Agent mode toggle, Refinement toggle
- Override button appears when override is available
- Disabled during execution to prevent inconsistent state

### Orchestrator Changes
- Add `skip_voting` config flag to bypass vote tool injection (used when refinement OFF + single agent)
- Add `final_answer_strategy` config flag with `winner_reuse`, `winner_present`, and `synthesize`
- Support runtime config overrides from TUI mode state
- Note: Single agent + refinement ON keeps voting (vote = "I'm done refining")
- In multi-agent + refinement OFF quick mode, keep deferred voting to select the synthesis presenter but default `final_answer_strategy` to `synthesize`

### Context Path Write Access (Refinement OFF)
- Single agent + refinement OFF: Enable write access for context paths even without final presentation LLM call
- Multi-agent + refinement OFF + `winner_reuse`: Skip final presentation when no write context paths exist
- Multi-agent + refinement OFF + `winner_present`: Run the selected winner's normal final presentation
- Multi-agent + refinement OFF + `synthesize`: Always run a synthesis presentation, even when no write context paths exist

### Context Path Write Tracking
- Track files written to context paths during final presentation
- Display written files in final answer footer (file-level granularity)
- When ≤5 files: show inline in footer
- When >5 files: show summary count with path to `{log_dir}/context_path_writes.txt`
- Purely mechanistic tracking (no prompt changes)

## Impact
- Affected specs: textual-tui (new capability)
- Affected code:
  - `massgen/frontend/displays/textual_terminal_display.py` (mode integration, write tracking display)
  - `massgen/frontend/displays/textual_widgets/tab_bar.py` (single-agent mode)
  - `massgen/frontend/interactive_controller.py` (mode state propagation)
  - `massgen/orchestrator.py` (skip_voting flag, final answer strategy handling, write context path helpers, write tracking exposure)
  - `massgen/agent_config.py` (new final-answer strategy config)
  - `massgen/filesystem_manager/_path_permission_manager.py` (write tracking)
  - New files: `tui_modes.py`, `mode_bar.py`
  - Theme files for new widget styling

## What's Next
- Implement `final_answer_strategy` in orchestrator and config plumbing
- Update quick-mode TUI overrides so multi-agent refinement OFF defaults to `synthesize`
- Add integration coverage for `winner_reuse`, `winner_present`, and `synthesize`
