"""Unit tests for per-agent runtime-injection badges on tabs."""

from massgen.frontend.displays.textual_widgets.tab_bar import AgentTab, AgentTabBar


def test_agent_tab_render_shows_pending_injection_badge():
    tab = AgentTab("agent_a", model_name="gpt-5.3-codex")
    tab.set_pending_injection_count(2)

    rendered = tab.render()
    assert " Q2" in rendered


def test_agent_tab_bar_updates_pending_counts_for_each_tab():
    tab_bar = AgentTabBar(["agent_a", "agent_b"])
    tab_bar._tabs = {
        "agent_a": AgentTab("agent_a"),
        "agent_b": AgentTab("agent_b"),
    }

    tab_bar.set_pending_injection_counts({"agent_b": 3})

    assert " Q3" in tab_bar._tabs["agent_b"].render()
    assert " Q" not in tab_bar._tabs["agent_a"].render()
