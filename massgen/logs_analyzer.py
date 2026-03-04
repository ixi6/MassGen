"""Log analysis and display for MassGen runs.

Provides CLI commands to analyze and display metrics from MassGen run logs.
"""

import json
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Default config file for log analysis
DEFAULT_ANALYSIS_CONFIG = Path(__file__).parent / "configs" / "analysis" / "log_analysis.yaml"


def _natural_sort_key(path: Path | str) -> list:
    """Generate a sort key for natural ordering of paths with numeric components.

    Splits the path string into numeric and non-numeric parts, converting
    numeric parts to integers for proper numeric comparison.
    This ensures turn_2 < turn_10 instead of lexicographic turn_10 < turn_2.

    Args:
        path: Path or string to generate sort key for

    Returns:
        List of mixed str/int tokens for comparison
    """
    path_str = str(path)
    # Split into numeric and non-numeric parts
    parts = re.split(r"(\d+)", path_str)
    # Convert numeric parts to integers for proper numeric sorting
    return [int(part) if part.isdigit() else part for part in parts]


def get_logs_dir() -> Path:
    """Get the logs directory, checking both relative and absolute paths."""
    # Try current directory first
    local_logs = Path(".massgen/massgen_logs")
    if local_logs.exists():
        return local_logs

    # Try home directory
    home_logs = Path.home() / ".massgen" / "massgen_logs"
    if home_logs.exists():
        return home_logs

    # Return local path (will fail later with appropriate error)
    return local_logs


def has_analysis_report(log_dir: Path) -> bool:
    """Check if a log directory has an ANALYSIS_REPORT.md.

    Args:
        log_dir: Path to the log session directory (e.g., log_20260105_105524_290672)

    Returns:
        True if any turn has an ANALYSIS_REPORT.md, False otherwise
    """
    for turn_dir in log_dir.glob("turn_*"):
        if (turn_dir / "ANALYSIS_REPORT.md").exists():
            return True
    return False


class LogAnalyzer:
    """Analyze MassGen log directories."""

    def __init__(self, log_dir: Path | None = None):
        """Initialize analyzer with a specific log directory or find the latest.

        Args:
            log_dir: Path to specific log attempt directory. If None, finds latest.
        """
        self.log_dir = log_dir or self._find_latest_log()
        self.metrics_summary = self._load_metrics_summary()
        self.metrics_events = self._load_metrics_events()

    def _find_latest_log(self) -> Path:
        """Find most recent log directory with metrics."""
        logs_dir = get_logs_dir()
        logs = sorted(logs_dir.glob("log_*"), reverse=True)
        if not logs:
            raise FileNotFoundError(f"No logs found in {logs_dir}")

        # Search through logs to find one with metrics
        for log in logs:
            turns = sorted(log.glob("turn_*"), key=_natural_sort_key)
            if turns:
                attempts = sorted(turns[-1].glob("attempt_*"), key=_natural_sort_key, reverse=True)
                for attempt in attempts:
                    if (attempt / "metrics_summary.json").exists():
                        return attempt

        # Fallback to latest log even without metrics
        log = logs[0]
        turns = sorted(log.glob("turn_*"), key=_natural_sort_key)
        if turns:
            attempts = sorted(turns[-1].glob("attempt_*"), key=_natural_sort_key)
            if attempts:
                return attempts[-1]
        return log

    def _load_metrics_summary(self) -> dict[str, Any]:
        """Load metrics summary JSON."""
        path = self.log_dir / "metrics_summary.json"
        if path.exists():
            return json.loads(path.read_text())
        return {}

    def _load_metrics_events(self) -> dict[str, Any]:
        """Load metrics events JSON."""
        path = self.log_dir / "metrics_events.json"
        if path.exists():
            return json.loads(path.read_text())
        return {}

    def get_summary(self) -> dict[str, Any]:
        """Get summary data for display."""
        return self.metrics_summary

    def get_tools_breakdown(self, sort_by: str = "time") -> list[dict[str, Any]]:
        """Get tool breakdown sorted by time or calls.

        Args:
            sort_by: Either "time" or "calls"

        Returns:
            List of tool metrics dicts sorted by specified key
        """
        tools = self.metrics_summary.get("tools", {}).get("by_tool", {})
        result = []
        for name, data in tools.items():
            result.append(
                {
                    "name": name,
                    "calls": data.get("call_count", 0),
                    "time_ms": data.get("total_execution_time_ms", 0),
                    "avg_ms": data.get("avg_execution_time_ms", 0),
                    "failures": data.get("failure_count", 0),
                },
            )

        key = "time_ms" if sort_by == "time" else "calls"
        return sorted(result, key=lambda x: x[key], reverse=True)

    def get_round_history(self) -> list[dict[str, Any]]:
        """Get round history for all agents."""
        agents = self.metrics_summary.get("agents", {})
        all_rounds = []
        for agent_id, agent_data in agents.items():
            for round_data in agent_data.get("round_history", []):
                round_copy = dict(round_data)
                round_copy["agent_id"] = agent_id
                all_rounds.append(round_copy)
        return sorted(all_rounds, key=lambda x: (x.get("round_number", 0), x.get("start_time", 0)))


def format_duration(ms: float) -> str:
    """Format milliseconds as human-readable duration."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    elif ms < 60000:
        return f"{ms/1000:.1f}s"
    else:
        minutes = ms / 60000
        return f"{minutes:.1f}m"


def display_summary(analyzer: LogAnalyzer, console: Console) -> None:
    """Display run summary using Rich."""
    data = analyzer.get_summary()

    if not data:
        console.print("[yellow]No metrics data found in this log directory.[/yellow]")
        console.print(f"Log directory: {analyzer.log_dir}")
        return

    meta = data.get("meta", {})
    totals = data.get("totals", {})
    data.get("tools", {})
    rounds = data.get("rounds", {})

    # Header panel
    question = meta.get("question", "Unknown")
    if len(question) > 70:
        question = question[:67] + "..."
    winner = meta.get("winner", "N/A")
    cost = totals.get("estimated_cost", 0)
    num_agents = meta.get("num_agents", 1)

    # Calculate duration from round history
    round_history = analyzer.get_round_history()
    if round_history:
        total_duration_ms = sum(r.get("duration_ms", 0) for r in round_history)
        duration_str = format_duration(total_duration_ms)
    else:
        duration_str = "N/A"

    console.print(
        Panel(
            f"[bold]{question}[/bold]\n\n"
            f"Winner: [cyan]{winner}[/cyan] | "
            f"Agents: [yellow]{num_agents}[/yellow] | "
            f"Duration: [magenta]{duration_str}[/magenta] | "
            f"Cost: [green]${cost:.2f}[/green]",
            title="MassGen Run Summary",
            border_style="blue",
        ),
    )

    # Tokens section
    console.print(
        f"\n[bold]Tokens:[/bold] "
        f"Input: [cyan]{totals.get('input_tokens', 0):,}[/cyan] | "
        f"Output: [cyan]{totals.get('output_tokens', 0):,}[/cyan] | "
        f"Reasoning: [cyan]{totals.get('reasoning_tokens', 0):,}[/cyan]",
    )

    # Rounds section
    by_outcome = rounds.get("by_outcome", {})
    total_rounds = rounds.get("total_rounds", 0)
    errors = by_outcome.get("error", 0)
    timeouts = by_outcome.get("timeout", 0)

    outcome_parts = []
    for outcome, count in by_outcome.items():
        if count > 0 and outcome not in ("error", "timeout"):
            outcome_parts.append(f"{outcome}: {count}")

    console.print(
        f"\n[bold]Rounds ({total_rounds}):[/bold] " + " | ".join(outcome_parts) + f"\n  Errors: [{'red' if errors else 'green'}]{errors}[/] | "
        f"Timeouts: [{'red' if timeouts else 'green'}]{timeouts}[/]",
    )

    # Tools table (top 5)
    tool_data = analyzer.get_tools_breakdown()[:5]
    if tool_data:
        console.print()
        table = Table(title="Top Tools by Time", border_style="dim")
        table.add_column("Tool", style="cyan", max_width=45)
        table.add_column("Calls", justify="right")
        table.add_column("Time", justify="right")
        table.add_column("Avg", justify="right")
        table.add_column("Fail", justify="right", style="red")

        for t in tool_data:
            name = t["name"]
            if len(name) > 45:
                name = "..." + name[-42:]
            fail_str = str(t["failures"]) if t["failures"] else ""
            table.add_row(
                name,
                str(t["calls"]),
                format_duration(t["time_ms"]),
                f"{t['avg_ms']:.0f}ms",
                fail_str,
            )
        console.print(table)

    # Subagents section
    subagents_data = data.get("subagents", {})
    if subagents_data and subagents_data.get("total_subagents", 0) > 0:
        total_subagents = subagents_data.get("total_subagents", 0)
        subagent_cost = subagents_data.get("total_estimated_cost", 0)
        agent_cost = totals.get("agent_cost", 0)

        console.print(
            f"\n[bold]Subagents ({total_subagents}):[/bold] " f"Cost: [green]${subagent_cost:.3f}[/green] " f"[dim](parent: ${agent_cost:.2f})[/dim]",
        )

        # Show subagent table
        subagent_list = subagents_data.get("subagents", [])
        if subagent_list:
            sub_table = Table(border_style="dim", show_header=True, header_style="bold")
            sub_table.add_column("Subagent", style="cyan", max_width=20)
            sub_table.add_column("Status", justify="center", max_width=10)
            sub_table.add_column("Time", justify="right")
            sub_table.add_column("Tokens", justify="right")
            sub_table.add_column("Cost", justify="right", style="green")
            sub_table.add_column("Task", max_width=50)

            for sub in subagent_list:
                status = sub.get("status", "unknown")
                status_style = "green" if status == "completed" else "yellow" if status == "running" else "red"
                elapsed = sub.get("elapsed_seconds", 0)
                time_str = f"{elapsed:.1f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
                input_tok = sub.get("input_tokens", 0)
                output_tok = sub.get("output_tokens", 0)
                tokens_str = f"{input_tok:,}→{output_tok:,}"
                cost_val = sub.get("estimated_cost", 0)
                task = sub.get("task", "")
                if len(task) > 50:
                    task = task[:47] + "..."

                sub_table.add_row(
                    sub.get("subagent_id", "?"),
                    f"[{status_style}]{status}[/{status_style}]",
                    time_str,
                    tokens_str,
                    f"${cost_val:.4f}",
                    task,
                )

            console.print(sub_table)

    # API Timing section
    api_timing = data.get("api_timing", {})
    if api_timing and api_timing.get("total_calls", 0) > 0:
        total_api_time = api_timing.get("total_time_ms", 0)
        total_api_calls = api_timing.get("total_calls", 0)
        avg_api_time = api_timing.get("avg_time_ms", 0)
        avg_ttft = api_timing.get("avg_ttft_ms", 0)

        console.print(
            f"\n[bold]API Calls:[/bold] "
            f"Count: [cyan]{total_api_calls}[/cyan] | "
            f"Total Time: [cyan]{format_duration(total_api_time)}[/cyan] | "
            f"Avg: [cyan]{format_duration(avg_api_time)}[/cyan] | "
            f"Avg TTFT: [cyan]{avg_ttft:.0f}ms[/cyan]",
        )

        # Show breakdown by backend if available
        by_backend = api_timing.get("by_backend", {})
        if by_backend and len(by_backend) > 1:
            backend_parts = []
            for backend, stats in by_backend.items():
                calls = stats.get("calls", 0)
                avg_ms = stats.get("avg_time_ms", 0)
                backend_parts.append(f"{backend}: {calls} calls, avg {format_duration(avg_ms)}")
            console.print(f"  [dim]{' | '.join(backend_parts)}[/dim]")

    # Show log directory
    console.print(f"\n[dim]Log: {analyzer.log_dir}[/dim]")


def display_tools(analyzer: LogAnalyzer, console: Console, sort_by: str) -> None:
    """Display full tool breakdown."""
    tool_data = analyzer.get_tools_breakdown(sort_by)

    if not tool_data:
        console.print("[yellow]No tool data found.[/yellow]")
        return

    table = Table(title=f"Tool Breakdown (sorted by {sort_by})", border_style="dim")
    table.add_column("Tool", style="cyan")
    table.add_column("Calls", justify="right")
    table.add_column("Time", justify="right")
    table.add_column("Avg", justify="right")
    table.add_column("Fail", justify="right", style="red")

    total_calls = 0
    total_time = 0.0
    total_fail = 0

    for t in tool_data:
        fail_str = str(t["failures"]) if t["failures"] else ""
        table.add_row(
            t["name"],
            str(t["calls"]),
            format_duration(t["time_ms"]),
            f"{t['avg_ms']:.0f}ms",
            fail_str,
        )
        total_calls += t["calls"]
        total_time += t["time_ms"]
        total_fail += t["failures"]

    table.add_section()
    fail_total = f"[bold red]{total_fail}[/bold red]" if total_fail else ""
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{total_calls}[/bold]",
        f"[bold]{format_duration(total_time)}[/bold]",
        "",
        fail_total,
    )

    console.print(table)
    console.print(f"\n[dim]Log: {analyzer.log_dir}[/dim]")


def display_list(
    console: Console,
    limit: int,
    analyzed_only: bool = False,
    unanalyzed_only: bool = False,
) -> None:
    """Display list of recent runs.

    Args:
        console: Rich console for output
        limit: Maximum number of runs to show
        analyzed_only: If True, only show logs with ANALYSIS_REPORT.md
        unanalyzed_only: If True, only show logs without ANALYSIS_REPORT.md
    """
    logs_dir = get_logs_dir()

    if not logs_dir.exists():
        console.print(f"[red]Logs directory not found:[/red] {logs_dir}")
        return

    all_logs = sorted(logs_dir.glob("log_*"), reverse=True)

    # Filter by analysis status if requested
    if analyzed_only or unanalyzed_only:
        filtered_logs = []
        for log_dir in all_logs:
            has_report = has_analysis_report(log_dir)
            if analyzed_only and has_report:
                filtered_logs.append(log_dir)
            elif unanalyzed_only and not has_report:
                filtered_logs.append(log_dir)
        logs = filtered_logs[:limit]
    else:
        logs = all_logs[:limit]

    if not logs:
        if analyzed_only:
            console.print("[yellow]No analyzed logs found.[/yellow]")
        elif unanalyzed_only:
            console.print("[yellow]No unanalyzed logs found.[/yellow]")
        else:
            console.print("[yellow]No logs found.[/yellow]")
        return

    # Determine title based on filter
    if analyzed_only:
        title = "Analyzed Runs"
    elif unanalyzed_only:
        title = "Unanalyzed Runs"
    else:
        title = "Recent Runs"

    table = Table(title=title, border_style="dim")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Duration", justify="right")
    table.add_column("Cost", justify="right", style="green")
    table.add_column("Analyzed", justify="center")
    table.add_column("Question", max_width=35)

    for i, log_dir in enumerate(logs, 1):
        # Find metrics in this log
        metrics_path = None
        for turn in sorted(log_dir.glob("turn_*"), key=_natural_sort_key):
            for attempt in sorted(turn.glob("attempt_*"), key=_natural_sort_key, reverse=True):
                p = attempt / "metrics_summary.json"
                if p.exists():
                    metrics_path = p
                    break
            if metrics_path:
                break

        # Check if analyzed
        is_analyzed = has_analysis_report(log_dir)
        analyzed_str = "[green]✓[/green]" if is_analyzed else "[dim]-[/dim]"

        # Parse timestamp from directory name: log_YYYYMMDD_HHMMSS_microseconds
        dir_name = log_dir.name
        try:
            parts = dir_name.replace("log_", "").split("_")
            date_part = parts[0]  # YYYYMMDD
            time_part = parts[1] if len(parts) > 1 else "000000"  # HHMMSS
            timestamp = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:]} {time_part[:2]}:{time_part[2:4]}"
        except (IndexError, ValueError):
            timestamp = dir_name

        if metrics_path:
            try:
                data = json.loads(metrics_path.read_text())
                meta = data.get("meta", {})
                totals = data.get("totals", {})

                question = meta.get("question", "")
                if len(question) > 35:
                    question = question[:32] + "..."

                cost = totals.get("estimated_cost", 0)

                # Calculate duration
                agents = data.get("agents", {})
                total_duration_ms = 0.0
                for agent_data in agents.values():
                    for round_data in agent_data.get("round_history", []):
                        total_duration_ms += round_data.get("duration_ms", 0)

                duration_str = format_duration(total_duration_ms) if total_duration_ms > 0 else "-"

                table.add_row(str(i), timestamp, duration_str, f"${cost:.2f}", analyzed_str, question)
            except Exception:
                table.add_row(str(i), timestamp, "?", "?", analyzed_str, "[red]Error reading metrics[/red]")
        else:
            table.add_row(str(i), timestamp, "-", "-", analyzed_str, "[dim]No metrics[/dim]")

    console.print(table)


def open_log_directory(log_dir: Path, console: Console) -> int:
    """Open log directory in system file manager.

    Args:
        log_dir: Path to the log directory to open
        console: Rich console for output

    Returns:
        Exit code (0 for success, 1 for error)
    """
    if not log_dir.exists():
        console.print(f"[red]Error:[/red] Log directory not found: {log_dir}")
        return 1

    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["open", str(log_dir)], check=True)
        elif system == "Windows":
            subprocess.run(["explorer", str(log_dir)], check=True)
        else:  # Linux and others
            subprocess.run(["xdg-open", str(log_dir)], check=True)

        console.print(f"[green]Opened:[/green] {log_dir}")
        return 0
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error opening directory:[/red] {e}")
        return 1
    except FileNotFoundError:
        console.print("[red]Error:[/red] Could not find file manager command")
        console.print(f"Log directory: {log_dir}")
        return 1


def generate_analysis_prompt(log_dir: Path, turn: int | None = None) -> str:
    """Generate a minimal prompt for Claude Code to analyze a log directory.

    Args:
        log_dir: Path to the log session directory (e.g., log_20260105_105524_290672)
        turn: Optional specific turn number to analyze

    Returns:
        A prompt string referencing the skill and log directory
    """
    # Resolve to absolute path for clarity
    abs_log_dir = log_dir.resolve()

    turn_info = f"\nAnalyze turn: turn_{turn}" if turn is not None else ""

    prompt = f"""Use the massgen-log-analyzer skill to analyze:

{abs_log_dir}{turn_info}
"""
    return prompt


def display_analyze_prompt(console: Console, log_dir: Path, turn: int | None = None) -> None:
    """Display analysis prompt with helpful context.

    Args:
        console: Rich console for output
        log_dir: Path to the log directory to analyze
        turn: Optional specific turn number to analyze
    """
    # Find turn directories
    turn_dirs = sorted(log_dir.glob("turn_*"), key=_natural_sort_key)

    if turn is not None:
        target_turn = log_dir / f"turn_{turn}"
        if not target_turn.exists():
            console.print(f"[red]Error:[/red] Turn {turn} not found in {log_dir}")
            if turn_dirs:
                console.print(f"Available turns: {[d.name for d in turn_dirs]}")
            return
    else:
        target_turn = turn_dirs[-1] if turn_dirs else None

    prompt = generate_analysis_prompt(log_dir, turn)

    # Check if analysis report already exists for the target turn
    if target_turn and (target_turn / "ANALYSIS_REPORT.md").exists():
        console.print(f"[yellow]Note: {target_turn.name} already has an ANALYSIS_REPORT.md[/yellow]\n")

    console.print(prompt)
    console.print("[dim italic]Copy this into your coding CLI if not already there[/dim italic]")


def run_self_analysis(
    log_dir: Path,
    config_path: Path | None = None,
    ui_mode: str = "automation",
    console: Console | None = None,
    turn: int | None = None,
    force: bool = False,
) -> int:
    """Run MassGen to analyze a log directory using multi-agent coordination.

    Args:
        log_dir: Path to the log session directory to analyze
        config_path: Optional custom config file. If None, uses default analysis config.
        ui_mode: UI mode - "automation" (headless), "rich_terminal", or "webui"
        console: Optional Rich console for output
        turn: Optional turn number to analyze. If None, analyzes the latest turn.
        force: If True, overwrite existing report without prompting.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    if console is None:
        console = Console()

    # Validate ui_mode
    valid_ui_modes = ["automation", "rich_terminal", "webui"]
    if ui_mode not in valid_ui_modes:
        console.print(f"[red]Error:[/red] Invalid UI mode '{ui_mode}'. Must be one of: {valid_ui_modes}")
        return 1

    # Check for Logfire token - warn if not set but continue
    has_logfire_token = bool(os.environ.get("LOGFIRE_READ_TOKEN"))
    if not has_logfire_token:
        console.print(
            "[yellow]Warning:[/yellow] LOGFIRE_READ_TOKEN not set. " "Logfire MCP will not be available.",
        )
        console.print(
            "[dim]Analysis will use local log files only. " "Set LOGFIRE_READ_TOKEN in .env file for timing/trace analysis.[/dim]\n",
        )

    # Resolve paths
    log_dir = log_dir.resolve()
    config_path = config_path or DEFAULT_ANALYSIS_CONFIG

    if not config_path.exists():
        console.print(f"[red]Error:[/red] Config file not found: {config_path}")
        return 1

    # Load the config
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    except Exception as e:
        console.print(f"[red]Error loading config:[/red] {e}")
        return 1

    # Find the turn directory for the ANALYSIS_REPORT.md
    turn_dirs = list(log_dir.glob("turn_*"))
    if not turn_dirs:
        console.print(f"[red]Error:[/red] No turn directories found in {log_dir}")
        return 1

    # Sort turns naturally (turn_2 < turn_10)
    turn_dirs = sorted(turn_dirs, key=_natural_sort_key)

    if turn is not None:
        # Find specific turn
        target_turn_dir = log_dir / f"turn_{turn}"
        if not target_turn_dir.exists():
            console.print(f"[red]Error:[/red] Turn {turn} not found in {log_dir}")
            console.print(f"Available turns: {[d.name for d in turn_dirs]}")
            return 1
        turn_dir = target_turn_dir
    else:
        # Default to latest turn
        turn_dir = turn_dirs[-1]

    report_path = turn_dir / "ANALYSIS_REPORT.md"
    # Handle existing report
    if report_path.exists():
        if force:
            console.print(f"[yellow]Overwriting existing report in {turn_dir.name}...[/yellow]")
        elif ui_mode == "automation":
            # In automation mode, require --force flag
            console.print(f"[red]Error:[/red] Report already exists for {turn_dir.name}.")
            console.print("Use --force to overwrite in automation mode.")
            return 1
        else:
            # Interactive mode - prompt user
            response = console.input(f"Report exists for {turn_dir.name}. Overwrite? [y/N]: ")
            if response.lower() not in ("y", "yes"):
                console.print("[yellow]Analysis cancelled.[/yellow]")
                return 0
            console.print()

    # Create empty ANALYSIS_REPORT.md if it doesn't exist
    # This is required for context_paths validation
    # Track if we created it so we can clean up on failure
    created_empty_report = False
    if not report_path.exists():
        report_path.touch()
        created_empty_report = True

    # Inject context_paths for safe log access
    # Log dir is read-only, only ANALYSIS_REPORT.md is writable
    config.setdefault("orchestrator", {})
    config["orchestrator"]["context_paths"] = [
        {"path": str(log_dir), "permission": "read"},
        {"path": str(report_path), "permission": "write"},
    ]

    # Remove Logfire MCP from agents if token not available
    if not has_logfire_token:
        for agent in config.get("agents", []):
            backend = agent.get("backend", {})
            mcp_servers = backend.get("mcp_servers", [])
            # Filter out logfire MCP
            backend["mcp_servers"] = [s for s in mcp_servers if s.get("name") != "logfire"]
            # Remove empty mcp_servers list
            if not backend["mcp_servers"]:
                backend.pop("mcp_servers", None)

    # Write modified config to a temporary file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".yaml",
        prefix="massgen_analysis_",
        delete=False,
    ) as tmp_config:
        yaml.dump(config, tmp_config)
        tmp_config_path = tmp_config.name

    try:
        # Build the analysis question - minimal, referencing the skill
        question = f"""Use the massgen-log-analyzer skill to analyze this log directory:
{log_dir}

Analyze turn: {turn_dir.name}

Write your analysis report to: {report_path}

IMPORTANT: Do NOT run any `massgen logs` CLI commands - that would cause infinite recursion.
Read log files directly and use Logfire MCP tools if available."""

        console.print(f"[cyan]Starting self-analysis of:[/cyan] {log_dir}")
        console.print(f"[cyan]Analyzing turn:[/cyan] {turn_dir.name}")
        console.print(f"[dim]Using config: {config_path}[/dim]")
        console.print(f"[dim]UI mode: {ui_mode}[/dim]")
        console.print(f"[dim]Report will be saved to: {report_path}[/dim]\n")

        # Run MassGen with the modified config using uv run massgen
        # This matches how subagent manager invokes MassGen
        cmd = [
            "uv",
            "run",
            "massgen",
            "--config",
            tmp_config_path,
        ]

        # Add UI mode flags (these are CLI flags, not config options)
        if ui_mode == "automation":
            cmd.append("--automation")
        elif ui_mode == "webui":
            cmd.append("--web")
        # rich_terminal is the default, no flag needed

        cmd.append(question)

        # Run as subprocess
        result = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            env=os.environ.copy(),
        )

        if result.returncode == 0:
            console.print("\n[green]Analysis complete![/green]")
            if report_path.exists() and report_path.stat().st_size > 0:
                console.print(f"[green]Report saved to:[/green] {report_path}")
            else:
                console.print("[yellow]Note: ANALYSIS_REPORT.md was not created by the agents.[/yellow]")
                # Clean up empty file we created
                if created_empty_report and report_path.exists() and report_path.stat().st_size == 0:
                    report_path.unlink()
        else:
            console.print(f"\n[red]Analysis failed with exit code {result.returncode}[/red]")
            # Clean up empty file we created on failure
            if created_empty_report and report_path.exists() and report_path.stat().st_size == 0:
                report_path.unlink()
                console.print("[dim]Cleaned up empty report file.[/dim]")

        return result.returncode

    finally:
        # Clean up temporary config file
        try:
            Path(tmp_config_path).unlink()
        except Exception:
            pass
        # Also clean up empty report if subprocess was interrupted
        try:
            if created_empty_report and report_path.exists() and report_path.stat().st_size == 0:
                report_path.unlink()
        except Exception:
            pass


def logs_command(args) -> int:
    """Handle logs subcommand.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    console = Console()

    try:
        logs_cmd = getattr(args, "logs_command", None)

        if logs_cmd == "list":
            limit = getattr(args, "limit", 10)
            analyzed_only = getattr(args, "analyzed", False)
            unanalyzed_only = getattr(args, "unanalyzed", False)
            display_list(console, limit, analyzed_only, unanalyzed_only)
        elif logs_cmd == "analyze":
            # Get log directory - either specified or find latest
            log_dir = None
            if hasattr(args, "log_dir") and args.log_dir:
                log_dir = Path(args.log_dir)
                if not log_dir.exists():
                    console.print(f"[red]Error:[/red] Log directory not found: {log_dir}")
                    return 1
            else:
                # Find the latest log session directory
                logs_dir = get_logs_dir()
                logs = sorted(logs_dir.glob("log_*"), reverse=True)
                if not logs:
                    console.print(f"[red]Error:[/red] No logs found in {logs_dir}")
                    return 1
                log_dir = logs[0]

            mode = getattr(args, "mode", "prompt")
            turn = getattr(args, "turn", None)
            force = getattr(args, "force", False)

            if mode == "prompt":
                display_analyze_prompt(console, log_dir, turn)
            elif mode == "self":
                # Get custom config if provided
                custom_config = None
                if hasattr(args, "config") and args.config:
                    custom_config = Path(args.config)
                    if not custom_config.exists():
                        console.print(f"[red]Error:[/red] Config file not found: {custom_config}")
                        return 1
                else:
                    # Default config uses Gemini - check for API key
                    api_key = os.environ.get("GEMINI_API_KEY", "")
                    # Check it's not empty and not a placeholder from .env.example
                    is_placeholder = api_key.lower().startswith("your-") and api_key.lower().endswith("-key-here")
                    if not api_key or is_placeholder:
                        console.print(
                            "[red]Error:[/red] Self-analysis mode requires GEMINI_API_KEY.\n" "Set it in your environment or use --config with a custom analysis config.",
                        )
                        return 1
                # Get UI mode
                ui_mode = getattr(args, "ui", "automation")
                return run_self_analysis(log_dir, custom_config, ui_mode, console, turn, force)
            else:
                console.print(f"[red]Error:[/red] Unknown mode: {mode}")
                return 1
        elif logs_cmd == "open":
            log_dir = None
            if hasattr(args, "log_dir") and args.log_dir:
                log_dir = Path(args.log_dir)
            else:
                # Find the latest log directory
                analyzer = LogAnalyzer(None)
                log_dir = analyzer.log_dir
            return open_log_directory(log_dir, console)
        else:
            log_dir = None
            if hasattr(args, "log_dir") and args.log_dir:
                log_dir = Path(args.log_dir)

            analyzer = LogAnalyzer(log_dir)

            if hasattr(args, "json") and args.json:
                console.print_json(data=analyzer.get_summary())
            elif logs_cmd == "tools":
                sort_by = getattr(args, "sort", "time")
                display_tools(analyzer, console, sort_by)
            else:  # summary (default)
                display_summary(analyzer, console)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        return 1
    except json.JSONDecodeError as e:
        console.print(f"[red]Error parsing metrics file:[/red] {e}")
        return 1

    return 0
