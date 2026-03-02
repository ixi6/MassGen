"""Standalone MCP server that exposes the MassGen submit_checklist tool.

This allows CLI-based backends (Codex) to use the checklist-gated voting
tool as a native MCP tool call.  The server reads checklist configuration
and mutable state from a JSON specs file written by the orchestrator.

The server re-reads the specs file on every tool call so the orchestrator
can update state (remaining budget, has_existing_answers) between rounds
without restarting the server process.

Usage (launched by backend via config.toml):
    fastmcp run massgen/mcp_tools/checklist_tools_server.py:create_server -- \
        --specs /path/to/checklist_specs.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import fastmcp

logger = logging.getLogger(__name__)

SERVER_NAME = "massgen_checklist"


def _resolve_hook_middleware() -> Any:
    """Return hook middleware class in both package and file-path launch modes."""
    try:
        from massgen.mcp_tools.hook_middleware import MassGenHookMiddleware

        return MassGenHookMiddleware
    except ImportError:
        pass

    try:
        from .hook_middleware import MassGenHookMiddleware

        return MassGenHookMiddleware
    except ImportError:
        pass

    # fastmcp file-path launches can drop package context; add repo root explicitly.
    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from massgen.mcp_tools.hook_middleware import MassGenHookMiddleware

    return MassGenHookMiddleware


async def create_server() -> fastmcp.FastMCP:
    """Factory function to create MCP server from checklist specs."""
    parser = argparse.ArgumentParser(description="MassGen Checklist MCP Server")
    parser.add_argument(
        "--specs",
        type=str,
        required=True,
        help="Path to JSON file containing checklist specs and state",
    )
    parser.add_argument(
        "--hook-dir",
        type=str,
        default=None,
        help="Optional path to directory for hook IPC files (PostToolUse injection).",
    )
    args = parser.parse_args()

    mcp = fastmcp.FastMCP(SERVER_NAME)

    # Attach hook middleware for PostToolUse injection if hook_dir is configured
    if args.hook_dir:
        MassGenHookMiddleware = _resolve_hook_middleware()
        mcp.add_middleware(MassGenHookMiddleware(Path(args.hook_dir)))
        logger.info("Hook middleware attached (hook_dir=%s)", args.hook_dir)
    specs_path = Path(args.specs)

    _register_checklist_tool(mcp, specs_path)

    logger.info(f"Checklist MCP server ready (specs: {specs_path})")
    return mcp


def _read_specs(specs_path: Path) -> dict[str, Any]:
    """Read specs file, returning empty dict on error."""
    try:
        with open(specs_path) as f:
            return json.load(f)
    except Exception as exc:
        logger.error(f"Failed to read checklist specs: {exc}")
        return {}


def _extract_score(entry: Any) -> int:
    """Extract numeric score from either int or {"score": int, "reasoning": str}."""
    if isinstance(entry, dict):
        return entry.get("score", 0)
    if isinstance(entry, (int, float)):
        return int(entry)
    return 0


def _find_plateaued_criteria(
    current_items: list[dict],
    checklist_history: list[dict],
    items: list[str] | None = None,
    item_categories: dict[str, str] | None = None,
    min_rounds: int = 2,
) -> list[dict]:
    """Return detail dicts for criteria whose scores haven't improved.

    Each returned dict contains:
    - id: criterion ID (e.g. "E1")
    - text: criterion text (from items list)
    - category: must/should/could
    - score_history: list of scores across rounds (prior + current)
    - current_score: latest score

    This rich detail is designed to be passed directly to quality/novelty
    subagents so they have full context about what's stuck and by how much.
    """
    if len(checklist_history) < min_rounds:
        return []
    items = items or []
    item_categories = item_categories or {}
    current_by_id = {d["id"]: d["score"] for d in current_items}
    plateaued = []
    for cid, current_score in current_by_id.items():
        stuck = True
        score_history = []
        for entry in checklist_history[-min_rounds:]:
            prev_items = {d["id"]: d["score"] for d in entry.get("items_detail", [])}
            prev_score = prev_items.get(cid)
            score_history.append(prev_score)
            if prev_score is None or current_score > prev_score + 1:
                stuck = False
                break
        if stuck:
            idx = int(cid[1:]) - 1
            score_history.append(current_score)
            plateaued.append(
                {
                    "id": cid,
                    "text": items[idx] if idx < len(items) else cid,
                    "category": item_categories.get(cid, "unknown"),
                    "score_history": score_history,
                    "current_score": current_score,
                },
            )
    return plateaued


def _normalize_improvement_entry(entry: Any) -> dict[str, Any]:
    """Normalize an improvement entry to {"plan": str, "sources": list}."""
    if isinstance(entry, str):
        return {"plan": entry, "sources": []}
    if isinstance(entry, dict):
        return {
            "plan": str(entry.get("plan", "")),
            "sources": list(entry.get("sources", [])),
        }
    return {"plan": str(entry), "sources": []}


def _normalize_preserve_entry(entry: Any) -> dict[str, str]:
    """Normalize a preserve entry to {"what": str, "source": str}."""
    if isinstance(entry, str):
        return {"what": entry, "source": ""}
    if isinstance(entry, dict):
        return {
            "what": str(entry.get("what", "")),
            "source": str(entry.get("source", "")),
        }
    return {"what": str(entry), "source": ""}


def evaluate_proposed_improvements(
    improvements: dict[str, Any],
    failed_criteria: list[str],
    items: list[str],
    all_criteria_ids: list[str] | None = None,
    preserve: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate that improvements cover all failing criteria and preserve strengths."""
    if not isinstance(improvements, dict):
        return {"valid": False, "error": "improvements must be a dict mapping criterion IDs to lists"}

    if not failed_criteria:
        return {"valid": False, "error": "No failed criteria to improve"}

    missing = [cid for cid in failed_criteria if cid not in improvements]
    empty = [cid for cid in failed_criteria if cid in improvements and not improvements[cid]]

    if missing or empty:
        issues = []
        if missing:
            issues.append(f"Missing improvements for: {', '.join(missing)}")
        if empty:
            issues.append(f"Empty improvements for: {', '.join(empty)}")
        return {
            "valid": False,
            "error": "; ".join(issues),
            "missing_criteria": missing,
            "empty_criteria": empty,
            "failed_criteria": failed_criteria,
        }

    # --- Preserve validation (only when all_criteria_ids is provided) ---
    preserve = preserve or {}
    normalized_preserve: dict[str, dict[str, str]] = {}

    if all_criteria_ids is not None:
        # Require at least one preserve entry when criteria exist
        if all_criteria_ids and not preserve:
            return {
                "valid": False,
                "error": ("Preserve is required: specify what to protect from regression. " f"Criteria available: {', '.join(all_criteria_ids)}"),
            }

        # Validate each preserve entry
        for cid, entry in preserve.items():
            if cid not in all_criteria_ids:
                return {
                    "valid": False,
                    "error": f"Preserve key {cid} is not a valid criterion ID. Valid: {', '.join(all_criteria_ids)}",
                }
            norm = _normalize_preserve_entry(entry)
            if not norm["what"].strip():
                return {
                    "valid": False,
                    "error": f"Preserve entry for {cid} has empty 'what' — describe what to protect.",
                }
            normalized_preserve[cid] = norm
    else:
        # Backward compat: normalize whatever was passed but don't enforce
        for cid, entry in preserve.items():
            normalized_preserve[cid] = _normalize_preserve_entry(entry)

    # --- Build task plan: preserve entries first, then improvements ---
    task_plan: list[dict[str, Any]] = []

    # Preserve entries first
    for cid, pentry in normalized_preserve.items():
        criterion_idx = int(cid[1:]) - 1
        criterion_text = items[criterion_idx] if criterion_idx < len(items) else cid
        task_plan.append(
            {
                "type": "preserve",
                "criterion_id": cid,
                "criterion": criterion_text,
                "what_to_protect": pentry["what"],
                "source": pentry["source"],
            },
        )

    # Improvement entries
    for cid in failed_criteria:
        criterion_idx = int(cid[1:]) - 1
        criterion_text = items[criterion_idx] if criterion_idx < len(items) else cid
        for imp_entry in improvements[cid]:
            norm = _normalize_improvement_entry(imp_entry)
            task_plan.append(
                {
                    "type": "improve",
                    "criterion_id": cid,
                    "criterion": criterion_text,
                    "plan": norm["plan"],
                    "sources": norm["sources"],
                    # Keep backward-compat "improvement" key
                    "improvement": norm["plan"],
                },
            )

    result: dict[str, Any] = {
        "valid": True,
        "task_plan": task_plan,
        "message": (
            f"Improvements validated for {len(failed_criteria)} criteria. "
            f"{len(normalized_preserve)} criteria marked for preservation. "
            "Add each item from task_plan to your task plan tool, then "
            "execute them. Preserve items are guardrails — verify them after "
            "implementing improvements. Do not skip criteria or substitute easier work."
        ),
    }
    if normalized_preserve:
        result["preserve"] = normalized_preserve
    return result


def _resolve_report_file(report_path: str, state: dict[str, Any]) -> tuple[Path | None, str | None]:
    """Resolve report path to a workspace-local absolute path."""
    raw_path = (report_path or "").strip()
    if not raw_path:
        return None, "Missing `report_path`."

    workspace_root = state.get("workspace_path")
    workspace = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (workspace / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(workspace)
    except ValueError:
        return None, f"Report path must stay inside workspace ({workspace})."

    return candidate, None


_DIAGNOSTIC_REPORT_MIN_LENGTH = 100


def _evaluate_gap_report(report_path: str, state: dict[str, Any]) -> dict[str, Any]:
    """Check diagnostic report file existence, substance, and capture content.

    When ``require_diagnostic_report`` is True in state, the report is gated:
    missing, empty, or trivially short reports cause ``passed=False``, which
    the caller uses to override the verdict to iterate. No keyword or
    heuristic matching is performed — the system prompt tells agents what
    sections to write, and we trust that (matching GEPA's approach).

    Report content is captured in ``result["content"]`` for logging and
    potential forwarding to future rounds.
    """
    require_report = bool(state.get("require_diagnostic_report", False))
    result: dict[str, Any] = {
        "provided": bool((report_path or "").strip()),
        "path": (report_path or "").strip(),
        "passed": True,  # default: pass (backward compat when gate inactive)
        "gate_active": require_report,
        "content": None,
        "issues": [],
    }

    if not result["provided"]:
        if require_report:
            result["passed"] = False
            result["issues"].append(
                "Diagnostic report is required before submitting scores. "
                "Write a markdown diagnostic report covering Failure Patterns, "
                "Root Causes, and Goal Alignment, then provide its path via report_path.",
            )
        return result

    resolved, error = _resolve_report_file(report_path, state)
    if error:
        result["issues"].append(error)
        if require_report:
            result["passed"] = False
        return result
    if resolved is None:
        if require_report:
            result["passed"] = False
        return result

    result["resolved_path"] = str(resolved)
    if not resolved.exists():
        result["issues"].append(f"Report file not found: {resolved}")
        if require_report:
            result["passed"] = False
        return result
    if not resolved.is_file():
        result["issues"].append(f"Report path is not a file: {resolved}")
        if require_report:
            result["passed"] = False
        return result

    try:
        report_text = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        result["issues"].append(f"Unable to read report file: {exc}")
        if require_report:
            result["passed"] = False
        return result

    if not report_text.strip():
        result["issues"].append("Report file is empty.")
        if require_report:
            result["passed"] = False
        return result

    result["file_exists"] = True
    result["content"] = report_text

    has_multimodal = bool(state.get("has_multimodal_tools", False))
    min_length = 300 if has_multimodal else _DIAGNOSTIC_REPORT_MIN_LENGTH

    if require_report and len(report_text.strip()) < min_length:
        result["passed"] = False
        msg = "Report is too short to contain meaningful diagnostic analysis. " "Include Failure Patterns, Root Causes, and Goal Alignment sections."
        if has_multimodal:
            msg += " When visual evaluation tools are available, your diagnostic " "report must include specific findings from read_media analysis."
        result["issues"].append(msg)

    return result


def _is_per_agent_scores(scores: dict[str, Any], item_prefix: str) -> bool:
    """Return True if scores is per-agent format (keyed by agent label, not E/T-prefixed)."""
    if not scores:
        return False
    return not any(k.startswith(item_prefix) or k.startswith("T") or k.startswith("E") for k in scores)


def _extract_flat_scores(
    per_agent: dict[str, Any],
    item_prefix: str,
    n_items: int,
) -> tuple[str, dict[str, Any], dict[str, dict[str, int]]]:
    """Find the best agent by aggregate score and return (best_label, flat_scores, per_agent_summary).

    per_agent_summary maps agent_label -> {criterion: score} for inclusion in the response.
    """
    per_agent_summary: dict[str, dict[str, int]] = {}
    best_label = ""
    best_total = -1
    best_scores: dict[str, Any] = {}

    for agent_label, agent_scores in per_agent.items():
        if not isinstance(agent_scores, dict):
            continue
        total = sum(_extract_score(agent_scores.get(f"{item_prefix}{i+1}", agent_scores.get(f"E{i+1}", 0))) for i in range(n_items))
        summary = {f"{item_prefix}{i+1}": _extract_score(agent_scores.get(f"{item_prefix}{i+1}", agent_scores.get(f"E{i+1}", 0))) for i in range(n_items)}
        per_agent_summary[agent_label] = summary
        if total > best_total:
            best_total = total
            best_label = agent_label
            best_scores = agent_scores

    return best_label, best_scores, per_agent_summary


def evaluate_checklist_submission(
    scores: dict[str, Any],
    report_path: str,
    items: list,
    state: dict[str, Any],
    checklist_history: list[dict] | None = None,
) -> dict[str, Any]:
    """Evaluate checklist submission and return verdict payload used by stdio + SDK."""
    if not isinstance(scores, dict):
        scores = {}

    terminate_action = state.get("terminate_action", "vote")
    iterate_action = state.get("iterate_action", "new_answer")
    has_existing_answers = state.get("has_existing_answers", False)
    required = state.get("required", len(items))
    cutoff = state.get("cutoff", 70)

    # Determine item prefix: use E-prefix (new default), but accept T-prefix
    # submissions for backwards compatibility
    item_prefix = state.get("item_prefix", "E")

    # Detect per-agent format and normalise to flat scores for verdict logic.
    # Per-agent: {"agent1": {"E1": ..., "E2": ...}, "agent2": {...}}
    # Flat (legacy): {"E1": ..., "E2": ...}
    best_agent: str | None = None
    per_agent_scores: dict[str, dict[str, int]] | None = None
    available_agent_labels: list[str] = state.get("available_agent_labels") or []
    if _is_per_agent_scores(scores, item_prefix):
        # Validate completeness for ALL agents before selecting best.
        expected_keys = {f"{item_prefix}{i+1}" for i in range(len(items))}
        incomplete_agents = []
        for agent_label, agent_scores in scores.items():
            if not isinstance(agent_scores, dict):
                continue
            agent_keys = {k.replace("T", item_prefix, 1) if k.startswith("T") else k for k in agent_scores}
            missing = sorted(expected_keys - agent_keys)
            if missing:
                incomplete_agents.append((agent_label, missing))
        if incomplete_agents and has_existing_answers:
            report_eval = _evaluate_gap_report(report_path, state)
            details = "; ".join(f"{a}: missing {', '.join(m)}" for a, m in incomplete_agents)
            return {
                "verdict": iterate_action,
                "explanation": (f"Incomplete per-agent submission: {details}. " f"You must score ALL {len(items)} criteria for EVERY agent. " f"Resubmit with complete scores."),
                "incomplete_scores": True,
                "true_count": 0,
                "required": required,
                "items": [],
                "report": report_eval,
                "report_gate_triggered": False,
            }
        # Validate all available agents are covered when labels are known.
        if available_agent_labels and has_existing_answers:
            missing_agents = sorted(set(available_agent_labels) - set(scores.keys()))
            if missing_agents:
                report_eval = _evaluate_gap_report(report_path, state)
                return {
                    "verdict": iterate_action,
                    "explanation": (
                        f"Missing scores for available agents: {', '.join(missing_agents)}. "
                        f"You must score ALL agents you have context for: "
                        f"{', '.join(sorted(available_agent_labels))}. "
                        f"Resubmit with per-agent scores covering every agent."
                    ),
                    "incomplete_scores": True,
                    "true_count": 0,
                    "required": required,
                    "items": [],
                    "report": report_eval,
                    "report_gate_triggered": False,
                }
        best_agent, scores, per_agent_scores = _extract_flat_scores(scores, item_prefix, len(items))
    elif len(available_agent_labels) >= 2 and has_existing_answers:
        # Flat format submitted but multiple agents are available — require per-agent format.
        report_eval = _evaluate_gap_report(report_path, state)
        return {
            "verdict": iterate_action,
            "explanation": (
                f"You submitted flat scores but you have {len(available_agent_labels)} agents available "
                f"({', '.join(sorted(available_agent_labels))}). "
                f"Use per-agent format to score ALL available agents: "
                f'{{"{available_agent_labels[0]}": {{"E1": {{"score": N, "reasoning": "..."}}, ...}}, '
                f'"{available_agent_labels[1]}": {{...}}}}.'
            ),
            "incomplete_scores": True,
            "true_count": 0,
            "required": required,
            "items": [],
            "report": report_eval,
            "report_gate_triggered": False,
        }

    # Reject incomplete submissions — agent must score ALL criteria
    expected_keys = {f"{item_prefix}{i+1}" for i in range(len(items))}
    submitted_keys = set(scores.keys())
    # Accept both E-prefix and T-prefix
    submitted_normalized = set()
    for k in submitted_keys:
        if k.startswith("T"):
            submitted_normalized.add(k.replace("T", item_prefix, 1))
        elif k.startswith("E"):
            submitted_normalized.add(k)
        else:
            submitted_normalized.add(k)
    missing_keys = sorted(expected_keys - submitted_normalized)

    if missing_keys and has_existing_answers:
        report_eval = _evaluate_gap_report(report_path, state)
        return {
            "verdict": iterate_action,
            "explanation": (
                f"Incomplete submission: missing scores for {', '.join(missing_keys)}. "
                f"You must score ALL {len(items)} criteria ({item_prefix}1-{item_prefix}{len(items)}). "
                f"Resubmit with scores for every criterion."
            ),
            "incomplete_scores": True,
            "true_count": 0,
            "required": required,
            "items": [],
            "report": report_eval,
            "report_gate_triggered": False,
        }

    items_detail = []
    true_count = 0
    for i, _item_text in enumerate(items):
        key = f"{item_prefix}{i+1}"
        # Accept both E-prefix and T-prefix submissions for backwards compat
        entry = scores.get(key, scores.get(f"T{i+1}", scores.get(f"E{i+1}", 0)))
        score = _extract_score(entry)
        passed = score >= cutoff
        if passed:
            true_count += 1
        items_detail.append({"id": key, "score": score, "passed": passed})

    report_eval = _evaluate_gap_report(report_path, state)

    plateaued_failing: list[dict] = []

    if not has_existing_answers:
        verdict = iterate_action
        explanation = f"First answer — no existing answers to evaluate. Verdict: {verdict}."
    else:
        # Verdict determined solely by item scores
        verdict = terminate_action if true_count >= required else iterate_action
        failed_ids = [d["id"] for d in items_detail if not d["passed"]]
        failed_set = set(failed_ids)

        if verdict == iterate_action:
            explanation = f"{true_count} of {len(items)} items passed (required: {required}). " f"Verdict: {verdict}. "
            if failed_ids:
                explanation += f"Items that need improvement: {', '.join(failed_ids)}. "

            # Per-criterion plateau → targeted subagent guidance
            _item_categories = state.get("item_categories", {})
            plateaued_all = _find_plateaued_criteria(
                items_detail,
                checklist_history or [],
                items=items,
                item_categories=_item_categories,
                min_rounds=2,
            )
            plateaued_failing = [d for d in plateaued_all if d["id"] in failed_set]

            _quality_rethinking_enabled = state.get(
                "quality_rethinking_subagent_enabled",
                False,
            )
            _novelty_enabled = state.get("novelty_subagent_enabled", False)
            _always_spawn = state.get("always_spawn_quality_subagents", False)

            if has_existing_answers and plateaued_failing:
                # Build score trajectory strings like "E5 (should, scores: 5→6→6)"
                trajectory_parts = []
                for pd in plateaued_failing:
                    scores_str = "\u2192".join(str(s) for s in pd["score_history"])
                    trajectory_parts.append(
                        f"{pd['id']} ({pd['category']}, scores: {scores_str})",
                    )
                plateaued_str = ", ".join(trajectory_parts)
                if _quality_rethinking_enabled and _novelty_enabled:
                    explanation += (
                        f"Criteria {plateaued_str} have plateaued. "
                        "Spawn a quality_rethinking subagent AND a novelty subagent "
                        "side-by-side in background \u2014 pass each the "
                        "plateaued_criteria detail from this result (it contains "
                        "criterion text, category, and full score history). "
                        "Meanwhile, proceed with propose_improvements and start "
                        "implementing. Integrate subagent proposals when they return. "
                    )
                elif _quality_rethinking_enabled:
                    explanation += (
                        f"Criteria {plateaued_str} have plateaued. "
                        "Spawn a quality_rethinking subagent in background \u2014 pass "
                        "it the plateaued_criteria detail from this result. It will "
                        "propose per-element craft improvements targeted at raising "
                        "these specific scores. "
                    )
                elif _novelty_enabled:
                    explanation += (
                        f"Criteria {plateaued_str} have plateaued. "
                        "Spawn a novelty subagent in background \u2014 pass it the "
                        "plateaued_criteria detail from this result. It will propose "
                        "fundamentally different approaches to break through. "
                    )

            # Always-spawn mode: fire quality/novelty guidance for ALL failing
            # criteria every round, not just plateaued ones.
            elif _always_spawn and failed_ids and (_quality_rethinking_enabled or _novelty_enabled):
                explanation += (
                    "Spawn a quality_rethinking subagent AND a novelty subagent "
                    "side-by-side in background \u2014 pass each the "
                    "failing_criteria_detail from this result (it contains "
                    "criterion text and category for every failing criterion). "
                    "Meanwhile, proceed with propose_improvements and start "
                    "implementing. Integrate subagent proposals when they return. "
                )

            explanation += "NEXT STEP: Call `propose_improvements` with specific improvements " "for each failing criterion. This is required before implementing."
        else:
            explanation = f"{true_count} of {len(items)} items passed (required: {required}). Verdict: {verdict}."

    # Apply diagnostic report gate (skip on first answer — nothing to diagnose yet)
    report_gate_triggered = False
    if has_existing_answers and not report_eval.get("passed", True):
        verdict = iterate_action
        report_gate_triggered = True
        report_issues = "; ".join(report_eval.get("issues", []))
        explanation += f" REPORT GATE: {report_issues}"

    # Include report diagnostics for transparency
    if report_eval.get("provided"):
        report_summary = " Diagnostic report provided."
        if report_eval.get("issues"):
            report_summary += f" Report notes: {'; '.join(report_eval['issues'])}."
        explanation += report_summary

    # Reuse plateaued_failing from the iterate branch if computed, otherwise
    # compute fresh for the result dict (e.g. when report gate changed verdict).
    if not plateaued_failing and has_existing_answers and verdict != terminate_action:
        _item_cats = state.get("item_categories", {})
        _plateaued = _find_plateaued_criteria(
            items_detail,
            checklist_history or [],
            items=items,
            item_categories=_item_cats,
            min_rounds=2,
        )
        _failed_set = {d["id"] for d in items_detail if not d["passed"]}
        plateaued_failing = [d for d in _plateaued if d["id"] in _failed_set]

    result = {
        "verdict": verdict,
        "explanation": explanation,
        "true_count": true_count,
        "required": required,
        "items": items_detail,
        "failed_criteria": [d["id"] for d in items_detail if not d["passed"]],
        "plateaued_criteria": plateaued_failing,
        "report": report_eval,
        "report_gate_triggered": report_gate_triggered,
    }
    if best_agent is not None:
        result["best_agent"] = best_agent
    if per_agent_scores is not None:
        result["per_agent_scores"] = per_agent_scores

    # In always-spawn mode, include detail for ALL failing criteria so agents
    # can pass rich context to quality/novelty subagents every round.
    _always_spawn = state.get("always_spawn_quality_subagents", False)
    if _always_spawn and result.get("failed_criteria"):
        _item_cats = state.get("item_categories", {})
        failing_detail = []
        for d in items_detail:
            if not d["passed"]:
                idx = int(d["id"][1:]) - 1
                failing_detail.append(
                    {
                        "id": d["id"],
                        "text": items[idx] if idx < len(items) else d["id"],
                        "category": _item_cats.get(d["id"], "unknown"),
                        "current_score": d["score"],
                    },
                )
        result["failing_criteria_detail"] = failing_detail

    return result


def _register_checklist_tool(mcp: fastmcp.FastMCP, specs_path: Path) -> None:
    """Register the submit_checklist tool on the FastMCP server."""
    import inspect

    # Read specs once at startup just for the tool schema
    specs = _read_specs(specs_path)
    items = specs.get("items", [])

    # Track last failed criteria so propose_improvements can validate coverage
    _last_result: dict[str, Any] = {"failed_criteria": [], "items": [], "all_criteria_ids": []}

    # Create handler that re-reads state on each call.
    async def submit_checklist(
        scores: dict,
        report_path: str = "",
    ) -> str:
        # Codex sometimes sends scores as a JSON string; normalise to dict
        if isinstance(scores, str):
            try:
                scores = json.loads(scores)
            except (json.JSONDecodeError, TypeError):
                return json.dumps(
                    {"error": "scores must be a JSON object, not a string"},
                )
        if not isinstance(scores, dict):
            return json.dumps(
                {"error": "scores must be a JSON object"},
            )

        # Re-read specs to get latest state from orchestrator
        current = _read_specs(specs_path)
        current_items = current.get("items", items)
        state = current.get("state", {})
        result = evaluate_checklist_submission(
            scores=scores,
            report_path=report_path,
            items=current_items,
            state=state,
        )
        _last_result["failed_criteria"] = result.get("failed_criteria", [])
        _last_result["items"] = current_items
        _last_result["all_criteria_ids"] = [f"E{i+1}" for i in range(len(current_items))]
        return json.dumps(result)

    submit_checklist.__doc__ = (
        "Submit your checklist evaluation. "
        "Score each agent's answer separately per criterion, then submit all "
        "agent scores in 'scores' as a nested object: "
        '{"agent1.1": {"E1": {"score": 8, "reasoning": "..."}, ...}, "agent2.1": {...}}. '
        "Use the exact agent labels from the 'Available answers' section of your context "
        "(e.g. agent1.1, agent2.1). "
        "The verdict is determined by the strongest agent's scores — the agent "
        "with the highest aggregate across all criteria. Include all agents so "
        "the evaluation is transparent and auditable. "
        "Use 'report_path' to provide a markdown gap report when report gating "
        "is enabled."
    )

    # Set proper signature so FastMCP sees all parameters
    sig = inspect.Signature(
        [
            inspect.Parameter("scores", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("report_path", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=""),
        ],
    )
    submit_checklist.__signature__ = sig

    mcp.tool(
        name="submit_checklist",
        description=submit_checklist.__doc__,
    )(submit_checklist)

    # propose_improvements: validate improvement coverage for all failing criteria
    async def propose_improvements(improvements: dict, preserve: dict = None) -> str:
        if isinstance(improvements, str):
            try:
                improvements = json.loads(improvements)
            except (json.JSONDecodeError, TypeError):
                return json.dumps(
                    {"valid": False, "error": "improvements must be a JSON object"},
                )
        if isinstance(preserve, str):
            try:
                preserve = json.loads(preserve)
            except (json.JSONDecodeError, TypeError):
                preserve = None
        result = evaluate_proposed_improvements(
            improvements=improvements,
            failed_criteria=_last_result["failed_criteria"],
            items=_last_result["items"],
            all_criteria_ids=_last_result.get("all_criteria_ids"),
            preserve=preserve,
        )
        return json.dumps(result)

    propose_improvements.__doc__ = (
        "Propose specific improvements for each failing criterion. "
        "Must be called after submit_checklist returns an iterate verdict. "
        "Pass 'improvements' mapping criterion IDs (e.g. 'E2') to lists of "
        "entries, each with 'plan' (what to do) and 'sources' (which answers "
        "to draw from). Pass 'preserve' mapping criterion IDs to entries with "
        "'what' (strength to protect) and 'source' (which answer). A criterion "
        "can appear in both improvements and preserve."
    )

    propose_sig = inspect.Signature(
        [
            inspect.Parameter("improvements", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("preserve", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None),
        ],
    )
    propose_improvements.__signature__ = propose_sig

    mcp.tool(
        name="propose_improvements",
        description=propose_improvements.__doc__,
    )(propose_improvements)

    logger.info("Registered submit_checklist + propose_improvements MCP tools")


# ---------- spec file I/O ----------


def write_checklist_specs(
    items: list,
    state: dict[str, Any],
    output_path: Path,
) -> Path:
    """Write checklist specs + state to a JSON file.

    Called by the orchestrator before launch and whenever state changes.
    """
    specs = {
        "items": items,
        "state": state,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        # State may include pathlib objects (for example workspace paths)
        # that need string normalization for JSON transport.
        json.dump(specs, f, indent=2, default=str)
    return output_path


def build_server_config(
    specs_path: Path,
    hook_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a stdio MCP server config dict for the checklist server."""
    script_path = Path(__file__).resolve()

    cmd_args = [
        "run",
        f"{script_path}:create_server",
        "--",
        "--specs",
        str(specs_path),
    ]
    if hook_dir is not None:
        cmd_args.extend(["--hook-dir", str(hook_dir)])

    return {
        "name": SERVER_NAME,
        "type": "stdio",
        "command": "fastmcp",
        "args": cmd_args,
        "env": {"FASTMCP_SHOW_CLI_BANNER": "false"},
        "tool_timeout_sec": 120,
    }
