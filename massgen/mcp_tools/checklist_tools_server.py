# -*- coding: utf-8 -*-
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
from pathlib import Path
from typing import Any, Dict

import fastmcp

logger = logging.getLogger(__name__)

SERVER_NAME = "massgen_checklist"


async def create_server() -> fastmcp.FastMCP:
    """Factory function to create MCP server from checklist specs."""
    parser = argparse.ArgumentParser(description="MassGen Checklist MCP Server")
    parser.add_argument(
        "--specs",
        type=str,
        required=True,
        help="Path to JSON file containing checklist specs and state",
    )
    args = parser.parse_args()

    mcp = fastmcp.FastMCP(SERVER_NAME)
    specs_path = Path(args.specs)

    _register_checklist_tool(mcp, specs_path)

    logger.info(f"Checklist MCP server ready (specs: {specs_path})")
    return mcp


def _read_specs(specs_path: Path) -> Dict[str, Any]:
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


def _as_non_negative_int(value: Any, default: int = 0) -> int:
    """Best-effort conversion to non-negative int."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _normalize_substantiveness(
    substantiveness: Any,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize structured substantiveness payload for checklist gating.

    Accepts two payload formats:

    **List format** (preferred — prevents satisficing by naming specific items):
    {
      "transformative": ["rewrite nav as SPA router"],
      "structural": ["add timeline", "add search"],
      "incremental": ["fix typos", "adjust colors"],
      "decision_space_exhausted": bool,
      "notes": str (optional)
    }

    **Legacy count format** (backward compatible):
    {
      "transformative_count": int >= 0,
      "structural_count": int >= 0,
      "incremental_count": int >= 0,
      "decision_space_exhausted": bool,
      "notes": str (optional)
    }

    List format is detected by the presence of a "transformative" key with a list value.
    Counts are derived via len() for list format.
    """
    require_substantiveness = bool(state.get("require_substantiveness", False))
    result: Dict[str, Any] = {
        "required": require_substantiveness,
        "provided": substantiveness is not None,
        "valid": True,
        "issues": [],
        "transformative_count": 0,
        "structural_count": 0,
        "incremental_count": 0,
        "transformative_items": [],
        "structural_items": [],
        "incremental_items": [],
        "decision_space_exhausted": False,
        "notes": "",
        "has_substantive_plan": False,
        "incremental_only": False,
    }

    if substantiveness is None:
        if require_substantiveness:
            result["valid"] = False
            result["issues"].append("Missing `substantiveness` payload.")
        return result

    if isinstance(substantiveness, str):
        try:
            substantiveness = json.loads(substantiveness)
        except (json.JSONDecodeError, TypeError):
            result["valid"] = False
            result["issues"].append("`substantiveness` must be a JSON object.")
            return result

    if not isinstance(substantiveness, dict):
        result["valid"] = False
        result["issues"].append("`substantiveness` must be an object.")
        return result

    # Detect format: list-based if "transformative" key holds a list
    uses_list_format = isinstance(substantiveness.get("transformative"), list)

    if uses_list_format:
        # List format: extract items, derive counts
        result["transformative_items"] = [str(x) for x in (substantiveness.get("transformative") or [])]
        result["structural_items"] = [str(x) for x in (substantiveness.get("structural") or [])]
        result["incremental_items"] = [str(x) for x in (substantiveness.get("incremental") or [])]
        result["transformative_count"] = len(result["transformative_items"])
        result["structural_count"] = len(result["structural_items"])
        result["incremental_count"] = len(result["incremental_items"])
    else:
        # Legacy count format: keep counts, empty item lists
        result["transformative_count"] = _as_non_negative_int(
            substantiveness.get("transformative_count", 0),
        )
        result["structural_count"] = _as_non_negative_int(
            substantiveness.get("structural_count", 0),
        )
        result["incremental_count"] = _as_non_negative_int(
            substantiveness.get("incremental_count", 0),
        )

    result["decision_space_exhausted"] = bool(
        substantiveness.get("decision_space_exhausted", False),
    )
    result["notes"] = str(substantiveness.get("notes", "") or "").strip()
    result["has_substantive_plan"] = (result["transformative_count"] + result["structural_count"]) > 0
    result["incremental_only"] = not result["has_substantive_plan"] and result["incremental_count"] > 0

    if require_substantiveness and not result["decision_space_exhausted"] and (result["transformative_count"] + result["structural_count"] + result["incremental_count"]) == 0:
        result["valid"] = False
        result["issues"].append(
            "Substantiveness is required: provide change lists or mark decision space as exhausted.",
        )

    return result


def _resolve_report_file(report_path: str, state: Dict[str, Any]) -> tuple[Path | None, str | None]:
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


def _evaluate_gap_report(report_path: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Check gap report file existence for diagnostics (no gate logic).

    The gap report is informational only — it never overrides the checklist verdict.
    Basic file existence and non-empty checks are retained for transparency in the
    explanation, but no heuristic scoring or keyword matching is performed.
    """
    result: Dict[str, Any] = {
        "provided": bool((report_path or "").strip()),
        "path": (report_path or "").strip(),
        "passed": True,  # Always passes — no gate
        "issues": [],
    }

    if not result["provided"]:
        return result

    resolved, error = _resolve_report_file(report_path, state)
    if error:
        result["issues"].append(error)
        return result
    if resolved is None:
        return result

    result["resolved_path"] = str(resolved)
    if not resolved.exists():
        result["issues"].append(f"Report file not found: {resolved}")
        return result
    if not resolved.is_file():
        result["issues"].append(f"Report path is not a file: {resolved}")
        return result

    try:
        report_text = resolved.read_text(encoding="utf-8")
    except Exception as exc:
        result["issues"].append(f"Unable to read report file: {exc}")
        return result

    if not report_text.strip():
        result["issues"].append("Report file is empty.")
        return result

    # Report exists and is non-empty — note it for transparency
    result["file_exists"] = True
    return result


def evaluate_checklist_submission(
    scores: Dict[str, Any],
    improvements: str,
    report_path: str,
    items: list,
    state: Dict[str, Any],
    substantiveness: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Evaluate checklist submission and return verdict payload used by stdio + SDK."""
    if not isinstance(scores, dict):
        scores = {}

    terminate_action = state.get("terminate_action", "vote")
    iterate_action = state.get("iterate_action", "new_answer")
    has_existing_answers = state.get("has_existing_answers", False)
    required = state.get("required", len(items))
    cutoff = state.get("cutoff", 70)

    items_detail = []
    true_count = 0
    for i, _item_text in enumerate(items):
        key = f"T{i+1}"
        entry = scores.get(key, 0)
        score = _extract_score(entry)
        passed = score >= cutoff
        if passed:
            true_count += 1
        items_detail.append({"id": key, "score": score, "passed": passed})

    report_eval = _evaluate_gap_report(report_path, state)
    substantiveness_eval = _normalize_substantiveness(substantiveness, state)
    substantiveness_gate_triggered = False
    convergence_offramp_triggered = False

    if not has_existing_answers:
        verdict = iterate_action
        explanation = f"First answer — no existing answers to evaluate. Verdict: {verdict}."
    else:
        # Verdict determined solely by T-item scores — no report gate
        verdict = terminate_action if true_count >= required else iterate_action

        # Substantiveness gate: require payload when configured
        if substantiveness_eval.get("required", False) and not substantiveness_eval.get("valid", True):
            verdict = iterate_action
            substantiveness_gate_triggered = True

        # Natural convergence off-ramp:
        # When core quality is strong and only tail "more improvement/novelty"
        # style items are failing, stop if no substantive plan remains.
        #
        # Important: changedoc and generic checklist modes use different
        # semantics for T3. In changedoc mode, T3 is traceability and should
        # remain part of core quality; in generic mode, T3 is a tail
        # "no meaningful improvements left" check.
        failed_ids = [d["id"] for d in items_detail if not d["passed"]]
        failed_set = set(failed_ids)
        passed_map = {d["id"]: d["passed"] for d in items_detail}

        changedoc_mode = bool(state.get("changedoc_mode", False))
        if changedoc_mode:
            core_item_candidates = ("T1", "T2", "T3")
            tail_failure_ids = {"T4"}
        else:
            core_item_candidates = ("T1", "T2", "T3")
            tail_failure_ids = {"T4"}

        core_quality_ids = [item_id for item_id in core_item_candidates if item_id in passed_map]
        core_quality_strong = all(passed_map[item_id] for item_id in core_quality_ids)
        only_tail_failures = bool(failed_set) and failed_set.issubset(tail_failure_ids)
        near_converged = true_count >= max(1, required - 2)
        no_substantive_path = (
            substantiveness_eval.get("valid", False)
            and not substantiveness_eval.get("has_substantive_plan", False)
            and (substantiveness_eval.get("decision_space_exhausted", False) or substantiveness_eval.get("incremental_only", False))
        )
        if verdict == iterate_action and not substantiveness_gate_triggered and only_tail_failures and core_quality_strong and near_converged and no_substantive_path:
            verdict = terminate_action
            convergence_offramp_triggered = True

        if verdict == iterate_action and not convergence_offramp_triggered:
            improvements_text = improvements.strip() if improvements else ""
            explanation = f"{true_count} of {len(items)} items passed (required: {required}). " f"Verdict: {verdict}. "
            if failed_ids:
                explanation += f"Items that need improvement: {', '.join(failed_ids)}. "
            if substantiveness_gate_triggered:
                explanation += (
                    "Substantiveness details are required before iterating: provide lists of "
                    "transformative/structural/incremental changes, or mark "
                    "`decision_space_exhausted=true` when no meaningful improvements remain. "
                )
            if (
                has_existing_answers
                and substantiveness_eval.get("valid", False)
                and not substantiveness_eval.get("has_substantive_plan", False)
                and not substantiveness_eval.get("decision_space_exhausted", False)
            ):
                explanation += (
                    "You have not identified any structural or transformative work yet. " "Do not spend another round on cosmetic changes — either define a " "substantive plan or terminate. "
                )

            # Echo specific structural/transformative items when available
            structural_items = substantiveness_eval.get("structural_items", [])
            transformative_items = substantiveness_eval.get("transformative_items", [])
            if structural_items or transformative_items:
                if transformative_items:
                    items_str = ", ".join(transformative_items)
                    explanation += f"Your own analysis identified these transformative changes: {items_str}. " f"Implement ALL of them. "
                if structural_items:
                    items_str = ", ".join(structural_items)
                    explanation += f"Your own analysis identified these structural changes: {items_str}. " f"Implement ALL of them. "

            # T4-specific ambition/craft guidance: when ambition fails, give the agent
            # concrete direction instead of just listing T4 as a failed item.
            t4_failed = "T4" in failed_set
            if t4_failed and substantiveness_eval.get("valid", False):
                if substantiveness_eval.get("decision_space_exhausted", False) or substantiveness_eval.get("incremental_only", False):
                    explanation += (
                        "T4 (ambition/craft) failed and you reported no structural/transformative "
                        "work remaining. Incremental polish will not fix an ambition deficit. "
                        "To pass T4 you must go beyond the safe, obvious approach — make an "
                        "existing element significantly richer, find an elegant solution to a "
                        "known hard problem, or introduce a distinctive design choice. Depth "
                        "counts: improving what exists can satisfy this. If no such move exists, "
                        "mark `decision_space_exhausted=true` and let the system converge. "
                    )
                else:
                    explanation += (
                        "T4 (ambition/craft) failed. Your next answer needs at least one "
                        "element showing creative ambition or meaningful craft — not just "
                        "mechanical execution. This can be a novel feature, an existing "
                        "element made significantly richer, or thoughtful synthesis that "
                        "combines the best of multiple approaches and improves on them. "
                    )
            explanation += "Your new answer MUST make material changes — do NOT simply copy or " "resubmit the same content."
            if improvements_text:
                explanation += (
                    f" Your own improvements analysis identified: {improvements_text} "
                    f"— implement all identified improvements, not just one. Each round "
                    f"is expensive; deliver the full scope of changes. The result must be "
                    f"obviously better, not just marginally different."
                )
        else:
            explanation = f"{true_count} of {len(items)} items passed (required: {required}). Verdict: {verdict}."
            if convergence_offramp_triggered:
                explanation += " Convergence off-ramp activated: core quality is strong and no " "substantive novelty plan remains, so additional rounds would likely " "be incremental-only."

    # Include report diagnostics for transparency (informational only)
    if report_eval.get("provided"):
        report_summary = " Gap report provided."
        if report_eval.get("issues"):
            report_summary += f" Report notes: {'; '.join(report_eval['issues'])}."
        explanation += report_summary

    # Include substantiveness diagnostics
    substantiveness_summary = (
        " Substantiveness: "
        f"T={substantiveness_eval.get('transformative_count', 0)}, "
        f"S={substantiveness_eval.get('structural_count', 0)}, "
        f"I={substantiveness_eval.get('incremental_count', 0)}, "
        f"exhausted={'yes' if substantiveness_eval.get('decision_space_exhausted') else 'no'}."
    )
    if substantiveness_eval.get("issues"):
        substantiveness_summary += f" Substantiveness issues: {'; '.join(substantiveness_eval['issues'])}."
    explanation += substantiveness_summary

    return {
        "verdict": verdict,
        "explanation": explanation,
        "true_count": true_count,
        "required": required,
        "items": items_detail,
        "report": report_eval,
        "substantiveness": substantiveness_eval,
        "report_gate_triggered": False,
        "substantiveness_gate_triggered": substantiveness_gate_triggered,
        "convergence_offramp_triggered": convergence_offramp_triggered,
    }


def _register_checklist_tool(mcp: fastmcp.FastMCP, specs_path: Path) -> None:
    """Register the submit_checklist tool on the FastMCP server."""
    import inspect

    # Read specs once at startup just for the tool schema
    specs = _read_specs(specs_path)
    items = specs.get("items", [])

    # Create handler that re-reads state on each call.
    # Each score entry is {"score": int, "reasoning": str} — the reasoning
    # forces the model to justify each item but is not used in verdict logic.
    # `improvements` captures unrealized potential.
    async def submit_checklist(
        scores: dict,
        improvements: str = "",
        report_path: str = "",
        substantiveness: dict | None = None,
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
            improvements=improvements,
            report_path=report_path,
            items=current_items,
            state=state,
            substantiveness=substantiveness,
        )
        return json.dumps(result)

    submit_checklist.__doc__ = (
        "Submit your checklist evaluation. Each score in 'scores' must be an "
        "object with 'score' (0-100) and 'reasoning' (why you gave that score). "
        "The 'improvements' field should describe features or content that an "
        "ideal answer would have but no existing answer has attempted. "
        "Use the 'substantiveness' object to report planned change counts "
        "(transformative/structural/incremental) and whether decision space is exhausted. "
        "Use 'report_path' to provide a markdown gap report when report gating "
        "is enabled."
    )

    # Set proper signature so FastMCP sees all parameters
    sig = inspect.Signature(
        [
            inspect.Parameter("scores", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("improvements", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("report_path", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter("substantiveness", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None),
        ],
    )
    submit_checklist.__signature__ = sig

    mcp.tool(
        name="submit_checklist",
        description=submit_checklist.__doc__,
    )(submit_checklist)

    logger.info("Registered submit_checklist MCP tool")


# ---------- spec file I/O ----------


def write_checklist_specs(
    items: list,
    state: Dict[str, Any],
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


def build_server_config(specs_path: Path) -> Dict[str, Any]:
    """Build a stdio MCP server config dict for the checklist server."""
    script_path = Path(__file__).resolve()

    return {
        "name": SERVER_NAME,
        "type": "stdio",
        "command": "fastmcp",
        "args": [
            "run",
            f"{script_path}:create_server",
            "--",
            "--specs",
            str(specs_path),
        ],
        "env": {"FASTMCP_SHOW_CLI_BANNER": "false"},
        "tool_timeout_sec": 120,
    }
