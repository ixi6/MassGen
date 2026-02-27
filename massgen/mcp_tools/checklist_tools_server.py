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


def _as_non_negative_int(value: Any, default: int = 0) -> int:
    """Best-effort conversion to non-negative int."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _normalize_substantiveness(
    substantiveness: Any,
    state: dict[str, Any],
) -> dict[str, Any]:
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
    result: dict[str, Any] = {
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
    improvements: str,
    report_path: str,
    items: list,
    state: dict[str, Any],
    substantiveness: dict[str, Any] | None = None,
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
                "substantiveness_gate_triggered": False,
                "convergence_offramp_triggered": False,
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
                    "substantiveness_gate_triggered": False,
                    "convergence_offramp_triggered": False,
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
            "substantiveness_gate_triggered": False,
            "convergence_offramp_triggered": False,
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
            "substantiveness_gate_triggered": False,
            "convergence_offramp_triggered": False,
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

        # Dynamic core/tail from item_categories in state, with fallback
        stored_categories = state.get("item_categories")
        if stored_categories:
            core_item_candidates = tuple(k for k, v in stored_categories.items() if v in ("core", "must", "should"))
            tail_failure_ids = {k for k, v in stored_categories.items() if v in ("stretch", "could")}
        else:
            # Legacy fallback: all items except last are core
            all_ids = [f"{item_prefix}{i+1}" for i in range(len(items))]
            core_item_candidates = tuple(all_ids[:-1])
            tail_failure_ids = {all_ids[-1]} if all_ids else set()

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
                # Require task plan logging so commitments can be verified
                explanation += (
                    "BEFORE starting work, add each committed item above to your task plan "
                    "as a separate task with verification and verification_method fields "
                    "describing how to confirm it is truly done (e.g., screenshot + read_media, "
                    "test output, visual inspection). Mark tasks 'completed' when implemented, "
                    "then 'verified' only after you confirm the result. Do not substitute "
                    "easier work — deliver exactly what you committed to. "
                )

            # Builder subagent guidance: when transformative changes are identified,
            # suggest delegating implementation to a builder subagent rather than
            # doing the work inline. Transformative = fundamental rethink = substantial
            # implementation effort, the right trigger for offloading to fresh context.
            # Complementary to novelty/critic (those fire when transformative_count == 0;
            # builder fires when transformative_count > 0).
            _builder_enabled = state.get("builder_subagent_enabled", False)
            if _builder_enabled and has_existing_answers and transformative_items:
                explanation += (
                    "These are transformative changes — delegate implementation to a "
                    "`builder` subagent (background=True) rather than doing the work "
                    "inline. Pass the builder: the current workspace, a prescriptive "
                    "spec with what to build AND what patterns are FORBIDDEN (negative "
                    "constraints), and the evaluation criteria. The builder runs in "
                    "fresh context and won't exhaust your token budget. Once it reports "
                    "back, you evaluate the result and submit the checklist. "
                )

            # Stretch-item guidance: when stretch criteria fail, give concrete direction
            stretch_failures = failed_set & tail_failure_ids
            if stretch_failures and substantiveness_eval.get("valid", False):
                # Build a human-readable label for the stretch items that failed
                stretch_labels = ", ".join(sorted(stretch_failures))
                if substantiveness_eval.get("decision_space_exhausted", False) or substantiveness_eval.get("incremental_only", False):
                    explanation += (
                        f"{stretch_labels} (stretch criteria) failed and you reported no structural/transformative "
                        "work remaining. Incremental polish will not fix a stretch-quality deficit. "
                        f"To pass {stretch_labels} you must go beyond the safe, obvious approach — make an "
                        "existing element significantly richer, find an elegant solution to a "
                        "known hard problem, or introduce a distinctive design choice. Depth "
                        "counts: improving what exists can satisfy this. If no such move exists, "
                        "mark `decision_space_exhausted=true` and let the system converge. "
                    )
                else:
                    explanation += (
                        f"{stretch_labels} (stretch criteria) failed. Your next answer needs at least one "
                        "element showing care beyond correctness — not just "
                        "mechanical execution. This can be a novel feature, an existing "
                        "element made significantly richer, or thoughtful synthesis that "
                        "combines the best of multiple approaches and improves on them. "
                    )
            # Novelty subagent guidance: when no transformative work identified,
            # suggest spawning a novelty subagent to break anchoring
            _novelty_enabled = state.get("novelty_subagent_enabled", False)
            if has_existing_answers and substantiveness_eval.get("valid", False) and substantiveness_eval.get("transformative_count", 0) == 0:
                if _novelty_enabled:
                    explanation += (
                        "Your evaluation found zero transformative changes — you are "
                        "stuck in a plateau. Spawn a novelty subagent in the background "
                        "(`background=True, refine=False`) — pass it your diagnostic "
                        "analysis, the current workspace, and evaluation findings. It "
                        "will propose fundamentally different directions while you "
                        "continue working on structural or incremental improvements "
                        "already identified. When its results arrive, evaluate each "
                        "direction: does it genuinely break the anchoring pattern? Is "
                        "it implementable? Does it differ from what's already been "
                        "tried? If at least one passes, adopt it and list it in the "
                        "`transformative` array of your next checklist submission. If "
                        "none pass, explain in `substantiveness.notes` which direction "
                        "failed and why — not just 'none apply.' Engaging seriously "
                        "with novelty's output, even to reject it, is what breaks the "
                        "plateau. Do not ignore it silently. "
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

    result = {
        "verdict": verdict,
        "explanation": explanation,
        "true_count": true_count,
        "required": required,
        "items": items_detail,
        "report": report_eval,
        "substantiveness": substantiveness_eval,
        "report_gate_triggered": report_gate_triggered,
        "substantiveness_gate_triggered": substantiveness_gate_triggered,
        "convergence_offramp_triggered": convergence_offramp_triggered,
    }
    if best_agent is not None:
        result["best_agent"] = best_agent
    if per_agent_scores is not None:
        result["per_agent_scores"] = per_agent_scores
    return result


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
        "Submit your checklist evaluation. "
        "Score each agent's answer separately per criterion, then submit all "
        "agent scores in 'scores' as a nested object: "
        '{"agent1": {"E1": {"score": 8, "reasoning": "..."}, ...}, "agent2": {...}}. '
        "The verdict is determined by the strongest agent's scores — the agent "
        "with the highest aggregate across all criteria. Include all agents so "
        "the evaluation is transparent and auditable. "
        "The 'improvements' field should describe dimensions where even the "
        "best agent fell short — genuine gaps requiring a new answer. "
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
