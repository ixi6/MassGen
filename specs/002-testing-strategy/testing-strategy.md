# MassGen Comprehensive Testing Strategy

## Executive Summary

MassGen currently has **80 test files** with **200 test classes** but suffers from critical gaps:

- **No CI test execution** — pytest never runs in CI; only linting/formatting checks exist
- **Zero TUI tests** — 70+ files in `massgen/frontend/` with no automated coverage
- **Zero WebUI tests** — No Vitest/Playwright setup, no test files
- **Core modules untested** — `orchestrator.py`, `chat_agent.py`, `coordination_tracker.py` have no unit tests
- **Security untested** — `mcp_tools/security.py` has no tests
- **18 expired xfails (as of 2026-02-06)** — stale known-failure entries needing cleanup
- **Manual-only integration testing** — scripts in `scripts/` require manual runs with API keys

This strategy addresses all gaps with a phased rollout prioritizing maximum impact per effort.

---

## Current State

### What Exists
| Category | Count | Notes |
|----------|-------|-------|
| Python test files | 80 | Under `massgen/tests/` |
| Test classes | 200 | `class Test*` classes in `massgen/tests/` |
| XFail registry entries | 29 | In `massgen/tests/xfail_registry.yml` |
| Expired xfails | 18 | Expired as of `2026-02-06` |
| Manual scripts | 5 | In `scripts/`, run outside pytest |
| CI workflows | 8 | None run pytest — only pre-commit, docs, release |
| TUI tests | 0 | Complete gap |
| WebUI tests | 0 | Complete gap |

### What Works Well
- **conftest.py gating** — integration/docker/expensive markers with CLI flags
- **xfail registry** — YAML-based known-failure tracking with expiry dates
- **Mock patterns** — 4 established patterns (MagicMock, subclass, mixin, SDK patch)
- **`--automation` mode** — Clean programmatic entry point via `massgen.run()`

### Critical Gaps
1. **No CI pytest execution** (highest impact gap)
2. **No orchestrator/coordination unit tests** (core logic untested)
3. **No TUI/WebUI automated tests** (all UI testing is manual)
4. **No shared mock fixtures** (each test file creates its own mocks)
5. **No coverage tracking** (pytest-cov configured but never run)

---

## Testing Pyramid

```
                    /\
                   /  \        E2E Tests
                  / E2E\       - Real API calls (expensive, nightly)
                 /------\      - Playwright WebUI flows
                /        \     - Full orchestration runs
               / Integr.  \
              /   Tests    \   Integration Tests (CI, no API keys)
             /--------------\  - MockLLMBackend orchestration flows
            /                \ - Tool execution with mock MCP
           /    Unit Tests    \- WebSocket event processing
          /                    \
         /______________________\  Unit Tests (CI, fast)
                                   - ToolBatchTracker state machine
                                   - ContentProcessor event handling
                                   - Config validation
                                   - Store logic (WebUI)
                                   - All pure functions
```

---

## Phase 1: Foundation (Highest Impact, ~1 week)

### 1.1 Add pytest to CI

Create `.github/workflows/tests.yml`:

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --all-extras
      - run: uv run pytest massgen/tests/ -v --tb=short -x
        env:
          RUN_INTEGRATION: "0"
          RUN_EXPENSIVE: "0"
          RUN_DOCKER: "0"
```

### 1.2 Clean up expired xfails

13 of 22 xfail entries are expired. For each:
- If the underlying issue is fixed → remove the xfail entry
- If the test is genuinely broken → fix it or update the expiry date
- If the feature was removed → delete the test

### 1.3 Create shared mock fixtures

Add to `massgen/tests/conftest.py`:

```python
# --- Shared Mock Backend ---

class MockLLMBackend:
    """Deterministic mock backend for integration testing.

    Provides scripted responses without API calls.
    Implements the stream_with_tools interface.
    """

    def __init__(self, responses=None, tool_call_responses=None):
        self.responses = responses or ["Mock response"]
        self.tool_call_responses = tool_call_responses or []
        self._call_count = 0
        self.agent_id = "mock_agent"
        self.is_stateful_val = False

    def is_stateful(self):
        return self.is_stateful_val

    async def stream_with_tools(self, messages, tools=None, **kwargs):
        response = self.responses[self._call_count % len(self.responses)]
        self._call_count += 1
        yield {"type": "content", "content": response}
        yield {"type": "complete_message", "complete_message": {"role": "assistant", "content": response}}
        yield {"type": "done"}


@pytest.fixture
def mock_backend():
    """Factory for mock backends with configurable responses."""
    def _factory(responses=None, **kwargs):
        return MockLLMBackend(responses=responses, **kwargs)
    return _factory


@pytest.fixture
def mock_agent(mock_backend):
    """Factory for mock agents."""
    def _factory(agent_id="test_agent", responses=None, system_message="Test"):
        backend = mock_backend(responses=responses)
        return SingleAgent(backend=backend, agent_id=agent_id, system_message=system_message)
    return _factory


@pytest.fixture
def mock_orchestrator(mock_agent):
    """Factory for orchestrator with N mock agents."""
    def _factory(num_agents=2, agent_responses=None):
        agents = {}
        for i in range(num_agents):
            agent_id = f"agent_{chr(ord('a') + i)}"
            responses = agent_responses[i] if agent_responses else None
            agents[agent_id] = mock_agent(agent_id=agent_id, responses=responses)
        return Orchestrator(agents=agents)
    return _factory
```

### 1.4 Add core module unit tests

Priority test files to create:

| New Test File | Target Module | Key Tests |
|---------------|--------------|-----------|
| `test_coordination_tracker.py` | `coordination_tracker.py` | Vote tallying, consensus detection, tie-breaking, round management |
| `test_orchestrator_unit.py` | `orchestrator.py` | Phase transitions, agent state management, enforcement logic |
| `test_system_message_builder.py` | `system_message_builder.py` | System prompt construction, section ordering |
| `test_mcp_security.py` | `mcp_tools/security.py` | Path validation, operation blocking, allowlist/denylist |
| `test_config_validator_extended.py` | `config_validator.py` | All backend types, edge cases, invalid configs |

### 1.5 Add instruction parity hook (AGENTS.md = CLAUDE.md)

Add a local pre-commit hook that synchronizes `CLAUDE.md` and `AGENTS.md` so agent instructions never drift:

- If only one file changed, copy it to the other file and stage both.
- If both files changed and differ, fail with a manual-merge message.
- Keep this as a required hook in `.pre-commit-config.yaml`.

---

## Phase 2: TUI Testing & Visual Evaluation (~2 weeks)

This is the most critical and novel section. The TUI is the primary user interface and the hardest to test. We propose a **5-layer** approach that ranges from pure unit tests to LLM-driven interactive evaluation.

### 2.1 Existing Infrastructure (Already Built — This Is Huge)

MassGen has **significant** debug/recording/replay infrastructure that can be leveraged immediately:

- **`timeline_transcript.py`** — Set `MASSGEN_TUI_TIMELINE_TRANSCRIPT=/path/to/file` to record every timeline event (text, tools, batches, separators) as structured text. This is a **golden file testing goldmine**.
- **`timeline_event_recorder.py`** — Contains `TimelineEventRecorder` class with `_MockTimeline` and `_MockPanel` that replay events through the **real TUI pipeline** (same filtering, deduplication, batching) **without any Textual dependency**. This is a ready-made unit testing seam.
- **`dump_timeline_from_events.py`** — Two modes:
  - **Text mode**: `uv run python scripts/dump_timeline_from_events.py /path/to/events.jsonl [agent_id]` — dumps transcript
  - **TUI mode**: `--tui` flag — creates a full `EventReplayApp` with real `TimelineSection` widgets, tab bar, and keyboard navigation. **This is already a visual test harness.**
- **`tui_debug.py`** — `tui_log()` function, writes to `/tmp/tui_debug.log`
- **`MASSGEN_TUI_TIMELINE_EVENTS`** env var — Emits timeline entries as events
- **`textual-ui-developer` skill** — Documented workflow using `textual-serve` for browser-based TUI development

**Key insight**: The `TimelineEventRecorder` uses mock widgets that capture rendering calls via callbacks. This means you can feed it a sequence of `MassGenEvent` objects and assert on exactly what the TUI **would** render — all in a fast unit test with zero Textual overhead. The `ContentProcessor` → `TimelineEventAdapter` → `TimelineSection` pipeline is fully testable through this path.

**Actual installed Textual version**: `6.2.1` (major version jump from the `>=0.47.0` constraint in pyproject.toml).
**Upstream latest**: `7.5.0` (plan a compatibility pass before adopting a new major).

### 2.2 Tool Landscape (Research Findings)

| Tool | Purpose | Format | Best For |
|------|---------|--------|----------|
| **Textual Pilot** | Built-in widget testing | Programmatic | Unit/widget tests |
| **pytest-textual-snapshot** | SVG visual regression | SVG | Detecting pixel-level regressions |
| **VHS (Charmbracelet)** | Terminal recording from scripts | GIF/MP4/PNG/TXT | Golden file testing, demo generation |
| **asciinema** | Terminal session recording | asciicast/text | Session replay, text extraction |
| **ht (Headless Terminal)** | JSON API for terminal interaction | JSON/text | LLM-driven terminal testing |
| **agent-tui** | MCP server for terminal control | MCP protocol | LLM agents driving TUI directly |
| **CairoSVG** | SVG → PNG conversion | PNG | Converting Textual screenshots for LLM vision |
| **@unblessed/vrt** | Terminal visual regression | SGR-encoded text | Configurable-threshold comparison |
| **Playwright Test Agents** | AI-assisted test authoring/repair | Playwright tests | WebUI E2E generation and maintenance |

### 2.3 Layer 1: Pure Unit Tests (No Textual, No Rendering)

These are fast, deterministic, and test the core logic. **Highest priority.**

**Using the existing `TimelineEventRecorder` for pipeline tests:**
```python
from massgen.frontend.displays.timeline_event_recorder import TimelineEventRecorder
from massgen.events import MassGenEvent, EventType

def test_event_pipeline_tool_batching():
    """Test that consecutive MCP tools from same server get batched."""
    rendered = []
    recorder = TimelineEventRecorder(agent_id="agent_a", callback=rendered.append)

    # Feed events through the real pipeline
    recorder.process_event(MassGenEvent.create(
        EventType.TOOL_START, agent_id="agent_a",
        tool_id="t1", tool_name="mcp__fs__read_file", args={"path": "/tmp/a.txt"}
    ))
    recorder.process_event(MassGenEvent.create(
        EventType.TOOL_START, agent_id="agent_a",
        tool_id="t2", tool_name="mcp__fs__write_file", args={"path": "/tmp/b.txt"}
    ))

    # Assert the pipeline batched them
    batch_lines = [l for l in rendered if "batch" in l.lower()]
    assert len(batch_lines) > 0, "Consecutive MCP tools should be batched"

def test_event_pipeline_content_breaks_batch():
    """Text content between tools should prevent batching."""
    rendered = []
    recorder = TimelineEventRecorder(agent_id="agent_a", callback=rendered.append)

    recorder.process_event(MassGenEvent.create(
        EventType.TOOL_START, agent_id="agent_a",
        tool_id="t1", tool_name="mcp__fs__read_file"
    ))
    recorder.process_event(MassGenEvent.create(
        EventType.TEXT, agent_id="agent_a", content="Some thinking..."
    ))
    recorder.process_event(MassGenEvent.create(
        EventType.TOOL_START, agent_id="agent_a",
        tool_id="t2", tool_name="mcp__fs__write_file"
    ))

    # Should have two standalone tools, no batch
    batch_lines = [l for l in rendered if "convert_to_batch" in l.lower()]
    assert len(batch_lines) == 0, "Tools with text between them should not batch"
```

**Direct ToolBatchTracker and ContentProcessor tests:**

**`tests/frontend/test_tool_batch_tracker.py`** — Tests the Timeline Chronology Rule:
```python
from massgen.frontend.displays.content_handlers import ToolBatchTracker, ToolDisplayData

def _make_tool(tool_id, tool_name, status="running"):
    return ToolDisplayData(
        tool_id=tool_id, tool_name=tool_name, display_name=tool_name,
        tool_type="mcp", category="filesystem", icon="F", color="blue",
        status=status, start_time=datetime.now(),
    )

def test_consecutive_mcp_tools_batch():
    tracker = ToolBatchTracker()
    action1, *_ = tracker.process_tool(_make_tool("t1", "mcp__fs__read"))
    assert action1 == "pending"
    action2, server, batch_id, pending_id = tracker.process_tool(_make_tool("t2", "mcp__fs__write"))
    assert action2 == "convert_to_batch"
    assert server == "fs"
    assert pending_id == "t1"

def test_content_breaks_batch():
    tracker = ToolBatchTracker()
    tracker.process_tool(_make_tool("t1", "mcp__fs__read"))
    tracker.mark_content_arrived()  # text between tools
    action, *_ = tracker.process_tool(_make_tool("t2", "mcp__fs__write"))
    assert action == "pending"  # NOT convert_to_batch

def test_non_mcp_tool_standalone():
    tracker = ToolBatchTracker()
    action, *_ = tracker.process_tool(_make_tool("t1", "web_search"))
    assert action == "standalone"

def test_third_tool_adds_to_batch():
    tracker = ToolBatchTracker()
    tracker.process_tool(_make_tool("t1", "mcp__fs__read"))
    tracker.process_tool(_make_tool("t2", "mcp__fs__write"))
    action, server, batch_id, _ = tracker.process_tool(_make_tool("t3", "mcp__fs__list"))
    assert action == "add_to_batch"

def test_reset_clears_state():
    tracker = ToolBatchTracker()
    tracker.process_tool(_make_tool("t1", "mcp__fs__read"))
    tracker.reset()
    # Next tool should start fresh
```

**`tests/frontend/test_content_processor.py`** — Tests event → output pipeline:
```python
from massgen.frontend.displays.content_processor import ContentProcessor

def test_tool_start_creates_output():
    processor = ContentProcessor()
    event = MassGenEvent.create(EventType.TOOL_START, tool_id="t1", tool_name="mcp__fs__read")
    output = processor.process_event(event, round_number=1)
    assert output.output_type == "tool"
    assert output.tool_data.status == "running"

def test_thinking_filters_whitespace():
    processor = ContentProcessor()
    event = MassGenEvent.create(EventType.THINKING, content="   ")
    assert processor.process_event(event, 1) is None

def test_status_info_level_skipped():
    processor = ContentProcessor()
    event = MassGenEvent.create(EventType.STATUS, message="Done", level="info")
    assert processor.process_event(event, 1) is None
```

**`tests/frontend/test_content_helpers.py`** — Tests helper functions:
```python
from massgen.frontend.displays.content_handlers import (
    get_mcp_server_name, get_mcp_tool_name, summarize_args, summarize_result
)

def test_get_mcp_server_name():
    assert get_mcp_server_name("mcp__filesystem__write_file") == "filesystem"
    assert get_mcp_server_name("web_search") is None

def test_summarize_args_truncation():
    result = summarize_args({"path": "a" * 200}, max_len=40)
    assert len(result) <= 40
```

### 2.4 Layer 2: Widget Tests (Textual Pilot)

Uses Textual's `app.run_test(headless=True)` + `Pilot` for isolated widget tests.

**Important caveat**: `App.run_test()` is incompatible with pytest fixtures. Must be called inside each test function directly.

```python
from textual.app import App, ComposeResult

class ToolCardTestApp(App):
    def compose(self) -> ComposeResult:
        yield ToolCallCard(tool_name="mcp__fs__read_file", tool_type="mcp", call_id="test1")

@pytest.mark.asyncio
async def test_tool_card_status_transitions():
    app = ToolCardTestApp()
    async with app.run_test(headless=True) as pilot:
        card = app.query_one(ToolCallCard)
        assert card.status == "running"
        card.set_result("File contents", "Full contents...")
        await pilot.pause()
        assert card.status == "success"

class TimelineTestApp(App):
    def compose(self) -> ComposeResult:
        yield TimelineSection(id="timeline")

@pytest.mark.asyncio
async def test_timeline_tool_batch_chronology():
    app = TimelineTestApp()
    async with app.run_test(headless=True, size=(120, 40)) as pilot:
        timeline = app.query_one(TimelineSection)
        timeline.add_tool(tool_data_1, round_number=1)
        timeline.add_tool(tool_data_2, round_number=1)  # same server → batch
        timeline.add_text("Some text", round_number=1)
        timeline.add_tool(tool_data_3, round_number=1)  # after text → standalone
        await pilot.pause()
        batches = timeline.query(ToolBatchCard)
        standalones = timeline.query(ToolCallCard)
        assert len(batches) == 1
        assert len(standalones) == 1
```

### 2.5 Layer 3: SVG Snapshot Testing (Visual Regression)

Add `pytest-textual-snapshot` for visual regression. Note from Harlequin maintainer: "These tests are easy to get started with, but super brittle — changing a single pixel fails the test. The tradeoffs are worth it to me because I really care about quality."

```bash
# Add to pyproject.toml dev dependencies:
# "pytest-textual-snapshot>=1.0"
```

```python
def test_tool_card_running(snap_compare):
    assert snap_compare(ToolCardTestApp(), terminal_size=(80, 10))

def test_timeline_mixed_content(snap_compare):
    async def setup(pilot):
        timeline = pilot.app.query_one(TimelineSection)
        timeline.add_tool(tool_data, round_number=1)
        timeline.add_text("Processing...", round_number=1)
        await pilot.pause()
    assert snap_compare(TimelineTestApp(), run_before=setup, terminal_size=(120, 40))

# Update snapshots when intentional changes are made:
# pytest --snapshot-update
```

### 2.6 Layer 4: Golden File Testing with Timeline Transcripts

Leverage the existing `timeline_transcript.py` infrastructure. This is the **most practical automated E2E approach** — run MassGen with `MASSGEN_TUI_TIMELINE_TRANSCRIPT` enabled and compare output against golden files.

```python
# scripts/test_tui_golden.py

import subprocess
import difflib

GOLDEN_DIR = Path("massgen/tests/golden/tui/")

def run_massgen_with_transcript(config_yaml, question, transcript_path):
    """Run MassGen and capture timeline transcript."""
    env = os.environ.copy()
    env["MASSGEN_TUI_TIMELINE_TRANSCRIPT"] = str(transcript_path)
    result = subprocess.run(
        ["uv", "run", "massgen", "--automation", "--config", config_yaml, question],
        env=env, capture_output=True, timeout=120,
    )
    return result.returncode

def test_two_agent_timeline_golden():
    """Compare timeline transcript against golden file."""
    transcript = tmp_path / "transcript.txt"
    run_massgen_with_transcript("two_agents.yaml", "What is 2+2?", transcript)

    actual = transcript.read_text().splitlines()
    golden = (GOLDEN_DIR / "two_agent_basic.txt").read_text().splitlines()

    # Compare structure (event types, ordering) not exact content
    actual_structure = [line.split(":")[0].strip() for line in actual]
    golden_structure = [line.split(":")[0].strip() for line in golden]
    assert actual_structure == golden_structure, \
        "\n".join(difflib.unified_diff(golden_structure, actual_structure))
```

### 2.7 Layer 5: LLM-Driven Interactive Testing (Advanced)

This is the frontier — using an LLM to observe and evaluate the TUI interactively.

#### Option A: `ht` (Headless Terminal) + LLM

[`ht`](https://github.com/andyk/ht) wraps any terminal binary with a JSON API, specifically designed for LLM interaction.

```bash
# Install
cargo install --git https://github.com/andyk/ht

# Start MassGen in headless terminal
echo '{"type": "sendKeys", "keys": ["uv run massgen --config two_agents.yaml", "Enter"]}' | ht bash

# Take snapshot (returns terminal state as text)
echo '{"type": "takeSnapshot"}' | ht bash
```

**Integration with Claude/LLM evaluation:**
```python
import subprocess
import json

class HeadlessTerminalTester:
    """Drive MassGen TUI via ht and evaluate with LLM."""

    def __init__(self):
        self.process = subprocess.Popen(
            ["ht", "bash", "--size", "120x40"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )

    def send_keys(self, keys):
        cmd = json.dumps({"type": "sendKeys", "keys": keys})
        self.process.stdin.write(cmd.encode() + b"\n")
        self.process.stdin.flush()

    def take_snapshot(self):
        cmd = json.dumps({"type": "takeSnapshot"})
        self.process.stdin.write(cmd.encode() + b"\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def evaluate_with_llm(self, snapshot, criteria):
        """Send terminal snapshot to LLM for evaluation."""
        # Use Claude API to evaluate the TUI state
        # "Does the TUI show agent tabs? Are tools batched correctly?
        #  Is the voting visualization visible?"
        pass
```

#### Option B: `agent-tui` MCP Server

[`agent-tui`](https://github.com/pproenca/agent-tui) provides MCP-native terminal control. An LLM agent can directly interact with the running TUI.

```bash
# Install
npm install -g agent-tui

# Start a terminal session
agent-tui start --name massgen

# Send commands
agent-tui type --name massgen "uv run massgen --config two_agents.yaml 'What is 2+2?'"
agent-tui key --name massgen Enter

# Take screenshot (text representation)
agent-tui screenshot --name massgen
```

#### Option C: VHS for Deterministic Recording

[VHS](https://github.com/charmbracelet/vhs) scripts terminal interactions and outputs GIF/MP4/**TXT** for comparison.

```tape
# massgen_test.tape
Output massgen_test.gif
Output massgen_test.txt   # Golden file for comparison!

Set Shell "bash"
Set Width 120
Set Height 40

Type "uv run massgen --config two_agents.yaml 'What is 2+2?'"
Enter
Sleep 30s
Screenshot massgen_screenshot.png
```

The `.txt` output is ideal for golden file comparison in CI:
```bash
vhs massgen_test.tape
diff massgen_test.txt golden/massgen_test.txt
```

#### Option D: Textual SVG → PNG → LLM Vision

Convert Textual's SVG screenshots to PNG and evaluate with a multimodal LLM:

```python
import cairosvg
from anthropic import Anthropic

async def capture_and_evaluate():
    app = TextualApp()
    async with app.run_test(headless=True, size=(120, 40)) as pilot:
        # ... drive the app to a state ...
        svg_string = app.export_screenshot()

        # Convert SVG to PNG for LLM vision
        png_bytes = cairosvg.svg2png(bytestring=svg_string.encode())

        # Evaluate with Claude vision
        client = Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64",
                     "media_type": "image/png",
                     "data": base64.b64encode(png_bytes).decode()}},
                    {"type": "text", "text":
                     "Evaluate this TUI screenshot. Check:\n"
                     "1. Are agent tabs visible and labeled?\n"
                     "2. Is the timeline showing content chronologically?\n"
                     "3. Are tool calls displayed with status indicators?\n"
                     "4. Is the voting visualization correct?\n"
                     "Rate each 1-5 and explain issues."}
                ]
            }]
        )
```

### 2.8 Tool Comparison Matrix

| Capability | Textual Pilot | agent-tui | ht | tmux/libtmux | VHS | pexpect |
|---|---|---|---|---|---|---|
| Element selection (CSS) | Yes | Partial (VOM) | No | No | No | No |
| Keyboard input | Yes | Yes | Yes (JSON) | Yes | Yes (tape) | Yes |
| Mouse input | Yes (click, hover) | No | No | No | No | No |
| Wait for condition | Yes (pause) | Yes (wait text) | Poll | Manual poll | Sleep | Yes (expect) |
| Screenshot/capture | SVG | Text/JSON | Text (snapshot) | Text (capture-pane) | GIF/PNG/TXT | Raw output |
| Visual regression | SVG diff | No | No | No | TXT diff | No |
| Runs in real terminal | No (headless) | Yes (PTY) | Yes (PTY) | Yes (real tmux) | Yes (PTY) | Yes (PTY) |
| Works with any TUI | No (Textual only) | Yes | Yes | Yes | Yes | Partially |
| CI-friendly | Yes | Yes | Yes | Yes | Yes | Yes |
| LLM integration | Via SVG→PNG→Vision | MCP native | JSON native | Via capture | Via TXT output | Via expect |

### 2.10 Recommended TUI Testing Stack

| Layer | Tool | CI? | Cost | Priority |
|-------|------|-----|------|----------|
| 1. Unit tests | pytest + TimelineEventRecorder | Yes | Free | **P0 — Do first** |
| 2. Widget tests | Textual Pilot (`run_test(headless=True)`) | Yes | Free | **P0** |
| 3. Snapshot tests | pytest-textual-snapshot | Yes | Free | P1 |
| 4. Golden transcripts | timeline_transcript.py + diff | Yes | Free* | **P0** |
| 5. Real terminal E2E | tmux/libtmux (launch in real PTY, capture-pane) | Yes | Free | P1 |
| 6. LLM evaluation | ht/agent-tui + Claude Vision | Nightly | ~$0.50/run | P2 |

*Golden transcripts require `--run-expensive` for real API calls, but the comparison logic itself is free.

### 2.11 Dependencies to Add

```toml
# pyproject.toml [project.optional-dependencies] or dev deps
"pytest>=9.0.2",
"pytest-asyncio>=1.3.0",
"pytest-cov>=7.0.0",
"pytest-textual-snapshot>=1.1.0",
"cairosvg>=2.8.2",   # For SVG→PNG conversion (LLM vision)
```

---

## Phase 3: WebUI Testing (~1 week)

### 3.1 Framework: Vitest + React Testing Library + Playwright

**Stack:**
- **Vitest** — Native Vite integration, fast, same transforms
- **@testing-library/react** — Component testing
- **Playwright** — E2E browser testing
- **MSW (Mock Service Worker)** — API/WebSocket mocking
- **Playwright Test Agents** — AI-assisted E2E authoring and healing (`npx playwright init-agents`)

### 3.2 Setup

Add to `webui/package.json` devDependencies:
```json
{
  "vitest": "^4.0.0",
  "@testing-library/react": "^16.3.2",
  "@testing-library/dom": "^10.4.1",
  "@testing-library/jest-dom": "^6.9.1",
  "@testing-library/user-event": "^14.0.0",
  "jsdom": "^27.2.0",
  "@playwright/test": "^1.57.0",
  "msw": "^2.12.7"
}
```

Create `webui/vitest.config.ts`:
```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/__tests__/setup.ts'],
    css: true,
  },
});
```

### 3.3 Test Plan

#### Tier 1: Store Unit Tests (highest value)

**`src/__tests__/stores/agentStore.test.ts`** — Most critical:
```typescript
describe('agentStore.processWSEvent', () => {
  beforeEach(() => useAgentStore.setState(initialState));

  it('handles init event - creates agents with models', () => {
    const store = useAgentStore.getState();
    store.processWSEvent({
      type: 'init', session_id: 's1', timestamp: 1, sequence: 1,
      question: 'test', agents: ['agent_a', 'agent_b'],
      agent_models: { agent_a: 'gpt-4o', agent_b: 'claude-3' },
    });
    expect(store.agents.agent_a.modelName).toBe('gpt-4o');
  });

  it('handles vote_cast - updates distribution', () => { ... });
  it('handles consensus_reached - transitions to finalStreaming', () => { ... });
  it('handles state_snapshot - restores full session state', () => { ... });
  it('deduplicates votes in same round', () => { ... });
});
```

**`src/__tests__/stores/wizardStore.test.ts`**:
```typescript
describe('wizardStore', () => {
  it('skips apiKeys step when provider has key', () => { ... });
  it('skips setupMode for single agent', () => { ... });
  it('generates correct agent IDs (agent_a, agent_b, ...)', () => { ... });
});
```

#### Tier 2: Utility Tests

```typescript
describe('detectArtifactType', () => {
  it('detects HTML from extension', () => { ... });
  it('detects mermaid from content', () => { ... });
  it('defaults to code for unknown', () => { ... });
});
```

#### Tier 3: Component Tests

```typescript
describe('AgentCard', () => {
  it('renders agent name with model', () => { ... });
  it('shows winner crown when isWinner=true', () => { ... });
  it('shows round dropdown when multiple rounds', () => { ... });
});
```

#### Tier 4: E2E Tests (Playwright)

```typescript
test('setup page redirects when not configured', async ({ page }) => {
  await page.route('/api/setup/status', route =>
    route.fulfill({ json: { needs_setup: true } })
  );
  await page.goto('/');
  await expect(page).toHaveURL('/setup');
});

test('coordination shows agent cards during streaming', async ({ page }) => {
  // Mock WebSocket, send events, verify cards appear
});
```

---

## Phase 4: Integration Tests Without API Keys (~1 week)

### 4.1 Strategy

Use the shared `MockLLMBackend` from Phase 1 to test full orchestration flows without API calls.

### 4.2 Key Scenarios

| # | Scenario | What It Tests |
|---|----------|--------------|
| 1 | 3-agent voting flow | Vote tallying, winner selection |
| 2 | Unanimous consensus | Early termination |
| 3 | Tie-breaking | Tie-break logic |
| 4 | Agent failure recovery | Restart with corrective message |
| 5 | Final presentation fallback | Empty presentation → stored answer |
| 6 | Backend factory | `create_backend()` returns correct class |
| 7 | Config validation matrix | All provider types validated |
| 8 | Hook deny/inject | Security hooks block/inject correctly |
| 9 | MCP tool registration | Tools registered and discoverable |
| 10 | Streaming buffer accumulation | Content accumulates correctly |
| 11 | Compression trigger | Threshold exceeded → compression |
| 12 | Multi-turn conversation | History preserved across turns |

### 4.3 Fixture: Scenario-Based Agent Factory

```python
def make_voting_agents(votes: dict[str, str], answers: dict[str, str]):
    """Create agents with scripted answers and votes.

    Args:
        votes: {agent_id: voted_for_agent_id}
        answers: {agent_id: answer_text}
    """
    agents = {}
    for agent_id, answer in answers.items():
        vote_target = votes[agent_id]
        agents[agent_id] = MockAgent(
            agent_id=agent_id,
            responses=[
                answer,                           # Phase 1: initial answer
                f'{{"vote": "{vote_target}"}}',   # Phase 2: vote
                answer,                           # Phase 3: presentation
            ]
        )
    return agents
```

---

## Phase 5: Nightly E2E with Real APIs (~ongoing)

### 5.1 Strategy

Run expensive tests nightly against real APIs. Budget: ~$1-2/night.

### 5.2 CI Workflow

```yaml
name: Nightly E2E
on:
  schedule:
    - cron: '0 6 * * *'  # 6am UTC daily
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --all-extras
      - run: uv run pytest massgen/tests/ -v --run-expensive --run-integration -k "expensive or integration"
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
          XAI_API_KEY: ${{ secrets.XAI_API_KEY }}
```

### 5.3 Cross-Backend Matrix

Follow the established pattern from `scripts/test_hook_backends.py`:

| Backend | Type | Model | API Style |
|---------|------|-------|-----------|
| Claude | `claude` | `claude-haiku-4-5-20251001` | anthropic |
| OpenAI | `openai` | `gpt-4o-mini` | openai |
| Gemini | `gemini` | `gemini-3-flash-preview` | gemini |
| OpenRouter | `chatcompletion` | `openai/gpt-4o-mini` | openai |
| Grok | `grok` | `grok-3-mini` | openai |

---

## File Structure

```
massgen/tests/
├── conftest.py                          # Add shared mock fixtures
├── mocks/
│   ├── __init__.py
│   ├── mock_backend.py                  # MockLLMBackend
│   └── mock_factories.py               # Scenario-based factories
├── unit/
│   ├── test_coordination_tracker.py     # NEW
│   ├── test_orchestrator_unit.py        # NEW
│   ├── test_system_message_builder.py   # NEW
│   └── test_mcp_security.py            # NEW
├── frontend/
│   ├── __init__.py
│   ├── test_tool_batch_tracker.py       # NEW - TUI
│   ├── test_content_processor.py        # NEW - TUI
│   ├── test_content_normalizer.py       # NEW - TUI
│   └── test_timeline_section.py         # NEW - TUI (widget tests)
├── integration/
│   ├── test_orchestrator_voting.py      # NEW
│   ├── test_orchestrator_consensus.py   # NEW
│   ├── test_hook_integration.py         # NEW (migrate from scripts/)
│   └── test_backend_factory.py          # NEW
└── [existing test files unchanged]

webui/
├── vitest.config.ts                     # NEW
├── playwright.config.ts                 # NEW
├── src/
│   └── __tests__/
│       ├── setup.ts                     # NEW - test setup
│       ├── stores/
│       │   ├── agentStore.test.ts       # NEW
│       │   ├── wizardStore.test.ts      # NEW
│       │   └── themeStore.test.ts       # NEW
│       ├── utils/
│       │   └── artifactTypes.test.ts    # NEW
│       ├── components/
│       │   ├── AgentCard.test.tsx        # NEW
│       │   └── VoteVisualization.test.tsx # NEW
│       └── e2e/
│           ├── setup-flow.spec.ts       # NEW
│           └── coordination.spec.ts     # NEW

.github/workflows/
├── tests.yml                            # NEW - pytest on every PR
└── nightly-e2e.yml                      # NEW - expensive tests nightly
```

---

## Implementation Roadmap

| Phase | Duration | Impact | Effort |
|-------|----------|--------|--------|
| **1. Foundation** | ~1 week | **Critical** — CI testing, mock fixtures, core unit tests | Medium |
| **2. TUI Testing** | ~2 weeks | **Critical** — 5-layer approach: unit → widget → snapshot → golden → LLM | High |
| **3. WebUI Testing** | ~1 week | **High** — Store tests, component tests, E2E setup | Medium |
| **4. Integration Tests** | ~1 week | **High** — Orchestrator flows without API keys | Medium |
| **5. Nightly E2E** | ~2 days | **Medium** — Real API validation on schedule | Low |

**Recommended order**: Phase 1 → Phase 2 (Layers 1-2) → Phase 4 → Phase 2 (Layers 3-5) → Phase 3 → Phase 5

Rationale: Phase 1 unblocks everything. TUI Layers 1-2 (unit + widget tests) are fast wins that test the core display logic — ToolBatchTracker and ContentProcessor are the most exercised code paths in daily use. Phase 4 tests orchestration. TUI Layers 3-5 (snapshots, golden files, LLM eval) are more effort but provide visual confidence. Phase 3 covers WebUI. Phase 5 adds nightly real-API coverage.

## TDD Execution Contract

For non-trivial feature work:

1. Align with the user on acceptance tests and pass/fail criteria first.
2. Implement tests before implementation changes.
3. Run tests to confirm expected failure first.
4. Implement code until the agreed tests pass.
5. Keep tests in CI so implementation can be safely automated later.

**Quick wins to start today:**
1. Add `pytest` to CI (Phase 1.1) — 30 minutes
2. Write ToolBatchTracker unit tests (Phase 2.3) — pure Python, 1-2 hours
3. Enable timeline transcript golden files (Phase 2.6) — leverages existing infrastructure

---

## Success Metrics

| Metric | Current | Target (3 months) |
|--------|---------|-------------------|
| CI runs pytest | Yes | Yes, every PR |
| Unit test coverage | ~30% estimated | 60%+ |
| Core modules tested | 0/5 | 5/5 |
| TUI automated tests | 0 | 20+ |
| WebUI automated tests | 0 | 30+ |
| Integration tests (no API) | 32 | 15+ |
| Expired xfails | 0 | 0 |
| Manual testing required | High | Low (E2E for validation only) |

---

## Implementation Status (as of 2026-02-09)

### Phase 1: Foundation

- [x] 1.1 Add pytest to CI (`.github/workflows/tests.yml`)
- [x] 1.2 Clean up expired/stale xfails (`massgen/tests/xfail_registry.yml`)
- [x] 1.3 Add shared mock fixtures in `massgen/tests/conftest.py`
- [x] 1.4a Add `coordination_tracker` core unit test file (`massgen/tests/unit/test_coordination_tracker.py`)
- [x] 1.4b Add remaining core unit test files (`orchestrator`, `system_message_builder`, `mcp_tools/security`)
  - [x] `orchestrator`: `massgen/tests/unit/test_orchestrator_unit.py`
  - [x] `system_message_builder`: `massgen/tests/unit/test_system_message_builder.py`
  - [x] `mcp_tools/security`: `massgen/tests/unit/test_mcp_security.py`
- [x] 1.5 Add AGENTS/CLAUDE instruction parity hook (`sync-agent-instructions`)

### Phase 2: TUI Testing

- [x] Layer 1 baseline: `ToolBatchTracker` unit tests
- [x] Layer 1 baseline: `ContentProcessor` unit tests
- [x] Layer 1 completion: helper-function coverage
  - [x] `massgen/tests/frontend/test_content_handlers_helpers.py`
  - [x] `massgen/tests/frontend/test_timeline_event_recorder.py`
- [x] Layer 2 widget tests (Textual Pilot)
  - [x] Initial timeline widget coverage
  - [x] `massgen/tests/frontend/test_timeline_section_widget.py`
- [x] Layer 3 snapshot tests (`pytest-textual-snapshot`)
  - [x] Plugin enabled (`pytest-textual-snapshot`)
  - [x] Initial SVG snapshot coverage
  - [x] Runtime Textual app snapshot coverage (full `TextualApp` layout)
  - [x] `massgen/tests/frontend/test_timeline_snapshot_scaffold.py`
  - [x] `massgen/tests/frontend/__snapshots__/test_timeline_snapshot_scaffold/test_timeline_snapshot_baseline.svg`
  - [x] `massgen/tests/frontend/__snapshots__/test_timeline_snapshot_scaffold/test_timeline_snapshot_batch_card.svg`
  - [x] `massgen/tests/frontend/__snapshots__/test_timeline_snapshot_scaffold/test_timeline_snapshot_final_presentation_lock_mode.svg`
  - [x] `massgen/tests/frontend/__snapshots__/test_timeline_snapshot_scaffold/test_timeline_snapshot_real_tui_round_view.svg`
  - [x] `massgen/tests/frontend/__snapshots__/test_timeline_snapshot_scaffold/test_timeline_snapshot_real_tui_final_presentation_lock_mode.svg`
- [x] Layer 4 golden transcript tests
  - [x] Initial chronology golden coverage
  - [x] Expanded chronology coverage (restart, final-presentation round transition, cross-server non-batching)
  - [x] `massgen/tests/frontend/test_timeline_transcript_golden.py`
  - [x] `massgen/tests/frontend/golden/consecutive_mcp_batch.txt`
  - [x] `massgen/tests/frontend/golden/different_servers_no_batch.txt`
  - [x] `massgen/tests/frontend/golden/final_presentation_round_transition.txt`
  - [x] `massgen/tests/frontend/golden/restart_deferred_banner.txt`
  - [x] `massgen/tests/frontend/golden/text_breaks_batch_sequence.txt`
- [ ] Layer 5 LLM-assisted terminal evaluation

### Phase 3: WebUI Testing

- [ ] Postponed by team decision (2026-02-09)
- [ ] Vitest + RTL setup
- [ ] Store tests (`agentStore`, `wizardStore`)
- [ ] Playwright smoke flows

### Phase 4: Non-API Integration Tests

- [x] Scenario suite using deterministic mock backend
  - [x] `massgen/tests/integration/test_orchestrator_voting.py`
  - [x] `massgen/tests/integration/test_orchestrator_consensus.py`
  - [x] `massgen/tests/integration/test_orchestrator_stream_enforcement.py`
  - [x] `massgen/tests/integration/test_orchestrator_timeout_selection.py`
  - [x] Phase 4 quality gate met: 32 deterministic non-API integration tests (`10+` required)

### Phase 5: Nightly E2E

- [ ] Nightly real-API workflow (`.github/workflows/nightly-e2e.yml`)

---

## Quality Gates and Exit Criteria

Each phase is complete only when all gates below are satisfied.

| Phase | Required Gates |
|-------|----------------|
| 1. Foundation | `tests.yml` runs on PRs, xfail cleanup complete, shared mock fixtures merged |
| 2. TUI Testing | ToolBatchTracker + ContentProcessor tests in CI, widget tests passing, at least 5 golden transcript tests |
| 3. WebUI Testing | Vitest in CI, store tests for `agentStore` and `wizardStore`, at least 2 Playwright smoke flows |
| 4. Integration | 10+ non-API integration tests passing in CI with deterministic fixtures |
| 5. Nightly E2E | Nightly workflow green for 7 consecutive runs with failure alerting enabled |

Global exit criteria:

1. `uv run pytest massgen/tests/ -v` must pass on every PR.
2. No expired xfail entry may remain in `massgen/tests/xfail_registry.yml`.
3. New core behavior changes must include at least one unit or integration test in the same PR.
4. Any intentional snapshot/golden updates must include a short rationale in the PR description.

---

## 30-60-90 Day Delivery Plan

### First 30 Days

1. Land Phase 1 completely.
2. Implement TUI Layer 1 tests for:
   - `ToolBatchTracker`
   - `ContentProcessor`
   - `TimelineEventRecorder` pipeline behavior
3. Add at least 5 orchestrator integration tests using `MockLLMBackend`.

### Days 31-60

1. Add TUI Layer 2 widget tests and initial snapshot coverage.
2. Stand up WebUI Vitest stack and add store tests.
3. Migrate 2 manual scripts from `scripts/` into pytest integration tests.

### Days 61-90

1. Enable Nightly E2E real-API workflow.
2. Add Playwright WebUI smoke tests for setup and coordination flows.
3. Reach target metrics:
   - 20+ TUI tests
   - 30+ WebUI tests
   - 15+ no-API integration tests

---

## Ownership and Review Model

| Area | Primary Owner | Secondary Owner | Review Requirement |
|------|---------------|-----------------|--------------------|
| Core backend and orchestration tests | Backend maintainers | Release maintainer | 1 backend maintainer approval |
| TUI tests and snapshots | Frontend/TUI maintainers | Backend maintainer | 1 TUI maintainer approval |
| WebUI tests | WebUI maintainers | Frontend/TUI maintainer | 1 WebUI maintainer approval |
| CI workflows and flake policy | Release maintainer | Backend maintainer | 1 release maintainer approval |

Pull request requirements for testing-related changes:

1. Include exact command(s) used for local verification.
2. Include test output summary (passed/failed/skipped counts).
3. If adding an xfail, include issue link and expiry date.

---

## Flaky Test and Failure Policy

### Classification

| Class | Definition | Required Action |
|-------|------------|-----------------|
| Deterministic failure | Fails repeatedly in same code path | Fix before merge |
| Intermittent/flaky | Non-deterministic pass/fail | Quarantine immediately and open tracking issue |
| External dependency failure | API/service outage or rate limits | Retry in nightly; do not block regular PR CI |

### Rules

1. A flaky test may be quarantined for a maximum of 14 days.
2. Quarantined tests must have:
   - `@pytest.mark.flaky`
   - Linked tracking issue
   - Owner and expected fix date
3. If a test flakes 3 times in 7 days, treat it as a release blocker until resolved or quarantined.

---

## Initial High-Value Test Backlog

Implement these first for maximum defect detection:

1. `massgen/tests/unit/test_coordination_tracker.py::test_consensus_detected_unanimous_vote`
2. `massgen/tests/unit/test_coordination_tracker.py::test_tie_breaker_selects_expected_winner`
3. `massgen/tests/unit/test_orchestrator_unit.py::test_phase_transitions_initial_to_enforcement` ✅
4. `massgen/tests/unit/test_orchestrator_unit.py::test_presentation_fallback_uses_stored_answer` ✅
5. `massgen/tests/unit/test_mcp_security.py::test_path_traversal_blocked` ✅
6. `massgen/tests/unit/test_mcp_security.py::test_allowlisted_operation_permitted` ✅
7. `massgen/tests/frontend/test_tool_batch_tracker.py::test_content_breaks_batch`
8. `massgen/tests/frontend/test_tool_batch_tracker.py::test_third_tool_adds_to_batch`
9. `massgen/tests/frontend/test_content_processor.py::test_status_info_level_skipped`
10. `massgen/tests/frontend/test_content_processor.py::test_tool_start_creates_output`
11. `massgen/tests/integration/test_orchestrator_voting.py::test_three_agent_voting_flow` ✅
12. `massgen/tests/integration/test_orchestrator_consensus.py::test_unanimous_consensus_early_exit` ✅
13. `webui/src/__tests__/stores/agentStore.test.ts::processWSEvent init`
14. `webui/src/__tests__/stores/agentStore.test.ts::processWSEvent consensus_reached`
15. `webui/src/__tests__/stores/wizardStore.test.ts::skips api key step when configured`

---

## Maintenance Cadence

| Cadence | Activity |
|---------|----------|
| Per PR | Run CI tests, enforce new-test requirement for behavior changes |
| Weekly | Review flaky/quarantined tests and expired xfails |
| Monthly | Review coverage trend and gaps in core modules |
| Per release | Validate nightly E2E stability and remove obsolete quarantines |

Quarterly review checklist:

1. Re-check phase metrics against targets.
2. Remove stale tests that no longer validate active behavior.
3. Reprioritize backlog based on recent production defects.

## Post Spec
After this spec we will have the ability to test every aspect of MassGen well. Since we can test it well, that also means we can improve it better using agents. We can embrace **test-driven development** where we always create tests first. We can also create agent skills in `massgen/skills` to utilize the aspects of testing (e.g., integration tests for adding new features, TUI testing for improving the TUI both what we show and how we show it by getting visuals, webui similar). This will be very important to creating a more end-to-end working loop that starts to put less burden on the humans to evaluate what the agents made.
