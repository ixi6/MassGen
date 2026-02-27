# MassGen v0.1.58 Roadmap

## Overview

Version 0.1.58 focuses on completing per-subagent runtime isolation in Docker, building on the file-based delegation protocol shipped in v0.1.57.

- **Per-Subagent Runtime Isolation in Docker** (Required): True container-based isolation for subagents spawned from a Docker parent

## Key Technical Priorities

1. **Docker Container Isolation**: Upgrade the delegation protocol from host-subprocess spawning to per-subagent Docker containers
   **Use Case**: Secure, isolated execution for parallel subagent tasks in containerized environments

## Key Milestones

### Milestone 1: Per-Subagent Docker Container Spawning (REQUIRED)

**Goal**: Subagents spawned from a Docker parent run in their own isolated containers instead of as host subprocesses

**Owner**: @ncrispino (nickcrispino on Discord)

**Issue**: [#910](https://github.com/massgen/MassGen/issues/910)

**Foundation**: v0.1.57 shipped the file-based delegation protocol (`launch_watcher.py`) with atomic JSON request/response exchange and workspace allowlist validation. This milestone upgrades the spawning target from host processes to Docker containers.

#### 1.1 Container Spawning Backend
- [ ] Extend `SubagentLaunchWatcher` to spawn subagents as Docker containers
- [ ] Container image selection and configuration (reuse parent image or configurable)
- [ ] Volume mounting for workspace directories and shared state
- [ ] Container lifecycle management (creation, monitoring, cleanup)

#### 1.2 Filesystem Isolation
- [ ] Per-subagent workspace isolation within containers
- [ ] Secure workspace path mapping between host and container
- [ ] Result collection from container filesystems back to host

#### 1.3 Networking & Communication
- [ ] Container-to-host communication for delegation protocol
- [ ] MCP server access from within containers
- [ ] API key forwarding to subagent containers

#### 1.4 Testing & Documentation
- [ ] Unit tests for container spawning logic
- [ ] Integration tests: subagent runs in container and returns results
- [ ] Backend parity tests (at minimum: one `base_with_custom_tool_and_mcp` backend, `claude_code`, `codex`)
- [ ] Update subagent documentation with Docker isolation configuration
- [ ] Add example configs in `massgen/configs/`

**Success Criteria**:
- Subagents spawn in isolated Docker containers (not host subprocesses)
- Workspace isolation enforced per-subagent container
- Delegation protocol upgraded from host-subprocess to container-based
- No regression in non-Docker subagent spawning

---

## Timeline

**Target Release**: March 2, 2026

### Phase 1 (Feb 28 - Mar 1)
- Container Spawning Backend (Milestone 1.1)
- Filesystem Isolation (Milestone 1.2)

### Phase 2 (Mar 1-2)
- Networking & Communication (Milestone 1.3)
- Testing & Documentation (Milestone 1.4)

---

## Success Metrics

- **Isolation**: Each subagent runs in its own Docker container with independent filesystem
- **Security**: Workspace paths validated and isolated per-container
- **Compatibility**: Non-Docker subagent spawning continues to work unchanged
- **Performance**: Container startup overhead acceptable for parallel subagent workflows

---

## Resources

- **Issue #910**: [Per-Subagent Runtime Isolation in Docker](https://github.com/massgen/MassGen/issues/910)
- **Owner**: @ncrispino (nickcrispino on Discord)
- **Foundation**: v0.1.57 delegation protocol (PR [#955](https://github.com/massgen/MassGen/pull/955))
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
- **v0.1.57**: Delegation Protocol (#955), Builder Subagent, Substantiveness Tracking, Claude Code Reasoning

And sets the foundation for:
- **v0.1.59**: ElevenLabs TTS & STT Support (#942)
- **v0.1.60**: Improve skill use and exploration (#873)
