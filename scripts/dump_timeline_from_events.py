#!/usr/bin/env python
"""Replay events.jsonl through the TUI pipeline for debugging.

Replays events through the same pipeline as the live TUI, including
agent_id filtering, round-banner dedup, and status filtering.

Three modes:
  Text mode (default) — dumps a transcript of what the TUI renders:
    uv run python scripts/dump_timeline_from_events.py /path/to/events.jsonl [agent_id]

  TUI mode (`--tui`) — lightweight visual replay around TimelineSection:
    uv run python scripts/dump_timeline_from_events.py --tui /path/to/events.jsonl [agent_id]

  Real TUI mode (`--tui-real`) — replays through the full runtime TextualApp shell:
    uv run python scripts/dump_timeline_from_events.py --tui-real /path/to/events.jsonl [agent_id]

If agent_id is omitted, auto-detects real agents (excludes orchestrator/None).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from massgen.events import MassGenEvent
from massgen.frontend.displays.timeline_event_recorder import TimelineEventRecorder

USAGE = "Usage: dump_timeline_from_events.py [--tui|--tui-real] /path/to/events.jsonl [agent_id]"
DEFAULT_REAL_TUI_SPEED = 8.0
MIN_REAL_TUI_DELAY = 0.05
MAX_REAL_TUI_DELAY = 0.75


def load_events(path: Path) -> list[MassGenEvent]:
    events = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(
                MassGenEvent(
                    timestamp=payload.get("timestamp"),
                    event_type=payload.get("event_type"),
                    agent_id=payload.get("agent_id"),
                    round_number=payload.get("round_number"),
                    data=payload.get("data"),
                ),
            )
    return events


def detect_agent_ids(events: list[MassGenEvent]) -> set[str]:
    """Find real agent IDs (excluding orchestrator/None)."""
    agents: set[str] = set()
    for event in events:
        aid = event.agent_id
        if aid and aid not in ("orchestrator",):
            agents.add(aid)
    return agents


def parse_mode_flags(args: list[str]) -> tuple[str, list[str]]:
    """Parse replay mode flags and return `(mode, remaining_args)`."""
    flag_to_mode = {
        "--tui": "tui",
        "--tui-real": "tui_real",
    }
    selected_flags = [flag for flag in flag_to_mode if flag in args]
    if len(selected_flags) > 1:
        raise ValueError("Use either --tui or --tui-real, not both.")

    mode = flag_to_mode[selected_flags[0]] if selected_flags else "text"
    filtered_args = [arg for arg in args if arg not in flag_to_mode]
    return mode, filtered_args


def _parse_event_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _compute_replay_delay(previous_event: MassGenEvent, next_event: MassGenEvent, speed: float) -> float:
    prev_ts = _parse_event_timestamp(previous_event.timestamp)
    next_ts = _parse_event_timestamp(next_event.timestamp)
    if prev_ts is None or next_ts is None:
        return 0.18

    delta_seconds = max(0.0, (next_ts - prev_ts).total_seconds())
    scaled = delta_seconds / max(speed, 0.1)
    return max(MIN_REAL_TUI_DELAY, min(MAX_REAL_TUI_DELAY, scaled))


def _get_real_tui_speed() -> float:
    raw = os.environ.get("MASSGEN_TUI_REPLAY_SPEED", str(DEFAULT_REAL_TUI_SPEED))
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_REAL_TUI_SPEED
    return value if value > 0 else DEFAULT_REAL_TUI_SPEED


def _derive_question(events: list[MassGenEvent], agent_ids: set[str]) -> str:
    for event in events:
        if event.agent_id not in agent_ids:
            continue
        if event.event_type != "text" or not isinstance(event.data, dict):
            continue
        content = str(event.data.get("content", "")).strip()
        if content:
            first_line = content.splitlines()[0].strip()
            if first_line:
                return first_line
    return "Synthetic event replay (no API calls)"


def _derive_agent_models(events: list[MassGenEvent], agent_ids: set[str]) -> dict[str, str]:
    models = {agent_id: "synthetic-replay" for agent_id in sorted(agent_ids)}
    for event in events:
        agent_id = event.agent_id
        if agent_id not in models or not isinstance(event.data, dict):
            continue
        candidate = event.data.get("model") or event.data.get("model_name")
        if isinstance(candidate, str) and candidate.strip():
            models[agent_id] = candidate.strip()
    return models


def filter_replay_events(events: list[MassGenEvent], agent_ids: set[str]) -> list[MassGenEvent]:
    """Keep events relevant for replay, applying the same skips as live TUI."""
    filtered: list[MassGenEvent] = []
    for event in events:
        if event.event_type in ("timeline_entry", "stream_chunk"):
            continue

        if event.agent_id is None:
            filtered.append(event)
            continue

        if event.agent_id in agent_ids:
            filtered.append(event)
    return filtered


# ─── Text mode ───────────────────────────────────────────────────────────


def run_text(events: list[MassGenEvent], agent_ids: set[str]) -> int:
    agents = sorted(agent_ids)
    multi = len(agents) > 1
    print(f"# Agents: {', '.join(agents)}", file=sys.stderr)

    # Per-agent recorders, mirroring the live TUI's per-agent adapters
    recorders: dict[str, TimelineEventRecorder] = {}
    for aid in agents:

        def make_cb(prefix: str):
            return lambda line: print(f"{prefix} {line}" if multi else line)

        recorders[aid] = TimelineEventRecorder(make_cb(f"[{aid}]"), agent_ids={aid})

    for event in events:
        if event.event_type == "timeline_entry":
            line = (event.data or {}).get("line")
            if line:
                print(line)
            continue
        aid = event.agent_id
        if aid and aid in recorders:
            recorders[aid].handle_event(event)

    for rec in recorders.values():
        rec.flush()
    return 0


# ─── TUI mode ────────────────────────────────────────────────────────────


def run_tui(events: list[MassGenEvent], agent_ids: set[str]) -> int:
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import Button, Footer, Header, Static

    from massgen.frontend.displays.textual_widgets.content_sections import (
        TimelineSection,
    )
    from massgen.frontend.displays.tui_event_pipeline import TimelineEventAdapter

    agents = sorted(agent_ids)

    class _FakePanel:
        """Minimal panel interface for TimelineEventAdapter."""

        def __init__(self, agent_id: str, timeline: TimelineSection):
            self.agent_id = agent_id
            self._timeline = timeline

        def _get_timeline(self) -> TimelineSection:
            return self._timeline

        def _hide_loading(self) -> None:
            pass

        def start_new_round(self, round_number: int, is_context_reset: bool = False) -> None:
            self._timeline.add_separator(
                f"Round {round_number}",
                round_number=round_number,
            )

    class EventReplayApp(App):
        CSS = """
        Screen { layout: vertical; }
        #tab-bar { height: 3; dock: top; background: $surface; }
        #tab-bar Button { min-width: 20; margin: 0 1; }
        #tab-bar Button.active { background: $accent; }
        #info-bar { height: 1; dock: top; background: $surface-darken-2; color: $text-muted; padding: 0 2; }
        #timeline-container { height: 1fr; }
        TimelineSection { height: 1fr; }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("tab", "next_agent", "Next Agent"),
            ("shift+tab", "prev_agent", "Prev Agent"),
        ]

        def __init__(self):
            super().__init__()
            self._agents = agents
            self._current_idx = 0
            self._timelines: dict[str, TimelineSection] = {}
            self._adapters: dict[str, TimelineEventAdapter] = {}

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal(id="tab-bar"):
                for i, aid in enumerate(self._agents):
                    btn = Button(aid, id=f"tab-{aid}", classes="active" if i == 0 else "")
                    yield btn
            yield Static(
                f"{len(events)} events  |  {len(self._agents)} agents",
                id="info-bar",
            )
            with Vertical(id="timeline-container"):
                for aid in self._agents:
                    tl = TimelineSection(id=f"timeline-{aid}")
                    tl.display = aid == self._agents[0]
                    self._timelines[aid] = tl
                    yield tl
            yield Footer()

        def on_mount(self) -> None:
            self.title = "Event Replay"
            # Build per-agent adapters and replay with agent_id filtering
            for aid in self._agents:
                tl = self._timelines[aid]
                panel = _FakePanel(aid, tl)
                adapter = TimelineEventAdapter(panel, agent_id=aid)
                self._adapters[aid] = adapter

                # Replay events, applying same agent_id gate as live TUI
                for event in events:
                    if event.event_type in ("timeline_entry", "stream_chunk"):
                        continue
                    if not event.agent_id or event.agent_id not in agent_ids:
                        continue
                    # Only route to this agent's adapter if event is for this agent
                    if event.agent_id == aid:
                        adapter.handle_event(event)
                adapter.flush()

        def _switch_to(self, idx: int) -> None:
            old_aid = self._agents[self._current_idx]
            self._current_idx = idx % len(self._agents)
            new_aid = self._agents[self._current_idx]
            self._timelines[old_aid].display = False
            self._timelines[new_aid].display = True
            for i, aid in enumerate(self._agents):
                btn = self.query_one(f"#tab-{aid}", Button)
                btn.set_classes("active" if i == self._current_idx else "")

        def on_button_pressed(self, event: Button.Pressed) -> None:
            bid = event.button.id or ""
            if bid.startswith("tab-"):
                aid = bid[4:]
                if aid in self._agents:
                    self._switch_to(self._agents.index(aid))

        def action_next_agent(self) -> None:
            self._switch_to(self._current_idx + 1)

        def action_prev_agent(self) -> None:
            self._switch_to(self._current_idx - 1)

    EventReplayApp().run()
    return 0


def run_tui_real(events: list[MassGenEvent], agent_ids: set[str]) -> int:
    """Replay events through the full runtime TextualApp shell."""
    from textual import events as textual_events
    from textual.binding import Binding
    from textual.widgets import Label, Static

    from massgen.frontend.displays import (
        textual_terminal_display as textual_display_module,
    )
    from massgen.frontend.displays.textual_terminal_display import (
        TextualTerminalDisplay,
    )

    agents = sorted(agent_ids)
    replay_events = filter_replay_events(events, agent_ids)
    replay_speed = _get_real_tui_speed()

    display = TextualTerminalDisplay(
        agents,
        agent_models=_derive_agent_models(events, agent_ids),
        theme="dark",
    )

    class RealEventReplayApp(textual_display_module.TextualApp):
        BINDINGS = [*textual_display_module.TextualApp.BINDINGS, Binding("q", "quit", "Quit", show=False)]

        def __init__(self):
            super().__init__(
                display=display,
                question=_derive_question(events, agent_ids),
                buffers=display._buffers,
                buffer_lock=display._buffer_lock,
                buffer_flush_interval=display.buffer_flush_interval,
            )
            self._replay_index = 0

        async def on_mount(self) -> None:
            await super().on_mount()
            self.title = "Event Replay (Real TUI)"
            self._prime_shell_for_replay()
            self.set_timer(0.05, self._replay_next_event)

        def on_key(self, event: textual_events.Key) -> None:
            if event.key == "q":
                self.exit()
                event.stop()
                return
            super().on_key(event)

        def _prime_shell_for_replay(self) -> None:
            for panel in self.agent_widgets.values():
                try:
                    panel._hide_loading()
                except Exception:
                    pass

            try:
                self.query_one("#status_cwd", Static).update("[dim]📁[/] /workspace")
            except Exception:
                pass
            try:
                self.query_one("#timeout_display", Label).update("⏱ 0:00 / 10:00")
            except Exception:
                pass

            try:
                if self.question_input:
                    self.question_input.can_focus = False
            except Exception:
                pass

            # Keep focus off input so "q" works as a quick exit key for replay.
            self.set_focus(None)

        def _replay_next_event(self) -> None:
            if self._replay_index >= len(replay_events):
                return

            current_event = replay_events[self._replay_index]
            self._replay_index += 1
            self._route_event_batch([current_event])

            for adapter in self._event_adapters.values():
                adapter.flush()

            if self._replay_index >= len(replay_events):
                return

            next_event = replay_events[self._replay_index]
            delay = _compute_replay_delay(current_event, next_event, replay_speed)
            self.set_timer(delay, self._replay_next_event)

    app = RealEventReplayApp()
    display._app = app
    app.run()
    return 0


# ─── Main ─────────────────────────────────────────────────────────────────


def main() -> int:
    try:
        mode, args = parse_mode_flags(sys.argv[1:])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1

    if not args:
        print(USAGE, file=sys.stderr)
        return 1

    path = Path(args[0])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    target_agent: str | None = args[1] if len(args) > 1 else None

    events = load_events(path)
    agent_ids = {target_agent} if target_agent else detect_agent_ids(events)

    if not agent_ids:
        print("No agents found in events.", file=sys.stderr)
        return 1

    if mode == "tui":
        return run_tui(events, agent_ids)
    if mode == "tui_real":
        return run_tui_real(events, agent_ids)
    return run_text(events, agent_ids)


if __name__ == "__main__":
    raise SystemExit(main())
