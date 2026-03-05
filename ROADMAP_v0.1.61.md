# MassGen v0.1.60 Roadmap

**Target Release:** March 6, 2026

## Overview

Version 0.1.60 focuses on improving skill use and exploration — local execution, hierarchical registry, and consolidation workflows.

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

- **v0.1.59**: Quality Round Improvements — planning improvements, checklist/eval enhancements, subagent improvements, media fixes ([#969](https://github.com/massgen/MassGen/pull/969))
- **v0.1.61**: Image/Video Edit Capabilities ([#959](https://github.com/massgen/MassGen/issues/959))
- **v0.1.62**: OpenAI Audio API ([#960](https://github.com/massgen/MassGen/issues/960))
