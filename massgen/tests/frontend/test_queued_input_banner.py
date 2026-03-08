"""Unit tests for queued-input banner target/pending state rendering."""

from massgen.frontend.displays.textual_widgets.queued_input_banner import (
    QueuedInputBanner,
)


def test_banner_shows_target_label_for_single_message():
    banner = QueuedInputBanner()
    rendered = []
    banner.update = lambda content: rendered.append(content)
    banner.add_message("Focus on integration tests", target_label="agent_b")
    text = rendered[-1].plain
    assert "agent_b" in text


def test_banner_shows_pending_agent_counts():
    banner = QueuedInputBanner()
    rendered = []
    banner.update = lambda content: rendered.append(content)
    banner.add_message("Broadcast context update", target_label="all agents")
    banner.set_pending_counts({"agent_a": 0, "agent_b": 1, "agent_c": 2})
    text = rendered[-1].plain
    assert "agent_b:1" in text
    assert "agent_c:2" in text


def test_banner_shows_recent_multiple_messages_with_targets():
    banner = QueuedInputBanner()
    rendered = []
    banner.update = lambda content: rendered.append(content)

    banner.add_message("First queue item", target_label="agent_a")
    banner.add_message("Second queue item", target_label="agent_b")
    banner.add_message("Third queue item", target_label="all agents")

    text = rendered[-1].plain
    assert "3 messages queued" in text
    assert "latest" in text
    assert "all agents" in text
    assert "Third queue item" in text


def test_banner_set_messages_renders_ids_and_pending_agents():
    banner = QueuedInputBanner()
    rendered = []
    banner.update = lambda content: rendered.append(content)

    banner.set_messages(
        [
            {
                "id": 11,
                "content": "Improve error handling for timeouts",
                "target_label": "all agents",
                "pending_agents": ["agent_a", "agent_b"],
            },
            {
                "id": 12,
                "content": "Add tests for fallback path",
                "target_label": "agent_b",
                "pending_agents": ["agent_b"],
            },
        ],
    )

    text = rendered[-1].plain
    assert "#12" in text
    assert "agent_b" in text
    assert "pending: agent_b" in text


def test_banner_set_messages_renders_source_label():
    banner = QueuedInputBanner()
    rendered = []
    banner.update = lambda content: rendered.append(content)

    banner.set_messages(
        [
            {
                "id": 21,
                "content": "Status update from parent",
                "target_label": "all agents",
                "pending_agents": ["agent_a"],
                "source_label": "parent",
            },
        ],
    )

    text = rendered[-1].plain
    assert "source: parent" in text
