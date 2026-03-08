"""Session export functionality for MassGen runs.

Exports MassGen sessions by sharing via GitHub Gist.

Enhanced to support multi-turn session sharing:
- find_session_root(): Returns session root directory (not just last turn)
- get_session_turns(): Enumerates all turns with metadata
- parse_turn_range(): Parses turn range specifications
"""

import json
import re
from pathlib import Path

from rich.console import Console

from .logs_analyzer import get_logs_dir
from .share import TurnInfo

# =============================================================================
# Multi-Turn Session Functions
# =============================================================================


def find_session_root(log_dir_arg: str | None = None) -> Path:
    """Find the session root directory (containing all turns).

    Unlike find_latest_log() which returns the last turn's attempt directory,
    this function returns the session root (log_YYYYMMDD_...) so we can
    access all turns for multi-turn sharing.

    Args:
        log_dir_arg: Optional user-provided log directory path or name

    Returns:
        Path to the session root directory (e.g., .massgen/massgen_logs/log_20251225_222632/)

    Raises:
        FileNotFoundError: If no valid session is found
    """
    logs_dir = get_logs_dir()

    if log_dir_arg:
        path = Path(log_dir_arg)

        # If absolute path provided
        if path.is_absolute():
            if path.exists():
                # If this is already a session root (has turn_* subdirs)
                if list(path.glob("turn_*")):
                    return path
                # If this is a turn or attempt directory, go up to session root
                if path.name.startswith("attempt_"):
                    return path.parent.parent.parent
                if path.name.startswith("turn_"):
                    return path.parent
                # If it exists but doesn't match patterns, might be the root
                return path
            raise FileNotFoundError(f"Log directory not found: {path}")

        # Try as a log directory name in logs_dir
        log_path = logs_dir / log_dir_arg
        if log_path.exists():
            return log_path

        # Try with log_ prefix
        if not log_dir_arg.startswith("log_"):
            log_path = logs_dir / f"log_{log_dir_arg}"
            if log_path.exists():
                return log_path

        raise FileNotFoundError(f"Log directory not found: {log_dir_arg}")

    # Find latest session
    logs = sorted(logs_dir.glob("log_*"), reverse=True)
    if not logs:
        raise FileNotFoundError(f"No logs found in {logs_dir}")

    # Return the most recent session that has at least one turn
    for log in logs:
        if list(log.glob("turn_*")):
            return log

    # Fallback to most recent even without turns
    return logs[0]


def get_session_turns(session_root: Path, include_all_attempts: bool = True) -> list[TurnInfo]:
    """Get all turns in a session with metadata.

    Args:
        session_root: Path to the session root directory
        include_all_attempts: If True, include all attempts for each turn.
                              If False, only include the latest attempt per turn.

    Returns:
        List of TurnInfo objects for each turn/attempt, sorted by turn number then attempt number
    """
    turns: list[TurnInfo] = []

    # Find all turn directories
    turn_dirs = sorted(session_root.glob("turn_*"))

    for turn_dir in turn_dirs:
        # Extract turn number from directory name (turn_1, turn_2, etc.)
        match = re.match(r"turn_(\d+)", turn_dir.name)
        if not match:
            continue
        turn_number = int(match.group(1))

        # Find all attempts in this turn
        attempts = sorted(turn_dir.glob("attempt_*"))
        if not attempts:
            continue

        total_attempts = len(attempts)

        # Either include all attempts or just the latest
        attempts_to_process = attempts if include_all_attempts else [attempts[-1]]

        for attempt_dir in attempts_to_process:
            attempt_match = re.match(r"attempt_(\d+)", attempt_dir.name)
            attempt_number = int(attempt_match.group(1)) if attempt_match else 1

            # Load status from status.json if available
            status = "complete"
            question = None
            winner = None

            status_file = attempt_dir / "status.json"
            if status_file.exists():
                try:
                    status_data = json.loads(status_file.read_text())

                    # Get question and winner first
                    meta = status_data.get("meta", {})
                    question = meta.get("question")
                    results = status_data.get("results", {})
                    winner = results.get("winner")

                    # Check for errors - but if there's a winner, the turn completed successfully
                    # (individual agent errors during coordination don't mean the turn failed)
                    if winner:
                        status = "complete"
                    else:
                        rounds = status_data.get("rounds", {}).get("by_outcome", {})
                        if rounds.get("error", 0) > 0:
                            status = "error"
                        elif rounds.get("timeout", 0) > 0:
                            status = "timeout"
                        # Check if this was a restarted attempt (no winner means it was superseded)
                        if attempt_number < total_attempts:
                            status = "restarted"

                except (json.JSONDecodeError, KeyError):
                    pass
            else:
                # No status.json means interrupted session
                status = "interrupted"

            turns.append(
                TurnInfo(
                    turn_number=turn_number,
                    attempt_number=attempt_number,
                    total_attempts=total_attempts,
                    attempt_path=attempt_dir,
                    status=status,
                    question=question,
                    winner=winner,
                ),
            )

    # Sort by turn number, then attempt number
    turns.sort(key=lambda t: (t.turn_number, t.attempt_number))
    return turns


def parse_turn_range(range_str: str, total_turns: int) -> list[int]:
    """Parse a turn range specification.

    Supported formats:
    - "all": All turns [1, 2, ..., total_turns]
    - "N": Turns 1 through N [1, 2, ..., N]
    - "N-M": Turns N through M [N, N+1, ..., M]
    - "latest": Only the last turn [total_turns]

    Args:
        range_str: The range specification string
        total_turns: Total number of turns in the session

    Returns:
        List of turn numbers to include

    Raises:
        ValueError: If the range specification is invalid or out of bounds
    """
    range_str = range_str.strip().lower()

    if range_str == "all":
        return list(range(1, total_turns + 1))

    if range_str == "latest":
        if total_turns == 0:
            return []
        return [total_turns]

    # Try N-M range format
    range_match = re.match(r"^(\d+)-(\d+)$", range_str)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start < 1 or end > total_turns:
            raise ValueError(
                f"Turn range {start}-{end} out of bounds. Session has {total_turns} turns.",
            )
        if start > end:
            raise ValueError(f"Invalid turn range: start ({start}) > end ({end})")
        return list(range(start, end + 1))

    # Try single number (means turns 1 through N)
    if range_str.isdigit():
        n = int(range_str)
        if n < 1 or n > total_turns:
            raise ValueError(f"Turn {n} not found. Session has {total_turns} turns.")
        return list(range(1, n + 1))

    raise ValueError(
        f'Invalid turn range "{range_str}". Use "all", "N", "N-M", or "latest".',
    )


def find_latest_log() -> Path:
    """Find the most recent log directory with data."""
    logs_dir = get_logs_dir()
    logs = sorted(logs_dir.glob("log_*"), reverse=True)

    if not logs:
        raise FileNotFoundError(f"No logs found in {logs_dir}")

    # Search through logs to find one with metrics
    for log in logs:
        turns = sorted(log.glob("turn_*"), reverse=True)  # Check turns in reverse order
        for turn in turns:
            attempts = sorted(turn.glob("attempt_*"), reverse=True)
            for attempt in attempts:
                if (attempt / "metrics_summary.json").exists() or (attempt / "status.json").exists():
                    return attempt

    # Fallback to latest log even without metrics
    log = logs[0]
    turns = sorted(log.glob("turn_*"))
    if turns:
        attempts = sorted(turns[-1].glob("attempt_*"))
        if attempts:
            return attempts[-1]

    raise FileNotFoundError(f"No valid log attempt found in {logs_dir}")


def resolve_log_dir(log_dir_arg: str | None) -> Path:
    """Resolve log directory from argument or find latest.

    Args:
        log_dir_arg: User-provided log directory path or name

    Returns:
        Path to the log attempt directory
    """
    if not log_dir_arg:
        return find_latest_log()

    path = Path(log_dir_arg)

    # If it's an absolute path, use it directly
    if path.is_absolute():
        if path.exists():
            # Check if this is already an attempt directory
            if (path / "metrics_summary.json").exists() or (path / "status.json").exists():
                return path
            # Check if it's a turn directory
            attempts = sorted(path.glob("attempt_*"))
            if attempts:
                return attempts[-1]
            # Check if it's a log directory
            turns = sorted(path.glob("turn_*"))
            if turns:
                attempts = sorted(turns[-1].glob("attempt_*"))
                if attempts:
                    return attempts[-1]
        raise FileNotFoundError(f"Log directory not found: {path}")

    # Try as a log directory name
    logs_dir = get_logs_dir()

    # Try exact name
    log_path = logs_dir / log_dir_arg
    if log_path.exists():
        turns = sorted(log_path.glob("turn_*"))
        if turns:
            attempts = sorted(turns[-1].glob("attempt_*"))
            if attempts:
                return attempts[-1]

    # Try with log_ prefix
    if not log_dir_arg.startswith("log_"):
        log_path = logs_dir / f"log_{log_dir_arg}"
        if log_path.exists():
            turns = sorted(log_path.glob("turn_*"))
            if turns:
                attempts = sorted(turns[-1].glob("attempt_*"))
                if attempts:
                    return attempts[-1]

    raise FileNotFoundError(f"Log directory not found: {log_dir_arg}")


def export_command(args) -> int:
    """Handle export subcommand - shares session via GitHub Gist.

    Args:
        args: Parsed command line arguments with:
            - log_dir: Optional log directory path/name
            - turns: Turn range ("all", "N", "N-M", "latest")
            - no_workspace: Exclude workspace artifacts
            - workspace_limit: Size limit string (e.g., "500KB")
            - yes: Skip interactive prompts
            - dry_run: Show what would be shared without creating gist
            - verbose: Show detailed file listing
            - json: Output result as JSON

    Returns:
        Exit code (0 for success, 1 for error)
    """
    from .share import ShareError, parse_size, share_session_multi_turn

    # Check for JSON output mode
    json_output = getattr(args, "json", False)
    dry_run = getattr(args, "dry_run", False)
    verbose = getattr(args, "verbose", False)

    # For JSON output, suppress console output until the end
    console = Console(quiet=json_output)

    result_data = {
        "success": False,
        "error": None,
        "url": None,
        "session_root": None,
        "turns": [],
        "files": [],
        "total_size": 0,
    }

    try:
        # Resolve log directory to session root
        log_dir_arg = getattr(args, "log_dir", None)
        session_root = find_session_root(log_dir_arg)
        result_data["session_root"] = str(session_root)

        # Get all turns in the session
        all_turns = get_session_turns(session_root)
        if not all_turns:
            error_msg = "No turns found in session"
            if json_output:
                result_data["error"] = error_msg
                print(json.dumps(result_data, indent=2))
            else:
                console.print(f"[red]Error:[/red] {error_msg}")
            return 1

        # Parse turn range
        turns_arg = getattr(args, "turns", "all")
        try:
            turn_numbers = parse_turn_range(turns_arg, len(all_turns))
        except ValueError as e:
            if json_output:
                result_data["error"] = str(e)
                print(json.dumps(result_data, indent=2))
            else:
                console.print(f"[red]Error:[/red] {e}")
            return 1

        # Filter turns to requested range
        turns = [t for t in all_turns if t.turn_number in turn_numbers]

        if not turns:
            error_msg = "No turns match the specified range"
            if json_output:
                result_data["error"] = error_msg
                print(json.dumps(result_data, indent=2))
            else:
                console.print(f"[red]Error:[/red] {error_msg}")
            return 1

        # Add turn info to result
        result_data["turns"] = [
            {
                "turn_number": t.turn_number,
                "attempt_number": t.attempt_number,
                "status": t.status,
                "question": t.question,
                "winner": t.winner,
            }
            for t in turns
        ]

        # Parse workspace options
        include_workspace = not getattr(args, "no_workspace", False)
        workspace_limit_str = getattr(args, "workspace_limit", "500KB")
        try:
            workspace_limit = parse_size(workspace_limit_str)
        except ValueError as e:
            if json_output:
                result_data["error"] = str(e)
                print(json.dumps(result_data, indent=2))
            else:
                console.print(f"[red]Error:[/red] {e}")
            return 1

        if not json_output:
            console.print(f"[blue]Sharing session from: {session_root}[/blue]")
            console.print()

        try:
            url = share_session_multi_turn(
                session_root,
                turns,
                console=console,
                include_workspace=include_workspace,
                workspace_limit=workspace_limit,
                dry_run=dry_run,
                verbose=verbose,
            )

            result_data["success"] = True
            result_data["url"] = url

            if json_output:
                print(json.dumps(result_data, indent=2))
            else:
                console.print()
                if dry_run:
                    console.print("[yellow]Dry run complete - no gist was created[/yellow]")
                else:
                    console.print(f"[bold green]Share URL: {url}[/bold green]")
                    console.print()
                    console.print("[dim]Anyone with this link can view the session (no login required).[/dim]")
            return 0
        except ShareError as e:
            if json_output:
                result_data["error"] = str(e)
                print(json.dumps(result_data, indent=2))
            else:
                console.print(f"[red]Error:[/red] {e}")
            return 1

    except FileNotFoundError as e:
        if json_output:
            result_data["error"] = str(e)
            print(json.dumps(result_data, indent=2))
        else:
            console.print(f"[red]Error:[/red] {e}")
        return 1
    except json.JSONDecodeError as e:
        error_msg = f"Error parsing JSON file: {e}"
        if json_output:
            result_data["error"] = error_msg
            print(json.dumps(result_data, indent=2))
        else:
            console.print(f"[red]{error_msg}[/red]")
        return 1
    except Exception as e:
        if json_output:
            result_data["error"] = str(e)
            print(json.dumps(result_data, indent=2))
        else:
            console.print(f"[red]Error:[/red] {e}")
        return 1
