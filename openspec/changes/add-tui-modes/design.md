# Design: TUI Mode System

## Context
The Textual TUI needs native mode toggles to seamlessly switch between different multi-agent workflows without CLI restarts. This brings MassGen's multi-agent capabilities into a simple coding agent UX.

**Stakeholders**: TUI users who want quick mode switching during interactive sessions.

## Goals / Non-Goals

### Goals
- Enable plan→execute workflow entirely within TUI
- Allow single-agent mode without restarting with different config
- Toggle refinement behavior (voting) on/off
- Override final answer selection before presentation
- Preserve context across mode changes

### Non-Goals
- Dynamic agent addition/removal during session (future work)
- Custom voting strategies (beyond on/off)
- Multi-agent refinement auto-prompts (noted as future enhancement)
- Post-completion override/redo (deferred to future spec)

## Decisions

### Decision: Mode State Location
Store mode state in a dedicated `TuiModeState` dataclass on the TextualApp instance.

**Rationale**: Centralizes mode logic, makes it easy to serialize/restore, and keeps compose() clean.

**Alternatives considered**:
- Scatter state across multiple widgets → harder to reason about, sync issues
- Store in orchestrator → TUI shouldn't depend on orchestrator internals

### Decision: Mode Bar Position
Position Mode Bar inside `#input_area` container, above the input hint line.

**Rationale**: User's eyes are near input area; mode toggles are quick-access controls.

**Alternatives considered**:
- Header → too far from input, breaks visual flow
- Status bar → too small, cluttered with agent status

### Decision: Single-Agent Voting Behavior
Single agent keeps voting when refinement is ON. Only skip voting when refinement is OFF.

**Rationale**: The vote acts as a "I'm done refining" signal. Even with one agent, allowing them to decide "my answer is ready" vs "let me try again" is valuable for iterative refinement.

**Alternatives considered**:
- Always skip voting for single agent → loses the "I'm satisfied" signal
- Force vote after first answer → too rigid, doesn't allow refinement

### Decision: Multi-Agent Quick Mode Final Answer Strategy
Introduce a `final_answer_strategy` setting with `winner_reuse`, `winner_present`, and `synthesize`. In multi-agent + refinement OFF quick mode, default it to `synthesize`.

**Rationale**: Independent first drafts are useful only if the final stage can preserve complementary strengths. Reusing the voted winner is fast, but it often throws away the best ideas from losing drafts. Default synthesis keeps quick mode lightweight while making better use of parallel work.

**Alternatives considered**:
- Keep winner reuse as the default quick-mode behavior → fastest path, but lowest leverage from multiple agents
- Force decomposition mode for synthesis → wrong mental model for users who want parallel independent drafts rather than owned subtasks
- Add a separate "combine mode" with no shared strategy flag → more UI complexity for a concept that is really one final-answer policy choice

### Decision: Override Timing
Allow override AFTER voting completes but BEFORE final presentation starts.

**Rationale**: Chosen agent can write to workspace normally. No special handling needed. Post-completion redo adds complexity (workspace conflicts) - defer to future spec.

**Alternatives considered**:
- Post-completion redo → workspace file conflicts, complex recovery needed
- Only during voting → too restrictive, user may not have reviewed all answers yet

## Risks / Trade-offs

### Risk: Mode State Drift
If mode state gets out of sync with orchestrator config during long sessions.

**Mitigation**: Mode state generates config overrides fresh on each turn. No persistent orchestrator-side state.

### Risk: Plan Mode Subprocess Complexity
Running planning phase may spawn subprocess or require async orchestrator call.

**Mitigation**: Use existing PlanStorage infrastructure. Planning runs through normal orchestrator with planning flag.

## Key Integration Points

### TUI → Controller → Orchestrator Flow
```
TextualApp._mode_state
    ↓ get_orchestrator_overrides()
InteractiveSessionController._run_turn()
    ↓ merge overrides into config
Orchestrator.chat() with modified config
```

### Single-Agent Tab Selection
```
User clicks tab in single-agent mode
    ↓ AgentTab.on_click()
    ↓ _mode_state.selected_single_agent = agent_id
    ↓ _tab_bar.set_single_agent_mode(True, agent_id)
    ↓ Other tabs get "disabled" class
```

### Override Flow
```
Voting completes
    ↓ TUI shows: "Press Ctrl+O to override, Enter to continue"
    ↓ If Ctrl+O: show OverrideModal with all answers
    ↓ User selects different agent
    ↓ Set orchestrator._selected_agent = chosen_agent
    ↓ Continue to presentation phase
    ↓ Chosen agent does final presentation
```

### Quick Multi-Agent Synthesis Flow
```
Refinement OFF + multi-agent
    ↓ each agent produces one independent answer
    ↓ deferred voting starts after all agents have answered
    ↓ selected agent is chosen from votes
    ↓ final_answer_strategy=synthesize
    ↓ selected agent receives all completed answers in presenter context
    ↓ selected agent synthesizes one final answer
```

## Open Questions
- Should mode bar be collapsible/hideable for minimal UI mode? (defer)
- Should we persist mode state across TUI restarts? (defer)
