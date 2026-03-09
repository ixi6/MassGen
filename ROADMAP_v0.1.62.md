# MassGen v0.1.62 Roadmap

**Target Release:** March 11, 2026

## Overview

Version 0.1.62 focuses on improving skill use and exploration — local execution, hierarchical registry, and consolidation workflows — plus adding a Gemini CLI backend. Skill use was originally planned for v0.1.60 but rolled forward as subsequent releases delivered other improvements instead.

---

## Feature: Improve Skill Use and Exploration

**Issue:** [#873](https://github.com/massgen/MassGen/issues/873)
**Owner:** @ncrispino

### Goals

- **Local Skill Execution**: Enable skills to run in local (non-Docker) mode via a local MCP tool for skill reading
- **Skill Registry**: Hierarchical organization replacing flat skill inclusion in system prompts, reducing prompt bloat
- **Skill Consolidation**: Cleanup submode in analyze mode for merging overlapping skills
- **TUI Indicator**: Visual signal when skill cleaning threshold is reached

### Success Criteria

- [ ] Skills usable in local (non-Docker) mode
- [ ] Skill registry created and used in system prompts
- [ ] Skill consolidation workflow available in analyze mode
- [ ] TUI indicator for skill cleaning threshold

---

## Feature: Gemini CLI Backend

**Issue:** [#952](https://github.com/massgen/MassGen/issues/952)
**Owner:** @ncrispino

### Goals

- **Gemini CLI Backend**: Add Gemini CLI as a first-class backend option alongside Claude Code and Codex

### Success Criteria

- [ ] Gemini CLI backend functional and tested

---

## Related Tracks

- **v0.1.61**: Round Evaluator Paradigm — new round evaluator subagent type, orchestrator refactoring, evaluation improvements ([#986](https://github.com/massgen/MassGen/pull/986))
- **v0.1.63**: Image/Video Edit Capabilities ([#959](https://github.com/massgen/MassGen/issues/959))
- **v0.1.64**: OpenAI Audio API ([#960](https://github.com/massgen/MassGen/issues/960))
