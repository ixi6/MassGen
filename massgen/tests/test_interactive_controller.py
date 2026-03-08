"""Tests for interactive session controller turn-history behavior."""

from __future__ import annotations

import pytest

from massgen.frontend.interactive_controller import (
    InteractiveSessionController,
    SessionContext,
    TurnResult,
)


class _QuestionSourceStub:
    async def get_next(self) -> str | None:
        return None

    def submit(self, text: str) -> None:  # pragma: no cover - not used
        return None

    def close(self) -> None:  # pragma: no cover - not used
        return None


class _AdapterStub:
    def __init__(self) -> None:
        self.processing_states: list[bool] = []
        self.turn_begins: list[tuple[int, str]] = []
        self.turn_ends: list[tuple[int, TurnResult]] = []
        self.notifications: list[tuple[str, str]] = []

    def set_processing(self, is_processing: bool) -> None:
        self.processing_states.append(is_processing)

    def on_turn_begin(self, turn: int, question: str) -> None:
        self.turn_begins.append((turn, question))

    def on_turn_end(self, turn: int, result: TurnResult) -> None:
        self.turn_ends.append((turn, result))

    def reset_turn_view(self) -> None:  # pragma: no cover - not used
        return None

    def notify(self, message: str, level: str = "info") -> None:  # pragma: no cover - not used
        self.notifications.append((level, message))


@pytest.mark.asyncio
async def test_run_turn_appends_user_and_assistant_on_success():
    context = SessionContext(session_id="session_1", current_turn=0, agents={})
    adapter = _AdapterStub()

    async def _turn_runner(**_kwargs) -> TurnResult:
        return TurnResult(
            answer_text="Final answer",
            was_cancelled=False,
            updated_session_id="session_1",
            updated_turn=1,
        )

    controller = InteractiveSessionController(
        question_source=_QuestionSourceStub(),
        adapter=adapter,
        context=context,
        turn_runner=_turn_runner,
    )

    await controller._run_turn("Original question")

    assert context.conversation_history == [
        {"role": "user", "content": "Original question"},
        {"role": "assistant", "content": "Final answer"},
    ]
    assert adapter.processing_states == [True, False]


@pytest.mark.asyncio
async def test_run_turn_appends_user_prompt_when_cancelled():
    context = SessionContext(session_id="session_1", current_turn=0, agents={})
    adapter = _AdapterStub()

    async def _turn_runner(**_kwargs) -> TurnResult:
        return TurnResult(
            was_cancelled=True,
            partial_saved=False,
            updated_session_id="session_1",
            updated_turn=0,
        )

    controller = InteractiveSessionController(
        question_source=_QuestionSourceStub(),
        adapter=adapter,
        context=context,
        turn_runner=_turn_runner,
    )

    await controller._run_turn("Queued fallback prompt")

    assert context.conversation_history == [
        {"role": "user", "content": "Queued fallback prompt"},
    ]


@pytest.mark.asyncio
async def test_cancelled_turn_prompt_is_available_in_future_rounds():
    context = SessionContext(session_id="session_1", current_turn=0, agents={})
    adapter = _AdapterStub()

    results = iter(
        [
            TurnResult(
                was_cancelled=True,
                partial_saved=False,
                updated_session_id="session_1",
                updated_turn=0,
            ),
            TurnResult(
                answer_text="Follow-up answer",
                was_cancelled=False,
                updated_session_id="session_1",
                updated_turn=1,
            ),
        ],
    )

    async def _turn_runner(**_kwargs) -> TurnResult:
        return next(results)

    controller = InteractiveSessionController(
        question_source=_QuestionSourceStub(),
        adapter=adapter,
        context=context,
        turn_runner=_turn_runner,
    )

    await controller._run_turn("Queued fallback prompt")
    await controller._run_turn("Next question")

    assert context.conversation_history == [
        {"role": "user", "content": "Queued fallback prompt"},
        {"role": "user", "content": "Next question"},
        {"role": "assistant", "content": "Follow-up answer"},
    ]
