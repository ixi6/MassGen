# MassGen v0.1.57 Roadmap

## Overview

Version 0.1.57 focuses on per-subagent runtime isolation in Docker environments and improving the iterative refinement loop for better convergence detection and quality-driven iteration.

- **Per-Subagent Runtime Isolation in Docker** (Required): True per-subagent isolation when parent runs in Docker
- **Improve Iterative Refinement** (Required): Better convergence detection and quality-driven iteration

## Key Technical Priorities

1. **Subagent Isolation**: Provide true per-subagent runtime isolation so each subagent has its own execution boundary when MassGen runs inside Docker
   **Use Case**: Subagent evaluators that launch local servers no longer interfere with one another

2. **Iterative Refinement**: Fix checklist off-ramp and convergence detection to distinguish genuine vs incremental improvement
   **Use Case**: Agents stop when quality is sufficient, push harder when there's real room to improve

## Key Milestones

### Milestone 1: Per-Subagent Runtime Isolation in Docker (REQUIRED)

**Goal**: True per-subagent runtime isolation when parent runs in Docker

**Owner**: @ncrispino (nickcrispino on Discord)

**Issue**: [#910](https://github.com/massgen/MassGen/issues/910)

#### 1.1 Runtime Architecture
- [ ] Define runtime architecture where subagents do not share command/process/network namespace by default
- [ ] Make launch mode explicit (no silent downgrade from docker to local for subagent execution paths)
- [ ] Eliminate port collisions, shared server state, and ambiguous timeout behavior

#### 1.2 Communication Contract
- [ ] Preserve existing subagent communication contract (answer files, workspace handoff, status/log streaming) across isolation modes
- [ ] Test containerized parent runs with concurrent subagents that each start local servers

#### 1.3 Testing & Validation
- [ ] Add tests covering containerized parent with concurrent server-launching subagents
- [ ] Verify subagent UX preserved (logs, status, streaming, cancellation, workspace/context semantics)
- [ ] Update documentation

**Success Criteria**:
- Subagents run in isolated runtime environments when parent is in Docker
- No port collisions or shared state between concurrent subagents
- Existing subagent communication contract preserved

---

### Milestone 2: Improve Iterative Refinement (REQUIRED)

**Goal**: Better convergence detection and quality-driven iteration

**Owner**: @ncrispino (nickcrispino on Discord)

**Issue**: [#874](https://github.com/massgen/MassGen/issues/874)

#### 2.1 Fix Checklist Off-Ramp
- [ ] Make `_checklist_required_true` respect voting threshold (currently hardcoded to all items)
- [ ] Relax off-ramp so convergence is reachable when only stretch items fail
- [ ] Fix core/stretch categorization to enable smarter convergence decisions

#### 2.2 Convergence Detection
- [ ] Implement improvement categorization: transformative, structural, incremental
- [ ] Add LLM-based comparison between round N and round N-1 answers
- [ ] Scale back overcorrection from low voting sensitivity when improvements are incremental

#### 2.3 Testing & Documentation
- [ ] Test convergence detection across different quality scenarios
- [ ] Verify checklist off-ramp behavior with various voting thresholds
- [ ] Document new convergence behavior and configuration options

**Success Criteria**:
- Checklist off-ramp respects voting threshold configuration
- Convergence detection distinguishes incremental from structural improvements
- Agents stop iterating when improvements are merely incremental

---

## Timeline

**Target Release**: February 27, 2026

### Phase 1 (Feb 25-26)
- Subagent Runtime Isolation (Milestone 1.1, 1.2)
- Checklist Off-Ramp Fix (Milestone 2.1)

### Phase 2 (Feb 26-27)
- Convergence Detection (Milestone 2.2)
- Testing & Validation (Milestones 1.3, 2.3)

---

## Success Metrics

- **Isolation Quality**: No port collisions or shared state between concurrent subagents in Docker
- **Convergence Accuracy**: Agents correctly identify when improvements are incremental vs structural
- **Off-Ramp Reachability**: Checklist convergence reachable with reasonable voting threshold settings

---

## Resources

- **Issue #910**: [Per-Subagent Runtime Isolation](https://github.com/massgen/MassGen/issues/910)
- **Issue #874**: [Improve Iterative Refinement](https://github.com/massgen/MassGen/issues/874)
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
- **v0.1.54**: Copilot SDK Backend (#862), Subagent Messaging (#926), Gemini 3.1 Pro
- **v0.1.55**: Specialized Subagent Types (#938), Dynamic Evaluation Criteria, Native Image Routing
- **v0.1.56**: Critic Subagent (#945), Spec Plan Mode, Audio Multimodal, ask_others Targeting

And sets the foundation for:
- **v0.1.58**: ElevenLabs TTS & STT (#942)
- **v0.1.59**: Improve skill use and exploration (#873)
