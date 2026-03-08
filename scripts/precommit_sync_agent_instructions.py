#!/usr/bin/env python3
"""Keep CLAUDE.md and AGENTS.md synchronized.

Rules:
- If only one file changed, copy it to the other file.
- If both changed and are identical, do nothing.
- If both changed and differ, fail so the user can resolve manually.

This hook also stages both files after synchronization.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _status_map(paths: list[str]) -> dict[str, str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    statuses: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        statuses[line[3:].strip()] = line[:2]
    return statuses


def _stage(paths: list[str]) -> None:
    result = subprocess.run(
        ["git", "add", *paths],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            "Warning: could not stage CLAUDE.md/AGENTS.md automatically. " "Please stage them manually.",
        )


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    claude_path = repo_root / "CLAUDE.md"
    agents_path = repo_root / "AGENTS.md"
    tracked = ["CLAUDE.md", "AGENTS.md"]

    if not claude_path.exists() and not agents_path.exists():
        print("Error: neither CLAUDE.md nor AGENTS.md exists.")
        return 1

    if claude_path.exists() and not agents_path.exists():
        _write_text(agents_path, _read_text(claude_path))
        _stage(tracked)
        print("Synced AGENTS.md from CLAUDE.md")
        return 0

    if agents_path.exists() and not claude_path.exists():
        _write_text(claude_path, _read_text(agents_path))
        _stage(tracked)
        print("Synced CLAUDE.md from AGENTS.md")
        return 0

    claude_text = _read_text(claude_path)
    agents_text = _read_text(agents_path)

    if claude_text == agents_text:
        return 0

    statuses = _status_map(tracked)
    claude_status = statuses.get("CLAUDE.md", "")
    agents_status = statuses.get("AGENTS.md", "")
    claude_changed = bool(claude_status)
    agents_changed = bool(agents_status)
    claude_untracked = claude_status == "??"
    agents_untracked = agents_status == "??"

    if claude_changed and not agents_changed:
        _write_text(agents_path, claude_text)
        _stage(tracked)
        print("Synced AGENTS.md from CLAUDE.md")
        return 0

    if agents_changed and not claude_changed:
        _write_text(claude_path, agents_text)
        _stage(tracked)
        print("Synced CLAUDE.md from AGENTS.md")
        return 0

    if claude_changed and agents_changed:
        if agents_untracked and not claude_untracked:
            _write_text(agents_path, claude_text)
            _stage(tracked)
            print("Synced AGENTS.md from CLAUDE.md")
            return 0

        if claude_untracked and not agents_untracked:
            _write_text(claude_path, agents_text)
            _stage(tracked)
            print("Synced CLAUDE.md from AGENTS.md")
            return 0

        print("Error: CLAUDE.md and AGENTS.md changed differently.")
        print("Resolve manually so both files are identical, then retry.")
        return 1

    _write_text(agents_path, claude_text)
    _stage(tracked)
    print("Synced AGENTS.md from CLAUDE.md (detected drift).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
