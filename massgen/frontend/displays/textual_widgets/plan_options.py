"""
Plan Options Popover Widget for MassGen TUI.

Provides a dropdown popover for plan mode configuration:
- Plan selection (choose existing plans)
- Plan details preview (tasks, status, created date)
- Depth selector (dynamic/shallow/medium/deep) - shown only in "plan" mode
- Optional explicit task/chunk target selectors - shown only in "plan" mode
- Broadcast toggle (human/agents/off) - shown only in "plan" mode
"""

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Label, Select, Static

if TYPE_CHECKING:
    from massgen.frontend.displays.tui_modes import PlanDepth
    from massgen.plan_storage import PlanSession


class PlanSelected(Message):
    """Message emitted when a plan is selected."""

    def __init__(self, plan_id: str | None, is_new: bool = False) -> None:
        """Initialize the message.

        Args:
            plan_id: The selected plan ID, or None if creating new.
            is_new: True if user selected "Create new plan".
        """
        self.plan_id = plan_id
        self.is_new = is_new
        super().__init__()


class PlanDepthChanged(Message):
    """Message emitted when plan depth is changed."""

    def __init__(self, depth: "PlanDepth") -> None:
        """Initialize the message.

        Args:
            depth: The new depth value ("dynamic", "shallow", "medium", or "deep").
        """
        self.depth = depth
        super().__init__()


class PlanStepTargetChanged(Message):
    """Message emitted when explicit task-count target is changed."""

    def __init__(self, target_steps: int | None) -> None:
        self.target_steps = target_steps
        super().__init__()


class PlanChunkTargetChanged(Message):
    """Message emitted when explicit chunk-count target is changed."""

    def __init__(self, target_chunks: int | None) -> None:
        self.target_chunks = target_chunks
        super().__init__()


class BroadcastModeChanged(Message):
    """Message emitted when broadcast mode is changed."""

    def __init__(self, broadcast: Any) -> None:
        """Initialize the message.

        Args:
            broadcast: The new broadcast value ("human", "agents", or False).
        """
        self.broadcast = broadcast
        super().__init__()


class ViewPlanRequested(Message):
    """Message emitted when user wants to view the full plan."""

    def __init__(self, plan_id: str, tasks: list[Any]) -> None:
        """Initialize the message.

        Args:
            plan_id: The plan ID to view.
            tasks: List of task dictionaries from the plan.
        """
        self.plan_id = plan_id
        self.tasks = tasks
        super().__init__()


class ExecutePrefillRequested(Message):
    """Message emitted when execute input should be prefilled from chunk controls."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__()


class ExecuteAutoContinueChanged(Message):
    """Message emitted when execute auto-continue setting changes."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        super().__init__()


class ExecuteRefinementModeChanged(Message):
    """Message emitted when execute refinement mode changes."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        super().__init__()


class AnalysisTargetTypeChanged(Message):
    """Message emitted when analysis target type is changed (log vs skills)."""

    def __init__(self, target: str) -> None:
        self.target = target
        super().__init__()


class AnalysisProfileChanged(Message):
    """Message emitted when analysis profile is changed."""

    def __init__(self, profile: str) -> None:
        self.profile = profile
        super().__init__()


class AnalysisTargetChanged(Message):
    """Message emitted when analysis log/turn target is changed."""

    def __init__(self, log_dir: str | None, turn: int | None) -> None:
        self.log_dir = log_dir
        self.turn = turn
        super().__init__()


class AnalysisSkillLifecycleChanged(Message):
    """Message emitted when analysis skill lifecycle mode is changed."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        super().__init__()


class ViewAnalysisRequested(Message):
    """Message emitted when user wants to view an analysis report."""

    def __init__(self, log_dir: str, turn: int) -> None:
        self.log_dir = log_dir
        self.turn = turn
        super().__init__()


def _popover_log(msg: str) -> None:
    """Log to TUI debug file."""
    from massgen.frontend.displays.shared.tui_debug import tui_log

    tui_log(f"[POPOVER] {msg}")


class PlanOptionsPopover(Widget):
    """Popover widget for plan mode configuration.

    Shows:
    - Plan selector (in execute mode) - choose from existing plans
    - Plan details preview - shows selected plan info
    - Depth selector (in plan mode) - dynamic/shallow/medium/deep
    - Optional explicit step/chunk targets (in plan mode)
    - Broadcast toggle (in plan mode) - human/agents/off
    """

    LOG_CONTROLS_ID = "analysis_log_controls"
    SKILLS_CONTROLS_ID = "analysis_skills_controls"

    DEFAULT_CSS = """
    PlanOptionsPopover {
        layer: overlay;
        dock: left;
        width: 84;
        min-width: 64;
        max-width: 92;
        height: auto;
        max-height: 44;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
        margin-bottom: 3;
        margin-left: 1;
        display: none;
    }

    PlanOptionsPopover.visible {
        display: block;
    }

    PlanOptionsPopover #popover_title {
        text-style: bold;
        color: $text;
        margin-bottom: 1;
    }

    PlanOptionsPopover #popover_content {
        width: 100%;
        height: auto;
        max-height: 34;
        overflow-y: auto;
        padding-right: 1;
    }

    PlanOptionsPopover .section-label {
        color: $text-muted;
        margin-top: 1;
        margin-bottom: 0;
    }

    PlanOptionsPopover Select {
        width: 100%;
        margin-bottom: 1;
    }

    PlanOptionsPopover #plan_details {
        background: $surface-darken-1;
        border: solid $primary-darken-2;
        padding: 1;
        margin: 1 0;
        height: auto;
        max-height: 14;
        text-wrap: wrap;
    }

    PlanOptionsPopover #plan_details.hidden {
        display: none;
    }

    PlanOptionsPopover .detail-line {
        color: $text-muted;
        height: 1;
    }

    PlanOptionsPopover .detail-value {
        color: $text;
    }

    PlanOptionsPopover .task-preview {
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
    }

    PlanOptionsPopover #analysis_preview {
        background: $surface-darken-1;
        border: solid $primary-darken-2;
        padding: 1;
        margin: 1 0;
        height: auto;
        max-height: 14;
        text-wrap: wrap;
        color: $text-muted;
    }

    PlanOptionsPopover #analysis_target_meta {
        color: $text-muted;
        margin: 0 0 1 0;
        text-wrap: wrap;
    }

    PlanOptionsPopover .chunk-browser-label {
        color: $text-muted;
        margin-top: 1;
        margin-bottom: 0;
    }

    PlanOptionsPopover .chunk-prefill-btn {
        width: 100%;
        margin-bottom: 1;
    }

    PlanOptionsPopover #chunk_range_selector {
        width: 100%;
        margin-top: 0;
        margin-bottom: 1;
    }

    PlanOptionsPopover #prefill_range_btn {
        width: 100%;
        margin-bottom: 1;
    }

    PlanOptionsPopover #close_btn {
        margin-top: 1;
        width: 100%;
    }

    PlanOptionsPopover .hidden-controls {
        display: none;
    }
    """

    def __init__(
        self,
        *,
        plan_mode: str = "normal",
        available_plans: list["PlanSession"] | None = None,
        current_plan_id: str | None = None,
        current_depth: "PlanDepth" = "dynamic",
        current_step_target: int | None = None,
        current_chunk_target: int | None = None,
        current_execute_auto_continue: bool = True,
        current_execute_refinement_mode: str = "inherit",
        current_broadcast: Any = False,
        analysis_target_type: str = "log",
        analysis_profile: str = "dev",
        analysis_log_options: list[tuple[str, str]] | None = None,
        analysis_selected_log_dir: str | None = None,
        analysis_turn_options: list[tuple[str, str]] | None = None,
        analysis_selected_turn: int | None = None,
        analysis_preview_text: str = "",
        analysis_skill_lifecycle_mode: str = "create_or_update",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize the plan options popover.

        Args:
            plan_mode: Current mode ("normal", "plan", "execute", or "analysis").
            available_plans: List of available plan sessions.
            current_plan_id: Currently selected plan ID.
            current_depth: Current plan depth setting.
            current_step_target: Optional explicit task-count target.
            current_chunk_target: Optional explicit chunk-count target.
            current_execute_auto_continue: Execute auto-continue toggle state.
            current_execute_refinement_mode: Execute refinement mode ("inherit", "on", "off").
            current_broadcast: Current broadcast setting.
            id: Optional DOM ID.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self._plan_mode = plan_mode
        self._available_plans = available_plans or []
        self._current_plan_id = current_plan_id
        self._current_depth = current_depth
        self._current_step_target = current_step_target
        self._current_chunk_target = current_chunk_target
        self._current_execute_auto_continue = current_execute_auto_continue
        self._current_execute_refinement_mode = current_execute_refinement_mode
        self._current_broadcast = current_broadcast
        self._analysis_target_type = analysis_target_type
        self._analysis_profile = analysis_profile
        self._analysis_log_options = analysis_log_options or []
        self._analysis_selected_log_dir = analysis_selected_log_dir
        self._analysis_turn_options = analysis_turn_options or []
        self._analysis_selected_turn = analysis_selected_turn
        self._analysis_preview_text = analysis_preview_text
        self._analysis_skill_lifecycle_mode = analysis_skill_lifecycle_mode
        self._plan_details_widget: Static | None = None
        self._chunk_button_values: dict[str, str] = {}
        self._chunk_range_options: list[tuple[str, str]] = []
        self._selected_chunk_range: str | None = None
        self._initialized = False  # Track if popover has been shown (to ignore events during recompose)

    @staticmethod
    def _safe_select_value(options: list[tuple[str, str]], preferred: str | None) -> str | None:
        """Return a safe select value from options, preferring the given value."""
        if not options:
            return None
        values = {value for _, value in options}
        if preferred in values:
            return preferred
        return options[0][1]

    def compose(self) -> ComposeResult:
        """Create the popover contents.

        Content differs by mode:
        - "plan" mode: Shows depth and human feedback options only
        - "execute" mode: Shows plan selector and plan details only
        - "analysis" mode: Shows profile, log target, and turn target controls
        """
        # Title changes based on mode
        if self._plan_mode == "plan":
            yield Label("Planning Options", id="popover_title")
        elif self._plan_mode == "spec":
            yield Label("Spec Options", id="popover_title")
        elif self._plan_mode == "analysis":
            title = "Skill Organization" if self._analysis_target_type == "skills" else "Log Analysis Options"
            yield Label(title, id="popover_title")
        else:
            yield Label("Select Plan", id="popover_title")

        with VerticalScroll(id="popover_content"):
            # Execute mode: Show plan selector and details
            if self._plan_mode == "execute" and self._available_plans:
                yield Label("Select Plan/Spec:", classes="section-label")

                # Build plan options
                has_resumable = False
                for plan in self._available_plans:
                    try:
                        metadata = plan.load_metadata()
                        if metadata.status == "resumable":
                            has_resumable = True
                            break
                    except Exception:
                        continue
                latest_label = "Latest resumable (auto)" if has_resumable else "Latest (auto)"
                plan_options = [(latest_label, "latest")]
                for plan in self._available_plans[:5]:  # Limit to 5 most recent
                    try:
                        metadata = plan.load_metadata()
                        # Show artifact type icon to distinguish plans from specs
                        artifact_type = getattr(metadata, "artifact_type", "plan")
                        type_marker = "[spec]" if artifact_type == "spec" else "[plan]"
                        label = f"{type_marker} {plan.plan_id[:13]}... ({metadata.status})"
                        plan_options.append((label, plan.plan_id))
                    except Exception:
                        plan_options.append((plan.plan_id[:20], plan.plan_id))

                yield Select(
                    plan_options,
                    value=self._current_plan_id or "latest",
                    id="plan_selector",
                )

                # Plan details section - shows info about selected plan
                self._plan_details_widget = Static("", id="plan_details")
                yield self._plan_details_widget

                # Load initial plan details
                self._update_plan_details(self._current_plan_id or "latest")

                # View Plan/Spec button - opens full task/requirement list modal
                selected = self._get_selected_plan_session()
                _view_label = "View Full Plan"
                if selected:
                    try:
                        _sel_meta = selected.load_metadata()
                        if getattr(_sel_meta, "artifact_type", "plan") == "spec":
                            _view_label = "View Full Spec"
                    except Exception:
                        pass
                yield Button(_view_label, id="view_plan_btn", variant="primary")

                yield Label("Execution Flow:", classes="section-label")
                execute_auto_options = [
                    ("Auto-continue next chunk", "auto"),
                    ("Pause after each chunk", "manual"),
                ]
                auto_value = "auto" if self._current_execute_auto_continue else "manual"
                yield Select(
                    execute_auto_options,
                    value=self._safe_select_value(execute_auto_options, auto_value),
                    id="execute_auto_continue_selector",
                )

                yield Label("Execute Refinement:", classes="section-label")
                execute_refine_options = [
                    ("Inherit mode bar setting", "inherit"),
                    ("Force refine ON", "on"),
                    ("Force refine OFF", "off"),
                ]
                yield Select(
                    execute_refine_options,
                    value=self._safe_select_value(execute_refine_options, self._current_execute_refinement_mode),
                    id="execute_refinement_mode_selector",
                )

                # Chunk browser / prefill controls
                selected_plan = self._get_selected_plan_session()
                chunk_entries = self._build_chunk_browser_entries(selected_plan)
                self._chunk_button_values = {}
                self._chunk_range_options = []

                if chunk_entries:
                    yield Label("Chunk Browser:", classes="chunk-browser-label")
                    for idx, entry in enumerate(chunk_entries):
                        chunk_value = entry["chunk"]
                        button_id = f"chunk_prefill_btn_{idx}"
                        button_label = f"{entry['icon']} {chunk_value} " f"({entry['completed']}/{entry['total']})"
                        self._chunk_button_values[button_id] = chunk_value
                        variant = "success" if entry["status"] == "completed" else "default"
                        yield Button(
                            button_label,
                            id=button_id,
                            classes="chunk-prefill-btn",
                            variant=variant,
                        )

                    chunk_names = [entry["chunk"] for entry in chunk_entries]
                    self._chunk_range_options = self._build_chunk_range_options(chunk_names)
                    if self._chunk_range_options:
                        self._selected_chunk_range = self._safe_select_value(
                            self._chunk_range_options,
                            self._selected_chunk_range,
                        )
                        yield Select(
                            self._chunk_range_options,
                            value=self._selected_chunk_range,
                            id="chunk_range_selector",
                        )
                        yield Button(
                            "Prefill Range",
                            id="prefill_range_btn",
                            variant="default",
                        )
                else:
                    yield Static("[dim]Chunk data unavailable for selected plan[/]", markup=True)

            # Plan mode: Show depth and human feedback options
            if self._plan_mode == "plan":
                yield Label("Plan Depth:", classes="section-label")
                depth_options = [
                    ("Dynamic (scope-adaptive)", "dynamic"),
                    ("Shallow (5-10 tasks)", "shallow"),
                    ("Medium (20-50 tasks)", "medium"),
                    ("Deep (100-200+ tasks)", "deep"),
                ]
                yield Select(
                    depth_options,
                    value=self._safe_select_value(depth_options, self._current_depth),
                    id="depth_selector",
                )

                yield Label("Task Count Target:", classes="section-label")
                step_target_options = [
                    ("Dynamic", "dynamic"),
                    ("10 tasks", "10"),
                    ("20 tasks", "20"),
                    ("30 tasks", "30"),
                    ("50 tasks", "50"),
                    ("80 tasks", "80"),
                    ("120 tasks", "120"),
                ]
                current_steps_value = str(self._current_step_target) if self._current_step_target and self._current_step_target > 0 else "dynamic"
                yield Select(
                    step_target_options,
                    value=self._safe_select_value(step_target_options, current_steps_value),
                    id="step_target_selector",
                )

                yield Label("Chunk Count Target:", classes="section-label")
                chunk_target_options = [
                    ("Dynamic", "dynamic"),
                    ("1 chunk (single run)", "1"),
                    ("3 chunks", "3"),
                    ("5 chunks", "5"),
                    ("7 chunks", "7"),
                    ("10 chunks", "10"),
                    ("12 chunks", "12"),
                ]
                current_chunks_value = str(self._current_chunk_target) if self._current_chunk_target and self._current_chunk_target > 0 else "dynamic"
                yield Select(
                    chunk_target_options,
                    value=self._safe_select_value(chunk_target_options, current_chunks_value),
                    id="chunk_target_selector",
                )

                yield Label("Human Feedback:", classes="section-label")
                broadcast_options = [
                    ("Enabled (agents ask human)", "human"),
                    ("Agents only (no human)", "agents"),
                    ("Disabled (autonomous)", "off"),
                ]
                # Convert False to "off" for display
                broadcast_value = self._current_broadcast if self._current_broadcast else "off"
                if broadcast_value is True:
                    broadcast_value = "human"
                yield Select(
                    broadcast_options,
                    value=broadcast_value,
                    id="broadcast_selector",
                )

            # Spec mode: chunk target + human feedback (no depth/task count)
            if self._plan_mode == "spec":
                yield Label("Chunk Count Target:", classes="section-label")
                chunk_target_options = [
                    ("Dynamic", "dynamic"),
                    ("1 chunk (single run)", "1"),
                    ("3 chunks", "3"),
                    ("5 chunks", "5"),
                    ("7 chunks", "7"),
                    ("10 chunks", "10"),
                    ("12 chunks", "12"),
                ]
                current_chunks_value = str(self._current_chunk_target) if self._current_chunk_target and self._current_chunk_target > 0 else "dynamic"
                yield Select(
                    chunk_target_options,
                    value=self._safe_select_value(chunk_target_options, current_chunks_value),
                    id="chunk_target_selector",
                )

                yield Label("Human Feedback:", classes="section-label")
                broadcast_options = [
                    ("Enabled (agents ask human)", "human"),
                    ("Agents only (no human)", "agents"),
                    ("Disabled (autonomous)", "off"),
                ]
                broadcast_value = self._current_broadcast if self._current_broadcast else "off"
                if broadcast_value is True:
                    broadcast_value = "human"
                yield Select(
                    broadcast_options,
                    value=broadcast_value,
                    id="broadcast_selector",
                )

            # Analysis mode: target type + profile + target controls
            if self._plan_mode == "analysis":
                yield Label("Analysis Target:", classes="section-label")
                yield Select(
                    [
                        ("Log Session", "log"),
                        ("Organize Skills", "skills"),
                    ],
                    value=self._analysis_target_type if self._analysis_target_type in ("log", "skills") else "log",
                    id="analysis_target_type_selector",
                )

                # Log-specific controls — always composed, visibility toggled via CSS
                log_classes = "hidden-controls" if self._analysis_target_type == "skills" else ""
                with Container(id=self.LOG_CONTROLS_ID, classes=log_classes):
                    turn_label = f"turn_{self._analysis_selected_turn}" if self._analysis_selected_turn is not None else "latest"
                    if self._analysis_selected_log_dir:
                        log_name = Path(self._analysis_selected_log_dir).name
                        report_exists = False
                        if self._analysis_selected_turn is not None:
                            report_exists = (Path(self._analysis_selected_log_dir) / f"turn_{self._analysis_selected_turn}" / "ANALYSIS_REPORT.md").exists()
                        report_label = "available" if report_exists else "not generated yet"
                        yield Static(
                            f"Target: {log_name} / {turn_label}\nReport: {report_label}",
                            id="analysis_target_meta",
                        )

                    yield Label("Analysis Profile:", classes="section-label")
                    yield Select(
                        [
                            ("Dev (internals)", "dev"),
                            ("User (skills)", "user"),
                        ],
                        value=self._analysis_profile if self._analysis_profile in ("dev", "user") else "dev",
                        id="analysis_profile_selector",
                    )

                    yield Label("Skill Lifecycle:", classes="section-label")
                    lifecycle_options = [
                        ("Create or Update (recommended)", "create_or_update"),
                        ("Create New Only", "create_new"),
                    ]
                    lifecycle_selected = self._safe_select_value(
                        lifecycle_options,
                        self._analysis_skill_lifecycle_mode,
                    )
                    yield Select(
                        lifecycle_options,
                        value=lifecycle_selected,
                        id="analysis_skill_lifecycle_selector",
                    )

                    yield Label("Log Session:", classes="section-label")
                    if self._analysis_log_options:
                        selected_log = self._safe_select_value(self._analysis_log_options, self._analysis_selected_log_dir)
                        yield Select(
                            self._analysis_log_options,
                            value=selected_log,
                            id="analysis_log_selector",
                        )
                    else:
                        yield Static("[dim]No log sessions found[/]", markup=True)

                    yield Label("Turn:", classes="section-label")
                    if self._analysis_turn_options:
                        selected_turn = self._safe_select_value(
                            self._analysis_turn_options,
                            str(self._analysis_selected_turn) if self._analysis_selected_turn is not None else None,
                        )
                        yield Select(
                            self._analysis_turn_options,
                            value=selected_turn,
                            id="analysis_turn_selector",
                        )
                    else:
                        yield Static("[dim]No turns found for selected log[/]", markup=True)

                    preview_text = self._analysis_preview_text or "Preview unavailable for this selection."
                    yield Static(preview_text, id="analysis_preview")

                    yield Button("View Analysis Report", id="view_analysis_btn", variant="primary")

                # Skills organization controls — always composed, visibility toggled via CSS
                skills_classes = "hidden-controls" if self._analysis_target_type == "log" else ""
                with Container(id=self.SKILLS_CONTROLS_ID, classes=skills_classes):
                    yield Static(
                        "Reads all installed skills, merges overlapping ones, "
                        "and generates a compact SKILL_REGISTRY.md routing guide.\n\n"
                        "[dim]Tip: Track skills in git by adding to .gitignore:[/]\n"
                        "[dim]  !.agent/skills/[/]\n"
                        "[dim]  !.agent/skills/**[/]",
                        markup=True,
                        id="analysis_skills_preview",
                    )

            yield Button("Close", id="close_btn", variant="default")

    def _get_plan_by_id(self, plan_id: str) -> Optional["PlanSession"]:
        """Find a plan by ID from available plans."""
        for plan in self._available_plans:
            if plan.plan_id == plan_id:
                return plan
        return None

    def _get_selected_plan_session(self) -> Optional["PlanSession"]:
        """Return the currently selected plan session."""
        plan_id = self._current_plan_id or "latest"
        if plan_id == "latest":
            for plan in self._available_plans:
                try:
                    if plan.load_metadata().status == "resumable":
                        return plan
                except Exception:
                    continue
            return self._available_plans[0] if self._available_plans else None
        return self._get_plan_by_id(plan_id)

    @staticmethod
    def _load_plan_payload(plan: "PlanSession") -> dict[str, Any]:
        """Load plan.json payload from a plan session workspace."""
        plan_file = plan.workspace_dir / "plan.json"
        if not plan_file.exists():
            return {}
        try:
            data = json.loads(plan_file.read_text())
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _build_chunk_browser_entries(self, plan: Optional["PlanSession"]) -> list[dict[str, Any]]:
        """Build chunk status entries for execute popover chunk browser."""
        if not plan:
            return []

        payload = self._load_plan_payload(plan)
        tasks = payload.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []

        try:
            metadata = plan.load_metadata()
        except Exception:
            return []

        chunk_order = list(getattr(metadata, "chunk_order", []) or [])
        if not chunk_order:
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                chunk = str(task.get("chunk", "")).strip()
                if chunk and chunk not in chunk_order:
                    chunk_order.append(chunk)

        if not chunk_order:
            return []

        chunk_counts: dict[str, dict[str, int]] = {}
        for chunk in chunk_order:
            chunk_counts[chunk] = {"total": 0, "completed": 0}

        for task in tasks:
            if not isinstance(task, dict):
                continue
            chunk = str(task.get("chunk", "")).strip()
            if chunk not in chunk_counts:
                continue
            chunk_counts[chunk]["total"] += 1
            status = str(task.get("status", "pending")).strip().lower()
            if status in {"completed", "verified"}:
                chunk_counts[chunk]["completed"] += 1

        completed_chunks = set(getattr(metadata, "completed_chunks", []) or [])
        current_chunk = getattr(metadata, "current_chunk", None)
        next_chunk = None
        for chunk in chunk_order:
            if chunk not in completed_chunks and chunk != current_chunk:
                next_chunk = chunk
                break

        entries: list[dict[str, Any]] = []
        for chunk in chunk_order:
            counts = chunk_counts.get(chunk, {"total": 0, "completed": 0})
            status = "pending"
            icon = "○"
            if chunk in completed_chunks:
                status = "completed"
                icon = "✓"
            elif chunk == current_chunk:
                status = "current"
                icon = "▶"
            elif chunk == next_chunk:
                status = "next"
                icon = "→"

            entries.append(
                {
                    "chunk": chunk,
                    "status": status,
                    "icon": icon,
                    "completed": counts["completed"],
                    "total": counts["total"],
                },
            )

        return entries

    @staticmethod
    def _build_chunk_range_options(chunk_names: list[str]) -> list[tuple[str, str]]:
        """Build bounded range options for chunk prefill controls."""
        options: list[tuple[str, str]] = []
        max_options = 12
        for start_idx in range(len(chunk_names)):
            for end_idx in range(start_idx + 1, len(chunk_names)):
                value = f"{chunk_names[start_idx]}-{chunk_names[end_idx]}"
                options.append((value, value))
                if len(options) >= max_options:
                    return options
        return options

    def _update_plan_details(self, plan_id: str) -> None:
        """Update the plan details display for the selected plan."""
        if not self._plan_details_widget:
            return

        if plan_id == "new":
            self._plan_details_widget.update("[dim]Will create a new plan[/]")
            return

        if plan_id == "latest":
            plan = self._get_selected_plan_session()
            if not plan:
                self._plan_details_widget.update("[dim]No plans available[/]")
                return
        else:
            plan = self._get_plan_by_id(plan_id)
            if not plan:
                self._plan_details_widget.update("[dim]Plan not found[/]")
                return

        # Build details text
        try:
            metadata = plan.load_metadata()

            # Parse created date
            try:
                created_dt = datetime.fromisoformat(metadata.created_at)
                created_str = created_dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                created_str = metadata.created_at[:16]

            # Get item count and preview (supports both plan.json and spec.json)
            item_count = 0
            item_preview = ""
            artifact_type = getattr(metadata, "artifact_type", "plan")
            is_spec = artifact_type == "spec"
            items_label = "Requirements" if is_spec else "Tasks"

            plan_file = plan.workspace_dir / "plan.json"
            spec_file = plan.workspace_dir / "spec.json"
            artifact_file = spec_file if is_spec and spec_file.exists() else plan_file

            if artifact_file.exists():
                try:
                    data = json.loads(artifact_file.read_text())
                    items_key = "requirements" if is_spec else "tasks"
                    items = data.get(items_key, [])
                    item_count = len(items)

                    # Get first 2-3 item descriptions as preview
                    if items:
                        previews = []
                        for t in items[:3]:
                            if is_spec:
                                desc = t.get("title", "")[:40]
                                if len(t.get("title", "")) > 40:
                                    desc += "..."
                            else:
                                desc = t.get("description", "")[:40]
                                if len(t.get("description", "")) > 40:
                                    desc += "..."
                            previews.append(f"  • {desc}")
                        item_preview = "\n".join(previews)
                except Exception:
                    pass

            # Format status with color
            status = metadata.status
            status_color = {
                "planning": "yellow",
                "ready": "green",
                "executing": "blue",
                "resumable": "yellow",
                "completed": "green",
                "failed": "red",
            }.get(status, "white")

            details = f"[bold]Status:[/] [{status_color}]{status}[/]\n"
            details += f"[bold]Created:[/] {created_str}\n"
            details += f"[bold]{items_label}:[/] {item_count}"

            chunk_entries = self._build_chunk_browser_entries(plan)
            if chunk_entries:
                completed_chunks = sum(1 for entry in chunk_entries if entry["status"] == "completed")
                details += f"\n[bold]Chunks:[/] {completed_chunks}/{len(chunk_entries)} complete"
                current_chunk = next(
                    (entry["chunk"] for entry in chunk_entries if entry["status"] == "current"),
                    None,
                )
                next_chunk = next(
                    (entry["chunk"] for entry in chunk_entries if entry["status"] == "next"),
                    None,
                )
                if current_chunk:
                    details += f"\n[dim]Current:[/] {current_chunk}"
                if next_chunk:
                    details += f"\n[dim]Next:[/] {next_chunk}"

            # Show the original planning prompt if available (most useful info)
            planning_prompt = getattr(metadata, "planning_prompt", None)
            planning_turn = getattr(metadata, "planning_turn", None)
            if planning_prompt:
                # Truncate long prompts
                prompt_preview = planning_prompt[:100]
                if len(planning_prompt) > 100:
                    prompt_preview += "..."
                # Show turn info if available
                turn_info = f" [dim](turn {planning_turn})[/]" if planning_turn else ""
                details += f"\n[dim]Query{turn_info}:[/]\n[italic]{prompt_preview}[/]"
            elif item_preview:
                # Fall back to item preview if no prompt stored
                details += f"\n[dim]Preview:[/]\n{item_preview}"

            self._plan_details_widget.update(details)

        except Exception as e:
            self._plan_details_widget.update(f"[red]Error loading plan: {e}[/]")

    def _toggle_analysis_controls(self, target: str) -> None:
        """Toggle visibility of log vs skills controls and update title."""
        try:
            log_controls = self.query_one(f"#{self.LOG_CONTROLS_ID}")
            skills_controls = self.query_one(f"#{self.SKILLS_CONTROLS_ID}")
            title_label = self.query_one("#popover_title", Label)
            if target == "skills":
                log_controls.add_class("hidden-controls")
                skills_controls.remove_class("hidden-controls")
                title_label.update("Skill Organization")
            else:
                log_controls.remove_class("hidden-controls")
                skills_controls.add_class("hidden-controls")
                title_label.update("Log Analysis Options")
        except Exception as e:
            _popover_log(f"_toggle_analysis_controls error: {e}")

    def show(self) -> None:
        """Show the popover."""
        _popover_log(f"show() called, current classes: {list(self.classes)}")

        self.add_class("visible")
        _popover_log(f"show() after add_class, classes: {list(self.classes)}")
        self._initialized = True
        _popover_log("show() set _initialized=True")

        # Refresh plan details when showing
        if self._plan_details_widget and self._available_plans:
            self._update_plan_details(self._current_plan_id or "latest")

    def hide(self) -> None:
        """Hide the popover."""
        _popover_log(f"hide() called, current classes: {list(self.classes)}")
        self.remove_class("visible")
        # Reset initialized so next show will work correctly
        self._initialized = False
        _popover_log("hide() set _initialized=False")

    def toggle(self) -> None:
        """Toggle popover visibility."""
        _popover_log(f"toggle() called, visible={'visible' in self.classes}")
        if "visible" in self.classes:
            self.hide()
        else:
            self.show()

    def on_blur(self, event) -> None:
        """Handle blur - log but don't hide."""
        _popover_log("on_blur() called")
        # Don't hide on blur - let user click elsewhere

    def on_focus(self, event) -> None:
        """Handle focus."""
        _popover_log("on_focus() called")

    def _validate_plan_for_execution(self, plan_id: str) -> tuple[bool, str]:
        """Validate a plan exists and is ready for execution.

        Args:
            plan_id: The plan ID to validate.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is empty.
        """
        plan = self._get_plan_by_id(plan_id)
        if not plan:
            return False, f"Plan '{plan_id}' not found"

        # Check metadata exists and has valid status
        try:
            metadata = plan.load_metadata()
            status = metadata.status
            if status not in ("ready", "completed", "resumable", "executing"):
                return False, (f"Plan status is '{status}' " "(expected ready/completed/resumable/executing)")
        except FileNotFoundError:
            return False, "Plan metadata file not found"
        except Exception as e:
            return False, f"Error loading plan metadata: {e}"

        # Check plan.json exists and has tasks
        plan_file = plan.workspace_dir / "plan.json"
        if not plan_file.exists():
            return False, "Plan file (plan.json) not found in workspace"

        try:
            plan_data = json.loads(plan_file.read_text())
            tasks = plan_data.get("tasks", [])
            if not tasks:
                return False, "Plan has no tasks"
            missing_chunk_ids = []
            for idx, task in enumerate(tasks, start=1):
                if not isinstance(task, dict):
                    continue
                chunk = str(task.get("chunk", "")).strip()
                if not chunk:
                    task_id = str(task.get("id", f"task[{idx}]"))
                    missing_chunk_ids.append(task_id)
            if missing_chunk_ids:
                return (
                    False,
                    f"Tasks missing chunk metadata: {', '.join(missing_chunk_ids[:8])}",
                )
        except json.JSONDecodeError as e:
            return False, f"Plan file is corrupted: {e}"
        except Exception as e:
            return False, f"Error reading plan file: {e}"

        return True, ""

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle select widget changes."""
        _popover_log(f"on_select_changed: selector={event.select.id}, value={event.value}, initialized={self._initialized}")

        # Ignore events during recompose (before show() is called)
        if not self._initialized:
            _popover_log("  -> ignoring, not initialized")
            return

        selector_id = event.select.id

        if selector_id == "plan_selector":
            value = str(event.value)
            next_plan_id = None if value == "latest" else value

            # Textual can emit Changed events when a Select is recomposed with the
            # same value. Treat those as no-ops to avoid message/recompose loops.
            if next_plan_id == self._current_plan_id:
                _popover_log("  -> ignoring no-op plan_selector change")
                return

            self._current_plan_id = next_plan_id

            # Update plan details display
            self._update_plan_details(value)

            if value == "new":
                self.post_message(PlanSelected(None, is_new=True))
            elif value == "latest":
                # Validate latest plan if one exists
                latest_plan = self._get_selected_plan_session()
                if latest_plan:
                    is_valid, error_msg = self._validate_plan_for_execution(
                        latest_plan.plan_id,
                    )
                    if not is_valid:
                        _popover_log(f"  -> latest plan validation failed: {error_msg}")
                        self.app.notify(f"Latest plan invalid: {error_msg}", severity="warning")
                        return
                self.post_message(PlanSelected(None, is_new=False))
            else:
                # Validate specific plan before accepting selection
                is_valid, error_msg = self._validate_plan_for_execution(value)
                if not is_valid:
                    _popover_log(f"  -> plan validation failed: {error_msg}")
                    self.app.notify(f"Plan invalid: {error_msg}", severity="warning")
                    return
                self.post_message(PlanSelected(value, is_new=False))

            # Recompose in execute mode so chunk browser reflects selected plan.
            if self._plan_mode == "execute":
                self._initialized = False
                self.refresh(recompose=True)
                self.call_later(self.show)

        elif selector_id == "depth_selector":
            self.post_message(PlanDepthChanged(str(event.value)))
        elif selector_id == "step_target_selector":
            raw_value = str(event.value)
            target_steps = int(raw_value) if raw_value.isdigit() else None
            self.post_message(PlanStepTargetChanged(target_steps))
        elif selector_id == "chunk_target_selector":
            raw_value = str(event.value)
            target_chunks = int(raw_value) if raw_value.isdigit() else None
            self.post_message(PlanChunkTargetChanged(target_chunks))
        elif selector_id == "execute_auto_continue_selector":
            enabled = str(event.value) == "auto"
            if enabled == self._current_execute_auto_continue:
                return
            self._current_execute_auto_continue = enabled
            self.post_message(ExecuteAutoContinueChanged(enabled))
        elif selector_id == "execute_refinement_mode_selector":
            mode = str(event.value)
            if mode not in {"inherit", "on", "off"}:
                mode = "inherit"
            if mode == self._current_execute_refinement_mode:
                return
            self._current_execute_refinement_mode = mode
            self.post_message(ExecuteRefinementModeChanged(mode))

        elif selector_id == "broadcast_selector":
            value = str(event.value)
            # Convert "off" back to False
            broadcast = False if value == "off" else value
            self.post_message(BroadcastModeChanged(broadcast))
        elif selector_id == "analysis_target_type_selector":
            target = str(event.value)
            if target == self._analysis_target_type:
                return
            self._analysis_target_type = target
            self.post_message(AnalysisTargetTypeChanged(target))
            # Toggle container visibility and update title
            self._toggle_analysis_controls(target)
        elif selector_id == "analysis_profile_selector":
            profile = str(event.value)
            if profile == self._analysis_profile:
                return
            self._analysis_profile = profile
            self.post_message(AnalysisProfileChanged(profile))
        elif selector_id == "analysis_log_selector":
            log_dir = str(event.value)
            if log_dir == self._analysis_selected_log_dir:
                return
            self._analysis_selected_log_dir = log_dir
            # turn=None signals app to pick latest valid turn for this log
            self.post_message(AnalysisTargetChanged(log_dir, None))
        elif selector_id == "analysis_skill_lifecycle_selector":
            mode = str(event.value)
            if mode == self._analysis_skill_lifecycle_mode:
                return
            self._analysis_skill_lifecycle_mode = mode
            self.post_message(AnalysisSkillLifecycleChanged(mode))
        elif selector_id == "analysis_turn_selector":
            turn_raw = str(event.value)
            turn = int(turn_raw) if turn_raw.isdigit() else None
            if turn == self._analysis_selected_turn:
                return
            self._analysis_selected_turn = turn
            self.post_message(AnalysisTargetChanged(self._analysis_selected_log_dir, turn))
        elif selector_id == "chunk_range_selector":
            self._selected_chunk_range = str(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "close_btn":
            self.hide()
            event.stop()
        elif event.button.id == "view_plan_btn":
            self._handle_view_plan()
            event.stop()
        elif event.button.id.startswith("chunk_prefill_btn_"):
            chunk_value = self._chunk_button_values.get(event.button.id)
            if chunk_value:
                self.post_message(ExecutePrefillRequested(chunk_value))
            event.stop()
        elif event.button.id == "prefill_range_btn":
            if self._selected_chunk_range:
                self.post_message(ExecutePrefillRequested(self._selected_chunk_range))
            event.stop()
        elif event.button.id == "view_analysis_btn":
            self._handle_view_analysis()
            event.stop()

    def _handle_view_plan(self) -> None:
        """Handle View Plan button click - emit ViewPlanRequested message."""
        _popover_log("_handle_view_plan called")

        # Get the currently selected plan
        plan_id = self._current_plan_id or "latest"

        if plan_id == "new":
            # Can't view a plan that doesn't exist yet
            return

        if plan_id == "latest":
            plan = self._get_selected_plan_session()
        else:
            plan = self._get_plan_by_id(plan_id)

        if not plan:
            _popover_log(f"  -> plan not found: {plan_id}")
            return

        # Load tasks from plan.json
        plan_file = plan.workspace_dir / "plan.json"
        if not plan_file.exists():
            _popover_log(f"  -> plan file not found: {plan_file}")
            return

        try:
            data = json.loads(plan_file.read_text())
            tasks = data.get("tasks", [])
            _popover_log(f"  -> loaded {len(tasks)} tasks from {plan.plan_id}")

            # Emit message to open the modal
            self.post_message(ViewPlanRequested(plan.plan_id, tasks))

            # Hide the popover after opening the modal
            self.hide()

        except Exception as e:
            _popover_log(f"  -> error loading plan: {e}")

    def _handle_view_analysis(self) -> None:
        """Emit an event to open the selected analysis report."""
        if not self._analysis_selected_log_dir:
            return
        if self._analysis_selected_turn is None:
            return
        self.post_message(
            ViewAnalysisRequested(
                self._analysis_selected_log_dir,
                int(self._analysis_selected_turn),
            ),
        )
        self.hide()
