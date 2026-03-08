"""Status-related modals: System, MCP, Cost, and Metrics."""

from typing import TYPE_CHECKING, Any

try:
    from textual.app import ComposeResult
    from textual.containers import Container, VerticalScroll
    from textual.widgets import Button, Label, Static, TextArea

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from ..modal_base import BaseModal

if TYPE_CHECKING:
    from massgen.frontend.displays.textual_terminal_display import (
        TextualTerminalDisplay,
    )


class SystemStatusModal(BaseModal):
    """Modal to display system status log."""

    def __init__(self, content: str):
        super().__init__()
        self.content = content

    def compose(self) -> ComposeResult:
        with Container(id="system_status_container"):
            yield Label("📋 System Status Log", id="system_status_header")
            yield TextArea(self.content, id="system_status_content", read_only=True)
            yield Button("Close (ESC)", id="close_system_status_button")


class MCPStatusModal(BaseModal):
    """Modal showing MCP server connection status and available tools."""

    def __init__(self, mcp_status: dict[str, Any]):
        super().__init__()
        self.mcp_status = mcp_status

    def compose(self) -> ComposeResult:
        with Container(id="mcp_status_container"):
            yield Label("🔌 MCP Server Status", id="mcp_status_header")
            total_servers = len(self.mcp_status.get("servers", []))
            total_tools = self.mcp_status.get("total_tools", 0)
            yield Label(
                f"{total_servers} server(s) connected • {total_tools} tools available",
                id="mcp_status_summary",
            )
            with VerticalScroll(id="mcp_servers_list"):
                servers = self.mcp_status.get("servers", [])
                if servers:
                    for server in servers:
                        status_icon = "✅" if server.get("connected", False) else "❌"
                        name = server.get("name", "Unknown")
                        tool_count = len(server.get("tools", []))
                        state = server.get("state", "unknown")
                        tools_preview = ", ".join(server.get("tools", [])[:5])
                        if len(server.get("tools", [])) > 5:
                            tools_preview += "..."

                        yield Static(
                            f"{status_icon} [bold]{name}[/]\n" f"   Tools: {tool_count} available\n" f"   State: {state}\n" f"   [dim]{tools_preview}[/]",
                            classes="mcp-server-item",
                            markup=True,
                        )
                else:
                    yield Static(
                        "[dim]No MCP servers connected[/]",
                        markup=True,
                    )
            yield Button("Close (ESC)", id="close_mcp_button")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_mcp_button":
            self.dismiss()


class CostBreakdownModal(BaseModal):
    """Modal to display token usage and cost breakdown per agent."""

    def __init__(self, display: "TextualTerminalDisplay"):
        super().__init__()
        self.coordination_display = display

    def compose(self) -> ComposeResult:
        with Container(id="cost_breakdown_container"):
            yield Label("💰 Cost Breakdown", id="cost_header")
            yield TextArea(self._build_cost_table(), id="cost_content", read_only=True)
            yield Button("Close (ESC)", id="close_cost_button")

    def _build_cost_table(self) -> str:
        """Build a formatted cost breakdown table."""
        orchestrator = getattr(self.coordination_display, "orchestrator", None)
        if not orchestrator:
            return "No orchestrator available. Complete a turn first."

        agents = getattr(orchestrator, "agents", {})
        if not agents:
            return "No agents available."

        lines = []
        lines.append("Agent         │ Input   │ Output  │ Reason  │ Cached  │ Total   │ Cost")
        lines.append("──────────────┼─────────┼─────────┼─────────┼─────────┼─────────┼────────")

        total_input = 0
        total_output = 0
        total_reasoning = 0
        total_cached = 0
        total_all = 0
        total_cost = 0.0

        for agent_id, agent in agents.items():
            backend = getattr(agent, "backend", None)
            if not backend:
                continue

            usage = backend.get_token_usage()
            input_tok = usage.input_tokens
            output_tok = usage.output_tokens
            reasoning_tok = usage.reasoning_tokens
            cached_tok = usage.cached_input_tokens
            total_tok = input_tok + output_tok + reasoning_tok
            cost = usage.estimated_cost

            total_input += input_tok
            total_output += output_tok
            total_reasoning += reasoning_tok
            total_cached += cached_tok
            total_all += total_tok
            total_cost += cost

            agent_name = agent_id[:12].ljust(12)
            lines.append(
                f"{agent_name}  │ {input_tok:>7,} │ {output_tok:>7,} │ " f"{reasoning_tok:>7,} │ {cached_tok:>7,} │ {total_tok:>7,} │ ${cost:>6.4f}",
            )

        lines.append("──────────────┼─────────┼─────────┼─────────┼─────────┼─────────┼────────")
        lines.append(
            f"TOTAL         │ {total_input:>7,} │ {total_output:>7,} │ " f"{total_reasoning:>7,} │ {total_cached:>7,} │ {total_all:>7,} │ ${total_cost:>6.4f}",
        )

        return "\n".join(lines)


class MetricsModal(BaseModal):
    """Modal to display tool execution metrics."""

    def __init__(self, display: "TextualTerminalDisplay"):
        super().__init__()
        self.coordination_display = display

    def compose(self) -> ComposeResult:
        with Container(id="metrics_container"):
            yield Label("📊 Tool Metrics", id="metrics_header")
            yield TextArea(self._build_metrics_table(), id="metrics_content", read_only=True)
            yield Button("Close (ESC)", id="close_metrics_button")

    def _build_metrics_table(self) -> str:
        """Build a formatted metrics table."""
        orchestrator = getattr(self.coordination_display, "orchestrator", None)
        if not orchestrator:
            return "No orchestrator available. Complete a turn first."

        # Try to get tool metrics from orchestrator or agents
        tool_metrics = self._collect_tool_metrics(orchestrator)

        if not tool_metrics:
            return "No tool execution metrics available yet."

        lines = []
        lines.append("Tool Name                │ Calls │ Success │ Failed │ Avg Time")
        lines.append("─────────────────────────┼───────┼─────────┼────────┼──────────")

        for tool_name, metrics in sorted(tool_metrics.items()):
            calls = metrics.get("calls", 0)
            success = metrics.get("success", 0)
            failed = metrics.get("failed", 0)
            avg_time = metrics.get("avg_time", 0.0)

            tool_display = tool_name[:23].ljust(23)
            lines.append(
                f"{tool_display}  │ {calls:>5} │ {success:>7} │ {failed:>6} │ {avg_time:>7.2f}s",
            )

        return "\n".join(lines)

    def _collect_tool_metrics(self, orchestrator) -> dict[str, dict[str, Any]]:
        """Collect tool metrics from the orchestrator or agents."""
        metrics = {}

        # Try to get metrics from orchestrator's tool tracker if available
        tool_tracker = getattr(orchestrator, "tool_tracker", None)
        if tool_tracker:
            raw_metrics = getattr(tool_tracker, "metrics", {})
            for tool_name, data in raw_metrics.items():
                metrics[tool_name] = {
                    "calls": data.get("call_count", 0),
                    "success": data.get("success_count", 0),
                    "failed": data.get("call_count", 0) - data.get("success_count", 0),
                    "avg_time": data.get("avg_duration", 0.0),
                }
            return metrics

        # Fallback: try to collect from agents
        agents = getattr(orchestrator, "agents", {})
        for agent_id, agent in agents.items():
            backend = getattr(agent, "backend", None)
            if not backend:
                continue
            tool_stats = getattr(backend, "tool_execution_stats", {})
            for tool_name, stats in tool_stats.items():
                if tool_name not in metrics:
                    metrics[tool_name] = {
                        "calls": 0,
                        "success": 0,
                        "failed": 0,
                        "total_time": 0.0,
                    }
                metrics[tool_name]["calls"] += stats.get("calls", 0)
                metrics[tool_name]["success"] += stats.get("success", 0)
                metrics[tool_name]["failed"] += stats.get("failed", 0)
                metrics[tool_name]["total_time"] += stats.get("total_time", 0.0)

        # Calculate averages
        for tool_name in metrics:
            calls = metrics[tool_name]["calls"]
            if calls > 0:
                metrics[tool_name]["avg_time"] = metrics[tool_name].get("total_time", 0.0) / calls
            else:
                metrics[tool_name]["avg_time"] = 0.0

        return metrics
