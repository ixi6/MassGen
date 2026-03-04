# MassGen v0.1.59 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.59 — Quality Round Improvements! 🚀 Smarter planning with auto-added improvements and plan review. Agents now save replayable verification steps to `verification_latest.md`, auto-injected into future rounds so the next agent can replay the exact verification pipeline. Plus: checklist evaluation fixes, subagent enhancements, and media generation improvements.

## Install

```bash
pip install massgen==0.1.59
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.59
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.59 — Quality Round Improvements! 🚀 Smarter planning with auto-added improvements and plan review. Agents now save replayable verification steps to `verification_latest.md`, auto-injected into future rounds so the next agent can replay the exact verification pipeline. Plus: checklist evaluation fixes, subagent enhancements, and media generation improvements.

**Key Improvements:**

**Planning Improvements** - Smarter quality rounds:
- Auto-add improvements to task plan for better iteration tracking
- Plan review enhancements for more thorough quality evaluation
- Verification replay memories — agents save replayable verification steps (commands, scripts, artifacts) to `memory/short_term/verification_latest.md`, auto-injected into future rounds so the next agent can replay the exact verification pipeline

**Checklist & Evaluation Enhancements** - More reliable evaluations:
- Better eval gen config for more accurate quality assessments
- Checklist fixes for consistent behavior across rounds
- Gemini tool name normalization for MCP compatibility

**Also in this release:**
- Subagent Improvements: Adjusted subagent behavior, subagent manager enhancements, Docker skill write access fixes
- Media Generation Fixes: Video gen skill adjustments (no fallback to animated on errors), video understanding criticality, impact metric restoration
- Bug Fixes: Answer anonymization fix, quickstart and test updates, plan/Docker small fixes

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.59

Feature highlights:

<!-- Paste feature-highlights.md content here -->
