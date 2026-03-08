"""
Shadow repository management for isolated environments outside of git repos.
"""

import logging
import os
import shutil
import tempfile

from git import GitCommandError, Repo

from ..utils.git_utils import get_changes as git_get_changes

logger = logging.getLogger(__name__)


class ShadowRepo:
    """
    Creates and manages an isolated git repository for non-git context paths.
    This allows using git-based diffing and review even for plain directories.
    """

    def __init__(self, source_path: str, temp_base: str | None = None):
        """
        Initialize the ShadowRepo.

        Args:
            source_path: The directory to shadow
            temp_base: Optional base directory for the temporary shadow repo
        """
        self.source_path = os.path.abspath(source_path)
        if not os.path.isdir(self.source_path):
            raise ValueError(f"Source path {source_path} is not a directory")

        self.temp_dir = tempfile.mkdtemp(prefix="massgen_shadow_", dir=temp_base)
        self.repo: Repo | None = None
        self.is_initialized = False

    def initialize(self) -> str:
        """
        Initialize the shadow repository.
        Copies files from source and creates an initial commit.

        Returns:
            The path to the shadow repository
        """
        try:
            # 1. Initialize empty git repo
            self.repo = Repo.init(self.temp_dir)

            # Configure local user for the shadow repo
            with self.repo.config_writer() as config:
                config.set_value("user", "email", "massgen@example.com")
                config.set_value("user", "name", "MassGen")

            # 2. Copy files from source to temp_dir
            self._copy_source_files()

            # 3. Initial commit (if there are files)
            self.repo.git.add(A=True)

            if self.repo.is_dirty() or self.repo.untracked_files:
                self.repo.index.commit("initial state")

            self.is_initialized = True
            logger.info(f"Initialized shadow repo at {self.temp_dir} for {self.source_path}")
            return self.temp_dir

        except GitCommandError as e:
            logger.error(f"Failed to initialize shadow repo: {e.stderr}")
            self.cleanup()
            raise RuntimeError(f"Failed to initialize shadow repo: {e.stderr}")

    def get_changes(self) -> list[dict[str, str]]:
        """
        Get list of changes in the shadow repo since initial commit.

        Returns:
            List of dicts with 'status' and 'path' keys
        """
        if not self.is_initialized or not self.repo:
            return []
        return git_get_changes(self.repo)

    def get_diff(self, staged: bool = False) -> str:
        """
        Get the diff of changes in the shadow repo.

        Args:
            staged: If True, show staged changes only

        Returns:
            Git diff output as string
        """
        if not self.is_initialized or not self.repo:
            return ""

        try:
            if staged:
                return self.repo.git.diff("--staged")
            return self.repo.git.diff()
        except GitCommandError:
            return ""

    def close(self) -> None:
        """Close the underlying Repo object to release file descriptors."""
        if hasattr(self, "repo") and self.repo:
            self.repo.close()

    def cleanup(self) -> None:
        """Remove the shadow repository and all its contents."""
        self.close()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            logger.info(f"Cleaned up shadow repo at {self.temp_dir}")

    def _copy_source_files(self) -> None:
        """Copy files from source to temp_dir, skipping .git directories.

        Symlinks are preserved as symlinks (not followed) to prevent
        path traversal outside the source directory.
        """
        for item in os.listdir(self.source_path):
            if item == ".git":
                continue

            s = os.path.join(self.source_path, item)
            d = os.path.join(self.temp_dir, item)

            if os.path.isdir(s):
                shutil.copytree(s, d, symlinks=True, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
            else:
                shutil.copy2(s, d)

    def get_path(self) -> str:
        """Get the path to the shadow repository."""
        return self.temp_dir
