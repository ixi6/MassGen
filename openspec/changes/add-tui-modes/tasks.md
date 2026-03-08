# Tasks: Add TUI Mode System

## 1. Core Mode Infrastructure
- [ ] 1.1 Create `massgen/frontend/displays/tui_modes.py` with TuiModeState dataclass
- [ ] 1.2 Implement `get_orchestrator_overrides()` method for config generation
- [ ] 1.3 Implement `get_effective_agents()` method for agent filtering

## 2. Mode Bar Widget
- [ ] 2.1 Create `massgen/frontend/displays/textual_widgets/mode_bar.py`
- [ ] 2.2 Implement ModeToggle component for plan/agent/refinement modes
- [ ] 2.3 Add Override button (hidden by default)
- [ ] 2.4 Export new widgets in `__init__.py`

## 3. Tab Bar Extension
- [ ] 3.1 Add `set_single_agent_mode()` method to AgentTabBar
- [ ] 3.2 Add disabled tab styling (greyed out visual)
- [ ] 3.3 Handle clicks on disabled tabs

## 4. TUI Integration
- [ ] 4.1 Add `_mode_state` to TextualApp
- [ ] 4.2 Integrate ModeBar into compose() above input area
- [ ] 4.3 Add Shift+Tab binding for plan mode toggle
- [ ] 4.4 Add Ctrl+O binding for override trigger

## 5. Plan Mode Flow
- [ ] 5.1 Implement `action_toggle_plan_mode()` handler
- [ ] 5.2 Modify `_submit_question()` to detect plan mode
- [ ] 5.3 Implement `_run_plan_phase()` for planning execution
- [ ] 5.4 Create PlanApprovalModal with plan preview and additional instructions input
- [ ] 5.5 Implement `_execute_approved_plan()` for execute phase transition
- [ ] 5.6 Add plan directory and status display during execution

## 6. Agent Mode Toggle
- [ ] 6.1 Implement `_on_agent_mode_change()` handler
- [ ] 6.2 Wire tab bar selection for single-agent mode
- [ ] 6.3 Update mode state when tab is clicked in single-agent mode

## 7. Refinement Mode Toggle
- [ ] 7.1 Implement `_on_refinement_mode_change()` handler
- [ ] 7.2 Show notifications explaining effect of toggle

## 8. Human Override (Before Presentation)
- [ ] 8.1 Implement `action_trigger_override()` handler (available after voting, before presentation)
- [ ] 8.2 Create OverrideModal to browse/select agent answers
- [ ] 8.3 Implement `_execute_override()` to set chosen agent before presentation
- [ ] 8.4 Add pause point after voting with "Press Ctrl+O to override, Enter to continue" notification

## 9. Orchestrator Changes
- [ ] 9.1 Add `skip_voting` config flag to AgentConfig (used when refinement OFF + single agent)
- [ ] 9.2 Implement skip_voting logic in `_stream_agent_execution()` (skip vote tool injection)
- [ ] 9.3 Update enforcement logic to not require vote when skip_voting=True
- [ ] 9.4 Handle single-agent direct presentation flow when refinement OFF
- [ ] 9.5 Ensure single-agent with refinement ON still has voting (vote = "I'm done refining")
- [x] 9.6 Add `disable_injection` config flag to AgentConfig
- [x] 9.7 Implement disable_injection logic (skip injection callback, skip restart signaling)
- [x] 9.8 Add `defer_voting_until_all_answered` config flag to AgentConfig
- [x] 9.9 Implement deferred voting with `_is_waiting_for_all_answers()` helper
- [x] 9.10 Update TuiModeState.get_orchestrator_overrides() for multi-agent refinement OFF
- [x] 9.11 Add `final_answer_strategy` config flag to AgentConfig and config exclusion lists
- [x] 9.12 Implement `winner_reuse`, `winner_present`, and `synthesize` branches in `_present_final_answer()`
- [x] 9.13 Ensure synthesis presentation receives all completed agent answers in presenter context
- [x] 9.14 Keep vote-based winner selection, but use the selected winner as synthesis presenter by default in multi-agent refinement OFF

## 10. Controller Integration
- [ ] 10.1 Modify `_run_turn()` to get mode state from adapter
- [ ] 10.2 Apply orchestrator overrides from mode state
- [ ] 10.3 Filter agents based on mode state

## 11. Slash Commands
- [ ] 11.1 Add `/plan` command to enter plan mode
- [ ] 11.2 Add `/execute [plan_id]` command
- [ ] 11.3 Add `/override` command to open override modal
- [ ] 11.4 Add `/mode` command to show current mode state

## 12. CSS Styling
- [ ] 12.1 Add ModeBar styles to dark.tcss
- [ ] 12.2 Add ModeBar styles to light.tcss
- [ ] 12.3 Add AgentTab.disabled styles
- [ ] 12.4 Add plan info display styles
- [ ] 12.5 Add override button styles

## 13. Context Path Write Access
- [ ] 13.1 Add `_has_write_context_paths()` helper to orchestrator
- [ ] 13.2 Add `_enable_context_write_access()` helper to orchestrator
- [x] 13.3 Refactor `skip_final_presentation` logic to handle write context paths
- [x] 13.4 Single agent: enable writes without LLM call when refinement OFF
- [x] 13.5 Multi-agent `winner_reuse`: require presentation only if write paths exist
- [x] 13.6 Multi-agent `synthesize`: run presentation even without write paths
- [x] 13.7 Add `recreate_container_for_write_access()` to FilesystemManager
- [x] 13.8 Call `recreate_container_for_write_access()` in orchestrator before final presentation

## 14. Context Path Write Tracking (Snapshot-based mtime comparison)
- [x] 14.1 Add `_context_path_snapshot: Dict[str, float]` to PathPermissionManager (path -> mtime)
- [x] 14.2 Add `snapshot_writable_context_paths()` method - walks dirs, stores path+mtime
- [x] 14.3 Add `compute_context_path_writes()` method - compares current state to snapshot, populates `_context_path_writes`
- [x] 14.4 Keep `get_context_path_writes()` method (returns computed list)
- [x] 14.5 Keep `clear_context_path_writes()` method (clears both snapshot and writes list)
- [x] 14.6 Call `snapshot_writable_context_paths()` in orchestrator before final presentation
- [x] 14.7 Call `compute_context_path_writes()` in orchestrator after final presentation
- [x] 14.8 Expose `get_context_path_writes()` through orchestrator
- [x] 14.9 Display written files in TUI final answer footer (inline if ≤5 files)
- [x] 14.10 Write full list to `{log_dir}/context_path_writes.txt` when >5 files
- [x] 14.11 Show summary with log path in footer for many files

## 15. Testing
- [x] 15.1 Test TuiModeState.get_orchestrator_overrides() logic
- [ ] 15.2 Test TuiModeState.get_effective_agents() filtering
- [ ] 15.3 Test tab bar disabled state
- [ ] 15.4 Manual test: plan mode flow end-to-end
- [ ] 15.5 Manual test: single-agent mode with tab selection
- [ ] 15.6 Manual test: refinement off behavior
- [ ] 15.7 Manual test: override post-completion
- [ ] 15.8 Manual test: single agent + refinement OFF + write context path
- [ ] 15.9 Manual test: multi-agent + refinement OFF + write context path
- [ ] 15.10 Manual test: multi-agent + refinement OFF + no write context path
- [ ] 15.11 Manual test: context path write tracking (inline display)
- [ ] 15.12 Manual test: context path write tracking (log file for many files)
- [ ] 15.13 Manual test: multi-agent + refinement OFF independent execution (no injection)
- [ ] 15.14 Manual test: multi-agent + refinement OFF deferred voting (agents wait for all)
- [x] 15.15 Add integration tests for `final_answer_strategy` branches (`winner_reuse`, `winner_present`, `synthesize`)
- [x] 15.16 Add regression test proving multi-agent + refinement OFF defaults to `synthesize`
