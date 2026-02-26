"""
Isolation Context Manager for MassGen - Manages isolated write contexts for agents.

This module provides isolated write environments using git worktrees (for git repos)
or shadow repositories (for non-git directories). This enables safe review and
approval workflows before changes are applied to the original context.

Each coordination round, agents get a fresh worktree with a `.massgen_scratch/`
directory (git-excluded) for experiments. Branches accumulate across rounds
(never deleted mid-session) so agents can see each other's work via diff summaries.
All branches are cleaned up in `cleanup_session()` at session end.
"""

import logging
import os
import secrets
import shutil
import tempfile
from typing import Any

from ..infrastructure import ShadowRepo, WorktreeManager, is_git_repo

# Use module-level logger
log = logging.getLogger(__name__)

# Name of the scratch directory inside worktrees (git-excluded)
SCRATCH_DIR_NAME = ".massgen_scratch"

# Name of the verification subdirectory inside scratch (for test results, screenshots, etc.)
VERIFICATION_DIR_NAME = "verification"


class IsolationContextManager:
    """
    Manages isolated write contexts for agent changes.

    This class creates isolated environments where agents can make changes
    without affecting the original files. Changes can be reviewed and
    selectively applied later.

    Supports two isolation modes:
    - Worktree: Uses git worktrees for git repositories (efficient, branch-based)
    - Shadow: Creates temporary git repos for non-git directories (full copy)

    Branch lifecycle (branches accumulate across rounds for cross-agent visibility):
    - initialize_context(): creates a new branch (old branches are kept)
    - cleanup_round(): removes worktree, keeps branch (for cross-agent diffs)
    - cleanup_session(): removes worktrees AND all remaining branches
    """

    def __init__(
        self,
        session_id: str,
        write_mode: str = "auto",
        temp_base: str | None = None,
        workspace_path: str | None = None,
        base_commit: str | None = None,
        branch_label: str | None = None,
    ):
        """
        Initialize the IsolationContextManager.

        Args:
            session_id: Unique session identifier for naming branches/repos
            write_mode: Isolation mode - "auto", "worktree", "isolated", or "legacy"
            temp_base: Optional base directory for temporary files
            workspace_path: Optional agent workspace path. When set, worktrees are
                created inside {workspace_path}/.worktree/ instead of temp directories.
                This makes the worktree accessible to the agent as a workspace subdirectory.
            base_commit: Optional commit/branch to use as the starting point for new
                worktrees. When set, the worktree starts from this commit instead of HEAD.
                Used for final presentation to start from the winner's branch.
            branch_label: Optional explicit branch name override (e.g. "presenter").
                When set, used as the branch name instead of the default massgen/{random}.
        """
        self.session_id = session_id
        self.write_mode = write_mode
        self.temp_base = temp_base
        self.workspace_path = workspace_path
        self.base_commit = base_commit
        self.branch_label = branch_label

        # Track active contexts: original_path -> context info
        self._contexts: dict[str, dict[str, Any]] = {}

        # Track WorktreeManager instances by repo root
        self._worktree_managers: dict[str, WorktreeManager] = {}

        # Track all branch names created in this session (for cleanup_session)
        self._session_branches: list[str] = []

        # Counter for unique branch names
        self._branch_counter = 0

        log.info(f"IsolationContextManager initialized: session={session_id}, mode={write_mode}, branch_label={branch_label}")

    def initialize_context(self, context_path: str, agent_id: str | None = None) -> str:
        """
        Initialize an isolated context for the given path.

        Args:
            context_path: Original path to create isolated context for
            agent_id: Optional agent ID for context naming

        Returns:
            Path to the isolated context (where agent should write)

        Raises:
            ValueError: If write_mode is invalid or context already exists
            RuntimeError: If isolation setup fails
        """
        context_path = os.path.abspath(context_path)

        if context_path in self._contexts:
            # Return existing isolated path
            return self._contexts[context_path]["isolated_path"]

        if self.write_mode == "legacy":
            # No isolation - return original path
            self._contexts[context_path] = {
                "isolated_path": context_path,
                "mode": "legacy",
                "manager": None,
            }
            return context_path

        # Determine actual mode for "auto"
        actual_mode = self._determine_mode(context_path)

        if actual_mode == "worktree":
            isolated_path = self._create_worktree_context(context_path, agent_id)
        elif actual_mode == "shadow":
            isolated_path = self._create_shadow_context(context_path, agent_id)
        else:
            # Fallback to legacy (direct writes)
            isolated_path = context_path
            actual_mode = "legacy"
            self._contexts[context_path] = {
                "isolated_path": isolated_path,
                "mode": actual_mode,
                "manager": None,
                "agent_id": agent_id,
            }

        # Note: _create_worktree_context and _create_shadow_context set self._contexts
        log.info(f"Created isolated context: {context_path} -> {isolated_path} (mode={actual_mode})")
        return isolated_path

    def _determine_mode(self, context_path: str) -> str:
        """Determine the actual isolation mode based on write_mode and path type."""
        if self.write_mode == "worktree":
            if is_git_repo(context_path):
                return "worktree"
            else:
                log.warning(f"Path {context_path} is not a git repo, falling back to shadow mode")
                return "shadow"

        if self.write_mode == "isolated":
            return "shadow"

        if self.write_mode == "auto":
            if is_git_repo(context_path):
                return "worktree"
            else:
                return "shadow"

        # Unknown mode - fallback to legacy
        log.warning(f"Unknown write_mode: {self.write_mode}, falling back to legacy")
        return "legacy"

    def _create_worktree_context(self, context_path: str, agent_id: str | None) -> str:
        """Create a git worktree for the context path."""
        from git import Repo

        from ..utils.git_utils import get_git_root

        repo_root = get_git_root(context_path)
        if not repo_root:
            raise RuntimeError(f"Cannot create worktree: {context_path} is not in a git repo")

        # Get or create WorktreeManager for this repo
        if repo_root not in self._worktree_managers:
            self._worktree_managers[repo_root] = WorktreeManager(repo_root)

        wm = self._worktree_managers[repo_root]

        # Generate branch name with random suffix for uniqueness
        self._branch_counter += 1
        random_suffix = secrets.token_hex(4)
        if self.branch_label:
            branch_name = f"{self.branch_label}_{random_suffix}"
        else:
            branch_name = f"massgen/{random_suffix}"

        # Create worktree path - prefer workspace if available
        if self.workspace_path:
            # Create worktree inside agent workspace at .worktree/ctx_N
            worktree_dir = os.path.join(self.workspace_path, ".worktree")
            os.makedirs(worktree_dir, exist_ok=True)
            worktree_path = os.path.join(worktree_dir, f"ctx_{self._branch_counter}")
        else:
            # Fallback: use temp directory (Docker mode or no workspace)
            if self.temp_base:
                worktree_base = self.temp_base
            else:
                worktree_base = tempfile.gettempdir()

            worktree_path = tempfile.mkdtemp(
                prefix=f"massgen_worktree_{self._branch_counter}_",
                dir=worktree_base,
            )
            # Remove the dir since git worktree add will create it
            os.rmdir(worktree_path)

        try:
            base = self.base_commit or "HEAD"
            isolated_path = wm.create_worktree(worktree_path, branch_name, base_commit=base)

            # Mirror source dirty state (tracked/untracked/deleted) into the worktree so
            # agents start from the user's current repo state, not just clean HEAD.
            self._mirror_source_state_into_worktree(
                repo_root=repo_root,
                context_path=context_path,
                isolated_path=isolated_path,
            )

            base_ref = None
            try:
                wt_repo = Repo(isolated_path)
                if wt_repo.is_dirty(untracked_files=True):
                    wt_repo.git.add("-A")
                    wt_repo.index.commit("[BASELINE] Mirror source working tree")
                base_ref = wt_repo.head.commit.hexsha
            except Exception as e:
                log.warning(
                    "Failed to create baseline commit for %s (drift detection disabled): %s",
                    context_path,
                    e,
                )
                base_ref = None

            # Store manager reference for cleanup
            self._contexts[context_path] = {
                "isolated_path": isolated_path,
                "original_path": context_path,
                "mode": "worktree",
                "manager": wm,
                "branch_name": branch_name,
                "base_ref": base_ref,
                "repo_root": repo_root,
                "agent_id": agent_id,
            }

            # Track branch for session cleanup
            self._session_branches.append(branch_name)

            # Setup scratch directory inside worktree
            self._setup_scratch_in_worktree(isolated_path, context_path)

            return isolated_path

        except Exception as e:
            log.error(f"Failed to create worktree: {e}")
            raise RuntimeError(f"Failed to create worktree context: {e}")

    @staticmethod
    def _is_in_context_scope(repo_rel_path: str, context_prefix: str) -> bool:
        """Return True if repo-relative path is within the context prefix."""
        normalized_rel = repo_rel_path.replace("\\", "/").strip("/")
        normalized_prefix = context_prefix.replace("\\", "/").strip("/")
        if normalized_prefix in ("", "."):
            return True
        return normalized_rel == normalized_prefix or normalized_rel.startswith(f"{normalized_prefix}/")

    def _mirror_source_state_into_worktree(
        self,
        repo_root: str,
        context_path: str,
        isolated_path: str,
    ) -> None:
        """Mirror source working-tree deltas into isolated worktree for a context scope."""
        from git import Repo

        try:
            source_repo = Repo(repo_root)
            context_abs = os.path.abspath(context_path)
            repo_root_abs = os.path.abspath(repo_root)
            if os.path.commonpath([context_abs, repo_root_abs]) != repo_root_abs:
                return

            context_prefix = os.path.relpath(context_abs, repo_root_abs)
            candidate_paths: set[str] = set()

            # Unstaged and staged deltas against HEAD.
            for diff in source_repo.index.diff(None):
                for candidate in (diff.a_path, diff.b_path):
                    if isinstance(candidate, str) and candidate:
                        candidate_paths.add(candidate)

            for diff in source_repo.index.diff("HEAD"):
                for candidate in (diff.a_path, diff.b_path):
                    if isinstance(candidate, str) and candidate:
                        candidate_paths.add(candidate)

            for rel_path in source_repo.untracked_files:
                if rel_path:
                    candidate_paths.add(rel_path)

            for rel_path in sorted(candidate_paths):
                if not self._is_in_context_scope(rel_path, context_prefix):
                    continue

                norm_parts = rel_path.replace("\\", "/").split("/")
                if ".git" in norm_parts or SCRATCH_DIR_NAME in norm_parts:
                    continue

                source_abs = os.path.join(repo_root_abs, rel_path)
                dest_abs = os.path.join(isolated_path, rel_path)

                if os.path.exists(source_abs):
                    os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
                    shutil.copy2(source_abs, dest_abs)
                else:
                    if os.path.isfile(dest_abs) or os.path.islink(dest_abs):
                        os.remove(dest_abs)
                    elif os.path.isdir(dest_abs):
                        shutil.rmtree(dest_abs)
        except Exception as e:
            log.warning("Failed to mirror source working tree into worktree: %s", e)

    def _create_shadow_context(self, context_path: str, agent_id: str | None) -> str:
        """Create a shadow repository for the context path."""
        try:
            shadow = ShadowRepo(context_path, temp_base=self.temp_base)
            isolated_path = shadow.initialize()

            # Store shadow repo reference for cleanup
            self._contexts[context_path] = {
                "isolated_path": isolated_path,
                "mode": "shadow",
                "manager": shadow,
                "agent_id": agent_id,
            }

            # Setup scratch directory inside shadow repo
            self._setup_scratch_in_worktree(isolated_path, context_path)

            return isolated_path

        except Exception as e:
            log.error(f"Failed to create shadow repo: {e}")
            raise RuntimeError(f"Failed to create shadow context: {e}")

    def _setup_scratch_in_worktree(self, isolated_path: str, context_path: str) -> None:
        """Create .massgen_scratch/ inside worktree and git-exclude it.

        Args:
            isolated_path: Path to the worktree or shadow repo
            context_path: Original context path (key in self._contexts)
        """
        scratch_path = os.path.join(isolated_path, SCRATCH_DIR_NAME)
        os.makedirs(scratch_path, exist_ok=True)

        # Create verification subdirectory for test results, screenshots, etc.
        verification_path = os.path.join(scratch_path, VERIFICATION_DIR_NAME)
        os.makedirs(verification_path, exist_ok=True)

        # Git-exclude the scratch directory
        try:
            from git import Repo

            repo = Repo(isolated_path)
            # For worktrees, info/exclude must be in the COMMON git dir (not worktree-specific).
            # Use --git-common-dir to get the shared .git directory.
            try:
                common_dir = repo.git.rev_parse("--git-common-dir")
            except Exception:
                common_dir = repo.git.rev_parse("--git-dir")
            # --git-common-dir may return a relative path (e.g. ".git") for non-worktree repos
            if not os.path.isabs(common_dir):
                common_dir = os.path.join(repo.working_dir, common_dir)
            exclude_file = os.path.join(common_dir, "info", "exclude")
            os.makedirs(os.path.dirname(exclude_file), exist_ok=True)

            # Check if already excluded
            exclude_entry = f"/{SCRATCH_DIR_NAME}/"
            existing_content = ""
            if os.path.exists(exclude_file):
                with open(exclude_file) as f:
                    existing_content = f.read()

            if exclude_entry not in existing_content:
                with open(exclude_file, "a") as f:
                    if existing_content and not existing_content.endswith("\n"):
                        f.write("\n")
                    f.write(f"{exclude_entry}\n")

            log.info(f"Created scratch directory at {scratch_path}")
        except Exception as e:
            log.warning(f"Failed to git-exclude scratch directory: {e}")

        # Store scratch path in context
        context_path = os.path.abspath(context_path)
        if context_path in self._contexts:
            self._contexts[context_path]["scratch_path"] = scratch_path

    def get_scratch_path(self, context_path: str) -> str | None:
        """Get the scratch directory path for a context.

        Args:
            context_path: Original context path

        Returns:
            Path to .massgen_scratch/ inside the worktree, or None
        """
        context_path = os.path.abspath(context_path)
        if context_path in self._contexts:
            return self._contexts[context_path].get("scratch_path")
        return None

    def get_branch_name(self, context_path: str) -> str | None:
        """Get the branch name for a context.

        Args:
            context_path: Original context path

        Returns:
            Branch name or None
        """
        context_path = os.path.abspath(context_path)
        if context_path in self._contexts:
            return self._contexts[context_path].get("branch_name")
        return None

    def get_all_branch_names(self) -> list[str]:
        """Get all branch names created in this session.

        Returns:
            List of branch names
        """
        return list(self._session_branches)

    def generate_branch_summaries(
        self,
        branches: dict[str, str],
        base_ref: str = "HEAD",
    ) -> dict[str, str]:
        """Generate diff summaries for a set of branches.

        Args:
            branches: Dict mapping label -> branch_name (e.g., {"agent1": "massgen/abc123"})
            base_ref: Base reference to diff against (default: HEAD)

        Returns:
            Dict mapping label -> formatted diff summary string.
            Labels with no diff or on error are omitted.
        """
        from ..utils.git_utils import get_branch_diff_summary

        summaries: dict[str, str] = {}

        # Find a repo path — prefer repo_root from contexts (worktree branches
        # live in the original repo), fall back to workspace_path
        repo_path = None
        for ctx in self._contexts.values():
            rr = ctx.get("repo_root")
            if rr:
                repo_path = rr
                break
        if not repo_path:
            repo_path = self.workspace_path

        if not repo_path:
            return summaries

        try:
            for label, branch_name in branches.items():
                summary = get_branch_diff_summary(repo_path, base_ref, branch_name)
                if summary:
                    summaries[label] = summary
        except Exception as e:
            log.warning(f"Failed to generate branch summaries: {e}")

        return summaries

    @staticmethod
    def cleanup_orphaned_branches(repo_path: str) -> int:
        """Delete massgen/* branches not backed by an active worktree.

        Only removes branches that are truly orphaned (no associated worktree).
        Branches with active worktrees are left alone so concurrent MassGen
        sessions sharing the same repo are not disrupted.

        This should be called at session start to clean up stale branches
        left behind by crashed or interrupted sessions.

        Args:
            repo_path: Path to the git repository

        Returns:
            Number of branches deleted
        """
        deleted = 0
        try:
            from git import Repo

            repo = Repo(repo_path, search_parent_directories=True)

            # Collect branches that have an active worktree — those must not be deleted.
            active_worktree_branches: set[str] = set()
            try:
                worktree_output = repo.git.worktree("list", "--porcelain")
                for line in worktree_output.splitlines():
                    if line.startswith("branch refs/heads/"):
                        active_worktree_branches.add(line.removeprefix("branch refs/heads/"))
            except Exception:
                # If worktree list fails, be conservative — skip cleanup entirely
                log.debug("Could not list worktrees; skipping orphaned branch cleanup")
                return 0

            for branch in list(repo.branches):
                if branch.name.startswith("massgen/") and branch.name not in active_worktree_branches:
                    try:
                        repo.delete_head(branch.name, force=True)
                        deleted += 1
                        log.info(f"Cleaned up orphaned branch: {branch.name}")
                    except Exception as e:
                        log.warning(f"Failed to delete orphaned branch {branch.name}: {e}")
        except Exception as e:
            log.warning(f"Failed to scan for orphaned branches in {repo_path}: {e}")

        if deleted:
            log.info(f"Cleaned up {deleted} orphaned massgen/* branches from {repo_path}")
        return deleted

    def _is_own_git_root(self, path: str) -> bool:
        """Check if path is the root of its own git repo (has .git/ directly in it).

        This is different from is_git_repo() which returns True for any path
        inside a git repo. We need this distinction because workspaces may live
        inside the user's project repo (e.g. .massgen/workspaces/) but should
        NOT create branches on the parent project.
        """
        return os.path.exists(os.path.join(path, ".git"))

    def setup_workspace_scratch(self, workspace_path: str, agent_id: str | None = None) -> str:
        """Set up scratch + git branch in the workspace itself (no external context_paths).

        When there are no context_paths, the workspace IS the agent's project.
        This method:
        1. Git-inits the workspace as its own repo (even if inside a parent repo)
        2. Creates a branch for this round
        3. Creates .massgen_scratch/ (git-excluded)

        Args:
            workspace_path: Path to the agent's workspace
            agent_id: Optional agent ID

        Returns:
            Path to the scratch directory
        """
        workspace_path = os.path.abspath(workspace_path)

        # Git-init workspace if it's not its own repo root.
        # Important: use _is_own_git_root, NOT is_git_repo(). The workspace may be
        # inside the user's project repo (e.g. .massgen/workspaces/), but we must NOT
        # create branches on the parent project — we need a standalone repo.
        if not self._is_own_git_root(workspace_path):
            from git import Repo

            repo = Repo.init(workspace_path)
            with repo.config_writer() as config:
                config.set_value("user", "email", "massgen@agent.local")
                config.set_value("user", "name", "MassGen Agent")
            # Create initial commit so branches can be created
            repo.index.commit("[INIT] MassGen workspace")
            log.info(f"Git-initialized workspace at {workspace_path}")

        # Create a branch for this round: use branch_label if explicitly provided
        if self.branch_label:
            branch_name = self.branch_label
        else:
            random_suffix = secrets.token_hex(4)
            branch_name = f"massgen/{random_suffix}"

        if workspace_path not in self._worktree_managers:
            self._worktree_managers[workspace_path] = WorktreeManager(workspace_path)
        wm = self._worktree_managers[workspace_path]

        try:
            from git import Repo

            repo = Repo(workspace_path)
            # Create and checkout the branch (no worktree - we're working in-place)
            repo.git.checkout("-b", branch_name)
            self._session_branches.append(branch_name)
            log.info(f"Created workspace branch: {branch_name}")
            base_ref = repo.head.commit.hexsha
        except Exception as e:
            log.warning(f"Failed to create workspace branch: {e}")
            branch_name = None
            base_ref = None

        # Track as a context so cleanup/archive works
        self._contexts[workspace_path] = {
            "isolated_path": workspace_path,
            "original_path": workspace_path,
            "mode": "workspace",
            "manager": wm if branch_name else None,
            "branch_name": branch_name,
            "base_ref": base_ref,
            "agent_id": agent_id,
        }

        # Setup scratch
        self._setup_scratch_in_worktree(workspace_path, workspace_path)

        scratch_path = os.path.join(workspace_path, SCRATCH_DIR_NAME)
        return scratch_path

    def move_scratch_to_workspace(self, context_path: str, archive_label: str | None = None) -> str | None:
        """Move .massgen_scratch/ to {workspace}/.scratch_archive/{label}/.

        This preserves scratch files after worktree teardown. The archive
        lives in the workspace (sibling of .worktree/), so it gets included
        in workspace snapshots shared with other agents.

        Args:
            context_path: Original context path
            archive_label: Human-readable label for the archive dir (e.g. "agent1").
                When set, used instead of extracting suffix from branch name.

        Returns:
            Path to the archive directory, or None if no scratch to move
        """
        context_path = os.path.abspath(context_path)
        if context_path not in self._contexts:
            return None

        ctx = self._contexts[context_path]
        scratch_path = ctx.get("scratch_path")
        if not scratch_path or not os.path.exists(scratch_path):
            return None

        # Check if scratch has any content
        if not os.listdir(scratch_path):
            log.debug(f"Scratch directory empty, skipping archive: {scratch_path}")
            return None

        # Use archive_label for directory name if provided, otherwise
        # extract the suffix from the branch name
        if archive_label:
            archive_name = archive_label
        else:
            branch_name = ctx.get("branch_name", "")
            archive_name = branch_name.rsplit("/", 1)[-1] if "/" in branch_name else secrets.token_hex(4)

        # Determine archive location
        workspace = self.workspace_path
        if not workspace:
            log.warning("No workspace_path set, cannot archive scratch")
            return None

        archive_dir = os.path.join(workspace, ".scratch_archive", archive_name)
        os.makedirs(os.path.dirname(archive_dir), exist_ok=True)

        try:
            shutil.move(scratch_path, archive_dir)
            log.info(f"Moved scratch to archive: {scratch_path} -> {archive_dir}")
            return archive_dir
        except Exception as e:
            log.warning(f"Failed to move scratch to archive: {e}")
            return None

    def _auto_commit_worktree(self, isolated_path: str, message: str = "[ROUND] Auto-commit") -> bool:
        """Auto-commit any uncommitted changes in a worktree before cleanup.

        This ensures agent work is preserved on the branch even after the
        worktree is removed. Without this, the branch would point at HEAD
        (empty) and cross-agent visibility would find nothing.

        Args:
            isolated_path: Path to the worktree or workspace
            message: Commit message

        Returns:
            True if a commit was made, False otherwise
        """
        try:
            from git import Repo

            repo = Repo(isolated_path)
            if repo.is_dirty(untracked_files=True):
                repo.git.add("-A")
                repo.index.commit(message)
                log.info(f"Auto-committed changes in worktree: {isolated_path}")
                return True
            return False
        except Exception as e:
            log.warning(f"Failed to auto-commit in worktree {isolated_path}: {e}")
            return False

    def cleanup_round(self, context_path: str) -> None:
        """Remove worktree but keep the branch (for cross-agent visibility).

        This is used between coordination rounds. The branch is preserved
        so other agents can see it via `git branch` / `git diff`.
        Any uncommitted changes are auto-committed first so the branch
        contains the agent's actual work.

        Args:
            context_path: Original context path
        """
        context_path = os.path.abspath(context_path)
        if context_path not in self._contexts:
            return

        ctx = self._contexts[context_path]
        mode = ctx.get("mode")

        if mode == "worktree":
            manager = ctx.get("manager")
            isolated_path = ctx.get("isolated_path")
            if isinstance(manager, WorktreeManager) and isolated_path:
                try:
                    # Auto-commit before removing worktree so branch has agent's work
                    self._auto_commit_worktree(isolated_path)
                    # Remove worktree but keep branch (delete_branch=False)
                    manager.remove_worktree(isolated_path, force=True, delete_branch=False)
                    log.info(f"Removed worktree (kept branch): {isolated_path}")
                except Exception as e:
                    log.warning(f"Failed to cleanup worktree {isolated_path}: {e}")

        elif mode == "workspace":
            # Workspace mode: auto-commit before switching branches
            isolated_path = ctx.get("isolated_path")
            if isolated_path:
                self._auto_commit_worktree(isolated_path)
            # Switch back to main/master but keep the branch
            try:
                from git import Repo

                repo = Repo(context_path)
                # Find the default branch (main or master)
                default_branch = None
                for name in ("main", "master"):
                    if name in [b.name for b in repo.branches]:
                        default_branch = name
                        break
                if default_branch:
                    repo.git.checkout(default_branch)
                    log.info(f"Switched workspace back to {default_branch} (kept branch)")
            except Exception as e:
                log.warning(f"Failed to switch workspace branch: {e}")

        elif mode == "shadow":
            manager = ctx.get("manager")
            if isinstance(manager, ShadowRepo):
                manager.cleanup()

        del self._contexts[context_path]

    def cleanup_session(self) -> None:
        """Full cleanup: remove all worktrees AND all remaining branches.

        This is called at the end of a session (after final presentation)
        to clean up everything.
        """
        # First remove all worktrees
        paths = list(self._contexts.keys())
        for context_path in paths:
            ctx = self._contexts[context_path]
            mode = ctx.get("mode")

            if mode == "worktree":
                manager = ctx.get("manager")
                isolated_path = ctx.get("isolated_path")
                if isinstance(manager, WorktreeManager) and isolated_path:
                    try:
                        manager.remove_worktree(isolated_path, force=True, delete_branch=True)
                    except Exception as e:
                        log.warning(f"Failed to cleanup worktree {isolated_path}: {e}")
            elif mode == "workspace":
                # Workspace mode: switch back to default branch, branch will be
                # deleted by the session branch cleanup below
                try:
                    from git import Repo

                    repo = Repo(context_path)
                    for name in ("main", "master"):
                        if name in [b.name for b in repo.branches]:
                            repo.git.checkout(name)
                            break
                except Exception as e:
                    log.warning(f"Failed to switch workspace branch: {e}")
            elif mode == "shadow":
                manager = ctx.get("manager")
                if isinstance(manager, ShadowRepo):
                    manager.cleanup()

            del self._contexts[context_path]

        # Delete any remaining session branches that weren't cleaned up with worktrees
        for branch_name in self._session_branches:
            for wm in self._worktree_managers.values():
                try:
                    wm._delete_branch(branch_name, force=True)
                    log.info(f"Cleaned up session branch: {branch_name}")
                except Exception:
                    pass
        self._session_branches.clear()

        # Prune any stale worktree metadata and close Repo FDs
        for wm in self._worktree_managers.values():
            try:
                wm.prune()
            except Exception:
                pass
            try:
                wm.close()
            except Exception:
                pass

        self._worktree_managers.clear()
        log.info("Cleaned up all isolated contexts and session branches")

    def get_isolated_path(self, original_path: str) -> str | None:
        """
        Get the isolated path for a given original path.

        Args:
            original_path: Original context path

        Returns:
            Isolated path if context exists, None otherwise
        """
        original_path = os.path.abspath(original_path)
        if original_path in self._contexts:
            return self._contexts[original_path]["isolated_path"]
        return None

    def get_changes(self, context_path: str, include_committed_since_base: bool = False) -> list[dict[str, Any]]:
        """
        Get list of changes in the isolated context.

        Args:
            context_path: Original context path
            include_committed_since_base: Include committed deltas between the
                context base ref and HEAD (if available).

        Returns:
            List of change dicts with 'status', 'path' keys
        """
        context_path = os.path.abspath(context_path)
        if context_path not in self._contexts:
            return []

        ctx = self._contexts[context_path]
        mode = ctx.get("mode")
        manager = ctx.get("manager")

        if mode == "legacy" or manager is None:
            return []

        if mode == "shadow" and isinstance(manager, ShadowRepo):
            return manager.get_changes()

        # For worktree, use shared git_utils
        if mode == "worktree":
            from git import InvalidGitRepositoryError, Repo

            from ..utils.git_utils import get_changes as git_get_changes

            isolated_path = ctx["isolated_path"]
            try:
                repo = Repo(isolated_path)
                base_ref = ctx.get("base_ref") if include_committed_since_base else None
                return git_get_changes(repo, base_ref=base_ref)
            except InvalidGitRepositoryError:
                return []

        return []

    def get_diff(
        self,
        context_path: str,
        staged: bool = False,
        include_committed_since_base: bool = False,
    ) -> str:
        """
        Get the diff of changes in the isolated context.

        Args:
            context_path: Original context path
            staged: If True, show staged changes only
            include_committed_since_base: Include committed diff between the
                context base ref and HEAD (if available).

        Returns:
            Git diff output as string
        """
        context_path = os.path.abspath(context_path)
        if context_path not in self._contexts:
            return ""

        ctx = self._contexts[context_path]
        mode = ctx.get("mode")

        if mode == "legacy":
            return ""

        if mode == "shadow":
            manager = ctx.get("manager")
            if isinstance(manager, ShadowRepo):
                return manager.get_diff(staged=staged)

        if mode == "worktree":
            from git import GitCommandError, InvalidGitRepositoryError, Repo

            isolated_path = ctx["isolated_path"]
            try:
                repo = Repo(isolated_path)
                committed_diff = ""
                if include_committed_since_base:
                    base_ref = ctx.get("base_ref")
                    if base_ref:
                        try:
                            committed_diff = repo.git.diff(base_ref, "HEAD")
                        except GitCommandError:
                            committed_diff = ""

                if staged:
                    working_diff = repo.git.diff("--staged")
                    if committed_diff and working_diff:
                        return f"{committed_diff}\n{working_diff}"
                    return committed_diff or working_diff
                # Stage everything so untracked (new) files appear in the diff,
                # then unstage so ChangeApplier can still detect changes via
                # repo.index.diff(None) and repo.untracked_files.
                repo.git.add("-A")
                try:
                    working_diff = repo.git.diff("--staged")
                finally:
                    repo.git.reset("HEAD")
                if committed_diff and working_diff:
                    return f"{committed_diff}\n{working_diff}"
                return committed_diff or working_diff
            except (InvalidGitRepositoryError, GitCommandError):
                return ""

        return ""

    def cleanup(self, context_path: str | None = None) -> None:
        """
        Cleanup isolated context(s).

        Args:
            context_path: Specific context to cleanup, or None for all
        """
        if context_path:
            context_path = os.path.abspath(context_path)
            if context_path in self._contexts:
                self._cleanup_single_context(context_path)
        else:
            self.cleanup_all()

    def _cleanup_single_context(self, context_path: str) -> None:
        """Cleanup a single isolated context."""
        if context_path not in self._contexts:
            return

        ctx = self._contexts[context_path]
        mode = ctx.get("mode")

        if mode == "shadow":
            manager = ctx.get("manager")
            if isinstance(manager, ShadowRepo):
                manager.cleanup()

        elif mode == "worktree":
            manager = ctx.get("manager")
            isolated_path = ctx.get("isolated_path")
            if isinstance(manager, WorktreeManager) and isolated_path:
                try:
                    manager.remove_worktree(isolated_path, force=True, delete_branch=True)
                except Exception as e:
                    log.warning(f"Failed to cleanup worktree {isolated_path}: {e}")

        del self._contexts[context_path]
        log.info(f"Cleaned up isolated context: {context_path}")

    def cleanup_all(self) -> None:
        """Cleanup all isolated contexts."""
        # Copy keys to avoid modification during iteration
        paths = list(self._contexts.keys())
        for context_path in paths:
            self._cleanup_single_context(context_path)

        # Prune any stale worktree metadata and close Repo FDs
        for wm in self._worktree_managers.values():
            try:
                wm.prune()
            except Exception:
                pass
            try:
                wm.close()
            except Exception:
                pass

        self._worktree_managers.clear()
        log.info("Cleaned up all isolated contexts")

    def get_context_info(self, context_path: str) -> dict[str, Any] | None:
        """
        Get information about an isolated context.

        Args:
            context_path: Original context path

        Returns:
            Context info dict or None if not found
        """
        context_path = os.path.abspath(context_path)
        if context_path in self._contexts:
            ctx = self._contexts[context_path]
            return {
                "original_path": context_path,
                "isolated_path": ctx.get("isolated_path"),
                "mode": ctx.get("mode"),
                "agent_id": ctx.get("agent_id"),
                "repo_root": ctx.get("repo_root"),
                "branch_name": ctx.get("branch_name"),
                "base_ref": ctx.get("base_ref"),
                "scratch_path": ctx.get("scratch_path"),
            }
        return None

    def list_contexts(self) -> list[dict[str, Any]]:
        """
        List all active isolated contexts.

        Returns:
            List of context info dicts
        """
        return [self.get_context_info(path) for path in self._contexts.keys()]

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup all contexts."""
        self.cleanup_all()
        return False
