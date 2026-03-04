# MassGen v0.1.59 — Quality Round Improvements

**Release Date:** March 4, 2026
**PyPI:** `pip install massgen==0.1.59`
**PR:** [#969](https://github.com/massgen/MassGen/pull/969)

---

## Highlights

This release focuses on **quality round improvements** — better planning, evaluation, subagents, and media fixes to make iterative refinement more effective.

### Planning Improvements
- **Auto-Add Improvements to Task Plan**: Improvements are now automatically incorporated into the task plan, giving agents better context for iteration
- **Plan Review Enhancements**: More thorough quality evaluation during plan review phases

### Checklist & Evaluation Enhancements
- **Better Eval Gen Config**: More accurate quality assessments with improved evaluation generation configuration
- **Checklist Fixes**: Consistent checklist behavior across quality rounds
- **Gemini Tool Name Normalization**: MCP tool name normalization for Gemini backend compatibility

### Subagent Improvements
- **Adjusted Subagent Behavior**: Subagent manager enhancements for better coordination and task delegation
- **Docker Skill Write Access**: Fixed write access for skills running in Docker containers

### Media Generation Fixes
- **Video Gen Skill Adjustments**: No fallback to animated on errors — fail cleanly instead of producing unexpected output
- **Video Understanding Criticality**: Improved video understanding importance in evaluations
- **Impact Metric Restoration**: Restored impact metrics for quality assessment

### Bug Fixes
- Fixed answer anonymization during evaluation
- Updated quickstart flow and test suite
- Small fixes for plan mode and Docker execution

---

## Contributors

- @ncrispino (7 commits)
- @HenryQi (1 commit)

---

## What's Next

**v0.1.60** — Improve Skill Use and Exploration ([#873](https://github.com/massgen/MassGen/issues/873)): Local skill execution, skill registry with hierarchical organization, and skill consolidation workflow.

---

**Full Changelog**: https://github.com/massgen/MassGen/compare/v0.1.58...v0.1.59
