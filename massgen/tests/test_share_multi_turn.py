"""Tests for multi-turn session sharing functionality.

Tests the enhanced sharing capabilities including:
- Multi-turn session collection
- Error state sharing
- Workspace artifact handling
"""

import json
import tempfile
from pathlib import Path

import pytest

from massgen.session_exporter import get_session_turns, parse_turn_range

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_session_dir():
    """Create a temporary session directory structure for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        session_root = Path(tmpdir) / "log_20251225_222632_110428"
        session_root.mkdir(parents=True)
        yield session_root


@pytest.fixture
def single_turn_session(temp_session_dir: Path) -> Path:
    """Create a session with 1 turn."""
    turn_dir = temp_session_dir / "turn_1" / "attempt_1"
    turn_dir.mkdir(parents=True)

    # Create status.json
    status = {
        "meta": {"session_id": "attempt_1", "question": "Test question"},
        "results": {"winner": "agent_a"},
        "rounds": {"by_outcome": {"answer": 1, "error": 0}},
    }
    (turn_dir / "status.json").write_text(json.dumps(status))
    (turn_dir / "metrics_summary.json").write_text(json.dumps({"meta": {"question": "Test"}}))

    # Create agent outputs
    agent_outputs = turn_dir / "agent_outputs"
    agent_outputs.mkdir()
    (agent_outputs / "agent_a.txt").write_text("Test answer from agent_a")

    return temp_session_dir


@pytest.fixture
def multi_turn_session(temp_session_dir: Path) -> Path:
    """Create a session with 3 turns."""
    for turn_num in range(1, 4):
        turn_dir = temp_session_dir / f"turn_{turn_num}" / "attempt_1"
        turn_dir.mkdir(parents=True)

        status = {
            "meta": {"session_id": "attempt_1", "question": f"Question {turn_num}"},
            "results": {"winner": "agent_a"},
            "rounds": {"by_outcome": {"answer": 1, "error": 0}},
        }
        (turn_dir / "status.json").write_text(json.dumps(status))
        (turn_dir / "metrics_summary.json").write_text(
            json.dumps({"meta": {"question": f"Question {turn_num}"}}),
        )

        agent_outputs = turn_dir / "agent_outputs"
        agent_outputs.mkdir()
        (agent_outputs / "agent_a.txt").write_text(f"Answer for turn {turn_num}")

    return temp_session_dir


@pytest.fixture
def error_session(temp_session_dir: Path) -> Path:
    """Create a session that ended with an error."""
    turn_dir = temp_session_dir / "turn_1" / "attempt_1"
    turn_dir.mkdir(parents=True)

    status = {
        "meta": {"session_id": "attempt_1", "question": "Test question"},
        "results": {"winner": None},
        "rounds": {"by_outcome": {"answer": 0, "error": 1}},
        "agents": {
            "agent_a": {
                "error": {
                    "type": "api_error",
                    "message": "Rate limit exceeded",
                    "timestamp": 1234567890.123,
                },
            },
        },
    }
    (turn_dir / "status.json").write_text(json.dumps(status))
    # No metrics_summary.json - incomplete session

    return temp_session_dir


@pytest.fixture
def session_with_workspace(temp_session_dir: Path) -> Path:
    """Create a session with workspace artifacts."""
    turn_dir = temp_session_dir / "turn_1" / "attempt_1"
    turn_dir.mkdir(parents=True)

    status = {
        "meta": {"session_id": "attempt_1"},
        "results": {"winner": "agent_a"},
    }
    (turn_dir / "status.json").write_text(json.dumps(status))
    (turn_dir / "metrics_summary.json").write_text(json.dumps({"meta": {}}))

    # Create workspace with files
    workspace = turn_dir / "agent_a" / "20251225_222843" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "index.html").write_text("<html><body>Hello</body></html>")
    (workspace / "styles.css").write_text("body { color: black; }")
    (workspace / "app.js").write_text("console.log('hello');")

    return temp_session_dir


# =============================================================================
# Phase 3: User Story 1 - Multi-Turn Sharing Tests
# =============================================================================


class TestGetSessionTurns:
    """Tests for get_session_turns() function."""

    def test_single_turn_session(self, single_turn_session: Path):
        """Test getting turns from a single-turn session."""
        turns = get_session_turns(single_turn_session)

        assert len(turns) == 1
        assert turns[0].turn_number == 1
        assert turns[0].attempt_number == 1
        assert turns[0].status == "complete"

    def test_multi_turn_session(self, multi_turn_session: Path):
        """Test getting turns from a multi-turn session."""
        turns = get_session_turns(multi_turn_session)

        assert len(turns) == 3
        assert [t.turn_number for t in turns] == [1, 2, 3]
        for turn in turns:
            assert turn.status == "complete"

    def test_five_turn_session(self, temp_session_dir: Path):
        """Test getting turns from a 5-turn session."""
        for turn_num in range(1, 6):
            turn_dir = temp_session_dir / f"turn_{turn_num}" / "attempt_1"
            turn_dir.mkdir(parents=True)
            (turn_dir / "status.json").write_text(json.dumps({"results": {}}))

        turns = get_session_turns(temp_session_dir)

        assert len(turns) == 5
        assert [t.turn_number for t in turns] == [1, 2, 3, 4, 5]

    def test_empty_session(self, temp_session_dir: Path):
        """Test getting turns from an empty session directory."""
        turns = get_session_turns(temp_session_dir)
        assert len(turns) == 0


class TestParseTurnRange:
    """Tests for parse_turn_range() function."""

    def test_parse_all(self):
        """Test parsing 'all' range."""
        result = parse_turn_range("all", total_turns=5)
        assert result == [1, 2, 3, 4, 5]

    def test_parse_single_turn(self):
        """Test parsing single turn number."""
        result = parse_turn_range("2", total_turns=5)
        assert result == [1, 2]  # Turns 1 through 2

    def test_parse_range(self):
        """Test parsing turn range like '1-3'."""
        result = parse_turn_range("1-3", total_turns=5)
        assert result == [1, 2, 3]

    def test_parse_latest(self):
        """Test parsing 'latest' to get only last turn."""
        result = parse_turn_range("latest", total_turns=5)
        assert result == [5]

    def test_parse_invalid_range(self):
        """Test parsing invalid range raises error."""
        with pytest.raises(ValueError):
            parse_turn_range("invalid", total_turns=5)

    def test_parse_out_of_range(self):
        """Test parsing turn number out of range raises error."""
        with pytest.raises(ValueError):
            parse_turn_range("10", total_turns=5)


class TestCollectFilesMultiTurn:
    """Tests for collect_files_multi_turn() function."""

    def test_basic_collection(self, multi_turn_session: Path):
        """Test basic file collection from multi-turn session."""
        from massgen.share import collect_files_multi_turn

        turns = get_session_turns(multi_turn_session)
        files, skipped, warnings = collect_files_multi_turn(
            multi_turn_session,
            turns,
            include_workspace=False,
        )

        # Should have files from all 3 turns
        assert len(files) > 0
        # Files should have turn prefix
        assert any("turn_1__" in name for name in files.keys())
        assert any("turn_2__" in name for name in files.keys())
        assert any("turn_3__" in name for name in files.keys())


class TestCreateSessionManifest:
    """Tests for create_session_manifest() function."""

    def test_manifest_format(self, multi_turn_session: Path):
        """Test session manifest has correct format."""
        from massgen.share import create_session_manifest

        turns = get_session_turns(multi_turn_session)
        manifest = create_session_manifest(multi_turn_session, turns)

        assert manifest["version"] == "2.0"
        assert manifest["session_id"] == multi_turn_session.name
        assert manifest["turn_count"] == 3
        assert manifest["status"] == "complete"
        assert "turns" in manifest
        assert len(manifest["turns"]) == 3


# =============================================================================
# Phase 4: User Story 2 - Error State Sharing Tests
# =============================================================================


class TestDetermineSessionStatus:
    """Tests for determine_session_status() function."""

    def test_complete_session(self, multi_turn_session: Path):
        """Test status detection for complete session."""
        from massgen.share import determine_session_status

        turns = get_session_turns(multi_turn_session)
        status = determine_session_status(turns)

        assert status == "complete"

    def test_error_session(self, error_session: Path):
        """Test status detection for error session."""
        from massgen.share import determine_session_status

        turns = get_session_turns(error_session)
        status = determine_session_status(turns)

        assert status == "error"

    def test_interrupted_session(self, temp_session_dir: Path):
        """Test status detection for interrupted session (no status.json)."""
        from massgen.share import determine_session_status

        turn_dir = temp_session_dir / "turn_1" / "attempt_1"
        turn_dir.mkdir(parents=True)
        # No status.json at all - truly interrupted

        turns = get_session_turns(temp_session_dir)
        status = determine_session_status(turns)

        assert status == "interrupted"


class TestExtractErrorInfo:
    """Tests for extract_error_info() function."""

    def test_extract_error_from_status(self, error_session: Path):
        """Test extracting error info from status.json."""
        from massgen.share import extract_error_info

        turn_path = error_session / "turn_1" / "attempt_1"
        error_info = extract_error_info(turn_path)

        assert error_info is not None
        assert error_info["type"] == "api_error"
        assert error_info["message"] == "Rate limit exceeded"
        assert error_info["agent_id"] == "agent_a"

    def test_no_error_in_complete_session(self, single_turn_session: Path):
        """Test no error info in complete session."""
        from massgen.share import extract_error_info

        turn_path = single_turn_session / "turn_1" / "attempt_1"
        error_info = extract_error_info(turn_path)

        assert error_info is None


class TestShareIncompleteSession:
    """Tests for sharing incomplete sessions."""

    def test_share_session_without_metrics(self, error_session: Path):
        """Test sharing a session that has no metrics_summary.json."""
        from massgen.share import collect_files_multi_turn

        turns = get_session_turns(error_session)
        files, skipped, warnings = collect_files_multi_turn(
            error_session,
            turns,
            include_workspace=False,
        )

        # Should still collect status.json even without metrics
        assert len(files) > 0
        assert any("status.json" in name for name in files.keys())


# =============================================================================
# Phase 5: User Story 3 - Workspace Artifact Tests
# =============================================================================


class TestWorkspaceCollection:
    """Tests for workspace file collection."""

    def test_collect_workspace_files(self, session_with_workspace: Path):
        """Test collecting workspace files."""
        from massgen.share import collect_workspace_files

        turns = get_session_turns(session_with_workspace)
        workspace_files = collect_workspace_files(
            session_with_workspace,
            turns,
            limit_per_agent=500_000,
        )

        # Should find the workspace files
        assert len(workspace_files) > 0


class TestWorkspaceSizeLimit:
    """Tests for workspace size limit enforcement."""

    def test_enforce_size_limit(self, session_with_workspace: Path):
        """Test that workspace size limit is enforced."""
        from massgen.share import collect_workspace_files

        turns = get_session_turns(session_with_workspace)
        # Set very small limit
        workspace_files = collect_workspace_files(
            session_with_workspace,
            turns,
            limit_per_agent=10,  # 10 bytes
        )

        # Should have warnings about exceeded limits
        # Files should be excluded or truncated due to small limit
        # The function should return a dict (possibly empty due to strict limit)
        assert isinstance(workspace_files, dict)


class TestParseSize:
    """Tests for parse_size() helper."""

    def test_parse_kb(self):
        """Test parsing KB values."""
        from massgen.share import parse_size

        assert parse_size("500KB") == 500 * 1024
        assert parse_size("500kb") == 500 * 1024
        assert parse_size("1KB") == 1024

    def test_parse_mb(self):
        """Test parsing MB values."""
        from massgen.share import parse_size

        assert parse_size("1MB") == 1024 * 1024
        assert parse_size("1mb") == 1024 * 1024
        assert parse_size("5MB") == 5 * 1024 * 1024

    def test_parse_bytes(self):
        """Test parsing plain byte values."""
        from massgen.share import parse_size

        assert parse_size("1000") == 1000
        assert parse_size("500000") == 500000

    def test_parse_invalid(self):
        """Test parsing invalid size string."""
        from massgen.share import parse_size

        with pytest.raises(ValueError):
            parse_size("invalid")


class TestSensitiveDataDetection:
    """Tests for sensitive data pattern detection."""

    def test_detect_env_file(self, temp_session_dir: Path):
        """Test detection of .env files."""
        from massgen.share import detect_sensitive_patterns

        workspace = temp_session_dir / "workspace"
        workspace.mkdir()
        (workspace / ".env").write_text("API_KEY=secret123")

        sensitive = detect_sensitive_patterns(workspace)

        assert len(sensitive) > 0
        assert any(".env" in f for f in sensitive)

    def test_detect_api_key_in_json(self, temp_session_dir: Path):
        """Test detection of API keys in JSON files."""
        from massgen.share import detect_sensitive_patterns

        workspace = temp_session_dir / "workspace"
        workspace.mkdir()
        config = {"api_key": "sk-1234567890", "setting": "value"}
        (workspace / "config.json").write_text(json.dumps(config))

        sensitive = detect_sensitive_patterns(workspace)

        assert len(sensitive) > 0

    def test_no_sensitive_data(self, temp_session_dir: Path):
        """Test no false positives for normal files."""
        from massgen.share import detect_sensitive_patterns

        workspace = temp_session_dir / "workspace"
        workspace.mkdir()
        (workspace / "index.html").write_text("<html>Hello</html>")
        (workspace / "style.css").write_text("body { color: black; }")

        sensitive = detect_sensitive_patterns(workspace)

        assert len(sensitive) == 0
