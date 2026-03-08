# MassGen v0.1.55 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.55, adding Specialized Subagent Types & Dynamic Evaluation Criteria! 🚀 Specialized subagent roles (evaluator, explorer, researcher, novelty) with a discovery-based type system via `SUBAGENT.md` frontmatter. Dynamic task-specific evaluation criteria with core/stretch gates replace static checklists. Plus: native backend routing for image understanding, configurable video frame extraction, and composition documentation.

## Install

```bash
pip install massgen==0.1.55
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.55
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.55, adding Specialized Subagent Types & Dynamic Evaluation Criteria! 🚀 Specialized subagent roles (evaluator, explorer, researcher, novelty) with a discovery-based type system via `SUBAGENT.md` frontmatter. Dynamic task-specific evaluation criteria with core/stretch gates replace static checklists. Plus: native backend routing for image understanding, configurable video frame extraction, and composition documentation.

**Key Features:**

**Specialized Subagent Types** - Discovery-based system for specialized subagent roles:
- Built-in types: evaluator (programmatic verification), explorer (investigation), researcher (deep analysis), novelty (breaks refinement plateaus)
- `SUBAGENT.md` frontmatter for role definition
- TUI visualization for subagent roles

**Dynamic Evaluation Criteria** - GEPA-inspired task-specific quality gates:
- Task-specific evaluation criteria generation replacing static E1-E4 items
- Domain-specific presets (persona, decomposition, evaluation, prompt, analysis)
- Core/stretch categorization for smarter convergence off-ramps
- Score scale 0-10, config: `evaluation_criteria_generator`

**Native Backend Image Routing** - `understand_image` now routes to agent's own backend:
- Claude, Gemini, Grok, Claude Code, Codex all use their native vision capabilities
- Fallback to OpenAI for backends without `image_understanding` capability

**Also in this release:**
- Configurable Video Frame Extraction: Scene-based (PySceneDetect) or uniform extraction with `max_frames` cost guardrail
- Remotion Skill in Quickstart: Video generation/editing skill installed when selected during quickstart
- Checklist System Update: T-prefix to E-prefix naming, 0-100 to 0-10 score scale, core/stretch item categories
- Unified Pre-Collaboration: Persona generation, decomposition, and eval criteria generation unified as composable primitives

**Bug Fixes:**
- Background subagent cancel name fix
- Initial TUI sizing fix

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.55

Feature highlights:

<!-- Paste feature-highlights.md content here -->
