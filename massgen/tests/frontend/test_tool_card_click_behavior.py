"""Tests for ToolCallCard click behavior for subagent tools.

Subagent tools should behave like regular tools on second click:
- First click: expand inline (show result)
- Second click on content: open detail modal (ToolCardClicked)
- Click on left edge (▸ indicator): collapse
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from massgen.frontend.displays.textual_widgets.tool_card import ToolCallCard


class _ToolCardApp(App):
    """Minimal app to host a ToolCallCard and capture messages."""

    def __init__(self, tool_name: str) -> None:
        super().__init__()
        self._tool_name = tool_name
        self.clicked_cards: list[ToolCallCard] = []

    def compose(self) -> ComposeResult:
        yield ToolCallCard(tool_name=self._tool_name)

    def on_tool_call_card_tool_card_clicked(
        self,
        event: ToolCallCard.ToolCardClicked,
    ) -> None:
        self.clicked_cards.append(event.card)
        event.stop()


@pytest.mark.asyncio
async def test_subagent_list_tool_first_click_expands() -> None:
    """First click on a non-expanded subagent tool expands it inline."""
    app = _ToolCardApp("list_subagents")
    async with app.run_test(headless=True) as pilot:
        card = app.query_one(ToolCallCard)
        card.set_result('{"success": true, "subagents": []}', '{"success": true, "subagents": []}')
        await pilot.pause()

        assert not card.is_expanded

        # Click in the middle of the card (not left edge)
        await pilot.click(ToolCallCard, offset=(10, 0))
        await pilot.pause()

        assert card.is_expanded
        # Should NOT have posted ToolCardClicked yet
        assert len(app.clicked_cards) == 0


@pytest.mark.asyncio
async def test_subagent_list_tool_second_click_opens_modal() -> None:
    """Second click (not on left edge) on expanded subagent tool opens detail modal."""
    app = _ToolCardApp("list_subagents")
    async with app.run_test(headless=True) as pilot:
        card = app.query_one(ToolCallCard)
        card.set_result('{"success": true, "subagents": []}', '{"success": true, "subagents": []}')
        await pilot.pause()

        # First click: expand
        await pilot.click(ToolCallCard, offset=(10, 0))
        await pilot.pause()
        assert card.is_expanded

        # Second click (not on left edge): should post ToolCardClicked
        await pilot.click(ToolCallCard, offset=(10, 0))
        await pilot.pause()

        assert len(app.clicked_cards) == 1
        assert app.clicked_cards[0] is card


@pytest.mark.asyncio
async def test_subagent_list_tool_left_edge_click_collapses() -> None:
    """Clicking the left edge (▸ indicator) of an expanded subagent tool collapses it."""
    app = _ToolCardApp("list_subagents")
    async with app.run_test(headless=True) as pilot:
        card = app.query_one(ToolCallCard)
        card.set_result('{"success": true, "subagents": []}', '{"success": true, "subagents": []}')
        await pilot.pause()

        # First click: expand
        await pilot.click(ToolCallCard, offset=(10, 0))
        await pilot.pause()
        assert card.is_expanded

        # Click left edge (x < 3): should collapse, NOT open modal
        await pilot.click(ToolCallCard, offset=(1, 0))
        await pilot.pause()

        assert not card.is_expanded
        assert len(app.clicked_cards) == 0


@pytest.mark.asyncio
async def test_subagent_cancel_tool_second_click_opens_modal() -> None:
    """cancel_subagent also opens modal on second click when expanded."""
    app = _ToolCardApp("cancel_subagent")
    async with app.run_test(headless=True) as pilot:
        card = app.query_one(ToolCallCard)
        card.set_result('{"success": true}', '{"success": true}')
        await pilot.pause()

        # First click: expand
        await pilot.click(ToolCallCard, offset=(10, 0))
        await pilot.pause()
        assert card.is_expanded

        # Second click: open modal
        await pilot.click(ToolCallCard, offset=(10, 0))
        await pilot.pause()

        assert len(app.clicked_cards) == 1


@pytest.mark.asyncio
async def test_spawn_subagents_second_click_opens_modal() -> None:
    """spawn_subagents also supports modal on second click (consistent behavior)."""
    app = _ToolCardApp("spawn_subagents")
    async with app.run_test(headless=True) as pilot:
        card = app.query_one(ToolCallCard)
        card.set_result('{"spawned": []}', '{"spawned": []}')
        await pilot.pause()

        # First click: expand
        await pilot.click(ToolCallCard, offset=(10, 0))
        await pilot.pause()
        assert card.is_expanded

        # Second click (not on left edge): open modal
        await pilot.click(ToolCallCard, offset=(10, 0))
        await pilot.pause()

        assert len(app.clicked_cards) == 1
