# MassGen v0.1.57 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.57, adding Delegated Subagent Protocol & Builder Subagent! 🚀 A new file-based delegation protocol enables container-to-host subagent spawning, and the builder subagent type handles large artifact generation with fresh context. Plus: Claude Code reasoning parameters for the updated SDK, smarter convergence with substantiveness tracking, and diagnostic report gating.

## Install

```bash
pip install massgen==0.1.57
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.57
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.57, adding Delegated Subagent Protocol & Builder Subagent! 🚀 A new file-based delegation protocol enables container-to-host subagent spawning, and the builder subagent type handles large artifact generation with fresh context. Plus: Claude Code reasoning parameters for the updated SDK, smarter convergence with substantiveness tracking, and diagnostic report gating.

**Key Features:**

**Subagent Delegation Protocol (MAS-325)** - File-based container-to-host subagent spawning:
- SubagentLaunchWatcher polls shared delegation directory for atomic JSON request/response files
- Workspace path validation against allowlist for security
- Enables subagent spawning without Docker API — agents write requests, host picks them up

**Builder Subagent** - New subagent type for substantial, pre-specified work:
- Transformative redesigns, large artifact generation, complex multi-file rewrites
- Fresh context with no anchoring to prior versions — prevents incremental drift
- Prescriptive spec with positive goals AND forbidden patterns (negative constraints)
- Auto-triggered by checklist when transformative changes are identified

**Also in this release:**
- Claude Code Reasoning Params: Updated SDK with unified `reasoning` config (type, effort, budget_tokens) replacing deprecated `max_thinking_tokens`
- Substantiveness Tracking: Checklist captures specific planned changes (transformative/structural/incremental) to prevent satisficing and trigger builder/novelty subagents
- Diagnostic Report Gating: Optional quality gate requiring structured diagnostic reports before checklist passes
- Simplified Subagent Workspaces: Auto-mounted parent workspace — no more `context_paths: ["./"]` boilerplate

**Bug Fixes:**
- Fixed codex backend subagent spawning
- Fixed subagent timing and synchronization
- Fixed temporary workspace directory support
- Fixed subagent type initialization

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.57

Feature highlights:

<!-- Paste feature-highlights.md content here -->
