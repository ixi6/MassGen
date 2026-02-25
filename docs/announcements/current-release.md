# MassGen v0.1.56 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.56, adding Spec Plan Mode! 🚀 A new formal requirements specification workflow before execution with TUI spec mode support. Plus: critic subagent for quality assessment, targeted agent-to-agent messaging, media conversation continuity, and Codex OAuth login fix.

## Install

```bash
pip install massgen==0.1.56
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.56
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.56, adding Spec Plan Mode! 🚀 A new formal requirements specification workflow before execution with TUI spec mode support. Plus: critic subagent for quality assessment, targeted agent-to-agent messaging, media conversation continuity, and Codex OAuth login fix.

**Key Features:**

**Spec Plan Mode** - Formal requirements specification before execution:
- `plan_mode="spec"` for structured requirements gathering
- Ensures agents understand and agree on deliverables before coding begins
- Spec creation, approval modal, and dedicated TUI spec mode state

**Also in this release:**
- Critic Subagent: New subagent type for honest, unbiased quality assessment detecting genuine vs incremental improvement
- ask_others Targeting: `target_agents` parameter for focused agent-to-agent communication instead of broadcast
- read_media Continue: Follow-up conversations on supported media (image) via `continue_from` conversation_id
- Codex OAuth Login Fix: OAuth authentication fix for Codex backend in web UI

**Bug Fixes:**
- Test and spec reading fixes
- Audio cleanup for future release stability

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.56

Feature highlights:

<!-- Paste feature-highlights.md content here -->
