"""Tests for ensemble coordination pattern (produce → vote → synthesize).

The ensemble pattern is a combination of existing parameters:
- disable_injection: true (agents work independently)
- defer_voting_until_all_answered: true (wait for all answers, then vote)
- max_new_answers_per_agent: 1 (each agent produces 1 answer)
- final_answer_strategy: synthesize (winner synthesizes from all)

These tests verify:
1. SubagentOrchestratorConfig defaults to ensemble behavior
2. Manager propagates ensemble defaults to child orchestrators
3. Skip-vote logic respects defer_voting_until_all_answered
4. Synthesize prompt varies based on whether voting occurred
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

# ── SubagentOrchestratorConfig defaults ──


def test_subagent_orch_default_max_new_answers_is_3():
    """SubagentOrchestratorConfig defaults max_new_answers to 3 (for refine=True).
    The refine=False path forces max_new_answers_per_agent=1 regardless."""
    from massgen.subagent.models import SubagentOrchestratorConfig

    config = SubagentOrchestratorConfig()
    assert config.max_new_answers == 3


def test_subagent_orch_default_disable_injection_is_true():
    """SubagentOrchestratorConfig defaults disable_injection to True."""
    from massgen.subagent.models import SubagentOrchestratorConfig

    config = SubagentOrchestratorConfig()
    assert config.disable_injection is True


def test_subagent_orch_default_defer_voting_is_true():
    """SubagentOrchestratorConfig defaults defer_voting_until_all_answered to True."""
    from massgen.subagent.models import SubagentOrchestratorConfig

    config = SubagentOrchestratorConfig()
    assert config.defer_voting_until_all_answered is True


def test_subagent_orch_serialization_roundtrip():
    """to_dict/from_dict preserves new ensemble fields."""
    from massgen.subagent.models import SubagentOrchestratorConfig

    original = SubagentOrchestratorConfig(
        enabled=True,
        max_new_answers=2,
        disable_injection=False,
        defer_voting_until_all_answered=False,
    )
    data = original.to_dict()
    restored = SubagentOrchestratorConfig.from_dict(data)
    assert restored.max_new_answers == 2
    assert restored.disable_injection is False
    assert restored.defer_voting_until_all_answered is False


def test_subagent_orch_from_dict_uses_defaults():
    """from_dict with empty dict uses ensemble defaults."""
    from massgen.subagent.models import SubagentOrchestratorConfig

    config = SubagentOrchestratorConfig.from_dict({})
    assert config.max_new_answers == 3  # refine=True default
    assert config.disable_injection is True
    assert config.defer_voting_until_all_answered is True


# ── Skip-vote fix ──


def test_skip_vote_respects_defer_voting():
    """_should_skip_vote_rounds_for_synthesize returns False when
    defer_voting_until_all_answered is True (user wants voting)."""
    try:
        from massgen.orchestrator import Orchestrator
    except ModuleNotFoundError as e:
        if "claude_code_sdk" in str(e):
            pytest.skip("Skipping: optional dependency 'claude_code_sdk' not installed")
        raise

    orch = Orchestrator(agents={})
    orch.config = SimpleNamespace(
        coordination_mode="voting",
        final_answer_strategy="synthesize",
        max_new_answers_per_agent=1,
        defer_voting_until_all_answered=True,
        skip_final_presentation=False,
    )
    orch.agents = {"a1": Mock(), "a2": Mock()}

    assert orch._should_skip_vote_rounds_for_synthesize() is False


def test_skip_vote_still_works_without_defer():
    """_should_skip_vote_rounds_for_synthesize still returns True when
    defer_voting_until_all_answered is False (existing behavior)."""
    try:
        from massgen.orchestrator import Orchestrator
    except ModuleNotFoundError as e:
        if "claude_code_sdk" in str(e):
            pytest.skip("Skipping: optional dependency 'claude_code_sdk' not installed")
        raise

    orch = Orchestrator(agents={})
    orch.config = SimpleNamespace(
        coordination_mode="voting",
        final_answer_strategy="synthesize",
        max_new_answers_per_agent=1,
        defer_voting_until_all_answered=False,
        skip_final_presentation=False,
    )
    orch.agents = {"a1": Mock(), "a2": Mock()}

    assert orch._should_skip_vote_rounds_for_synthesize() is True


# ── Synthesize prompt variants ──


def test_synthesize_with_voting_is_winner_biased():
    """When had_voting=True, synthesize prompt is winner-biased."""
    from massgen.message_templates import MessageTemplates

    mt = MessageTemplates(
        original_message="test task",
        agent_count=3,
    )
    result = mt.build_final_presentation_message(
        original_task="test task",
        vote_summary="You received 2 votes",
        all_answers={"a1": "answer 1", "a2": "answer 2"},
        selected_agent_id="a1",
        final_answer_strategy="synthesize",
        had_voting=True,
    )
    assert "selected as the best by your peers" in result
    assert "primary basis" in result


def test_synthesize_without_voting_is_neutral():
    """When had_voting=False, synthesize prompt is neutral (no winner bias)."""
    from massgen.message_templates import MessageTemplates

    mt = MessageTemplates(
        original_message="test task",
        agent_count=3,
    )
    result = mt.build_final_presentation_message(
        original_task="test task",
        vote_summary="No voting round was run.",
        all_answers={"a1": "answer 1", "a2": "answer 2"},
        selected_agent_id="a1",
        final_answer_strategy="synthesize",
        had_voting=False,
    )
    assert "selected as the best" not in result
    assert "primary basis" not in result
    assert "Synthesize the strongest" in result


def test_synthesize_no_voting_hides_your_answer_marker():
    """When had_voting=False, the (YOUR ANSWER) marker is not shown."""
    from massgen.message_templates import MessageTemplates

    mt = MessageTemplates(
        original_message="test task",
        agent_count=3,
    )
    result = mt.build_final_presentation_message(
        original_task="test task",
        vote_summary="No voting round was run.",
        all_answers={"a1": "answer 1", "a2": "answer 2"},
        selected_agent_id="a1",
        final_answer_strategy="synthesize",
        had_voting=False,
    )
    assert "(YOUR ANSWER)" not in result


def test_synthesize_with_voting_shows_your_answer_marker():
    """When had_voting=True, the (YOUR ANSWER) marker is shown."""
    from massgen.message_templates import MessageTemplates

    mt = MessageTemplates(
        original_message="test task",
        agent_count=3,
    )
    result = mt.build_final_presentation_message(
        original_task="test task",
        vote_summary="You received 2 votes",
        all_answers={"a1": "answer 1", "a2": "answer 2"},
        selected_agent_id="a1",
        final_answer_strategy="synthesize",
        had_voting=True,
    )
    assert "(YOUR ANSWER)" in result


def test_winner_present_still_shows_your_answer_marker():
    """winner_present strategy always shows (YOUR ANSWER) marker regardless of had_voting."""
    from massgen.message_templates import MessageTemplates

    mt = MessageTemplates(
        original_message="test task",
        agent_count=3,
    )
    result = mt.build_final_presentation_message(
        original_task="test task",
        vote_summary="You received 2 votes",
        all_answers={"a1": "answer 1", "a2": "answer 2"},
        selected_agent_id="a1",
        final_answer_strategy="winner_present",
        had_voting=True,
    )
    assert "(YOUR ANSWER)" in result


# ── Manager propagation: refine=True must NOT get ensemble defaults ──


# ── Killed agent handling (don't wait forever for errored agents) ──


def test_waiting_skips_killed_agents():
    """_is_waiting_for_all_answers should not wait for killed agents."""
    try:
        from massgen.orchestrator import Orchestrator
    except ModuleNotFoundError as e:
        if "claude_code_sdk" in str(e):
            pytest.skip("Skipping: optional dependency 'claude_code_sdk' not installed")
        raise

    orch = Orchestrator(agents={})
    orch.config = SimpleNamespace(
        coordination_mode="voting",
        final_answer_strategy="synthesize",
        max_new_answers_per_agent=1,
        defer_voting_until_all_answered=True,
        skip_final_presentation=False,
    )
    orch.agents = {"a1": Mock(), "a2": Mock(), "a3": Mock()}

    # a1 answered, a2 answered, a3 killed (errored out)
    orch.agent_states = {
        "a1": SimpleNamespace(answer="answer 1", has_voted=False, is_killed=False, answer_count=1),
        "a2": SimpleNamespace(answer="answer 2", has_voted=False, is_killed=False, answer_count=1),
        "a3": SimpleNamespace(answer=None, has_voted=False, is_killed=True, answer_count=0),
    }
    orch.coordination_tracker = Mock()
    orch.coordination_tracker.answers_by_agent = {"a1": ["ans"], "a2": ["ans"]}

    # a1 should NOT be waiting — a3 is killed, so all "live" agents have answered
    assert orch._is_waiting_for_all_answers("a1") is False


def test_waiting_still_waits_for_live_agents():
    """_is_waiting_for_all_answers should still wait for live unanswered agents."""
    try:
        from massgen.orchestrator import Orchestrator
    except ModuleNotFoundError as e:
        if "claude_code_sdk" in str(e):
            pytest.skip("Skipping: optional dependency 'claude_code_sdk' not installed")
        raise

    orch = Orchestrator(agents={})
    orch.config = SimpleNamespace(
        coordination_mode="voting",
        final_answer_strategy="synthesize",
        max_new_answers_per_agent=1,
        defer_voting_until_all_answered=True,
        skip_final_presentation=False,
    )
    orch.agents = {"a1": Mock(), "a2": Mock(), "a3": Mock()}

    # a1 answered, a2 still working, a3 killed
    orch.agent_states = {
        "a1": SimpleNamespace(answer="answer 1", has_voted=False, is_killed=False, answer_count=1),
        "a2": SimpleNamespace(answer=None, has_voted=False, is_killed=False, answer_count=0),
        "a3": SimpleNamespace(answer=None, has_voted=False, is_killed=True, answer_count=0),
    }
    orch.coordination_tracker = Mock()
    orch.coordination_tracker.answers_by_agent = {"a1": ["ans"]}

    # a1 should still wait — a2 is alive and hasn't answered yet
    assert orch._is_waiting_for_all_answers("a1") is True


# ── Manager propagation tests ──


def _make_subagent_manager(tmp_path, orch_config=None):
    """Helper to create a SubagentManager with minimal config."""
    from massgen.subagent.manager import SubagentManager
    from massgen.subagent.models import SubagentOrchestratorConfig

    parent_workspace = tmp_path / "workspace"
    parent_workspace.mkdir(exist_ok=True)

    if orch_config is None:
        orch_config = SubagentOrchestratorConfig(
            enabled=True,
            agents=[
                {"id": "a1", "backend": {"type": "openai", "model": "gpt-4o"}},
                {"id": "a2", "backend": {"type": "openai", "model": "gpt-4o"}},
            ],
        )

    return SubagentManager(
        parent_workspace=str(parent_workspace),
        parent_agent_id="parent",
        orchestrator_id="orch",
        parent_agent_configs=[
            {"id": "parent", "backend": {"type": "openai", "model": "gpt-4o"}},
        ],
        subagent_orchestrator_config=orch_config,
    )


def test_refine_true_does_not_get_ensemble_defaults(tmp_path):
    """refine=True should NOT inherit disable_injection/defer_voting from
    SubagentOrchestratorConfig — it means collaborative iteration."""
    from massgen.subagent.models import SubagentConfig

    manager = _make_subagent_manager(tmp_path)
    config = SubagentConfig.create(
        task="Evaluate.",
        parent_agent_id="parent",
        metadata={"refine": True, "subagent_type": "round_evaluator"},
    )
    workspace = manager._create_workspace(config.id)
    yaml_config = manager._generate_subagent_yaml_config(config, workspace, context_paths=[])
    orch = yaml_config["orchestrator"]

    # refine=True should NOT have ensemble isolation defaults
    assert orch.get("disable_injection") is not True or "disable_injection" not in orch
    assert orch.get("defer_voting_until_all_answered") is not True or "defer_voting_until_all_answered" not in orch


def test_refine_false_gets_ensemble_defaults(tmp_path):
    """refine=False should get disable_injection and defer_voting from config."""
    from massgen.subagent.models import SubagentConfig

    manager = _make_subagent_manager(tmp_path)
    config = SubagentConfig.create(
        task="Evaluate.",
        parent_agent_id="parent",
        metadata={"refine": False, "subagent_type": "round_evaluator"},
    )
    workspace = manager._create_workspace(config.id)
    yaml_config = manager._generate_subagent_yaml_config(config, workspace, context_paths=[])
    orch = yaml_config["orchestrator"]

    assert orch.get("disable_injection") is True
    assert orch.get("defer_voting_until_all_answered") is True
