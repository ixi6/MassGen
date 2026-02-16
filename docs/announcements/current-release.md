# MassGen v0.1.52 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.52, focused on Final Answer Modal & Coordination Quality Gates! 🚀 Dedicated final answer modal with tabbed answer and workspace/review interface. Substantive gate prevents low-value iteration rounds. Novelty injection combats premature convergence. Agent identity versioning for answer provenance tracking.

## Install

```bash
pip install massgen==0.1.52
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.52
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.52, focused on Final Answer Modal & Coordination Quality Gates! 🚀 Dedicated final answer modal with tabbed answer and workspace/review interface. Substantive gate prevents low-value iteration rounds. Novelty injection combats premature convergence. Agent identity versioning for answer provenance tracking.

**Key Features:**

**Dedicated Final Answer Modal** - Tabbed answer review:
- Answer tab with markdown content, post-evaluation, and file list; Workspace/Review Changes tab for diff review
- Trophy header with agent identity and model name
- Approve/Reject/Cancel action bar with rework controls for iteration

**Substantive Gate** - Quality gate for coordination:
- Prevents coordination from continuing when only incremental changes are planned
- Tracks `transformative`/`structural`/`incremental` classification with `decision_space_exhausted` detection
- Config: `require_substantiveness: true` (mandatory in checklist)

**Novelty Injection** - Creative pressure against convergence:
- Configurable injection when agents converge — levels: `none`, `gentle`, `moderate`, `aggressive`
- Pressure increases after failed iteration restarts
- Config: `novelty_injection` in coordination section

**Agent Identity & Versioning** - Answer provenance:
- Versioned answer labels (e.g., `agent1.2`) with `answer_label_mapping` for tracking

**Also in this release:**
- First answer non-restart: first answers no longer trigger automatic restarts on quality check failure
- Subagent evaluation infrastructure for delegating evaluation to spawned subagent instances

**Bug Fixes:**
- Approved/rejected state display in final answer card
- Auto-open workspace behavior
- Final answer view in main timeline
- Tool spacing in final card

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.52

Feature highlights:

<!-- Paste feature-highlights.md content here -->
