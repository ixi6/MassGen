"""
Infrastructure components for MassGen isolated write contexts.

Provides git worktree and shadow repository management for isolated
agent workspaces during coordination phases.
"""

# Re-export git utilities for convenience
from ..utils.git_utils import get_git_branch, get_git_root, get_git_status, is_git_repo
from .shadow_repo import ShadowRepo
from .worktree_manager import WorktreeManager

__all__ = [
    "WorktreeManager",
    "ShadowRepo",
    "get_git_root",
    "get_git_branch",
    "get_git_status",
    "is_git_repo",
]
