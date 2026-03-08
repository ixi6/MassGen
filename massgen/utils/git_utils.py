"""
Git discovery and utility functions using GitPython.
"""

import os
from typing import Any

from git import InvalidGitRepositoryError, Repo
from loguru import logger


def get_git_root(path: str) -> str | None:
    """
    Find the root of the git repository containing the given path.

    Args:
        path: Directory path to check

    Returns:
        Absolute path to git root, or None if not in a git repo
    """
    if not os.path.exists(path):
        return None

    try:
        repo = Repo(path, search_parent_directories=True)
        return repo.working_tree_dir
    except InvalidGitRepositoryError:
        return None


def get_git_branch(path: str) -> str | None:
    """
    Get the current git branch name.

    Args:
        path: Path within the git repository

    Returns:
        Branch name, or None if not in a git repo or detached HEAD
    """
    try:
        repo = Repo(path, search_parent_directories=True)
        if repo.head.is_detached:
            return None
        return repo.active_branch.name
    except (InvalidGitRepositoryError, TypeError):
        return None


def get_git_status(path: str) -> dict[str, bool]:
    """
    Get current git status (dirty, untracked).

    Args:
        path: Path within the git repository

    Returns:
        Dictionary with 'is_dirty' and 'has_untracked' flags
    """
    status: dict[str, Any] = {"is_dirty": False, "has_untracked": False}
    try:
        repo = Repo(path, search_parent_directories=True)
        status["is_dirty"] = repo.is_dirty()
        status["has_untracked"] = len(repo.untracked_files) > 0
    except InvalidGitRepositoryError:
        pass
    return status


def get_current_commit(path: str) -> str | None:
    """
    Get the current commit SHA.

    Args:
        path: Path within the git repository

    Returns:
        Full commit SHA, or None if not in a git repo
    """
    try:
        repo = Repo(path, search_parent_directories=True)
        return repo.head.commit.hexsha
    except (InvalidGitRepositoryError, ValueError):
        return None


def is_git_repo(path: str) -> bool:
    """Check if the given path is inside a git repository."""
    return get_git_root(path) is not None


def get_repo(path: str) -> Repo | None:
    """
    Get a Repo object for the given path.

    Args:
        path: Path within the git repository

    Returns:
        Repo object, or None if not in a git repo
    """
    try:
        return Repo(path, search_parent_directories=True)
    except InvalidGitRepositoryError:
        return None


def get_changes(repo: Repo, base_ref: str | None = None) -> list[dict[str, str]]:
    """
    Get list of all changes (committed, staged, unstaged, untracked) in a repo.

    Args:
        repo: GitPython Repo object
        base_ref: Optional baseline ref/commit SHA. When provided, include
            committed deltas between base_ref and HEAD.

    Returns:
        List of dicts with 'status' and 'path' keys
    """
    changes_by_path: dict[str, str] = {}

    def _record_name_status(diff_output: str) -> None:
        for line in diff_output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status = parts[0][:1].upper()
            rel_path = parts[-1]
            if rel_path:
                changes_by_path[rel_path] = status

    if base_ref:
        try:
            _record_name_status(repo.git.diff("--name-status", base_ref, "HEAD"))
        except Exception as e:
            logger.warning("Failed to diff base_ref {} against HEAD: {}", base_ref, e)

    # Staged changes (index vs HEAD)
    try:
        _record_name_status(repo.git.diff("--name-status", "--cached"))
    except Exception:
        pass

    # Unstaged changes (working tree vs index)
    try:
        _record_name_status(repo.git.diff("--name-status"))
    except Exception:
        pass

    # Untracked files
    for path in repo.untracked_files:
        changes_by_path[path] = "?"

    return [{"status": status, "path": path} for path, status in changes_by_path.items()]


def get_branch_diff_summary(
    repo_path: str,
    base_ref: str,
    target_branch: str,
    max_files: int = 10,
) -> str:
    """Get a short diff summary between base_ref and target_branch.

    Returns a formatted string like:
        3 files (+45/-12)
        M src/auth.py | A src/oauth.py | M tests/test_auth.py

    Args:
        repo_path: Path to the git repository
        base_ref: Base reference (e.g., "HEAD", commit SHA, branch name)
        target_branch: Target branch name to diff against
        max_files: Maximum number of files to list (avoids prompt bloat)

    Returns:
        Formatted diff summary string, or empty string on failure
    """
    try:
        repo = Repo(repo_path, search_parent_directories=True)

        # Get shortstat summary (e.g., "3 files changed, 45 insertions(+), 12 deletions(-)")
        shortstat = repo.git.diff("--shortstat", base_ref, target_branch).strip()
        if not shortstat:
            return ""

        # Parse shortstat into compact form
        import re

        files_match = re.search(r"(\d+) file", shortstat)
        ins_match = re.search(r"(\d+) insertion", shortstat)
        del_match = re.search(r"(\d+) deletion", shortstat)
        n_files = files_match.group(1) if files_match else "0"
        n_ins = ins_match.group(1) if ins_match else "0"
        n_del = del_match.group(1) if del_match else "0"
        summary_line = f"{n_files} file{'s' if int(n_files) != 1 else ''} (+{n_ins}/-{n_del})"

        # Get name-status for file list
        name_status = repo.git.diff("--name-status", base_ref, target_branch).strip()
        if not name_status:
            return summary_line

        file_entries = []
        for line in name_status.splitlines()[:max_files]:
            parts = line.split("\t")
            if len(parts) >= 2:
                status = parts[0][:1].upper()
                filepath = parts[-1]
                file_entries.append(f"{status} {filepath}")

        total_files = len(name_status.splitlines())
        file_list = " | ".join(file_entries)
        if total_files > max_files:
            file_list += f" | ... (+{total_files - max_files} more)"

        return f"{summary_line}\n  {file_list}"

    except Exception:
        return ""
