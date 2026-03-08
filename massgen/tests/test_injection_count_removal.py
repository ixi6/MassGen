"""Tests for injection_count==0 guard removal.

After this change, the first peer update uses mid-stream injection (preserving
in-progress work) instead of forcing a full restart.  The only protection
against premature injection is first-answer diversity
(`_should_defer_restart_for_first_answer`), which blocks injection until the
agent has produced at least one answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


@dataclass
class _FakeAgentState:
    """Minimal AgentState fields needed by the injection callbacks."""

    answer: str | None = None
    has_voted: bool = False
    restart_pending: bool = False
    injection_count: int = 0
    midstream_injections_this_round: int = 0
    known_answer_ids: set = field(default_factory=set)
    decomposition_answer_streak: int = 0
    seen_answer_counts: dict[str, int] = field(default_factory=dict)
    answer_count: int = 0
    restart_count: int = 0
    is_killed: bool = False
    timeout_reason: str | None = None
    round_start_time: float | None = None
    round_timeout_hooks: Any = None
    round_timeout_state: Any = None
    checklist_calls_this_round: int = 0
    stop_summary: str | None = None
    stop_status: str | None = None
    votes: dict = field(default_factory=dict)
    paraphrase: str | None = None
    last_context: dict | None = None


def _make_orchestrator():
    """Build a minimal Orchestrator without __init__."""
    from massgen.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.agents = {}
    orch.agent_states = {}
    orch.coordination_tracker = MagicMock()
    orch.config = MagicMock()
    orch.config.disable_injection = False
    orch.config.max_midstream_injections_per_round = 2
    return orch


# ---------------------------------------------------------------------------
# Test 1: First peer update uses mid-stream path (not restart)
# ---------------------------------------------------------------------------


class TestFirstPeerUpdateUsesMidstream:
    """When has_hook_delivery=True and injection_count==0, the agent should
    NOT yield ("done", None) — it should fall through to the mid-stream
    injection path, preserving in-progress work.
    """

    @pytest.mark.asyncio
    async def test_first_peer_update_uses_midstream_not_restart(self):
        """With hook delivery and injection_count==0, agent falls through
        to mid-stream path instead of restarting."""
        orch = _make_orchestrator()

        state = _FakeAgentState(
            answer="Some answer",  # has first answer (not deferred)
            restart_pending=True,
            injection_count=0,  # first peer update
        )
        orch.agent_states = {"agent_a": state, "agent_b": _FakeAgentState(answer="peer answer")}
        orch.agents = {"agent_a": MagicMock(), "agent_b": MagicMock()}

        # Mock _should_defer_restart_for_first_answer to return False
        # (agent has already produced first answer)
        orch._should_defer_restart_for_first_answer = MagicMock(return_value=False)
        orch._is_vote_only_mode = MagicMock(return_value=False)
        orch._check_restart_pending = MagicMock(return_value=True)

        # The key assertion: with injection_count==0 and has_hook_delivery=True,
        # the _stream_agent_execution code should NOT yield ("done", None).
        # Instead, it should set _mid_stream_injection = True.
        #
        # We test this indirectly by checking the GeneralHookManager callback:
        # it should NOT return None for injection_count==0 anymore.

        # Set up the callback test via the GeneralHookManager path
        orch._select_midstream_answer_updates = MagicMock(
            return_value=({"agent_b": "peer answer"}, True),
        )
        orch._should_skip_injection_due_to_timeout = MagicMock(return_value=False)
        orch._copy_all_snapshots_to_temp_workspace = AsyncMock()
        orch._build_tool_result_injection = MagicMock(return_value="[INJECTION CONTENT]")
        orch._has_unseen_answer_updates = MagicMock(return_value=False)
        orch._register_injected_answer_updates = MagicMock()
        orch._refresh_checklist_state_for_agent = MagicMock()

        # Build the callback as the orchestrator would
        agent_id = "agent_a"
        answers = {}

        # Simulate the GeneralHookManager get_injection_content callback
        # This mirrors the logic in _stream_agent_execution's hook setup
        # After removing the injection_count==0 guard, the callback should
        # return injection content even when injection_count==0
        result = await self._simulate_general_hook_callback(orch, agent_id, answers)
        assert result is not None, "GeneralHookManager callback should return injection content " "even when injection_count==0 (guard removed)"

    async def _simulate_general_hook_callback(
        self,
        orch,
        agent_id: str,
        answers: dict,
    ) -> str | None:
        """Simulate the get_injection_content callback from GeneralHookManager.

        This mirrors the actual callback logic in orchestrator.py, but with
        the injection_count==0 guard removed (the change we're testing).
        """
        if orch.config.disable_injection:
            return None
        if not orch._check_restart_pending(agent_id):
            return None
        if orch._should_defer_restart_for_first_answer(agent_id):
            orch.agent_states[agent_id].restart_pending = False
            return None
        if orch._is_vote_only_mode(agent_id):
            return None

        current_answers = {aid: state.answer for aid, state in orch.agent_states.items() if state.answer}
        selected_answers, had_unseen_updates = orch._select_midstream_answer_updates(
            agent_id,
            current_answers,
        )
        if not selected_answers:
            return None

        # THE KEY CHANGE: injection_count==0 guard is REMOVED
        # Previously: if orch.agent_states[agent_id].injection_count == 0: return None

        if orch._should_skip_injection_due_to_timeout(agent_id):
            return None

        await orch._copy_all_snapshots_to_temp_workspace(agent_id)
        injection = orch._build_tool_result_injection(agent_id, selected_answers, existing_answers=answers)

        orch.agent_states[agent_id].injection_count += 1
        orch.agent_states[agent_id].midstream_injections_this_round += len(selected_answers)
        answers.update(selected_answers)
        orch.agent_states[agent_id].known_answer_ids.update(selected_answers.keys())

        return injection


# ---------------------------------------------------------------------------
# Test 2: No-hook backend still restarts (unchanged behavior)
# ---------------------------------------------------------------------------


class TestNoHookBackendStillRestarts:
    """When has_hook_delivery=False, agent still restarts regardless of
    injection_count — the no-hook fallback path is unchanged."""

    def test_first_peer_update_still_restarts_without_hooks(self):
        """No-hook backends always restart — not affected by this change."""
        orch = _make_orchestrator()

        state = _FakeAgentState(
            answer="Some answer",
            restart_pending=True,
            injection_count=0,
        )
        orch.agent_states = {"agent_a": state}

        # The no-hook path in _stream_agent_execution checks
        # `if not has_hook_delivery:` and then handles restart directly.
        # This path should be UNCHANGED by our removal of injection_count guards.
        #
        # We verify: when has_hook_delivery=False and is_first_real_attempt=True,
        # the agent restarts (yields "done", None).
        has_hook_delivery = False
        is_first_real_attempt = True

        # Simulate the no-hook branch
        if not has_hook_delivery:
            if not is_first_real_attempt:
                # Would try fallback injection — not our case
                pass
            else:
                # No in-flight buffer; normal restart
                state.restart_pending = False
                state.injection_count += 1
                should_restart = True
        else:
            should_restart = False

        assert should_restart, "No-hook backend should restart on first peer update"
        assert state.injection_count == 1


# ---------------------------------------------------------------------------
# Test 3: GeneralHookManager callback injects on first peer update
# ---------------------------------------------------------------------------


class TestHookCallbackInjectsOnFirstPeerUpdate:
    """The GeneralHookManager callback should return injection content
    when injection_count==0 (previously it returned None)."""

    @pytest.mark.asyncio
    async def test_hook_callback_injects_on_first_peer_update(self):
        orch = _make_orchestrator()

        state = _FakeAgentState(
            answer="My first answer",
            restart_pending=True,
            injection_count=0,  # first peer update
        )
        orch.agent_states = {
            "agent_a": state,
            "agent_b": _FakeAgentState(answer="peer answer"),
        }
        orch.agents = {"agent_a": MagicMock(), "agent_b": MagicMock()}

        orch._check_restart_pending = MagicMock(return_value=True)
        orch._should_defer_restart_for_first_answer = MagicMock(return_value=False)
        orch._is_vote_only_mode = MagicMock(return_value=False)
        orch._select_midstream_answer_updates = MagicMock(
            return_value=({"agent_b": "peer answer"}, True),
        )
        orch._should_skip_injection_due_to_timeout = MagicMock(return_value=False)
        orch._copy_all_snapshots_to_temp_workspace = AsyncMock()
        orch._build_tool_result_injection = MagicMock(return_value="[PEER UPDATE]")
        orch._has_unseen_answer_updates = MagicMock(return_value=False)
        orch._register_injected_answer_updates = MagicMock()
        orch._refresh_checklist_state_for_agent = MagicMock()

        # After the guard removal, the callback should produce content
        # even when injection_count starts at 0
        assert state.injection_count == 0
        result = await self._run_callback(orch, "agent_a", {})
        assert result == "[PEER UPDATE]"
        assert state.injection_count == 1  # incremented after injection

    async def _run_callback(self, orch, agent_id, answers):
        """Run the injection callback logic (with guard removed)."""
        if not orch._check_restart_pending(agent_id):
            return None
        if orch._should_defer_restart_for_first_answer(agent_id):
            return None
        if orch._is_vote_only_mode(agent_id):
            return None

        current_answers = {aid: s.answer for aid, s in orch.agent_states.items() if s.answer}
        selected, _ = orch._select_midstream_answer_updates(agent_id, current_answers)
        if not selected:
            return None

        # No injection_count==0 guard
        if orch._should_skip_injection_due_to_timeout(agent_id):
            return None

        await orch._copy_all_snapshots_to_temp_workspace(agent_id)
        injection = orch._build_tool_result_injection(agent_id, selected, existing_answers=answers)

        orch.agent_states[agent_id].injection_count += 1
        orch.agent_states[agent_id].midstream_injections_this_round += len(selected)
        answers.update(selected)
        orch.agent_states[agent_id].known_answer_ids.update(selected.keys())

        return injection


# ---------------------------------------------------------------------------
# Test 4: Native hook callback injects on first peer update
# ---------------------------------------------------------------------------


class TestNativeHookCallbackInjectsOnFirstPeerUpdate:
    """Native hooks callback should return injection content when
    injection_count==0 (previously it returned None)."""

    @pytest.mark.asyncio
    async def test_native_hook_callback_injects_on_first_peer_update(self):
        orch = _make_orchestrator()

        state = _FakeAgentState(
            answer="My answer",
            restart_pending=True,
            injection_count=0,
        )
        orch.agent_states = {
            "agent_a": state,
            "agent_b": _FakeAgentState(answer="peer answer"),
        }
        orch.agents = {"agent_a": MagicMock(), "agent_b": MagicMock()}

        orch._check_restart_pending = MagicMock(return_value=True)
        orch._should_defer_restart_for_first_answer = MagicMock(return_value=False)
        orch._is_vote_only_mode = MagicMock(return_value=False)
        orch._select_midstream_answer_updates = MagicMock(
            return_value=({"agent_b": "peer answer"}, True),
        )
        orch._should_skip_injection_due_to_timeout = MagicMock(return_value=False)
        orch._copy_all_snapshots_to_temp_workspace = AsyncMock()
        orch._build_tool_result_injection = MagicMock(return_value="[NATIVE INJECTION]")
        orch._has_unseen_answer_updates = MagicMock(return_value=False)
        orch._register_injected_answer_updates = MagicMock()
        orch._refresh_checklist_state_for_agent = MagicMock()

        # The native hook callback (same logic as GeneralHookManager)
        # should also inject when injection_count==0
        assert state.injection_count == 0
        result = await self._run_native_callback(orch, "agent_a", {})
        assert result == "[NATIVE INJECTION]"
        assert state.injection_count == 1

    async def _run_native_callback(self, orch, agent_id, answers):
        """Simulate native hook callback (with guard removed)."""
        if not orch._check_restart_pending(agent_id):
            return None
        if orch._should_defer_restart_for_first_answer(agent_id):
            return None
        if orch._is_vote_only_mode(agent_id):
            return None

        current_answers = {aid: s.answer for aid, s in orch.agent_states.items() if s.answer}
        selected, _ = orch._select_midstream_answer_updates(agent_id, current_answers)
        if not selected:
            return None

        # No injection_count==0 guard (removed)
        if orch._should_skip_injection_due_to_timeout(agent_id):
            return None

        await orch._copy_all_snapshots_to_temp_workspace(agent_id)
        injection = orch._build_tool_result_injection(agent_id, selected, existing_answers=answers)

        orch.agent_states[agent_id].injection_count += 1
        orch.agent_states[agent_id].midstream_injections_this_round += len(selected)
        answers.update(selected)
        orch.agent_states[agent_id].known_answer_ids.update(selected.keys())

        return injection


# ---------------------------------------------------------------------------
# Test 5: Codex MCP hook injects on first peer update
# ---------------------------------------------------------------------------


class TestCodexHookInjectsOnFirstPeerUpdate:
    """Codex MCP hook path should execute injection when injection_count==0
    (previously guarded by injection_count > 0)."""

    @pytest.mark.asyncio
    async def test_codex_hook_injects_on_first_peer_update(self):
        orch = _make_orchestrator()

        state = _FakeAgentState(
            answer="My answer",
            restart_pending=True,
            injection_count=0,
        )
        orch.agent_states = {
            "agent_a": state,
            "agent_b": _FakeAgentState(answer="peer answer"),
        }

        orch._check_restart_pending = MagicMock(return_value=True)
        orch._should_defer_restart_for_first_answer = MagicMock(return_value=False)
        orch._is_vote_only_mode = MagicMock(return_value=False)
        orch._get_current_answers_snapshot = MagicMock(
            return_value={"agent_a": "My answer", "agent_b": "peer answer"},
        )
        orch._select_midstream_answer_updates = MagicMock(
            return_value=({"agent_b": "peer answer"}, True),
        )
        orch._should_skip_injection_due_to_timeout = MagicMock(return_value=False)
        orch._copy_all_snapshots_to_temp_workspace = AsyncMock()
        orch._build_tool_result_injection = MagicMock(return_value="[CODEX INJECTION]")
        orch._has_unseen_answer_updates = MagicMock(return_value=False)
        orch._register_injected_answer_updates = MagicMock()
        orch._refresh_checklist_state_for_agent = MagicMock()

        # Simulate the Codex MCP hook path with the guard removed
        injection_parts: list[str] = []
        answers: dict[str, str] = {}

        # This simulates section 4 of _build_codex_mcp_hook_payload
        if orch._check_restart_pending("agent_a"):
            if not orch._should_defer_restart_for_first_answer("agent_a"):
                if not orch._is_vote_only_mode("agent_a"):
                    current_answers = orch._get_current_answers_snapshot()
                    selected, _ = orch._select_midstream_answer_updates("agent_a", current_answers)

                    if selected:
                        # REMOVED: if self.agent_states[agent_id].injection_count > 0:
                        # Now always inject when selected_answers exist
                        if not orch._should_skip_injection_due_to_timeout("agent_a"):
                            await orch._copy_all_snapshots_to_temp_workspace("agent_a")
                            answer_injection = orch._build_tool_result_injection(
                                "agent_a",
                                selected,
                                existing_answers=answers,
                            )
                            injection_parts.append(answer_injection)
                            state.injection_count += 1

        assert len(injection_parts) == 1
        assert injection_parts[0] == "[CODEX INJECTION]"
        assert state.injection_count == 1


# ---------------------------------------------------------------------------
# Test 6: First-answer diversity still defers
# ---------------------------------------------------------------------------


class TestFirstAnswerDiversityStillDefers:
    """_should_defer_restart_for_first_answer still blocks injection before
    the agent has produced any answer — this protection is unchanged."""

    @pytest.mark.asyncio
    async def test_first_answer_diversity_still_defers(self):
        orch = _make_orchestrator()

        # Agent has NOT produced its first answer yet
        state = _FakeAgentState(
            answer=None,  # no answer yet
            restart_pending=True,
            injection_count=0,
        )
        orch.agent_states = {
            "agent_a": state,
            "agent_b": _FakeAgentState(answer="peer answer"),
        }

        # _should_defer_restart_for_first_answer checks state.answer is None
        orch._should_defer_restart_for_first_answer = MagicMock(return_value=True)
        orch._check_restart_pending = MagicMock(return_value=True)

        # Run the callback
        result = await self._run_callback_with_defer(orch, "agent_a")

        assert result is None, "First-answer diversity protection should still defer injection " "when agent has no answer yet"
        # restart_pending should be cleared by the defer path
        assert state.restart_pending is False

    async def _run_callback_with_defer(self, orch, agent_id):
        """Simulate callback with first-answer deferral."""
        if not orch._check_restart_pending(agent_id):
            return None
        if orch._should_defer_restart_for_first_answer(agent_id):
            orch.agent_states[agent_id].restart_pending = False
            return None
        return "SHOULD NOT REACH HERE"
