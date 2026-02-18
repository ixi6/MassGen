# MassGen v0.1.54 Roadmap

## Overview

Version 0.1.54 focuses on adding spec support to planning workflows and targeted agent queries for more efficient coordination.

- **Spec Support for Planning Mode** (Required): Add spec/proposal support to planning workflows
- **Refactor ask_others for Targeted Agent Queries** (Required): Support targeted queries to specific agents

## Key Technical Priorities

1. **Spec Support for Planning**: Add spec/proposal support to planning workflows
   **Use Case**: Structured specification creation and review during planning mode

2. **Targeted Agent Queries**: Support targeted queries to specific agents via subagent spawning
   **Use Case**: More efficient coordination by querying specific agents rather than broadcasting to all

## Key Milestones

### Milestone 1: Spec Support for Planning Mode (REQUIRED)

**Goal**: Add spec/proposal support to planning workflows

**Owner**: @ncrispino (nickcrispino on Discord)

**Issue**: [#881](https://github.com/massgen/MassGen/issues/881)

#### 1.1 Spec Integration
- [ ] Design spec format and workflow for planning mode
- [ ] Implement spec creation and review capabilities
- [ ] Integrate with existing planning infrastructure

#### 1.2 Testing & Validation
- [ ] Test spec workflows end-to-end
- [ ] Verify integration with planning mode
- [ ] Update documentation

**Success Criteria**:
- Spec support integrated into planning workflows
- Specs can be created, reviewed, and applied during planning

---

### Milestone 2: Refactor ask_others for Targeted Agent Queries (REQUIRED)

**Goal**: Support targeted queries to specific agents via subagent spawning

**Owner**: @ncrispino (nickcrispino on Discord)

**Issue**: [#809](https://github.com/massgen/MassGen/issues/809)

#### 2.1 Targeted Query Implementation
- [ ] Implement `ask_others(target_agent_id="Agent-1", question="...")` mode
- [ ] Implement selective broadcast with `agent_prompts` dict
- [ ] Pass full `_streaming_buffer` to shadow agents for improved context

#### 2.2 Testing & Documentation
- [ ] Test all three modes: broadcast to all, selective broadcast, targeted ask
- [ ] Verify context passing via streaming buffer
- [ ] Document new query modes

**Success Criteria**:
- Targeted `ask_others` working for specific agent queries
- Selective broadcast with per-agent prompts functional
- Improved context passing via streaming buffer

---

## Timeline

**Target Release**: February 20, 2026

### Phase 1 (Feb 18-19)
- Spec Support for Planning (Milestone 1)
- Targeted Query Implementation (Milestone 2.1)

### Phase 2 (Feb 19-20)
- Testing & Validation (Milestones 1.2, 2.2)

---

## Success Metrics

- **Spec Quality**: Specs capture structured requirements during planning
- **Query Efficiency**: Targeted queries reduce unnecessary agent communication
- **Compatibility**: Seamless integration with existing coordination workflows

---

## Resources

- **Issue #881**: [Spec Support for Planning Mode](https://github.com/massgen/MassGen/issues/881)
- **Issue #809**: [Refactor ask_others for Targeted Agent Queries](https://github.com/massgen/MassGen/issues/809)
- **Owner**: @ncrispino (nickcrispino on Discord)
- **Related PRs**: TBD

---

## Related Tracks

This release builds on previous work:
- **v0.1.49**: Fairness Gate, Checklist Voting, Log Analysis TUI (#869)
- **v0.1.50**: Chunked Plan Execution (#877), Skill Lifecycle Management (#878)
- **v0.1.51**: Change Documents (#896), Changedoc Evaluation, Drift Conflict Policy
- **v0.1.52**: Final Answer Modal (#901), Substantive Gate, Novelty Injection, Agent Identity
- **v0.1.53**: Background Tools & Specialized Subagents (#917)

And sets the foundation for:
- **v0.1.55**: Quickstart model curation (#840), TUI screenshot support (#831)
- **v0.1.56**: Per-agent isolated write contexts (#854), multi-turn round/log fixes (#848)
