"""Regression tests for Web quickstart reasoning default sync."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "webui" / "src" / "components" / "wizard" / "quickstartReasoningSync.ts"


def _compile_reasoning_helper(tmp_path: Path) -> Path:
    out_dir = tmp_path / "compiled"
    subprocess.run(
        [
            str(REPO_ROOT / "webui" / "node_modules" / ".bin" / "tsc"),
            "--noEmit",
            "false",
            "--target",
            "ES2020",
            "--module",
            "NodeNext",
            "--moduleResolution",
            "NodeNext",
            "--outDir",
            str(out_dir),
            str(HELPER_PATH),
        ],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    compiled_path = out_dir / "quickstartReasoningSync.js"
    assert compiled_path.exists()
    return compiled_path


def _run_reasoning_sync(tmp_path: Path, payload: dict) -> dict:
    compiled_helper = _compile_reasoning_helper(tmp_path)
    script = f"""
import {{ resolveQuickstartReasoningSync }} from {json.dumps(compiled_helper.as_uri())};
const result = resolveQuickstartReasoningSync({json.dumps(payload)});
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        check=True,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_reasoning_sync_resets_sonnet46_to_medium_on_model_change(tmp_path: Path) -> None:
    result = _run_reasoning_sync(
        tmp_path,
        {
            "profile": {
                "choices": [
                    ["Low (faster)", "low"],
                    ["Medium (recommended)", "medium"],
                    ["High (deeper reasoning)", "high"],
                ],
                "default_effort": "medium",
                "description": "Claude Sonnet 4.6 reasoning profile",
            },
            "profileKey": "claude_code::claude-sonnet-4-6",
            "lastAppliedProfileKey": "claude_code::claude-opus-4-6",
            "currentEffort": "high",
        },
    )

    assert result == {
        "nextEffort": "medium",
        "nextProfileKey": "claude_code::claude-sonnet-4-6",
        "shouldApply": True,
    }


def test_reasoning_sync_resets_codex_gpt54_to_high_on_model_change(tmp_path: Path) -> None:
    result = _run_reasoning_sync(
        tmp_path,
        {
            "profile": {
                "choices": [
                    ["Low (faster)", "low"],
                    ["Medium", "medium"],
                    ["High (deeper reasoning, recommended)", "high"],
                    ["XHigh (maximum depth)", "xhigh"],
                ],
                "default_effort": "high",
                "description": "Codex GPT-5.4 reasoning profile",
            },
            "profileKey": "codex::gpt-5.4",
            "lastAppliedProfileKey": "claude_code::claude-opus-4-6",
            "currentEffort": "medium",
        },
    )

    assert result == {
        "nextEffort": "high",
        "nextProfileKey": "codex::gpt-5.4",
        "shouldApply": True,
    }


def test_reasoning_sync_preserves_manual_selection_with_same_profile(tmp_path: Path) -> None:
    result = _run_reasoning_sync(
        tmp_path,
        {
            "profile": {
                "choices": [
                    ["Low (faster)", "low"],
                    ["Medium", "medium"],
                    ["High (deeper reasoning, recommended)", "high"],
                    ["XHigh (maximum depth)", "xhigh"],
                ],
                "default_effort": "high",
                "description": "Codex GPT-5.4 reasoning profile",
            },
            "profileKey": "codex::gpt-5.4",
            "lastAppliedProfileKey": "codex::gpt-5.4",
            "currentEffort": "low",
        },
    )

    assert result == {
        "nextEffort": "low",
        "nextProfileKey": "codex::gpt-5.4",
        "shouldApply": False,
    }


def test_reasoning_sync_clears_effort_when_new_model_has_no_profile(tmp_path: Path) -> None:
    result = _run_reasoning_sync(
        tmp_path,
        {
            "profile": None,
            "profileKey": "openai::gpt-4o",
            "lastAppliedProfileKey": "codex::gpt-5.4",
            "currentEffort": "xhigh",
        },
    )

    assert result == {
        "nextEffort": None,
        "nextProfileKey": None,
        "shouldApply": True,
    }
