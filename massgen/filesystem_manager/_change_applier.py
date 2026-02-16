# -*- coding: utf-8 -*-
"""
Change Applier for MassGen - Applies changes from isolated context to original paths.

This module provides the ChangeApplier class for applying approved changes from
an isolated write context (worktree or shadow repo) to the original context path.
"""

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """Result from the change review process.

    Attributes:
        approved: Whether the user approved applying changes
        approved_files: List of specific files to apply (None = all files)
        comments: Optional user comments about the review
        metadata: Optional additional metadata from the review
        action: The user's chosen action (approve, reject, cancel, rework, quick_fix)
        feedback: Optional feedback text for rework/quick_fix actions
    """

    approved: bool
    approved_files: Optional[List[str]] = None
    comments: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)
    action: str = "approve"
    feedback: Optional[str] = None


class ChangeApplier:
    """Applies approved changes from isolated context to original paths.

    This class handles the transfer of changes from an isolated write context
    (git worktree or shadow repository) back to the original context path,
    respecting user approval decisions on a per-file basis.
    """

    def apply_changes(
        self,
        source_path: str,
        target_path: str,
        approved_files: Optional[List[str]] = None,
        approved_hunks: Optional[Dict[str, List[int]]] = None,
        context_prefix: Optional[str] = None,
        base_ref: Optional[str] = None,
        blocked_files: Optional[List[str]] = None,
        combined_diff: Optional[str] = None,
    ) -> List[str]:
        """
        Apply changes from source (isolated) to target (original).

        Args:
            source_path: Isolated context path (worktree or shadow repo)
            target_path: Original context path
            approved_files: List of relative paths to apply (None = all changes)
            approved_hunks: Optional mapping of file path -> approved hunk indexes
                (0-based). Keys may be repo-relative or context-relative paths.
            context_prefix: Optional repo-relative path prefix that constrains
                which changed files are eligible to apply. Use this to enforce
                context-path boundaries when source is a full repo checkout.
            base_ref: Optional git ref/commit SHA used as the baseline for
                committed changes. When provided, committed-only deltas between
                base_ref and HEAD are eligible for apply.
            blocked_files: Optional file paths to skip applying (for example,
                drifted target files detected since baseline capture).
            combined_diff: Optional unified diff text for all changes. Required
                for selective hunk apply. When omitted, file-level apply is used.

        Returns:
            List of applied file paths (relative to target)
        """
        source = Path(source_path)
        target = Path(target_path)
        applied: List[str] = []

        if not source.exists():
            log.warning(f"Source path does not exist: {source_path}")
            return applied

        if not target.exists():
            log.warning(f"Target path does not exist: {target_path}")
            return applied

        try:
            # Try to use git to get accurate change list
            applied = self._apply_git_changes(
                source,
                target,
                approved_files,
                approved_hunks=approved_hunks,
                context_prefix=context_prefix,
                base_ref=base_ref,
                blocked_files=blocked_files,
                combined_diff=combined_diff,
            )
        except Exception as e:
            log.warning(f"Git-based change detection failed: {e}, falling back to file comparison")
            # Fallback to file comparison if git fails
            applied = self._apply_file_changes(
                source,
                target,
                approved_files,
                approved_hunks=approved_hunks,
                context_prefix=context_prefix,
                blocked_files=blocked_files,
            )

        return applied

    def _apply_git_changes(
        self,
        source: Path,
        target: Path,
        approved_files: Optional[List[str]],
        approved_hunks: Optional[Dict[str, List[int]]] = None,
        context_prefix: Optional[str] = None,
        base_ref: Optional[str] = None,
        blocked_files: Optional[List[str]] = None,
        combined_diff: Optional[str] = None,
    ) -> List[str]:
        """Apply changes using git diff detection."""
        from git import InvalidGitRepositoryError, Repo

        applied: List[str] = []

        try:
            repo = Repo(str(source))
        except InvalidGitRepositoryError:
            raise ValueError(f"Source is not a git repository: {source}")

        changed_files = self._collect_git_changed_files(repo, base_ref=base_ref)
        normalized_prefix = self._normalize_context_prefix(context_prefix)
        parsed_diffs = self._parse_per_file_diffs(combined_diff or "")

        # Apply each change
        for rel_path, change_type in changed_files.items():
            # Skip .git and .massgen_scratch paths (matches _apply_file_changes filter)
            norm_parts = rel_path.replace("\\", "/").split("/")
            if ".git" in norm_parts or ".massgen_scratch" in norm_parts:
                continue

            mapped_path = self._map_context_path(rel_path, normalized_prefix)
            if mapped_path is None:
                log.debug(f"Skipping file outside context prefix '{normalized_prefix}': {rel_path}")
                continue

            # Filter by approved files if specified
            if not self._is_approved_path(
                repo_relative_path=rel_path,
                context_relative_path=mapped_path,
                approved_files=approved_files,
            ):
                log.debug(f"Skipping unapproved file: {rel_path}")
                continue
            if self._is_blocked_path(
                repo_relative_path=rel_path,
                context_relative_path=mapped_path,
                blocked_files=blocked_files,
            ):
                log.debug(f"Skipping blocked file: {rel_path}")
                continue

            selected_hunks = self._resolve_approved_hunks(
                repo_relative_path=rel_path,
                context_relative_path=mapped_path,
                approved_hunks=approved_hunks,
            )
            if selected_hunks is not None:
                if not selected_hunks:
                    log.debug(f"Skipping file with zero approved hunks: {rel_path}")
                    continue

                partial_result = self._apply_selected_hunks_for_file(
                    target=target,
                    target_relative_path=mapped_path,
                    change_type=change_type,
                    selected_hunks=selected_hunks,
                    file_diff=self._find_file_diff(rel_path, parsed_diffs),
                )
                if partial_result == "applied":
                    applied_path = mapped_path or str(target.name)
                    applied.append(applied_path)
                    log.info(f"Applied selective hunks: {applied_path} (hunks={selected_hunks})")
                    continue
                if partial_result == "skipped":
                    log.warning(f"Skipped file because selected hunks could not be applied: {rel_path}")
                    continue

            src_file = source / rel_path
            dst_file = target / mapped_path if mapped_path else target

            try:
                if change_type in ("M", "A", "R", "C"):  # Modified, Added, Renamed, Copied
                    if src_file.exists():
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_file, dst_file)
                        applied_path = mapped_path or str(target.name)
                        applied.append(applied_path)
                        log.info(f"Applied {change_type}: {applied_path}")
                    else:
                        log.warning(f"Source file missing for {change_type}: {rel_path}")

                elif change_type == "D":  # Deleted
                    if dst_file.exists():
                        dst_file.unlink()
                        applied_path = mapped_path or str(target.name)
                        applied.append(applied_path)
                        log.info(f"Applied D: {applied_path}")
                    else:
                        log.debug(f"File already deleted: {mapped_path or str(target.name)}")

            except Exception as e:
                log.error(f"Failed to apply change for {rel_path}: {e}")

        return applied

    def _apply_file_changes(
        self,
        source: Path,
        target: Path,
        approved_files: Optional[List[str]],
        approved_hunks: Optional[Dict[str, List[int]]] = None,
        context_prefix: Optional[str] = None,
        blocked_files: Optional[List[str]] = None,
    ) -> List[str]:
        """Fallback: Apply changes by comparing file contents."""
        applied: List[str] = []
        normalized_prefix = self._normalize_context_prefix(context_prefix)

        # Walk source directory and compare with target
        for src_file in source.rglob("*"):
            if src_file.is_file():
                # Skip .git directory and .massgen_scratch
                if ".git" in src_file.parts:
                    continue
                if ".massgen_scratch" in src_file.parts:
                    continue

                rel_path = str(src_file.relative_to(source))
                mapped_path = self._map_context_path(rel_path, normalized_prefix)
                if mapped_path is None:
                    continue

                # Filter by approved files if specified
                if not self._is_approved_path(
                    repo_relative_path=rel_path,
                    context_relative_path=mapped_path,
                    approved_files=approved_files,
                ):
                    continue
                if self._is_blocked_path(
                    repo_relative_path=rel_path,
                    context_relative_path=mapped_path,
                    blocked_files=blocked_files,
                ):
                    continue
                # Hunk-level apply requires a unified diff, which isn't available
                # in file-comparison fallback mode. Defer to file-level filtering.
                if (
                    self._resolve_approved_hunks(
                        repo_relative_path=rel_path,
                        context_relative_path=mapped_path,
                        approved_hunks=approved_hunks,
                    )
                    == []
                ):
                    continue

                dst_file = target / mapped_path if mapped_path else target

                try:
                    # Check if file is new or modified
                    should_copy = False
                    if not dst_file.exists():
                        should_copy = True
                    else:
                        # Compare contents
                        src_content = src_file.read_bytes()
                        dst_content = dst_file.read_bytes()
                        if src_content != dst_content:
                            should_copy = True

                    if should_copy:
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_file, dst_file)
                        applied_path = mapped_path or str(target.name)
                        applied.append(applied_path)
                        log.info(f"Applied change: {applied_path}")

                except Exception as e:
                    log.error(f"Failed to apply {rel_path}: {e}")

        return applied

    @staticmethod
    def _normalize_context_prefix(context_prefix: Optional[str]) -> Optional[str]:
        """Normalize repo-relative context prefix for path filtering."""
        if context_prefix is None:
            return None
        normalized = context_prefix.replace("\\", "/").strip("/")
        if normalized in ("", "."):
            return None
        return normalized

    @staticmethod
    def _map_context_path(rel_path: str, context_prefix: Optional[str]) -> Optional[str]:
        """Map repo-relative path to context-relative path, or None if out of scope."""
        normalized_rel = rel_path.replace("\\", "/").strip("/")
        if not context_prefix:
            return normalized_rel

        if normalized_rel == context_prefix:
            return ""

        prefix_with_sep = f"{context_prefix}/"
        if not normalized_rel.startswith(prefix_with_sep):
            return None

        return normalized_rel[len(prefix_with_sep) :]

    @staticmethod
    def _is_approved_path(
        repo_relative_path: str,
        context_relative_path: str,
        approved_files: Optional[List[str]],
    ) -> bool:
        """Check whether a changed file is included in the approved set."""
        if approved_files is None:
            return True
        return repo_relative_path in approved_files or context_relative_path in approved_files

    @staticmethod
    def _is_blocked_path(
        repo_relative_path: str,
        context_relative_path: str,
        blocked_files: Optional[List[str]],
    ) -> bool:
        """Check whether a changed file is explicitly blocked from apply."""
        if not blocked_files:
            return False
        return repo_relative_path in blocked_files or context_relative_path in blocked_files

    @staticmethod
    def _resolve_approved_hunks(
        repo_relative_path: str,
        context_relative_path: str,
        approved_hunks: Optional[Dict[str, List[int]]],
    ) -> Optional[List[int]]:
        """Resolve approved hunks for a file path.

        Returns:
            None when no hunk-level selection applies to this file.
            [] when explicitly no hunks are approved.
            [idx, ...] for approved hunk indexes (0-based).
        """
        if approved_hunks is None:
            return None

        selected = approved_hunks.get(repo_relative_path)
        if selected is None:
            selected = approved_hunks.get(context_relative_path)
        if selected is None:
            return None

        normalized: List[int] = []
        for idx in selected:
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                continue
            if idx_int >= 0:
                normalized.append(idx_int)
        return sorted(set(normalized))

    @staticmethod
    def _parse_per_file_diffs(combined_diff: str) -> Dict[str, str]:
        """Parse a combined unified diff into file-scoped diff chunks."""
        if not combined_diff or not combined_diff.strip():
            return {}

        parsed: Dict[str, str] = {}
        sections = re.split(r"(?=^diff --git )", combined_diff, flags=re.MULTILINE)
        for section in sections:
            section = section.strip()
            if not section.startswith("diff --git"):
                continue
            match = re.match(r"diff --git a/(.*?) b/(.*?)$", section, re.MULTILINE)
            if not match:
                continue
            file_a = match.group(1)
            file_b = match.group(2)
            parsed[file_b] = section
            if file_a != file_b:
                parsed[file_a] = section
        return parsed

    @staticmethod
    def _find_file_diff(
        file_path: str,
        parsed_diffs: Dict[str, str],
    ) -> Optional[str]:
        """Find a file's diff text from parsed diff sections."""
        if file_path in parsed_diffs:
            return parsed_diffs[file_path]

        file_name = Path(file_path).name
        for diff_path, diff_text in parsed_diffs.items():
            if Path(diff_path).name == file_name:
                return diff_text

        for diff_path, diff_text in parsed_diffs.items():
            if diff_path.endswith(file_path) or file_path.endswith(diff_path):
                return diff_text

        return None

    @staticmethod
    def _parse_hunks(file_diff: str) -> List[Dict[str, Any]]:
        """Parse unified diff hunks for a single file diff."""
        if not file_diff:
            return []

        hunks: List[Dict[str, Any]] = []
        current: Optional[Dict[str, Any]] = None

        for line in file_diff.splitlines(keepends=True):
            if line.startswith("@@"):
                if current is not None:
                    hunks.append(current)
                current = {
                    "header": line.rstrip("\n"),
                    "lines": [],
                }
                continue

            if current is None:
                continue

            if line.startswith("\\ No newline at end of file"):
                continue

            if line[:1] in {" ", "+", "-"}:
                current["lines"].append(line)

        if current is not None:
            hunks.append(current)

        return hunks

    @staticmethod
    def _find_subsequence(lines: List[str], needle: List[str], start: int = 0) -> Optional[int]:
        """Find the starting index of needle in lines from start."""
        if not needle:
            return start if start <= len(lines) else None

        max_start = len(lines) - len(needle)
        for idx in range(max(0, start), max_start + 1):
            if lines[idx : idx + len(needle)] == needle:
                return idx
        return None

    def _apply_selected_hunks_for_file(
        self,
        target: Path,
        target_relative_path: str,
        change_type: str,
        selected_hunks: List[int],
        file_diff: Optional[str],
    ) -> str:
        """Apply selected hunks for a single modified file.

        Returns:
            "applied": selected hunks were applied successfully
            "fallback": caller should continue with full-file apply
            "skipped": selected-hunk apply failed; skip file for safety
        """
        if change_type != "M":
            return "fallback"
        if not file_diff:
            return "fallback"

        hunks = self._parse_hunks(file_diff)
        if not hunks:
            return "fallback"

        selected = sorted({idx for idx in selected_hunks if 0 <= idx < len(hunks)})
        if not selected:
            return "skipped"
        if len(selected) == len(hunks):
            return "fallback"

        target_file = target / target_relative_path if target_relative_path else target
        if not target_file.exists() or not target_file.is_file():
            return "skipped"

        try:
            target_lines = target_file.read_text().splitlines(keepends=True)
        except Exception:
            return "skipped"

        search_start = 0
        for hunk_idx in selected:
            hunk = hunks[hunk_idx]
            hunk_lines: List[str] = hunk.get("lines", [])
            old_block = [line[1:] for line in hunk_lines if line[:1] in {" ", "-"}]
            new_block = [line[1:] for line in hunk_lines if line[:1] in {" ", "+"}]

            match_index = self._find_subsequence(target_lines, old_block, start=search_start)
            if match_index is None:
                match_index = self._find_subsequence(target_lines, old_block, start=0)
            if match_index is None:
                return "skipped"

            target_lines = target_lines[:match_index] + new_block + target_lines[match_index + len(old_block) :]
            search_start = match_index + len(new_block)

        target_file.write_text("".join(target_lines))
        return "applied"

    @staticmethod
    def _collect_git_changed_files(repo, base_ref: Optional[str] = None) -> Dict[str, str]:
        """Collect committed, staged, unstaged, and untracked changes."""
        changed_files: Dict[str, str] = {}  # path -> change_type (M, A, D, R, C)

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
                    changed_files[rel_path] = status

        if base_ref:
            try:
                _record_name_status(repo.git.diff("--name-status", base_ref, "HEAD"))
            except Exception as e:
                log.warning("Failed to diff base_ref %s against HEAD: %s", base_ref, e)

        try:
            _record_name_status(repo.git.diff("--name-status", "--cached"))
        except Exception:
            pass

        try:
            _record_name_status(repo.git.diff("--name-status"))
        except Exception:
            pass

        for rel_path in repo.untracked_files:
            changed_files[rel_path] = "A"  # Treat untracked as added

        return changed_files

    def detect_target_drift(
        self,
        source_path: str,
        target_path: str,
        base_ref: Optional[str],
        approved_files: Optional[List[str]] = None,
        context_prefix: Optional[str] = None,
    ) -> List[str]:
        """Return changed files whose current target content drifted from baseline."""
        if not base_ref:
            return []

        source = Path(source_path)
        target = Path(target_path)
        if not source.exists() or not target.exists():
            return []

        from git import InvalidGitRepositoryError, Repo

        try:
            repo = Repo(str(source))
        except InvalidGitRepositoryError:
            return []

        normalized_prefix = self._normalize_context_prefix(context_prefix)
        changed_files = self._collect_git_changed_files(repo, base_ref=base_ref)
        baseline_tree = repo.commit(base_ref).tree
        drifted: set[str] = set()

        for rel_path in changed_files:
            norm_parts = rel_path.replace("\\", "/").split("/")
            if ".git" in norm_parts or ".massgen_scratch" in norm_parts:
                continue

            mapped_path = self._map_context_path(rel_path, normalized_prefix)
            if mapped_path is None:
                continue

            if not self._is_approved_path(
                repo_relative_path=rel_path,
                context_relative_path=mapped_path,
                approved_files=approved_files,
            ):
                continue

            baseline_bytes: Optional[bytes]
            try:
                baseline_blob = baseline_tree / rel_path
                baseline_bytes = baseline_blob.data_stream.read()
            except Exception:
                baseline_bytes = None

            target_file = target / mapped_path if mapped_path else target
            target_bytes: Optional[bytes]
            if target_file.exists() and target_file.is_file():
                target_bytes = target_file.read_bytes()
            elif target_file.exists():
                target_bytes = b"__MASSGEN_NON_FILE__"
            else:
                target_bytes = None

            if target_bytes != baseline_bytes:
                drifted.add(mapped_path or rel_path)

        return sorted(drifted)

    def get_changes_summary(
        self,
        source_path: str,
    ) -> Dict[str, List[str]]:
        """
        Get a summary of changes in the isolated context.

        Args:
            source_path: Isolated context path

        Returns:
            Dict with keys 'modified', 'added', 'deleted' containing file lists
        """
        source = Path(source_path)
        summary: Dict[str, List[str]] = {
            "modified": [],
            "added": [],
            "deleted": [],
        }

        if not source.exists():
            return summary

        try:
            from git import InvalidGitRepositoryError, Repo

            repo = Repo(str(source))

            # Unstaged changes
            for diff in repo.index.diff(None):
                rel_path = diff.a_path or diff.b_path
                if rel_path:
                    change_type = diff.change_type[0].upper()
                    if change_type == "M":
                        summary["modified"].append(rel_path)
                    elif change_type == "D":
                        summary["deleted"].append(rel_path)
                    elif change_type == "A":
                        summary["added"].append(rel_path)

            # Untracked files
            for rel_path in repo.untracked_files:
                summary["added"].append(rel_path)

        except InvalidGitRepositoryError:
            log.warning(f"Not a git repository: {source_path}")
        except Exception as e:
            log.error(f"Failed to get changes summary: {e}")

        return summary


__all__ = [
    "ChangeApplier",
    "ReviewResult",
]
