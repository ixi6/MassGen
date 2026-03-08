"""Session state management for MassGen.

This module provides functionality to save and restore session state,
including conversation history, workspace snapshots, and turn metadata.
"""

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _build_cancelled_turn_history_entry(
    partial_result: dict[str, Any],
    question: str,
) -> str:
    """Build conversation history entry for a cancelled turn.

    Creates a formatted message that summarizes what happened during a cancelled
    turn, appropriate for inclusion in conversation history. The format depends
    on how far the turn progressed before cancellation.

    Args:
        partial_result: Dict containing phase, selected_agent, answers, voting_complete
        question: The user's question for this turn

    Returns:
        Formatted string for the assistant's message in conversation history
    """
    phase = partial_result.get("phase", "unknown")
    selected_agent = partial_result.get("selected_agent")
    answers = partial_result.get("answers", {})
    voting_complete = partial_result.get("voting_complete", False)

    # Case 1: No answers generated (idle or very early coordination)
    if phase == "idle" or not answers:
        return "[CANCELLED - Turn interrupted before any answers were generated.]"

    # Case 2: During presentation phase with selected winner - use their answer
    if phase == "presenting" and selected_agent:
        winner_answer = answers.get(selected_agent, {}).get("answer", "")
        if winner_answer:
            return f"""[CANCELLED - Turn interrupted during final presentation]
Selected winner: {selected_agent}

{winner_answer}"""
        # Fallback if winner has no answer (shouldn't happen)
        return f"[CANCELLED - Turn interrupted during final presentation. Selected winner: {selected_agent}]"

    # Case 3: During coordination - show what agents had
    if phase == "coordinating":
        parts = []

        if voting_complete:
            parts.append("[CANCELLED - Turn interrupted after voting completed, before final presentation]")
        else:
            parts.append("[CANCELLED - Turn interrupted during coordination]")

        parts.append("\nAgents had submitted these answers before cancellation:")
        for agent_id, answer_data in sorted(answers.items()):
            answer_text = answer_data.get("answer", "")
            if answer_text:
                # Truncate long answers for history readability
                preview = answer_text[:500] + "..." if len(answer_text) > 500 else answer_text
                parts.append(f"\n**{agent_id}**: {preview}")

        return "\n".join(parts)

    # Default fallback
    return "[CANCELLED - Turn interrupted.]"


@dataclass
class SessionState:
    """Complete state of a MassGen session.

    Attributes:
        session_id: Unique session identifier
        conversation_history: Full conversation history as messages
        current_turn: Number of completed turns
        last_workspace_path: Path to most recent workspace snapshot
        winning_agents_history: History of winning agents per turn
        previous_turns: Turn metadata for orchestrator
        session_storage_path: Actual directory where session was found (for consistency)
        log_directory: Log directory name to reuse (e.g., "log_20251101_151837")
        incomplete_turn: Info about the last incomplete turn if session was cancelled
        incomplete_turn_workspaces: Dict of agent_id -> workspace path for incomplete turn
    """

    session_id: str
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    current_turn: int = 0
    last_workspace_path: Path | None = None
    winning_agents_history: list[dict[str, Any]] = field(default_factory=list)
    previous_turns: list[dict[str, Any]] = field(default_factory=list)
    session_storage_path: str = "sessions"  # Where the session was actually found
    log_directory: str | None = None  # Log directory to reuse for all turns
    incomplete_turn: dict[str, Any] | None = None  # Last incomplete turn if cancelled
    incomplete_turn_workspaces: dict[str, Path] = field(default_factory=dict)  # agent_id -> workspace


def restore_session(
    session_id: str,
    session_storage: str = "sessions",
    registry: Any | None = None,
) -> SessionState | None:
    """Restore complete session state from disk.

    Loads all turn data from session storage directory, reconstructing:
    - Conversation history from task + answer pairs
    - Turn metadata for orchestrator
    - Winning agents history for memory sharing
    - Most recent workspace path
    - Log directory to reuse

    Args:
        session_id: Session to restore
        session_storage: Base directory for session storage (default: "sessions")
        registry: Optional SessionRegistry instance to load metadata from

    Returns:
        SessionState object if session exists and has turns, None otherwise

    Raises:
        ValueError: If session exists but has no conversation messages (empty session)

    Example:
        >>> state = restore_session("session_20251029_120000")
        >>> if state:
        ...     print(f"Restored {state.current_turn} turns")
        ...     print(f"History: {len(state.conversation_history)} messages")
    """
    # Load log directory from registry if available
    log_directory = None
    if registry:
        session_metadata = registry.get_session(session_id)
        if session_metadata:
            log_directory = session_metadata.get("log_directory")
    # Session storage location (primary: sessions/, legacy: .massgen/memory_test_sessions/)
    session_dir = Path(session_storage) / session_id

    # Check primary location first, then ONE legacy location for backward compatibility
    if not session_dir.exists():
        legacy_dir = Path(".massgen/memory_test_sessions") / session_id
        if legacy_dir.exists():
            session_dir = legacy_dir
            logger.info(f"Using legacy session location: {legacy_dir}")

    # Check if session directory exists
    if not session_dir.exists():
        raise ValueError(
            f"Session '{session_id}' not found in {session_storage} or legacy locations. " f"Cannot continue a non-existent session.",
        )

    # Helper to find turn directories
    def find_turns(base_dir: Path) -> set:
        """Return set of turn numbers that exist in this directory."""
        turns = set()
        for item in base_dir.iterdir():
            if item.is_dir() and item.name.startswith("turn_"):
                try:
                    turn_num = int(item.name.split("_")[1])
                    turns.add(turn_num)
                except (ValueError, IndexError):
                    continue
        return turns

    # Find all turn numbers
    all_turn_nums = find_turns(session_dir)

    if not all_turn_nums:
        raise ValueError(
            f"Session '{session_id}' exists at {session_dir} but has no saved turns. " f"Cannot continue an empty session.",
        )

    # Use the session directory we found
    actual_storage_path = str(session_dir.parent)
    logger.debug(f"Restoring session from: {actual_storage_path}")

    # Load previous turns metadata
    previous_turns = []
    incomplete_turn = None  # Track the last incomplete turn if any

    # Process turns in order
    for turn_num in sorted(all_turn_nums):
        turn_dir = session_dir / f"turn_{turn_num}"

        metadata_file = turn_dir / "metadata.json"
        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                workspace_path = (turn_dir / "workspace").resolve()

                turn_data = {
                    "turn": turn_num,
                    "path": str(workspace_path),
                    "task": metadata.get("task", ""),
                    "winning_agent": metadata.get("winning_agent", ""),
                }

                # Check if this is an incomplete turn (from graceful cancellation)
                if metadata.get("status") == "incomplete":
                    turn_data["status"] = "incomplete"
                    turn_data["phase"] = metadata.get("phase", "unknown")
                    turn_data["voting_complete"] = metadata.get("voting_complete", False)
                    turn_data["selected_agent"] = metadata.get("winning_agent")
                    incomplete_turn = turn_data
                    logger.info(
                        f"Found incomplete turn {turn_num} (cancelled during {turn_data['phase']} phase)",
                    )
                    # Check for partial answers
                    partial_answers_file = turn_dir / "partial_answers.json"
                    if partial_answers_file.exists():
                        try:
                            partial_answers = json.loads(
                                partial_answers_file.read_text(encoding="utf-8"),
                            )
                            turn_data["partial_answers"] = partial_answers
                            turn_data["agents_with_answers"] = list(partial_answers.keys())
                        except (json.JSONDecodeError, OSError):
                            pass

                    # Load all agent workspaces for incomplete turns
                    # These are stored in turn_N/workspaces/{agent_id}/
                    workspaces_dir = turn_dir / "workspaces"
                    if workspaces_dir.exists():
                        agent_workspaces = {}
                        for agent_dir in workspaces_dir.iterdir():
                            if agent_dir.is_dir():
                                agent_workspaces[agent_dir.name] = agent_dir.resolve()
                        turn_data["agent_workspaces"] = agent_workspaces
                        logger.info(
                            f"Found {len(agent_workspaces)} agent workspace(s) for incomplete turn",
                        )

                previous_turns.append(turn_data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load metadata for turn {turn_num}: {e}")

    # Build conversation history from turns
    conversation_history = []

    for turn_data in previous_turns:
        turn_dir = session_dir / f"turn_{turn_data['turn']}"
        answer_file = turn_dir / "answer.txt"

        # Add user message (task)
        if turn_data["task"]:
            conversation_history.append(
                {
                    "role": "user",
                    "content": turn_data["task"],
                },
            )

        # Handle incomplete turns differently - use the cancelled turn history builder
        if turn_data.get("status") == "incomplete":
            partial_answers = turn_data.get("partial_answers", {})

            # Build partial_result dict for the history builder
            partial_result = {
                "phase": turn_data.get("phase", "unknown"),
                "selected_agent": turn_data.get("selected_agent"),
                "answers": partial_answers,
                "voting_complete": turn_data.get("voting_complete", False),
            }

            # Use the history builder to create appropriate entry
            history_content = _build_cancelled_turn_history_entry(
                partial_result,
                turn_data["task"],
            )
            conversation_history.append(
                {
                    "role": "assistant",
                    "content": history_content,
                },
            )
        else:
            # Complete turn - use the final answer
            if answer_file.exists():
                try:
                    answer_text = answer_file.read_text(encoding="utf-8")
                    conversation_history.append(
                        {
                            "role": "assistant",
                            "content": answer_text,
                        },
                    )
                except OSError as e:
                    logger.warning(f"Failed to load answer for turn {turn_data['turn']}: {e}")

    # Validate that we have actual conversation content
    if not conversation_history:
        raise ValueError(
            f"Session '{session_id}' exists but has no conversation messages. "
            f"Found {len(previous_turns)} turn(s) but all tasks/answers were empty or missing. "
            f"Cannot continue an empty session.",
        )

    # Load winning agents history
    winning_agents_history = []
    winning_agents_file = session_dir / "winning_agents_history.json"
    if winning_agents_file.exists():
        try:
            winning_agents_history = json.loads(
                winning_agents_file.read_text(encoding="utf-8"),
            )
            logger.debug(
                f"Loaded {len(winning_agents_history)} winning agent(s) " f"from {winning_agents_file}: {winning_agents_history}",
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load winning agents history from {winning_agents_file}: {e}")

    # Find most recent workspace
    last_workspace_path = None
    if previous_turns:
        last_turn = previous_turns[-1]
        workspace_path = Path(last_turn["path"])
        if workspace_path.exists():
            last_workspace_path = workspace_path

    # Extract incomplete turn workspaces if present
    incomplete_turn_workspaces: dict[str, Path] = {}
    if incomplete_turn and incomplete_turn.get("agent_workspaces"):
        incomplete_turn_workspaces = incomplete_turn["agent_workspaces"]

    # Create and return session state
    state = SessionState(
        session_id=session_id,
        conversation_history=conversation_history,
        current_turn=len(previous_turns),
        last_workspace_path=last_workspace_path,
        winning_agents_history=winning_agents_history,
        previous_turns=previous_turns,
        session_storage_path=actual_storage_path,  # Use actual path where session was found
        log_directory=log_directory,  # Reuse log directory from session metadata
        incomplete_turn=incomplete_turn,  # Last incomplete turn if session was cancelled
        incomplete_turn_workspaces=incomplete_turn_workspaces,  # All agent workspaces from incomplete turn
    )

    # Log restoration info
    incomplete_info = ""
    if incomplete_turn:
        incomplete_info = f" (last turn incomplete, cancelled during {incomplete_turn.get('phase', 'unknown')} phase)"
    logger.info(
        f"📚 Restored session {session_id} from {actual_storage_path}: " f"{state.current_turn} turns, " f"{len(state.conversation_history)} messages{incomplete_info}",
    )

    return state


def save_partial_turn(
    session_id: str,
    turn_number: int,
    question: str,
    partial_result: dict[str, Any],
    session_storage: str = "sessions",
) -> Path:
    """Save partial turn data when a session is cancelled mid-coordination.

    Creates a turn directory with incomplete status that can be reviewed
    or used as context when the session is resumed.

    Args:
        session_id: Session identifier
        turn_number: The turn number (1-indexed)
        question: The user's question for this turn
        partial_result: Dict from orchestrator.get_partial_result() containing:
            - status: "incomplete"
            - phase: Current workflow phase
            - current_task: The task being worked on
            - answers: Dict of agent_id -> answer data
            - workspaces: Dict of agent_id -> workspace path
            - selected_agent: Winning agent if voting completed
        session_storage: Base directory for session storage

    Returns:
        Path to the created turn directory

    Example:
        >>> partial = orchestrator.get_partial_result()
        >>> if partial:
        ...     turn_dir = save_partial_turn(
        ...         "session_123", 1, "What is AI?", partial
        ...     )
        ...     print(f"Saved to {turn_dir}")
    """
    session_dir = Path(session_storage) / session_id
    turn_dir = session_dir / f"turn_{turn_number}"
    turn_dir.mkdir(parents=True, exist_ok=True)

    # Save metadata with incomplete status
    metadata = {
        "turn": turn_number,
        "timestamp": datetime.now().isoformat(),
        "status": "incomplete",
        "phase": partial_result.get("phase", "unknown"),
        "task": question,
        "session_id": session_id,
        "voting_complete": partial_result.get("voting_complete", False),
    }

    # If we have a selected agent (voting completed), record it
    if partial_result.get("selected_agent"):
        metadata["winning_agent"] = partial_result["selected_agent"]

    metadata_file = turn_dir / "metadata.json"
    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logger.info(f"Saved partial turn metadata to {metadata_file}")

    # Save partial answers
    answers = partial_result.get("answers", {})
    if answers:
        answers_file = turn_dir / "partial_answers.json"
        answers_file.write_text(json.dumps(answers, indent=2), encoding="utf-8")
        logger.info(f"Saved {len(answers)} partial answer(s) to {answers_file}")

        # Save answer.txt from best available answer for session restoration
        # Priority: selected_agent > agent with most content > first agent
        best_answer = None
        best_agent = None

        if partial_result.get("selected_agent"):
            best_agent = partial_result["selected_agent"]
            best_answer = answers.get(best_agent, {}).get("answer")

        if not best_answer:
            # Find agent with longest answer
            for agent_id, data in answers.items():
                answer_text = data.get("answer")
                if answer_text:
                    if not best_answer or len(answer_text) > len(best_answer):
                        best_answer = answer_text
                        best_agent = agent_id

        if best_answer:
            answer_file = turn_dir / "answer.txt"
            # Add header noting this is a partial answer
            header = f"[PARTIAL ANSWER - Session was cancelled during {metadata['phase']} phase]\n" f"[Best answer from: {best_agent}]\n" f"{'=' * 60}\n\n"
            answer_file.write_text(header + best_answer, encoding="utf-8")
            logger.info(f"Saved best partial answer from {best_agent} to {answer_file}")

    # Copy workspaces for all agents with answers
    workspaces = partial_result.get("workspaces", {})
    workspaces_dir = turn_dir / "workspaces"
    copied_count = 0

    for agent_id, workspace_path in workspaces.items():
        if workspace_path and Path(workspace_path).exists():
            try:
                dest = workspaces_dir / agent_id
                shutil.copytree(
                    workspace_path,
                    dest,
                    dirs_exist_ok=True,
                    symlinks=True,
                    ignore_dangling_symlinks=True,
                )
                copied_count += 1
            except Exception as e:
                logger.warning(f"Failed to copy workspace for {agent_id}: {e}")

    if copied_count > 0:
        logger.info(f"Copied {copied_count} workspace(s) to {workspaces_dir}")

    # Also copy the selected agent's workspace as 'workspace' for compatibility
    # with session restoration that expects turn_N/workspace/
    if partial_result.get("selected_agent"):
        selected_workspace = workspaces.get(partial_result["selected_agent"])
        if selected_workspace and Path(selected_workspace).exists():
            try:
                main_workspace = turn_dir / "workspace"
                shutil.copytree(
                    selected_workspace,
                    main_workspace,
                    dirs_exist_ok=True,
                    symlinks=True,
                    ignore_dangling_symlinks=True,
                )
                logger.info(f"Copied selected agent workspace to {main_workspace}")
            except Exception as e:
                logger.warning(f"Failed to copy selected agent workspace: {e}")

    # Update session summary
    session_summary_file = session_dir / "SESSION_SUMMARY.txt"
    summary_lines = []

    if session_summary_file.exists():
        summary_lines = session_summary_file.read_text(encoding="utf-8").splitlines()
    else:
        summary_lines.append("=" * 80)
        summary_lines.append(f"Multi-Turn Session: {session_id}")
        summary_lines.append("=" * 80)
        summary_lines.append("")

    # Add turn separator and info
    summary_lines.append("")
    summary_lines.append("=" * 80)
    summary_lines.append(f"TURN {turn_number} [INCOMPLETE - CANCELLED]")
    summary_lines.append("=" * 80)
    summary_lines.append(f"Timestamp: {metadata['timestamp']}")
    summary_lines.append(f"Phase when cancelled: {metadata['phase']}")
    summary_lines.append(f"Task: {question}")
    if partial_result.get("selected_agent"):
        summary_lines.append(f"Selected Agent: {partial_result['selected_agent']}")
    summary_lines.append(f"Agents with answers: {', '.join(answers.keys()) if answers else 'None'}")

    # Show agents with workspaces but no answers
    agents_with_workspace_only = set(workspaces.keys()) - set(answers.keys())
    if agents_with_workspace_only:
        summary_lines.append(f"Agents with workspace only (no answer): {', '.join(agents_with_workspace_only)}")

    if answers:
        summary_lines.append(f"Partial answers saved: {turn_dir / 'partial_answers.json'}")
    if copied_count > 0:
        summary_lines.append(f"Workspaces saved: {workspaces_dir}")
    summary_lines.append("")

    session_summary_file.write_text("\n".join(summary_lines), encoding="utf-8")

    logger.info(f"📝 Saved partial turn {turn_number} to {turn_dir}")
    return turn_dir
