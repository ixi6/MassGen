# MassGen v0.1.61 Roadmap

**Target Release:** March 9, 2026

## Overview

Version 0.1.61 focuses on improving skill use and exploration — local execution, hierarchical registry, and consolidation workflows. This was originally planned for v0.1.60 but rolled forward as v0.1.60 delivered verification & decomposition improvements instead.

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

## Related Tracks

- **v0.1.60**: Multimodal Tools, Subagent Enhancements & GPT-5.4 — read_media rewrite, MediaCallLedgerHook, subagent backend inheritance, GPT-5.4, decomp+checklist cooperation ([#978](https://github.com/massgen/MassGen/pull/978))
- **v0.1.62**: Image/Video Edit Capabilities ([#959](https://github.com/massgen/MassGen/issues/959))
- **v0.1.63**: OpenAI Audio API ([#960](https://github.com/massgen/MassGen/issues/960))
