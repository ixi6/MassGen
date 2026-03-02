"""Tests for plan-mode evaluation criteria generation toggles."""

from types import SimpleNamespace

from massgen.cli import (
    _disable_evaluation_criteria_generation_for_planning,
    _is_planning_turn,
    _set_planning_checklist_criteria_defaults,
)


def _mode(plan_mode: str):
    return SimpleNamespace(plan_mode=plan_mode)


def test_is_planning_turn_for_tui_plan_modes():
    assert _is_planning_turn(_mode("plan")) is True
    assert _is_planning_turn(_mode("plan_and_execute")) is True
    assert _is_planning_turn(_mode("execute")) is False
    assert _is_planning_turn(_mode("normal")) is False


def test_is_planning_turn_for_cli_plan_flag():
    assert _is_planning_turn(None, cli_plan_enabled=True) is True
    assert _is_planning_turn(None, cli_plan_enabled=False) is False


def test_disable_eval_criteria_for_object_coordination_config():
    ec_cfg = SimpleNamespace(enabled=True, persist_across_turns=True)
    coordination_config = SimpleNamespace(evaluation_criteria_generator=ec_cfg)

    changed = _disable_evaluation_criteria_generation_for_planning(
        coordination_config,
    )

    assert changed is True
    assert ec_cfg.enabled is False
    assert ec_cfg.persist_across_turns is True


def test_disable_eval_criteria_for_dict_coordination_config():
    coordination_config = {
        "evaluation_criteria_generator": {
            "enabled": True,
            "persist_across_turns": True,
        },
    }

    changed = _disable_evaluation_criteria_generation_for_planning(
        coordination_config,
    )

    assert changed is True
    assert coordination_config["evaluation_criteria_generator"]["enabled"] is False
    assert coordination_config["evaluation_criteria_generator"]["persist_across_turns"] is True


def test_disable_eval_criteria_noops_when_already_disabled():
    coordination_config = {"evaluation_criteria_generator": {"enabled": False}}

    changed = _disable_evaluation_criteria_generation_for_planning(
        coordination_config,
    )

    assert changed is False


def test_set_planning_checklist_defaults_for_object_coordination_config():
    coordination_config = SimpleNamespace(
        checklist_criteria_inline=None,
        checklist_criteria_preset=None,
    )

    changed = _set_planning_checklist_criteria_defaults(
        coordination_config,
    )

    assert changed is True
    assert coordination_config.checklist_criteria_preset == "planning"


def test_set_planning_checklist_defaults_for_dict_coordination_config():
    coordination_config = {
        "checklist_criteria_inline": None,
        "checklist_criteria_preset": None,
    }

    changed = _set_planning_checklist_criteria_defaults(
        coordination_config,
    )

    assert changed is True
    assert coordination_config["checklist_criteria_preset"] == "planning"


def test_set_planning_checklist_defaults_noops_when_inline_set():
    coordination_config = {
        "checklist_criteria_inline": [{"text": "Use this", "category": "must"}],
        "checklist_criteria_preset": None,
    }

    changed = _set_planning_checklist_criteria_defaults(
        coordination_config,
    )

    assert changed is False
    assert coordination_config["checklist_criteria_preset"] is None


def test_set_planning_checklist_defaults_noops_when_preset_set():
    coordination_config = {
        "checklist_criteria_inline": None,
        "checklist_criteria_preset": "persona",
    }

    changed = _set_planning_checklist_criteria_defaults(
        coordination_config,
    )

    assert changed is False
    assert coordination_config["checklist_criteria_preset"] == "persona"
