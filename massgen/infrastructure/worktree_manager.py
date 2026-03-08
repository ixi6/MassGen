"""
Git worktree management for isolated session environments using GitPython.
"""

import logging
import os

from git import GitCommandError, InvalidGitRepositoryError, Repo

logger = logging.getLogger(__name__)


class WorktreeManager:
    """Manages temporary git worktrees for MassGen sessions."""

    def __init__(self, repo_path: str):
        """
        Initialize the WorktreeManager.

        Args:
            repo_path: Path within the git repository
        """
        try:
            self.repo = Repo(repo_path, search_parent_directories=True)
            self.repo_path = self.repo.working_tree_dir
        except InvalidGitRepositoryError:
            raise ValueError(f"Path {repo_path} is not in a git repository")

    def create_worktree(self, target_path: str, branch_name: str, base_commit: str = "HEAD") -> str:
        """
        Create a new worktree at target_path on a new branch.

        Args:
            target_path: Path where the worktree should be created
            branch_name: Name of the new branch to create
            base_commit: Commit to base the new branch on (default: HEAD)

        Returns:
            The absolute path to the created worktree
        """
        target_path = os.path.abspath(target_path)

        try:
            # git worktree add -b <branch> <path> <base_commit>
            self.repo.git.worktree("add", "-b", branch_name, target_path, base_commit)
            logger.info(f"Created worktree at {target_path} on branch {branch_name}")
            return target_path
        except GitCommandError as e:
            logger.error(f"Failed to create worktree: {e.stderr}")
            raise RuntimeError(f"Failed to create worktree: {e.stderr}")

    def remove_worktree(self, target_path: str, force: bool = False, delete_branch: bool = True) -> None:
        """
        Remove the worktree at target_path and optionally delete the branch.

        Args:
            target_path: Path to the worktree to remove
            force: Whether to force removal even if there are changes
            delete_branch: Whether to delete the branch associated with the worktree
        """
        target_path = os.path.abspath(target_path)
        branch_name = self._get_branch_for_worktree(target_path)

        try:
            if force:
                self.repo.git.worktree("remove", "--force", target_path)
            else:
                self.repo.git.worktree("remove", target_path)
            logger.info(f"Removed worktree at {target_path}")

            if delete_branch and branch_name:
                self._delete_branch(branch_name, force=force)

        except GitCommandError as e:
            logger.error(f"Failed to remove worktree: {e.stderr}")
            raise RuntimeError(f"Failed to remove worktree: {e.stderr}")

    def list_worktrees(self) -> list[dict]:
        """
        List all worktrees in the repository.

        Returns:
            List of dicts with 'path', 'head', and 'branch' keys
        """
        try:
            output = self.repo.git.worktree("list", "--porcelain")
            worktrees = []
            current_wt: dict = {}

            for line in output.split("\n"):
                if not line:
                    if current_wt:
                        worktrees.append(current_wt)
                        current_wt = {}
                    continue

                if line.startswith("worktree "):
                    current_wt["path"] = line[9:]
                elif line.startswith("HEAD "):
                    current_wt["head"] = line[5:]
                elif line.startswith("branch "):
                    current_wt["branch"] = line[7:].replace("refs/heads/", "")

            if current_wt:
                worktrees.append(current_wt)

            return worktrees
        except GitCommandError:
            return []

    def prune(self) -> None:
        """Prune stale worktree metadata."""
        try:
            self.repo.git.worktree("prune")
        except GitCommandError:
            pass

    def _get_branch_for_worktree(self, target_path: str) -> str | None:
        """Find the branch name associated with a worktree path."""
        for wt in self.list_worktrees():
            if os.path.abspath(wt.get("path", "")) == target_path:
                return wt.get("branch")
        return None

    def close(self) -> None:
        """Close the underlying Repo object to release file descriptors."""
        if hasattr(self, "repo") and self.repo:
            self.repo.close()

    def _delete_branch(self, branch_name: str, force: bool = False) -> None:
        """Delete a git branch."""
        try:
            if force:
                self.repo.git.branch("-D", branch_name)
            else:
                self.repo.git.branch("-d", branch_name)
            logger.info(f"Deleted branch {branch_name}")
        except GitCommandError as e:
            logger.debug(f"Failed to delete branch {branch_name}: {e}")
