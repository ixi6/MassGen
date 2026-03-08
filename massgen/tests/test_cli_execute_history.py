"""Unit tests for execute-mode conversation history selection."""

from types import SimpleNamespace

from massgen.cli import _should_use_conversation_history_for_turn


def _mode(plan_mode: str):
    return SimpleNamespace(plan_mode=plan_mode)


def _agent(auto_discover_custom_tools: bool):
    return SimpleNamespace(
        backend=SimpleNamespace(
            config={"auto_discover_custom_tools": auto_discover_custom_tools},
        ),
    )


def test_no_history_never_injects():
    assert (
        _should_use_conversation_history_for_turn(
            conversation_history=[],
            mode_state=_mode("execute"),
            agents={"agent_a": _agent(True)},
        )
        is False
    )


def test_non_execute_mode_keeps_history():
    assert (
        _should_use_conversation_history_for_turn(
            conversation_history=[{"role": "user", "content": "hello"}],
            mode_state=_mode("normal"),
            agents={"agent_a": _agent(False)},
        )
        is True
    )


def test_execute_mode_disables_history_without_evolving_skills():
    assert (
        _should_use_conversation_history_for_turn(
            conversation_history=[{"role": "user", "content": "hello"}],
            mode_state=_mode("execute"),
            agents={"agent_a": _agent(False)},
        )
        is False
    )


def test_execute_mode_keeps_history_when_evolving_skills_enabled():
    assert (
        _should_use_conversation_history_for_turn(
            conversation_history=[{"role": "user", "content": "hello"}],
            mode_state=_mode("execute"),
            agents={"agent_a": _agent(True)},
        )
        is True
    )


def test_execute_mode_keeps_history_when_any_agent_has_evolving_skills():
    assert (
        _should_use_conversation_history_for_turn(
            conversation_history=[{"role": "user", "content": "hello"}],
            mode_state=_mode("execute"),
            agents={
                "agent_a": _agent(False),
                "agent_b": _agent(True),
            },
        )
        is True
    )
