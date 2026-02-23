# Testing Module

## Goal

Build a fully automated testing system for MassGen across:

- Core Python orchestration and backends
- TUI event/rendering behavior
- WebUI stores/components/E2E flows
- Integration and nightly real-provider checks

The target workflow is test-first: agree on tests with the user, implement tests, then implement code until tests pass.

## Baseline (Validated on 2026-02-07)

- `102` Python test files in `massgen/tests/`
- `198` `Test*` classes in `massgen/tests/`
- `0` active xfail registry entries in `massgen/tests/xfail_registry.yml`
- CI runs `pytest` on push/PR via `.github/workflows/tests.yml`
- No first-party WebUI test files in `webui/src/`
- Frontend unit coverage has started in `massgen/tests/frontend/`:
  - `test_tool_batch_tracker.py`
  - `test_content_processor.py`
  - `test_content_handlers_helpers.py`
  - `test_timeline_event_recorder.py`
  - `test_timeline_section_widget.py`
  - `test_timeline_transcript_golden.py`
  - Golden transcript fixtures in `massgen/tests/frontend/golden/`
  - `test_timeline_snapshot_scaffold.py`
  - SVG snapshot fixtures in `massgen/tests/frontend/__snapshots__/`
    - Includes both widget-scoped snapshots and full runtime app snapshots (`TextualApp` layout)
- Deterministic non-API integration coverage has started in `massgen/tests/integration/`:
  - `test_orchestrator_voting.py`
  - `test_orchestrator_consensus.py`
  - `test_orchestrator_stream_enforcement.py`
  - `test_orchestrator_timeout_selection.py`
  - `test_orchestrator_restart_and_external_tools.py`
  - `test_orchestrator_hooks_broadcast_subagents.py`
  - `test_orchestrator_final_presentation_matrix.py`

## Marker Model

MassGen test selection now uses two separate axes:

- `integration`: test scope (multi-component integration behavior).
- `live_api`: real external provider calls (requires API keys, may incur cost).
- `expensive`: high-cost subset of tests (typically also `live_api`).
- `docker`: requires Docker runtime.

Default policy is to skip gated categories unless explicitly enabled.

- `--run-integration` or `RUN_INTEGRATION=1`
- `--run-live-api` or `RUN_LIVE_API=1`
- `--run-expensive` or `RUN_EXPENSIVE=1`
- `--run-docker` or `RUN_DOCKER=1`

Test log isolation:
- Pytest sets `MASSGEN_LOG_BASE_DIR` to a temporary session directory so test-generated logs do not mix with user `.massgen/massgen_logs/` runs.

## Testing Strategy
See `specs/002-testing-strategy/testing-strategy.md` for full information.

### P0: PR-Gated Fast Automation

1. Add `pytest` workflow in `.github/workflows/tests.yml` for every push/PR.
2. Keep gated tests off by default (`RUN_INTEGRATION=0`, `RUN_LIVE_API=0`, `RUN_EXPENSIVE=0`, `RUN_DOCKER=0`).
3. Add deterministic unit tests for:
   - `massgen/orchestrator.py`
   - `massgen/coordination_tracker.py`
   - `massgen/system_message_builder.py`
   - `massgen/mcp_tools/security.py`
4. Add TUI pipeline tests using:
   - `massgen/frontend/displays/timeline_event_recorder.py`
   - `massgen/frontend/displays/content_handlers.py`
   - `massgen/frontend/displays/content_processor.py`
5. Add WebUI tests (Vitest + Testing Library) for stores and critical components.

### P1: Deterministic UI Regression

1. TUI snapshot tests with `pytest-textual-snapshot`.
2. Golden transcript tests using `MASSGEN_TUI_TIMELINE_TRANSCRIPT`.
3. Playwright E2E for setup + coordination flows in WebUI.

### P2: Nightly Deep Validation

1. Nightly expensive tests against real providers.
2. Optional LLM-assisted visual/interaction checks for TUI and WebUI.

## TUI Testing Layers

1. Unit logic: `ToolBatchTracker`, helpers, normalization logic.
2. Event pipeline: `TimelineEventRecorder` with scripted `MassGenEvent` sequences.
3. Widget behavior: Textual `run_test(headless=True)` + Pilot.
4. Snapshot regression: SVG snapshots (`pytest-textual-snapshot`).
5. Transcript golden files: compare timeline structure instead of full text.

## WebUI Testing Layers

1. Store unit tests (`agentStore`, `wizardStore`, `workspaceStore`).
2. Utility tests (artifact detection, path normalization).
3. Component tests (cards, voting view, key workflow widgets).
4. Playwright E2E (setup gate, live coordination rendering, reconnect behavior).

## Recommended Package Baselines (2026 Refresh)

Python:

- `pytest` 9.x
- `pytest-asyncio` 1.3+
- `pytest-cov` 7.x
- `pytest-textual-snapshot` 1.1+
- `cairosvg` 2.8+ (optional, for SVG-to-PNG vision checks)

WebUI:

- `vitest` 4.x
- `@testing-library/react` 16.x
- `@testing-library/dom` (required peer for React Testing Library 16)
- `@testing-library/jest-dom` 6.9+
- `@testing-library/user-event` 14.x+
- `jsdom` 27.x
- `@playwright/test` 1.57+
- `msw` 2.12+

## LLM-Assisted Test Automation

WebUI:

- Prefer Playwright's native test agent workflow (`npx playwright init-agents`) for faster authoring, healing, and maintenance of E2E tests.

TUI:

- Keep deterministic tests as primary gate.
- Use LLM-driven terminal tools (`ht`, `agent-tui`) only as optional nightly evaluators, not PR gates.

## TDD Execution Contract

**TDD is the default development methodology.** See `CLAUDE.md` § "Test-Driven Development (TDD)" for the authoritative contract with full tables for when TDD applies, test placement, and anti-patterns.

The short version for every non-trivial change:

1. **Agree on acceptance tests** with the user — define pass/fail criteria before coding.
2. **Write tests first** that express the desired behavior.
3. **Confirm tests fail** for the right reason (missing feature, not test bug).
4. **Implement minimum code** until the test suite passes.
5. **Refactor under green** — clean up only while tests remain passing.
6. **Commit tests alongside code** — tests are permanent regression protection, not scaffolding.

This contract applies to backend logic, TUI behavior, WebUI behavior, config changes, and integration workflows. The only exception is trivial one-liner fixes where silent breakage is impossible.

## Instruction File Parity Hook

`CLAUDE.md` and `AGENTS.md` must remain identical. This repo uses a pre-commit hook:

- Hook id: `sync-agent-instructions`
- Script: `scripts/precommit_sync_agent_instructions.py`
- Behavior:
  - If one file changes, sync it to the other.
  - If both files change differently, fail and require manual merge.

## Core Commands

```bash
# Fast local suite
make test-fast

# Integration/expensive (manual or nightly)
make test-all

# Equivalent direct command for fast lane
uv run pytest massgen/tests --run-integration -m "not live_api and not docker and not expensive" -q --tb=no

# Non-API push gate (includes deterministic integration, excludes live provider calls/docker/expensive)
uv run pytest massgen/tests --run-integration -m "not live_api and not docker and not expensive" -q --tb=no

# Deterministic integration tests (non-costly)
uv run pytest massgen/tests/integration -q

# Timeline transcript goldens (Layer 4)
uv run pytest massgen/tests/frontend/test_timeline_transcript_golden.py -q
UPDATE_GOLDENS=1 uv run pytest massgen/tests/frontend/test_timeline_transcript_golden.py -q

# Textual SVG snapshots (Layer 3)
uv run pytest massgen/tests/frontend/test_timeline_snapshot_scaffold.py -q
uv run pytest massgen/tests/frontend/test_timeline_snapshot_scaffold.py --snapshot-update -q

# Force HTML report location for snapshot mismatches
uv run pytest massgen/tests/frontend/test_timeline_snapshot_scaffold.py -q --snapshot-report snapshot_report.html

# Live API integration tests (costly, explicit opt-in)
uv run pytest massgen/tests -m "integration and live_api" --run-integration --run-live-api -q

# WebUI unit tests (after setup)
cd webui && npm run test

# WebUI E2E (after setup)
cd webui && npx playwright test
```

## Viewing Snapshot Output

1. Run snapshot tests:
   - `uv run pytest massgen/tests/frontend/test_timeline_snapshot_scaffold.py -q`
2. If there is a mismatch, open the generated HTML report:
   - `snapshot_report.html` (project root by default)
3. In the HTML report, use `Show difference` carefully:
   - `ON`: blend-difference overlay (can look purple/black and is not raw baseline colors).
   - `OFF`: raw current and historical snapshots.
4. Inspect committed baseline SVGs directly:
   - `massgen/tests/frontend/__snapshots__/test_timeline_snapshot_scaffold/`
5. After intentional UI changes, regenerate baselines:
   - `uv run pytest massgen/tests/frontend/test_timeline_snapshot_scaffold.py --snapshot-update -q`
6. Snapshot tests that validate runtime shell visuals force color-capable env in-test (`TERM=xterm-256color`, `COLORTERM=truecolor`, unset `NO_COLOR`) to avoid monochrome captures.
7. If your tool cannot display `svg` directly, render with a browser engine (recommended):
   - `npx playwright screenshot "file:///ABS/PATH/to/snapshot.svg" /tmp/snapshot.png`
   - This preserves Textual styling and avoids conversion artifacts.
   - Batch helper: `uv run python scripts/render_snapshot_svgs.py --real-tui-only`
8. Avoid ImageMagick-based SVG conversion for Textual snapshots when checking typography/emoji fidelity; it can introduce mojibake-like artifacts that are not present in the source SVG.
9. For highest-fidelity UI checks, prioritize:
   - `test_timeline_snapshot_real_tui_round_view.svg`
   - `test_timeline_snapshot_real_tui_final_presentation_lock_mode.svg`
   These are full `TextualApp` shell snapshots, not widget-only scaffold captures.

## Synthetic TUI Demo (No API Cost)

To visually inspect a full timeline/final-presentation flow without calling any model APIs:

1. Lightweight replay (`--tui`): quick timeline-focused UI (not full runtime shell).
   - `uv run python scripts/dump_timeline_from_events.py --tui massgen/tests/frontend/fixtures/synthetic_tui_events.jsonl agent_a`
2. Real runtime replay (`--tui-real`): boots actual `TextualApp` shell and replays synthetic events through it.
   - `uv run python scripts/dump_timeline_from_events.py --tui-real massgen/tests/frontend/fixtures/synthetic_tui_events.jsonl agent_a`
3. Exit replay with `q` (or `Ctrl+D`).
4. Optional playback speed control for `--tui-real`:
   - `MASSGEN_TUI_REPLAY_SPEED=8 uv run python scripts/dump_timeline_from_events.py --tui-real massgen/tests/frontend/fixtures/synthetic_tui_events.jsonl agent_a`

Text-only replay (same events):
- `uv run python scripts/dump_timeline_from_events.py massgen/tests/frontend/fixtures/synthetic_tui_events.jsonl agent_a`

### Parity Notes (`--tui` vs `--tui-real`)

- `--tui` uses a minimal `EventReplayApp` around `TimelineSection` for quick debugging; layout can differ and may include extra vertical space.
- `--tui-real` runs the production `TextualApp` shell for high-fidelity visual checks without API cost.

Remaining obstacle to perfect parity: some runtime-only orchestration state (status timers, winner/tab transitions, workspace/status metadata, animation timing) is not fully encoded in `events.jsonl`. Full equivalence for every frame requires richer replay metadata or a recorder that captures additional shell-state transitions.

For regression gates, continue to rely on deterministic snapshot/golden tests in `massgen/tests/frontend/`.

## Skill Candidate (Future)

The synthetic replay workflow (`--tui` / `--tui-real`) is a strong candidate for a dedicated skill under `massgen/skills/` so contributors can quickly:

1. replay real run logs without API cost,
2. inspect timeline/render behavior in a consistent way,
3. generate follow-up debugging artifacts for testing and docs.

This fits best as an end-of-testing workflow for learning, debugging, and reproducing UI behavior before deciding whether to update snapshots/goldens.

## Integration Testing Across Backends

When creating integration tests that involve backend functionality (hooks, tool execution, streaming, compression, etc.), **test across all 5 standard backends**:

| Backend | Type | Model | API Style |
|---------|------|-------|-----------|
| Claude | `claude` | `claude-haiku-4-5-20251001` | anthropic |
| OpenAI | `openai` | `gpt-4o-mini` | openai |
| Gemini | `gemini` | `gemini-3-flash-preview` | gemini |
| OpenRouter | `chatcompletion` | `openai/gpt-4o-mini` | openai |
| Grok | `grok` | `grok-3-mini` | openai |

**Reference scripts**:
- `scripts/test_hook_backends.py` - Hook framework integration tests
- `scripts/test_compression_backends.py` - Context compression tests

**Integration test pattern**:
```python
BACKEND_CONFIGS = {
    "claude": {"type": "claude", "model": "claude-haiku-4-5-20251001"},
    "openai": {"type": "openai", "model": "gpt-4o-mini"},
    "gemini": {"type": "gemini", "model": "gemini-3-flash-preview"},
    "openrouter": {"type": "chatcompletion", "model": "openai/gpt-4o-mini", "base_url": "..."},
    "grok": {"type": "grok", "model": "grok-3-mini"},
}
```

Use `--verbose` flag to show detailed output (injection content, message formats, etc.).

## Native Multimodal Routing Tests (MAS-300)

`massgen/tests/test_native_multimodal_routing.py` verifies that `read_media` → `understand_image` routes image analysis to the agent's own backend (Claude, Gemini, Grok, Claude Code, Codex, OpenAI) instead of always hardcoding OpenAI.

### Unit tests (mocked, no API keys needed)

```bash
# All 24 unit tests — routing, wiring, capability checks, backend payload construction
uv run pytest massgen/tests/test_native_multimodal_routing.py -m "not live_api and not expensive" -v
```

Test categories:
- **Capability registry**: Verify `image_understanding` is declared for claude, openai, gemini, grok, claude_code, codex; absent for lmstudio.
- **Routing dispatch**: `understand_image(backend_type="claude")` calls `call_claude`, etc. Backends without the capability fall back to OpenAI gpt-5.2.
- **Wiring**: `read_media` passes `backend_type` and `model` through to `understand_image` in both single-file and batch modes. Config model overrides agent model.
- **Video routing**: `understand_video` skips `backend_selector` when the agent's backend has `video_understanding`.
- **Backend payload construction**: Each `call_*` function builds the correct wire format (mocked API clients).

### Live API tests (opt-in, expensive)

```bash
# Run with verbose output to see actual model responses
uv run pytest massgen/tests/test_native_multimodal_routing.py -m "live_api and expensive" -v -s --run-live-api --run-expensive
```

| Test | Backend | Requires |
|------|---------|----------|
| `test_call_openai_live` | OpenAI gpt-4.1 | `OPENAI_API_KEY` |
| `test_call_claude_live` | Claude claude-sonnet-4-5 | `ANTHROPIC_API_KEY` |
| `test_call_gemini_live` | Gemini gemini-3-flash-preview | `GOOGLE_API_KEY` or `GEMINI_API_KEY` |
| `test_call_grok_live` | Grok grok-4 | `XAI_API_KEY` |
| `test_call_claude_code_live` | Claude Code SDK | `claude` CLI installed + auth |
| `test_call_codex_live` | Codex CLI | `codex` CLI installed + auth |

Each test loads `massgen/configs/resources/v0.0.27-example/multimodality.jpg`, sends it to the backend, and asserts a non-empty response. Tests skip gracefully if the required key or CLI is unavailable.

## Pre-Commit vs Fast Lane

- `.pre-commit-config.yaml` includes a `pre-push` hook (`run-non-api-tests-on-push`) that runs the non-API lane.
- Enable it locally with: `uv run pre-commit install --hook-type pre-push`.
- The fast automation lane (`make test-fast` and `.github/workflows/tests.yml`) is where deterministic integration tests are expected to run.
- Live API tests stay opt-in behind `live_api` gating to avoid accidental paid runs.
