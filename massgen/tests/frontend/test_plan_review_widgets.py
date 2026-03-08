"""Unit tests for plan review and execute popover widgets."""

import json
from pathlib import Path
from types import SimpleNamespace

from massgen.frontend.displays import textual_terminal_display as textual_display_module
from massgen.frontend.displays.textual_widgets.plan_approval_modal import (
    PlanApprovalModal,
    PlanApprovalResult,
    PlanJsonEditorModal,
)
from massgen.frontend.displays.textual_widgets.plan_options import (
    ExecuteAutoContinueChanged,
    ExecutePrefillRequested,
    ExecuteRefinementModeChanged,
    PlanChunkTargetChanged,
    PlanOptionsPopover,
    PlanStepTargetChanged,
)
from massgen.frontend.interactive_controller import (
    TextualInteractiveAdapter,
    TurnResult,
)


class _ButtonEvent:
    def __init__(self, button_id: str) -> None:
        self.button = SimpleNamespace(id=button_id)
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _SelectEvent:
    def __init__(self, selector_id: str, value: str) -> None:
        self.select = SimpleNamespace(id=selector_id)
        self.value = value


class _PlanSelectedEvent:
    def __init__(self, plan_id, is_new: bool = False) -> None:
        self.plan_id = plan_id
        self.is_new = is_new
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _DummyPlan:
    def __init__(
        self,
        plan_id: str,
        workspace_dir: Path,
        *,
        status: str = "ready",
        chunk_order=None,
        current_chunk=None,
        completed_chunks=None,
    ) -> None:
        self.plan_id = plan_id
        self.workspace_dir = workspace_dir
        self._metadata = SimpleNamespace(
            status=status,
            created_at="2026-02-10T00:00:00",
            planning_prompt="Build a feature",
            planning_turn=1,
            chunk_order=chunk_order or [],
            current_chunk=current_chunk,
            completed_chunks=completed_chunks or [],
        )

    def load_metadata(self):
        return self._metadata


class _DummyQuestionInput:
    def __init__(self) -> None:
        self.text = ""
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


def test_plan_review_modal_routes_continue_action():
    modal = PlanApprovalModal(
        tasks=[{"id": "T001", "chunk": "C01", "description": "Task"}],
        plan_path=Path("/tmp/plan.json"),
        plan_data={"tasks": [{"id": "T001", "chunk": "C01"}]},
        revision=2,
    )

    modal._rework_feedback_value = "Tighten scope and rebalance chunks."
    modal.refresh = lambda *args, **kwargs: None
    captured = {}
    modal.dismiss = lambda result: captured.setdefault("result", result)
    modal.on_button_pressed(_ButtonEvent("continue_btn"))

    result = captured["result"]
    assert result.action == "continue"
    assert result.approved is False


def test_plan_review_modal_blocks_continue_without_feedback():
    modal = PlanApprovalModal(
        tasks=[{"id": "T001", "chunk": "C01", "description": "Task"}],
        plan_path=Path("/tmp/plan.json"),
        plan_data={"tasks": [{"id": "T001", "chunk": "C01"}]},
    )

    captured = {}
    modal.refresh = lambda *args, **kwargs: None
    modal.dismiss = lambda result: captured.setdefault("result", result)
    modal.on_button_pressed(_ButtonEvent("continue_btn"))

    assert "result" not in captured
    assert "Enter a planning prompt" in modal._rework_action_status


def test_plan_review_modal_routes_finalize_action():
    modal = PlanApprovalModal(
        tasks=[{"id": "T001", "chunk": "C01", "description": "Task"}],
        plan_path=Path("/tmp/plan.json"),
        plan_data={"tasks": [{"id": "T001", "chunk": "C01"}]},
    )

    captured = {}
    modal.dismiss = lambda result: captured.setdefault("result", result)
    modal.on_button_pressed(_ButtonEvent("finalize_btn"))

    result = captured["result"]
    assert result.action == "finalize"
    assert result.approved is True


def test_plan_review_modal_routes_finalize_manual_action():
    modal = PlanApprovalModal(
        tasks=[{"id": "T001", "chunk": "C01", "description": "Task"}],
        plan_path=Path("/tmp/plan.json"),
        plan_data={"tasks": [{"id": "T001", "chunk": "C01"}]},
    )

    captured = {}
    modal.dismiss = lambda result: captured.setdefault("result", result)
    modal.on_button_pressed(_ButtonEvent("finalize_manual_btn"))

    result = captured["result"]
    assert result.action == "finalize_manual"
    assert result.approved is True


def test_show_plan_approval_modal_routes_finalize_manual_to_non_auto_execute(
    tmp_path,
):
    display = textual_display_module.TextualTerminalDisplay.__new__(
        textual_display_module.TextualTerminalDisplay,
    )
    display._persist_planning_revision_snapshot = lambda *_args, **_kwargs: None
    display._continue_planning_refinement = lambda *_args, **_kwargs: None

    captured = {}

    def _capture_execute(result, mode_state, auto_submit=True):
        captured["result"] = result
        captured["mode_state"] = mode_state
        captured["auto_submit"] = auto_submit

    display._execute_approved_plan = _capture_execute

    plan_path = tmp_path / "project_plan.json"
    plan_data = {"tasks": [{"id": "T001", "chunk": "C01", "description": "Task"}]}
    approval_result = PlanApprovalResult(
        approved=True,
        action="finalize_manual",
        plan_data=plan_data,
        plan_path=plan_path,
    )

    display._app = SimpleNamespace(
        _mode_bar=None,
        notify=lambda *_args, **_kwargs: None,
        call_from_thread=lambda fn: fn(),
        push_screen=lambda _modal, callback: callback(approval_result),
    )

    mode_state = SimpleNamespace(
        plan_revision=1,
        quick_edit_restore_pending=False,
        planning_feedback_history=[],
        last_planning_mode="multi",
        reset_plan_state=lambda: None,
    )

    display.show_plan_approval_modal(
        tasks=plan_data["tasks"],
        plan_path=plan_path,
        plan_data=plan_data,
        mode_state=mode_state,
    )

    assert captured["auto_submit"] is False


def test_plan_review_modal_apply_json_edit_updates_plan_data(tmp_path):
    plan_data = {
        "tasks": [
            {"id": "T001", "chunk": "C01", "description": "Task 1"},
            {"id": "T002", "chunk": "C01", "description": "Task 2"},
        ],
    }
    modal = PlanApprovalModal(
        tasks=plan_data["tasks"],
        plan_path=tmp_path / "plan.json",
        plan_data=plan_data,
    )
    modal._plan_json_value = json.dumps(
        {
            "tasks": [
                {"id": "T001", "chunk": "C02_backend", "description": "Task 1"},
                {"id": "T002", "chunk": "C02_backend", "description": "Task 2"},
            ],
        },
    )
    modal.refresh = lambda *args, **kwargs: None

    ok = modal._apply_plan_json_edit()

    assert ok is True
    assert all(task["chunk"] == "C02_backend" for task in modal.plan_data["tasks"])
    assert "Applied JSON edits" in modal._json_edit_status


def test_plan_review_modal_toggle_expand():
    modal = PlanApprovalModal(
        tasks=[{"id": "T001", "chunk": "C01", "description": "Task"}],
        plan_path=Path("/tmp/plan.json"),
        plan_data={"tasks": [{"id": "T001", "chunk": "C01"}]},
    )
    modal.refresh = lambda *args, **kwargs: None
    assert modal._expanded is True
    modal.action_toggle_expand()
    assert modal._expanded is False
    modal.action_toggle_expand()
    assert modal._expanded is True


def test_plan_review_modal_edit_plan_json_opens_modal_and_applies_changes():
    modal = PlanApprovalModal(
        tasks=[{"id": "T001", "chunk": "C01", "description": "Task"}],
        plan_path=Path("/tmp/plan.json"),
        plan_data={"tasks": [{"id": "T001", "chunk": "C01", "description": "Task"}]},
    )
    modal.refresh = lambda *args, **kwargs: None

    edited_json = json.dumps(
        {
            "tasks": [
                {"id": "T001", "chunk": "C02_refined", "description": "Task"},
            ],
        },
    )

    captured = {}

    def _fake_push_screen(screen, callback):
        captured["screen"] = screen
        callback(edited_json)

    modal.push_screen = _fake_push_screen
    modal.on_button_pressed(_ButtonEvent("edit_plan_json_btn"))

    assert isinstance(captured["screen"], PlanJsonEditorModal)
    assert modal.plan_data["tasks"][0]["chunk"] == "C02_refined"
    assert "Applied JSON edits" in modal._json_edit_status


def test_plan_review_modal_edit_plan_json_cancel_keeps_existing_plan():
    modal = PlanApprovalModal(
        tasks=[{"id": "T001", "chunk": "C01", "description": "Task"}],
        plan_path=Path("/tmp/plan.json"),
        plan_data={"tasks": [{"id": "T001", "chunk": "C01", "description": "Task"}]},
    )
    modal.refresh = lambda *args, **kwargs: None
    before = json.dumps(modal.plan_data, sort_keys=True)

    captured = {}

    def _fake_push_screen(screen, callback):
        captured["screen"] = screen
        callback(None)

    modal.push_screen = _fake_push_screen
    modal.on_button_pressed(_ButtonEvent("edit_plan_json_btn"))

    assert isinstance(captured["screen"], PlanJsonEditorModal)
    after = json.dumps(modal.plan_data, sort_keys=True)
    assert after == before


def test_plan_options_builds_chunk_browser_entries(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "plan.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"id": "T001", "chunk": "C01", "status": "completed"},
                    {"id": "T002", "chunk": "C02", "status": "in_progress"},
                    {"id": "T003", "chunk": "C03", "status": "pending"},
                ],
            },
        ),
    )
    plan = _DummyPlan(
        "plan_1",
        workspace,
        chunk_order=["C01", "C02", "C03"],
        current_chunk="C02",
        completed_chunks=["C01"],
    )

    popover = PlanOptionsPopover(
        plan_mode="execute",
        available_plans=[plan],
    )

    entries = popover._build_chunk_browser_entries(plan)
    assert [entry["status"] for entry in entries] == ["completed", "current", "next"]


def test_plan_options_emits_prefill_messages():
    popover = PlanOptionsPopover(plan_mode="execute")
    popover._chunk_button_values = {"chunk_prefill_btn_0": "C02_backend"}
    popover._selected_chunk_range = "C02_backend-C04_tests"

    posted = []
    popover.post_message = lambda message: posted.append(message)

    popover.on_button_pressed(_ButtonEvent("chunk_prefill_btn_0"))
    popover.on_button_pressed(_ButtonEvent("prefill_range_btn"))

    assert len(posted) == 2
    assert isinstance(posted[0], ExecutePrefillRequested)
    assert posted[0].value == "C02_backend"
    assert isinstance(posted[1], ExecutePrefillRequested)
    assert posted[1].value == "C02_backend-C04_tests"


def test_plan_options_validation_blocks_missing_chunk_metadata(tmp_path):
    workspace = tmp_path / "workspace_invalid"
    workspace.mkdir()
    (workspace / "plan.json").write_text(
        json.dumps({"tasks": [{"id": "T001", "description": "No chunk"}]}),
    )
    plan = _DummyPlan("plan_missing_chunk", workspace, status="ready")

    popover = PlanOptionsPopover(
        plan_mode="execute",
        available_plans=[plan],
        current_plan_id=plan.plan_id,
    )

    is_valid, error = popover._validate_plan_for_execution(plan.plan_id)
    assert is_valid is False
    assert "missing chunk metadata" in error


def test_plan_options_emits_step_and_chunk_target_messages():
    popover = PlanOptionsPopover(plan_mode="plan")
    popover._initialized = True

    posted = []
    popover.post_message = lambda message: posted.append(message)

    popover.on_select_changed(_SelectEvent("step_target_selector", "30"))
    popover.on_select_changed(_SelectEvent("chunk_target_selector", "dynamic"))

    assert len(posted) == 2
    assert isinstance(posted[0], PlanStepTargetChanged)
    assert posted[0].target_steps == 30
    assert isinstance(posted[1], PlanChunkTargetChanged)
    assert posted[1].target_chunks is None


def test_plan_options_emits_execute_mode_setting_messages():
    popover = PlanOptionsPopover(plan_mode="execute")
    popover._initialized = True

    posted = []
    popover.post_message = lambda message: posted.append(message)

    popover.on_select_changed(_SelectEvent("execute_auto_continue_selector", "manual"))
    popover.on_select_changed(_SelectEvent("execute_refinement_mode_selector", "off"))

    assert len(posted) == 2
    assert isinstance(posted[0], ExecuteAutoContinueChanged)
    assert posted[0].enabled is False
    assert isinstance(posted[1], ExecuteRefinementModeChanged)
    assert posted[1].mode == "off"


def test_plan_options_ignores_noop_plan_selector_change_in_execute_mode(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "plan.json").write_text(
        json.dumps({"tasks": [{"id": "T001", "chunk": "C01", "status": "pending"}]}),
    )
    plan = _DummyPlan("plan_1", workspace, status="ready")

    popover = PlanOptionsPopover(
        plan_mode="execute",
        available_plans=[plan],
        current_plan_id=plan.plan_id,
    )
    popover._initialized = True
    popover._update_plan_details = lambda *_args, **_kwargs: None
    popover.refresh = lambda *_args, **_kwargs: None
    popover.call_later = lambda *_args, **_kwargs: None

    posted = []
    popover.post_message = lambda message: posted.append(message)

    popover.on_select_changed(_SelectEvent("plan_selector", "plan_1"))

    assert posted == []


def test_plan_options_ignores_noop_execute_setting_changes():
    popover = PlanOptionsPopover(
        plan_mode="execute",
        current_execute_auto_continue=True,
        current_execute_refinement_mode="inherit",
    )
    popover._initialized = True

    posted = []
    popover.post_message = lambda message: posted.append(message)

    popover.on_select_changed(_SelectEvent("execute_auto_continue_selector", "auto"))
    popover.on_select_changed(_SelectEvent("execute_refinement_mode_selector", "inherit"))

    assert posted == []


def test_on_plan_selected_ignores_noop_event_while_locked():
    notifications = []
    event = _PlanSelectedEvent("plan_1", is_new=False)
    app = SimpleNamespace(
        _mode_state=SimpleNamespace(is_locked=lambda: True, selected_plan_id="plan_1"),
        notify=lambda message, **kwargs: notifications.append((message, kwargs)),
    )

    textual_display_module.TextualApp.on_plan_selected(app, event)

    assert notifications == []
    assert event.stopped is True


def test_on_plan_selected_blocks_real_change_while_locked():
    notifications = []
    event = _PlanSelectedEvent("plan_2", is_new=False)
    app = SimpleNamespace(
        _mode_state=SimpleNamespace(is_locked=lambda: True, selected_plan_id="plan_1"),
        notify=lambda message, **kwargs: notifications.append((message, kwargs)),
    )

    textual_display_module.TextualApp.on_plan_selected(app, event)

    assert len(notifications) == 1
    assert notifications[0][0] == "Cannot change plan selection during execution."
    assert event.stopped is True


def test_submit_question_queues_input_during_execution_without_bypass():
    queued_inputs = []
    clear_calls = []
    setup_calls = []

    app = SimpleNamespace(
        question_input=_DummyQuestionInput(),
        _mode_state=SimpleNamespace(plan_mode="execute"),
        _plan_options_popover=SimpleNamespace(classes=set()),
        _clear_cancelled_state=lambda: clear_calls.append(True),
        _is_execution_in_progress=lambda: True,
        _human_input_hook=object(),
        _status_bar=SimpleNamespace(_current_phase="coordination"),
        _queue_human_input=lambda text: queued_inputs.append(text),
        _setup_plan_execution=lambda text: setup_calls.append(text),
    )

    textual_display_module.TextualApp._submit_question(app, "C02_backend")

    assert queued_inputs == ["C02_backend"]
    assert app.question_input.cleared is True
    assert clear_calls == [True]
    assert setup_calls == []


def test_submit_question_does_not_queue_empty_input_during_execution():
    queued_inputs = []
    clear_calls = []
    setup_calls = []

    app = SimpleNamespace(
        question_input=_DummyQuestionInput(),
        _mode_state=SimpleNamespace(plan_mode="execute"),
        _plan_options_popover=SimpleNamespace(classes=set()),
        _clear_cancelled_state=lambda: clear_calls.append(True),
        _is_execution_in_progress=lambda: True,
        _human_input_hook=object(),
        _status_bar=SimpleNamespace(_current_phase="coordination"),
        _queue_human_input=lambda text: queued_inputs.append(text),
        _setup_plan_execution=lambda text: setup_calls.append(text),
    )

    textual_display_module.TextualApp._submit_question(app, "   ")

    assert queued_inputs == []
    assert app.question_input.cleared is True
    assert clear_calls == [True]
    assert setup_calls == []


def test_submit_question_bypass_execution_queue_runs_execute_setup():
    queued_inputs = []
    clear_calls = []
    setup_calls = []

    app = SimpleNamespace(
        question_input=_DummyQuestionInput(),
        _mode_state=SimpleNamespace(plan_mode="execute"),
        _plan_options_popover=SimpleNamespace(classes=set()),
        _clear_cancelled_state=lambda: clear_calls.append(True),
        _is_execution_in_progress=lambda: True,
        _human_input_hook=object(),
        _status_bar=SimpleNamespace(_current_phase="coordination"),
        _queue_human_input=lambda text: queued_inputs.append(text),
        _setup_plan_execution=lambda text: setup_calls.append(text) or None,
    )

    textual_display_module.TextualApp._submit_question(
        app,
        "C02_backend",
        bypass_execution_queue=True,
    )

    assert queued_inputs == []
    assert clear_calls == [True]
    assert setup_calls == ["C02_backend"]


def test_chunk_advance_modal_continue_submits_next_chunk_with_bypass(monkeypatch):
    submitted = []
    notices = []

    class _DummyChunkAdvanceModal:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    app = SimpleNamespace(
        _mode_state=SimpleNamespace(plan_mode="execute"),
        question_input=SimpleNamespace(value=""),
        notify=lambda message, **kwargs: notices.append((message, kwargs)),
        _submit_question=lambda text, **kwargs: submitted.append((text, kwargs)),
        call_later=lambda fn: fn(),
        push_screen=lambda modal, cb: cb(True),
    )

    monkeypatch.setattr(textual_display_module, "ChunkAdvanceModal", _DummyChunkAdvanceModal)
    textual_display_module.TextualApp._show_chunk_advance_modal(
        app,
        completed_chunk="C01_foundation",
        next_chunk="C02_backend",
        auto_continue=True,
    )

    assert app.question_input.value == "C02_backend"
    assert submitted == [("C02_backend", {"bypass_execution_queue": True})]
    assert any("Continuing with next chunk" in msg for msg, _ in notices)


def test_chunk_advance_modal_pause_does_not_submit(monkeypatch):
    submitted = []
    notices = []

    class _DummyChunkAdvanceModal:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    app = SimpleNamespace(
        _mode_state=SimpleNamespace(plan_mode="execute"),
        question_input=SimpleNamespace(value=""),
        notify=lambda message, **kwargs: notices.append((message, kwargs)),
        _submit_question=lambda text, **kwargs: submitted.append((text, kwargs)),
        call_later=lambda fn: fn(),
        push_screen=lambda modal, cb: cb(False),
    )

    monkeypatch.setattr(textual_display_module, "ChunkAdvanceModal", _DummyChunkAdvanceModal)
    textual_display_module.TextualApp._show_chunk_advance_modal(
        app,
        completed_chunk="C01_foundation",
        next_chunk="C02_backend",
        auto_continue=False,
    )

    assert submitted == []
    assert any("Paused after chunk" in msg for msg, _ in notices)


def test_execute_plan_lookup_prefers_tasks_plan_json(monkeypatch, tmp_path):
    session_root = tmp_path / "session"
    workspace = session_root / "final" / "agent_1" / "workspace"
    (workspace / "tasks").mkdir(parents=True)
    (workspace / "deliverable").mkdir(parents=True)

    # Simulate a stale planning artifact plus a current chunk-scoped execution plan.
    (workspace / "deliverable" / "project_plan.json").write_text(
        json.dumps({"tasks": [{"id": "T001", "chunk": "C01", "status": "pending"}]}),
    )
    (workspace / "tasks" / "plan.json").write_text(
        json.dumps({"tasks": [{"id": "T002", "chunk": "C02", "status": "in_progress"}]}),
    )

    monkeypatch.setattr("massgen.logger_config.get_log_session_dir", lambda: session_root)

    adapter = TextualInteractiveAdapter(display=None)
    result = adapter._find_plan_from_workspace(prefer_execution_scope=True)
    assert result is not None
    plan_path, plan_data = result
    assert str(plan_path).endswith("tasks/plan.json")
    assert plan_data["tasks"][0]["id"] == "T002"


def test_execute_turn_progress_updates_even_without_answer_text():
    mode_state = SimpleNamespace(
        plan_mode="execute",
        plan_session=object(),
        analysis_config=SimpleNamespace(profile="dev"),
    )
    app = SimpleNamespace(_mode_state=mode_state)
    display = SimpleNamespace(
        _app=app,
        _call_app_method=lambda *_args, **_kwargs: None,
    )

    adapter = TextualInteractiveAdapter(display=display)
    calls = []
    adapter._update_execute_chunk_progress = lambda result, state: calls.append((result, state))

    adapter.on_turn_end(
        2,
        TurnResult(
            answer_text=None,
            was_cancelled=False,
            error=None,
        ),
    )

    assert len(calls) == 1
