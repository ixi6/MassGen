# MassGen v0.1.65 Roadmap

**Target Release:** March 18, 2026

## Overview

Version 0.1.65 focuses on running MassGen as a cloud job on Modal.

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

- **v0.1.64**: Gemini CLI Backend — Gemini CLI, WebSocket streaming, execution trace analyzer, Copilot Docker ([#999](https://github.com/massgen/MassGen/pull/999), [#990](https://github.com/massgen/MassGen/pull/990), [#1002](https://github.com/massgen/MassGen/pull/1002))
- **v0.1.66**: OpenAI Audio API ([#960](https://github.com/massgen/MassGen/issues/960))
