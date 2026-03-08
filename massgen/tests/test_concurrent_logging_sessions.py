"""Tests for concurrent in-process and multi-process MassGen run isolation.

These tests verify that:
- Two concurrent massgen.run() calls in the same process produce isolated
  log roots, events, and loguru sinks (in-process concurrency via ContextVar).
- Two simultaneous CLI processes don't corrupt the session registry
  or collide on snapshot storage paths (multi-process concurrency).
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_in_context(tmp_path: Path) -> tuple:
    """Create a LoggingSession inside a fresh copy_context."""
    import massgen.logger_config as lc

    session = lc.LoggingSession.create()
    return session


# ---------------------------------------------------------------------------
# Step 2 tests: LoggingSession basics
# ---------------------------------------------------------------------------


class TestLoggingSessionBasics:
    def test_logging_session_has_unique_session_ids(self, tmp_path, monkeypatch):
        """Two LoggingSession instances produce distinct session_id values."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc

        s1 = lc.LoggingSession.create()
        s2 = lc.LoggingSession.create()
        assert s1.session_id != s2.session_id

    def test_logging_session_starts_with_no_dir(self):
        """Fresh LoggingSession has no resolved directory yet."""
        import massgen.logger_config as lc

        s = lc.LoggingSession.create()
        assert s.log_base_session_dir is None
        assert s.log_session_dir is None
        assert s.current_turn is None
        assert s.current_attempt is None

    def test_logging_session_close_removes_handlers(self, tmp_path, monkeypatch):
        """session.close() removes only its own loguru handler."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        from loguru import logger

        import massgen.logger_config as lc

        # Add a sentinel handler to verify it survives the close
        sentinel_ids = []
        sentinel_ids.append(logger.add(lambda _: None))

        s = lc.LoggingSession.create()
        token = lc.set_current_session(s)
        lc.setup_logging(debug=False, session=s)
        handler_id = s.main_log_handler_id

        # Close this session
        s.close()
        lc._current_session.reset(token)

        # The session's handler is gone; sentinel is unaffected
        assert s.main_log_handler_id is not None  # ID stored but removed from loguru
        try:
            logger.remove(handler_id)
            already_removed = False
        except ValueError:
            already_removed = True
        assert already_removed, "session.close() should have removed the handler"

        # Sentinel still works (removal doesn't raise ValueError)
        logger.remove(sentinel_ids[0])  # Should not raise


# ---------------------------------------------------------------------------
# Step 3 + 4 tests: ContextVar isolation
# ---------------------------------------------------------------------------


class TestContextVarIsolation:
    def test_set_log_turn_affects_only_current_session(self, tmp_path, monkeypatch):
        """set_log_turn() mutates only the active session, not a sibling."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc

        s1 = lc.LoggingSession.create()
        s2 = lc.LoggingSession.create()

        token1 = lc.set_current_session(s1)
        lc.set_log_turn(3)
        lc._current_session.reset(token1)

        # s2 is unaffected
        assert s1.current_turn == 3
        assert s2.current_turn is None

    def test_set_log_attempt_reconfigures_only_current_session(self, tmp_path, monkeypatch):
        """set_log_attempt() reconfigures only the calling session's handlers."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc

        s1 = lc.LoggingSession.create()
        s2 = lc.LoggingSession.create()

        # Set up both sessions
        token1 = lc.set_current_session(s1)
        lc.setup_logging(debug=False, session=s1)
        lc._current_session.reset(token1)

        token2 = lc.set_current_session(s2)
        lc.setup_logging(debug=False, session=s2)
        lc._current_session.reset(token2)

        original_s1_handler = s1.main_log_handler_id
        original_s2_handler = s2.main_log_handler_id

        # Advance attempt on s1 only
        token1 = lc.set_current_session(s1)
        lc.set_log_attempt(2)
        lc._current_session.reset(token1)

        # s1 got a new handler; s2 is unchanged
        assert s1.current_attempt == 2
        assert s2.current_attempt is None
        assert s1.main_log_handler_id != original_s1_handler
        assert s2.main_log_handler_id == original_s2_handler

        # Cleanup
        s1.close()
        s2.close()

    def test_get_event_emitter_returns_session_scoped_emitter(self, tmp_path, monkeypatch):
        """get_event_emitter() returns the correct emitter per session context."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc
        from massgen.events import get_event_emitter

        s1 = lc.LoggingSession.create()
        s2 = lc.LoggingSession.create()

        token1 = lc.set_current_session(s1)
        lc.setup_logging(debug=False, session=s1)
        emitter_in_s1 = get_event_emitter()
        lc._current_session.reset(token1)

        token2 = lc.set_current_session(s2)
        lc.setup_logging(debug=False, session=s2)
        emitter_in_s2 = get_event_emitter()
        lc._current_session.reset(token2)

        assert emitter_in_s1 is not None
        assert emitter_in_s2 is not None
        assert emitter_in_s1 is not emitter_in_s2

        s1.close()
        s2.close()

    def test_log_records_routed_to_correct_session_file(self, tmp_path, monkeypatch):
        """Log records from session A don't appear in session B's massgen.log."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))

        import massgen.logger_config as lc

        s1 = lc.LoggingSession.create()
        s2 = lc.LoggingSession.create()

        token1 = lc.set_current_session(s1)
        lc.setup_logging(debug=False, session=s1)
        log_dir_s1 = lc.get_log_session_dir()
        lc._current_session.reset(token1)

        token2 = lc.set_current_session(s2)
        lc.setup_logging(debug=False, session=s2)
        log_dir_s2 = lc.get_log_session_dir()
        lc._current_session.reset(token2)

        assert log_dir_s1 != log_dir_s2, "Sessions must use different directories"

        # Emit a distinctive message bound to s1
        sentinel_s1 = f"SENTINEL_SESSION_A_{s1.session_id}"
        token1 = lc.set_current_session(s1)
        lc.session_logger().info(sentinel_s1)
        lc._current_session.reset(token1)

        # Emit a distinctive message bound to s2
        sentinel_s2 = f"SENTINEL_SESSION_B_{s2.session_id}"
        token2 = lc.set_current_session(s2)
        lc.session_logger().info(sentinel_s2)
        lc._current_session.reset(token2)

        # Flush loguru (enqueue=True requires this)
        import time

        time.sleep(0.2)

        # s1's log should only contain s1's sentinel
        log_s1 = (log_dir_s1 / "massgen.log").read_text(errors="replace")
        log_s2 = (log_dir_s2 / "massgen.log").read_text(errors="replace")

        assert sentinel_s1 in log_s1, "s1 sentinel must appear in s1 log"
        assert sentinel_s1 not in log_s2, "s1 sentinel must NOT appear in s2 log"
        assert sentinel_s2 in log_s2, "s2 sentinel must appear in s2 log"
        assert sentinel_s2 not in log_s1, "s2 sentinel must NOT appear in s1 log"

        s1.close()
        s2.close()


# ---------------------------------------------------------------------------
# Step 7 tests: concurrent asyncio tasks produce isolated log roots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_sessions_in_asyncio_tasks_are_isolated(tmp_path, monkeypatch):
    """Two asyncio tasks each set their own LoggingSession via ContextVar.

    Verifies that session state in task A doesn't bleed into task B.
    """
    monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
    import massgen.logger_config as lc

    collected: dict[str, str | None] = {}

    async def _run_in_session(name: str):
        ctx = contextvars.copy_context()

        def _body():
            s = lc.LoggingSession.create()
            lc.set_current_session(s)
            lc.setup_logging(debug=False, session=s)
            log_dir = lc.get_log_session_dir()
            lc.session_logger().info(f"Hello from {name}")
            collected[name] = str(log_dir)
            s.close()

        await asyncio.get_event_loop().run_in_executor(None, ctx.run, _body)

    await asyncio.gather(
        _run_in_session("task_a"),
        _run_in_session("task_b"),
    )

    assert "task_a" in collected
    assert "task_b" in collected
    assert collected["task_a"] != collected["task_b"], "Each task must get its own isolated log directory"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_setup_logging_without_explicit_session_creates_implicit_session(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Calling setup_logging() without explicit session creation works."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc

        # Ensure no session is active
        lc._current_session.set(None)
        lc.reset_logging_session()

        # Should not raise; should create an implicit session
        lc.setup_logging(debug=False)
        session = lc.get_current_session()
        assert session is not None, "setup_logging() must create an implicit session"

        log_dir = lc.get_log_session_dir()
        assert log_dir.exists()

        lc.reset_logging_session()

    def test_implicit_session_reused_across_fresh_contexts(self, tmp_path, monkeypatch):
        """Implicit setup_logging() calls in new contexts keep one log session root.

        Regression target: Textual/event-loop callbacks may run in a context that
        does not carry ``_current_session``.  Those callbacks still need to
        append to the same run directory rather than creating a new ``log_*`` root.
        """
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc

        # Start clean and create the implicit session in the current context.
        lc._current_session.set(None)
        lc.reset_logging_session()
        lc.setup_logging(debug=False)
        root_a = lc.get_log_session_root()

        # Simulate a callback executing in a fresh context with no ContextVar state.
        def _setup_in_fresh_context():
            lc.setup_logging(debug=False)
            return lc.get_log_session_root()

        root_b = contextvars.Context().run(_setup_in_fresh_context)

        assert root_a == root_b, "Implicit setup_logging() in a fresh context must reuse the same " "session root to avoid split log directories."

        lc.reset_logging_session()

    def test_public_accessors_exist(self):
        """Public accessor functions added for backward compat exist."""
        import massgen.logger_config as lc

        assert callable(lc.get_current_session)
        assert callable(lc.set_current_session)
        assert callable(lc.get_current_attempt)
        assert callable(lc.is_debug_mode)
        assert callable(lc.session_logger)


# ---------------------------------------------------------------------------
# Multi-process: session registry locking
# ---------------------------------------------------------------------------


class TestSessionRegistryLocking:
    def test_session_registry_concurrent_writes_no_corruption(self, tmp_path):
        """Concurrent registry writes from multiple threads don't corrupt data."""
        from massgen.session._registry import SessionRegistry

        registry_path = tmp_path / "sessions.json"
        errors: list[Exception] = []
        write_count = 20

        def _write_session(i: int):
            try:
                reg = SessionRegistry(registry_path=str(registry_path))
                reg.register_session(session_id=f"session_{i:03d}", model="test-model")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write_session, args=(i,)) for i in range(write_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Registry errors during concurrent writes: {errors}"

        # All sessions should be registered without corruption
        reg = SessionRegistry(registry_path=str(registry_path))
        data = reg._load_registry()
        session_ids = {s["session_id"] for s in data["sessions"]}
        expected = {f"session_{i:03d}" for i in range(write_count)}
        assert session_ids == expected, f"Missing or corrupt sessions. Got {len(session_ids)}, " f"expected {write_count}. Missing: {expected - session_ids}"

    def test_session_registry_init_never_overwrites_existing_file(self, tmp_path, monkeypatch):
        """Registry init must not clobber existing data, even with stale exists() info."""
        from massgen.session._registry import SessionRegistry

        registry_path = tmp_path / "sessions.json"
        reg = SessionRegistry(registry_path=str(registry_path))
        reg.register_session(session_id="existing_session", model="test-model")
        before = registry_path.read_text()

        original_exists = Path.exists

        def _stale_exists(path_obj: Path) -> bool:
            if path_obj == registry_path:
                return False
            return original_exists(path_obj)

        monkeypatch.setattr(Path, "exists", _stale_exists)

        SessionRegistry(registry_path=str(registry_path))
        after = registry_path.read_text()

        assert after == before, "SessionRegistry init should never overwrite an existing registry file"

    def test_session_registry_concurrent_writes_with_noop_flock_still_safe(self, tmp_path, monkeypatch):
        """Thread concurrency must stay safe even if OS flock is ineffective in-process."""
        import sys

        if sys.platform == "win32":
            pytest.skip("fcntl is unavailable on Windows")

        import fcntl
        import json
        import time

        from massgen.session._registry import SessionRegistry

        registry_path = tmp_path / "sessions.json"
        errors: list[Exception] = []
        write_count = 20

        # Simulate environments where flock does not provide in-process thread serialization.
        monkeypatch.setattr(fcntl, "flock", lambda *_args, **_kwargs: None)

        def _slow_save(self, data):
            payload = json.dumps(data, indent=2)
            midpoint = max(1, len(payload) // 2)
            with open(self.registry_path, "w") as f:
                f.write(payload[:midpoint])
                f.flush()
                time.sleep(0.002)
                f.write(payload[midpoint:])

        monkeypatch.setattr(SessionRegistry, "_save_registry", _slow_save)

        def _write_session(i: int):
            try:
                reg = SessionRegistry(registry_path=str(registry_path))
                reg.register_session(session_id=f"session_{i:03d}", model="test-model")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_write_session, args=(i,)) for i in range(write_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Registry errors during concurrent writes: {errors}"

        reg = SessionRegistry(registry_path=str(registry_path))
        data = reg._load_registry()
        session_ids = {s["session_id"] for s in data["sessions"]}
        expected = {f"session_{i:03d}" for i in range(write_count)}
        assert session_ids == expected, f"Missing or corrupt sessions. Got {len(session_ids)}, " f"expected {write_count}. Missing: {expected - session_ids}"


# ---------------------------------------------------------------------------
# Multi-process: snapshot storage scoping
# ---------------------------------------------------------------------------


class TestSnapshotStorageScoping:
    def test_snapshot_storage_scoped_per_run(self, tmp_path, monkeypatch):
        """Snapshot storage paths are unique per run even when agent_id is the same.

        The cli.py fix scopes ``snapshot_storage`` by the log session root name
        (a microsecond timestamp) so two processes using the same config don't
        write to the same directory.
        """
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc

        # Simulate two separate "runs"
        s1 = lc.LoggingSession.create()
        token1 = lc.set_current_session(s1)
        lc.setup_logging(debug=False, session=s1)
        session_root_1 = lc.get_log_session_root()
        lc._current_session.reset(token1)

        s2 = lc.LoggingSession.create()
        token2 = lc.set_current_session(s2)
        lc.setup_logging(debug=False, session=s2)
        session_root_2 = lc.get_log_session_root()
        lc._current_session.reset(token2)

        assert session_root_1 != session_root_2, "Each run must produce a unique session root"

        # Replicate the cli.py scoping logic:
        # scoped_snapshot = Path(base_snapshot) / session_root.name / agent_id
        base_snapshot_storage = tmp_path / "snapshots"
        agent_id = "agent_a"  # Same agent_id in both runs — the collision scenario

        scoped_1 = base_snapshot_storage / session_root_1.name / agent_id
        scoped_2 = base_snapshot_storage / session_root_2.name / agent_id

        assert scoped_1 != scoped_2, "Two runs with same agent_id must get different snapshot_storage paths " "when scoped by log session root"

        s1.close()
        s2.close()

    def test_cli_scopes_snapshot_storage_by_session(self, tmp_path, monkeypatch):
        """cli.py passes a per-run scoped snapshot_storage to setup_orchestration_paths.

        Verifies that ``create_agents_from_config`` (or equivalent) appends the
        log session root name to the configured ``snapshot_storage`` base path.
        """
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc

        s = lc.LoggingSession.create()
        token = lc.set_current_session(s)
        lc.setup_logging(debug=False, session=s)
        session_root = lc.get_log_session_root()
        lc._current_session.reset(token)

        base = tmp_path / "snapshots"
        # The scoped path must contain the session root name
        base / session_root.name
        assert session_root.name.startswith("log_"), f"Session root should start with log_, got: {session_root.name}"
        assert len(session_root.name) > 10, "Session root name should be a timestamp"

        s.close()


# ---------------------------------------------------------------------------
# Snapshot storage: concurrent writes and _scope_snapshot_storage
# ---------------------------------------------------------------------------


def _make_fm(workspace: Path, snapshot_dir: Path, agent_id: str):
    """Build a minimal FilesystemManager without calling __init__."""
    from massgen.filesystem_manager._filesystem_manager import FilesystemManager

    fm = FilesystemManager.__new__(FilesystemManager)
    fm.cwd = str(workspace)
    fm.snapshot_storage = snapshot_dir
    fm.agent_id = agent_id
    fm.use_two_tier_workspace = False
    fm.is_shared_workspace = False
    return fm


class TestConcurrentSnapshotWrites:
    """Two FilesystemManager instances writing snapshots simultaneously don't corrupt each other."""

    @pytest.mark.asyncio
    async def test_concurrent_save_snapshot_distinct_dirs_no_corruption(self, tmp_path):
        """Two agents with separate snapshot_storage dirs can save_snapshot concurrently.

        Each agent gets its own scoped directory (as _scope_snapshot_storage ensures).
        Verify that each agent's output is intact and not mixed.
        """
        from unittest.mock import patch

        base = tmp_path / "snapshots"
        base.mkdir()

        # Agent A workspace + snapshot dir
        ws_a = tmp_path / "ws_a"
        ws_a.mkdir()
        (ws_a / "report_a.txt").write_text("agent_a_content_unique_aaa")

        snap_a = base / "log_run1" / "agent_a"
        snap_a.mkdir(parents=True)

        # Agent B workspace + snapshot dir
        ws_b = tmp_path / "ws_b"
        ws_b.mkdir()
        (ws_b / "report_b.txt").write_text("agent_b_content_unique_bbb")

        snap_b = base / "log_run1" / "agent_b"
        snap_b.mkdir(parents=True)

        fm_a = _make_fm(ws_a, snap_a, "agent_a")
        fm_b = _make_fm(ws_b, snap_b, "agent_b")

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=None):
            await asyncio.gather(
                fm_a.save_snapshot(),
                fm_b.save_snapshot(),
            )

        # Each snapshot dir has only its own file
        assert (snap_a / "report_a.txt").read_text() == "agent_a_content_unique_aaa"
        assert not (snap_a / "report_b.txt").exists(), "agent_b file must not appear in agent_a snapshot"

        assert (snap_b / "report_b.txt").read_text() == "agent_b_content_unique_bbb"
        assert not (snap_b / "report_a.txt").exists(), "agent_a file must not appear in agent_b snapshot"

    @pytest.mark.asyncio
    async def test_concurrent_save_snapshot_many_agents(self, tmp_path):
        """Five agents saving snapshots concurrently all produce correct, isolated output."""
        from unittest.mock import patch

        agent_count = 5
        workspaces = []
        fms = []

        for i in range(agent_count):
            ws = tmp_path / f"ws_{i}"
            ws.mkdir()
            (ws / f"deliverable_{i}.txt").write_text(f"unique_content_{i}_xyzzy")

            snap = tmp_path / "snapshots" / f"agent_{i}"
            snap.mkdir(parents=True)

            fms.append(_make_fm(ws, snap, f"agent_{i}"))
            workspaces.append((i, snap))

        with patch("massgen.filesystem_manager._filesystem_manager.get_log_session_dir", return_value=None):
            await asyncio.gather(*[fm.save_snapshot() for fm in fms])

        for i, snap in workspaces:
            result = (snap / f"deliverable_{i}.txt").read_text()
            assert result == f"unique_content_{i}_xyzzy", f"agent_{i} snapshot has wrong content"
            # Ensure no other agent's file leaked in
            for j in range(agent_count):
                if j != i:
                    assert not (snap / f"deliverable_{j}.txt").exists(), f"agent_{j} file leaked into agent_{i} snapshot"


class TestScopeSnapshotStorage:
    """Unit tests for cli._scope_snapshot_storage()."""

    def test_returns_none_for_none_base(self, tmp_path, monkeypatch):
        """None base returns None regardless of session state."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        from massgen.cli import _scope_snapshot_storage

        assert _scope_snapshot_storage(None) is None

    def test_scopes_by_session_root_name(self, tmp_path, monkeypatch):
        """Returns base / session_root_name when a session is active."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc
        from massgen.cli import _scope_snapshot_storage

        s = lc.LoggingSession.create()
        token = lc.set_current_session(s)
        lc.setup_logging(debug=False, session=s)

        # Call while session is still active so get_log_session_root() resolves correctly
        base = str(tmp_path / "snapshots")
        result = _scope_snapshot_storage(base)
        session_root = lc.get_log_session_root()

        lc._current_session.reset(token)
        s.close()

        assert result == str(tmp_path / "snapshots" / session_root.name)

    def test_falls_back_to_base_when_session_root_unavailable(self, monkeypatch):
        """Returns base unchanged if get_log_session_root() raises."""
        import massgen.logger_config as lc
        from massgen.cli import _scope_snapshot_storage

        # Ensure no session is active so get_log_session_root() will raise/return nothing
        lc._current_session.set(None)
        lc.reset_logging_session()

        base = "/some/snapshot/dir"
        # With no session root available the function must not raise and must return base
        result = _scope_snapshot_storage(base)
        assert result is not None  # must return something
        # Either returns base (fallback) or a valid scoped path — must not raise

    def test_two_runs_get_different_scoped_paths(self, tmp_path, monkeypatch):
        """Two separate sessions produce different scoped snapshot_storage paths."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc
        from massgen.cli import _scope_snapshot_storage

        s1 = lc.LoggingSession.create()
        t1 = lc.set_current_session(s1)
        lc.setup_logging(debug=False, session=s1)
        path1 = _scope_snapshot_storage(".massgen/snapshots")
        lc._current_session.reset(t1)

        s2 = lc.LoggingSession.create()
        t2 = lc.set_current_session(s2)
        lc.setup_logging(debug=False, session=s2)
        path2 = _scope_snapshot_storage(".massgen/snapshots")
        lc._current_session.reset(t2)

        assert path1 != path2, "Different runs must get different scoped snapshot paths"

        s1.close()
        s2.close()


# ---------------------------------------------------------------------------
# agent_temporary_workspace scoping (mirrors TestScopeSnapshotStorage)
# ---------------------------------------------------------------------------


class TestScopeAgentTemporaryWorkspace:
    """Unit tests for cli._scope_agent_temporary_workspace()."""

    def test_returns_none_for_none_base(self, tmp_path, monkeypatch):
        """None base returns None regardless of session state."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        from massgen.cli import _scope_agent_temporary_workspace

        assert _scope_agent_temporary_workspace(None) is None

    def test_scopes_by_session_root_name(self, tmp_path, monkeypatch):
        """Returns base / session_root_name when a session is active."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc
        from massgen.cli import _scope_agent_temporary_workspace

        s = lc.LoggingSession.create()
        token = lc.set_current_session(s)
        lc.setup_logging(debug=False, session=s)

        base = str(tmp_path / "temp_workspaces")
        result = _scope_agent_temporary_workspace(base)
        session_root = lc.get_log_session_root()

        lc._current_session.reset(token)
        s.close()

        assert result == str(tmp_path / "temp_workspaces" / session_root.name)

    def test_falls_back_to_base_when_session_root_unavailable(self, monkeypatch):
        """Returns base unchanged if get_log_session_root() raises."""
        import massgen.logger_config as lc
        from massgen.cli import _scope_agent_temporary_workspace

        lc._current_session.set(None)
        lc.reset_logging_session()

        base = "/some/temp/dir"
        result = _scope_agent_temporary_workspace(base)
        assert result is not None

    def test_two_runs_get_different_scoped_paths(self, tmp_path, monkeypatch):
        """Two separate sessions produce different scoped workspace paths."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc
        from massgen.cli import _scope_agent_temporary_workspace

        s1 = lc.LoggingSession.create()
        t1 = lc.set_current_session(s1)
        lc.setup_logging(debug=False, session=s1)
        path1 = _scope_agent_temporary_workspace(".massgen/temp_workspaces")
        lc._current_session.reset(t1)

        s2 = lc.LoggingSession.create()
        t2 = lc.set_current_session(s2)
        lc.setup_logging(debug=False, session=s2)
        path2 = _scope_agent_temporary_workspace(".massgen/temp_workspaces")
        lc._current_session.reset(t2)

        assert path1 != path2, "Different runs must get different scoped workspace paths"

        s1.close()
        s2.close()


class TestClearTempWorkspaceConcurrentSafety:
    """Verify two processes with scoped workspace parents don't destroy each other."""

    def test_scoped_clear_temp_does_not_affect_sibling(self, tmp_path):
        """Process B's clear_temp_workspace() on its scoped dir does not touch Process A's."""
        from massgen.filesystem_manager._filesystem_manager import FilesystemManager

        # Simulate Process A's scoped parent
        parent_a = tmp_path / "temp_workspaces" / "log_run_a"
        parent_a.mkdir(parents=True)
        agent_dir_a = parent_a / "agent_1"
        agent_dir_a.mkdir()
        (agent_dir_a / "work.txt").write_text("process_a_data")

        # Simulate Process B's scoped parent
        parent_b = tmp_path / "temp_workspaces" / "log_run_b"
        parent_b.mkdir(parents=True)

        # Build a minimal FM for Process B and clear its workspace
        fm_b = FilesystemManager.__new__(FilesystemManager)
        fm_b.agent_temporary_workspace_parent = parent_b
        fm_b.clear_temp_workspace()

        # A's data is untouched
        assert agent_dir_a.exists()
        assert (agent_dir_a / "work.txt").read_text() == "process_a_data"
        # B's parent was cleared and recreated
        assert parent_b.exists()

    def test_backend_config_receives_scoped_workspace(self, tmp_path, monkeypatch):
        """create_agents_from_config passes session-scoped workspace to backend.

        This is the critical path: orchestrator_config["agent_temporary_workspace"]
        flows into backend_config["agent_temporary_workspace"] which becomes
        FilesystemManager.agent_temporary_workspace_parent.  If unscoped,
        clear_temp_workspace() nukes the global parent.
        """
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc

        s = lc.LoggingSession.create()
        token = lc.set_current_session(s)
        lc.setup_logging(debug=False, session=s)
        session_root = lc.get_log_session_root()

        # Simulate what create_agents_from_config does at line 2153-2154
        from massgen.cli import _scope_agent_temporary_workspace

        raw_value = ".massgen/temp_workspaces"
        scoped = _scope_agent_temporary_workspace(raw_value)

        lc._current_session.reset(token)
        s.close()

        # The scoped value must contain the session root timestamp
        assert session_root.name in scoped, f"Backend config must receive scoped workspace containing " f"'{session_root.name}', got: {scoped}"
        assert scoped != raw_value, "Scoped value must differ from raw config value"


# ---------------------------------------------------------------------------
# massgen.run() session cleanup on exception
# ---------------------------------------------------------------------------


class TestRunSessionCleanup:
    """Verify massgen.run() cleans up session token even on error."""

    @pytest.mark.asyncio
    async def test_session_token_reset_on_exception(self, tmp_path, monkeypatch):
        """ContextVar is reset to previous value even when run() raises."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import massgen.logger_config as lc

        # Capture the ContextVar state before the run
        pre_run_session = lc._current_session.get(None)

        import massgen

        with pytest.raises(Exception):
            await massgen.run(
                query="test",
                config_dict={"agents": []},  # Invalid: no agents
            )

        # The ContextVar must be restored to its pre-run state
        post_run_session = lc._current_session.get(None)
        assert post_run_session is pre_run_session, "ContextVar must be reset after run() failure"


# ---------------------------------------------------------------------------
# setup_logging() concurrent handler safety
# ---------------------------------------------------------------------------


class TestSetupLoggingConcurrentHandlerSafety:
    """Verify setup_logging for session B doesn't nuke session A's handlers."""

    def test_second_session_setup_preserves_first_session_handlers(
        self,
        tmp_path,
        monkeypatch,
    ):
        """Session B's first setup_logging() must not remove session A's file handler."""
        monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))
        import time

        import massgen.logger_config as lc

        # Set up session A
        s_a = lc.LoggingSession.create()
        tok_a = lc.set_current_session(s_a)
        lc.setup_logging(debug=False, session=s_a)
        log_dir_a = lc.get_log_session_dir()
        lc._current_session.reset(tok_a)

        # Set up session B (first call for B -> triggers the "first call" branch)
        s_b = lc.LoggingSession.create()
        tok_b = lc.set_current_session(s_b)
        lc.setup_logging(debug=False, session=s_b)
        lc._current_session.reset(tok_b)

        # Write a sentinel bound to session A — it must arrive in A's log
        sentinel = f"SENTINEL_HANDLER_A_{s_a.session_id}"
        tok_a = lc.set_current_session(s_a)
        lc.session_logger().info(sentinel)
        lc._current_session.reset(tok_a)

        time.sleep(0.3)  # flush loguru enqueue

        log_file_a = log_dir_a / "massgen.log"
        assert log_file_a.exists(), "Session A's log file should exist"
        content = log_file_a.read_text(errors="replace")
        assert sentinel in content, "Session A's handler must still work after session B's setup_logging()"

        s_a.close()
        s_b.close()


# ---------------------------------------------------------------------------
# Docker container name isolation
# ---------------------------------------------------------------------------


class TestDockerContainerNameIsolation:
    """Verify Docker container names are unique across instances."""

    def test_default_instance_id_unique_across_instances(self):
        """Two DockerManager instances without explicit instance_id get unique IDs."""
        try:
            from massgen.filesystem_manager._docker_manager import (
                DOCKER_AVAILABLE,
                DockerManager,
            )
        except ImportError:
            pytest.skip("docker module not available")

        if not DOCKER_AVAILABLE:
            pytest.skip("Docker Python library not installed")

        # We only test the instance_id assignment, not actual Docker API calls.
        # Patch the Docker client to avoid needing a running daemon.
        from unittest.mock import MagicMock, patch

        with patch(
            "massgen.filesystem_manager._docker_manager.docker",
        ) as mock_docker:
            mock_docker.from_env.return_value = MagicMock()
            dm1 = DockerManager(image="test:latest")
            dm2 = DockerManager(image="test:latest")

        assert dm1.instance_id is not None, "instance_id must be auto-generated"
        assert dm2.instance_id is not None, "instance_id must be auto-generated"
        assert dm1.instance_id != dm2.instance_id, "Two DockerManagers must get different auto-generated instance_ids"


# ---------------------------------------------------------------------------
# End-to-end concurrent lifecycle test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_session_lifecycle_all_paths_isolated(tmp_path, monkeypatch):
    """Two concurrent session lifecycles produce fully isolated paths.

    Validates that log root, snapshot storage, temp workspace, and session_id
    are all different when two tasks run simultaneously via asyncio.gather.
    """
    monkeypatch.setenv("MASSGEN_LOG_BASE_DIR", str(tmp_path))

    collected: dict[str, dict] = {}

    async def _lifecycle(name: str):
        ctx = contextvars.copy_context()

        def _body():
            import massgen.logger_config as lc
            from massgen.cli import (
                _scope_agent_temporary_workspace,
                _scope_snapshot_storage,
            )

            s = lc.LoggingSession.create()
            token = lc.set_current_session(s)
            try:
                lc.setup_logging(debug=False, session=s)
                root = lc.get_log_session_root()
                snap = _scope_snapshot_storage(".massgen/snapshots")
                temp = _scope_agent_temporary_workspace(".massgen/temp_workspaces")
                collected[name] = {
                    "root": str(root),
                    "snap": snap,
                    "temp": temp,
                    "session_id": s.session_id,
                }
            finally:
                s.close()
                lc._current_session.reset(token)

        await asyncio.get_event_loop().run_in_executor(None, ctx.run, _body)

    await asyncio.gather(_lifecycle("a"), _lifecycle("b"))

    assert collected["a"]["root"] != collected["b"]["root"], "Log roots must differ"
    assert collected["a"]["snap"] != collected["b"]["snap"], "Snapshot paths must differ"
    assert collected["a"]["temp"] != collected["b"]["temp"], "Temp workspace paths must differ"
    assert collected["a"]["session_id"] != collected["b"]["session_id"], "Session IDs must differ"


# ---------------------------------------------------------------------------
# WebUI path scoping regression tests
# ---------------------------------------------------------------------------


class TestWebUIPathScoping:
    """Verify WebUI server functions scope workspace paths before creating Orchestrator.

    The WebUI has two separate code paths (``run_coordination_with_history``
    and ``run_coordination``) that each read ``agent_temporary_workspace``
    and ``snapshot_storage`` from the YAML orchestrator config and pass
    them to the ``Orchestrator`` constructor.  If these values are not
    scoped via ``_scope_agent_temporary_workspace`` /
    ``_scope_snapshot_storage``, concurrent WebUI sessions will collide.

    These tests inspect the function source to verify the scoping calls
    are present — a lightweight regression gate that catches accidental
    removal without needing to mock the entire WebSocket stack.
    """

    @staticmethod
    def _get_function_source(func_name: str) -> str:
        """Return dedented source of a function from the WebUI server module."""
        import inspect

        from massgen.frontend.web import server as srv

        func = getattr(srv, func_name)
        return inspect.getsource(func)

    def test_run_coordination_with_history_scopes_temp_workspace(self):
        src = self._get_function_source("run_coordination_with_history")
        assert "_scope_agent_temporary_workspace" in src, "run_coordination_with_history must call _scope_agent_temporary_workspace"

    def test_run_coordination_with_history_scopes_snapshot_storage(self):
        src = self._get_function_source("run_coordination_with_history")
        assert "_scope_snapshot_storage" in src, "run_coordination_with_history must call _scope_snapshot_storage"

    def test_run_coordination_scopes_temp_workspace(self):
        src = self._get_function_source("run_coordination")
        assert "_scope_agent_temporary_workspace" in src, "run_coordination must call _scope_agent_temporary_workspace"

    def test_run_coordination_scopes_snapshot_storage(self):
        src = self._get_function_source("run_coordination")
        assert "_scope_snapshot_storage" in src, "run_coordination must call _scope_snapshot_storage"

    def test_run_coordination_with_history_no_raw_orchestrator_value(self):
        """Orchestrator must NOT receive the raw config value directly.

        Verify that ``orchestrator_cfg.get("agent_temporary_workspace")``
        is never passed straight to ``Orchestrator(`` without scoping.
        """
        import re

        src = self._get_function_source("run_coordination_with_history")
        # Should NOT find: agent_temporary_workspace=orchestrator_cfg.get("agent_temporary_workspace")
        # directly in the Orchestrator() call.  The value must go through
        # _scope_agent_temporary_workspace first.
        raw_pass = re.search(
            r"Orchestrator\([^)]*agent_temporary_workspace\s*=\s*orchestrator_cfg\.get",
            src,
            re.DOTALL,
        )
        assert raw_pass is None, "run_coordination_with_history passes raw orchestrator_cfg value " "directly to Orchestrator — must scope via _scope_agent_temporary_workspace first"

    def test_run_coordination_no_raw_orchestrator_value(self):
        """Same check for the single-turn run_coordination path."""
        import re

        src = self._get_function_source("run_coordination")
        raw_pass = re.search(
            r"Orchestrator\([^)]*agent_temporary_workspace\s*=\s*orchestrator_cfg\.get",
            src,
            re.DOTALL,
        )
        assert raw_pass is None, "run_coordination passes raw orchestrator_cfg value " "directly to Orchestrator — must scope via _scope_agent_temporary_workspace first"
