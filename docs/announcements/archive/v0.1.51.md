# MassGen v0.1.51 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.51, focused on Reviewing Coordination & Change Documents! 🚀 Review modal with multi-file diff visualization. Decision journal system for multi-agent coordination traceability. Changedoc-anchored evaluation checklists with gap reports. Drift conflict policy for safer change application. `--cwd-context` CLI flag.

## Install

```bash
pip install massgen==0.1.51
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.51
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.51, focused on Reviewing Coordination & Change Documents! 🚀 Review modal with multi-file diff visualization. Decision journal system for multi-agent coordination traceability. Changedoc-anchored evaluation checklists with gap reports. Drift conflict policy for safer change application. `--cwd-context` CLI flag.

**Key Features:**

**Change Documents (Changedoc)** - Decision journals for coordination:
- Agents write `tasks/changedoc.md` during coordination capturing decision provenance, rationale, and code traceability
- Changedocs passed to other agents in `<changedoc>` tags for shared decision awareness
- Config: `enable_changedoc: true` (default on)

**Changedoc-Anchored Evaluation** - Structured quality checklist:
- 5 changedoc-specific checklist items: Decision Completeness, Rationale Quality, Traceability, Output Quality, Novel Elements
- Mandatory gap report before verdict (`checklist_require_gap_report: true`)

**Review Modal Improvements** - Enhanced diff visualization:
- Multi-context, multi-file diff visualization with critique capabilities

**Drift Conflict Policy** - Safer change application:
- Configurable handling of target-file drift: `skip` (default), `prefer_presenter`, or `fail`

**Also in this release:**
- `--cwd-context` CLI flag for injecting CWD as context path (`ro`/`rw`)
- `.massgen_scratch/` scratch directory in worktrees for temporary agent files
- Mode bar responsive labels adapting to terminal width

**Bug Fixes:**
- Final presentation fallback for empty presentations
- Task execution timing fixes

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.51

Feature highlights:

<!-- Paste feature-highlights.md content here -->
