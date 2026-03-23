# MassGen v0.1.68 Roadmap

**Target Release:** March 25, 2026

## Overview

Version 0.1.68 focuses on running MassGen as a cloud job on Modal.

---

## Feature: Cloud Modal MVP

**Issue:** [#982](https://github.com/massgen/MassGen/issues/982)
**Owner:** @ncrispino

### Goals

- **Cloud Execution**: Run MassGen jobs in the cloud via `--cloud` option on Modal
- Progress streams to terminal, results saved locally under `.massgen/cloud_jobs/`

### Success Criteria

- [ ] Cloud job execution functional on Modal
- [ ] Progress streaming and artifact extraction working

---

## Related Tracks

- **v0.1.67**: Modernized WebUI — WebUI, Budget Guard, pre-collab, regression guard ([#1016](https://github.com/massgen/MassGen/pull/1016), [#1013](https://github.com/massgen/MassGen/pull/1013))
- **v0.1.69**: OpenAI Audio API ([#960](https://github.com/massgen/MassGen/issues/960))
