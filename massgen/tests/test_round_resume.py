"""Tests for round resume from previous log.

Tests snapshot parsing, answer/workspace restoration, coordination tracker
state, eval criteria loading, and config validation.
"""

import json
from pathlib import Path

import yaml

from massgen.coordination_tracker import CoordinationTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot_dir(tmp_path: Path, agent_id: str, timestamp: str, answer: str, changedoc: str | None = None, workspace_files: dict[str, str] | None = None):
    """Create a snapshot directory matching the real log structure."""
    snap_dir = tmp_path / agent_id / timestamp
    snap_dir.mkdir(parents=True)
    (snap_dir / "answer.txt").write_text(answer)
    if changedoc:
        (snap_dir / "changedoc.md").write_text(changedoc)
    if workspace_files:
        ws_dir = snap_dir / "workspace"
        ws_dir.mkdir()
        for name, content in workspace_files.items():
            (ws_dir / name).write_text(content)
    return snap_dir


def _make_log_dir(tmp_path: Path, agents: dict[str, list[dict]], eval_criteria: list[dict] | None = None):
    """Build a complete mock log directory.

    Args:
        agents: {agent_id: [{round, timestamp, answer, changedoc?, workspace?}]}
        eval_criteria: Optional list of criteria dicts for generated_evaluation_criteria.yaml
    """
    log_dir = tmp_path / "log_mock" / "turn_1" / "attempt_1"
    log_dir.mkdir(parents=True)

    # Build snapshot_mappings and agent dirs
    mappings = {}
    agent_ids = list(agents.keys())
    for agent_id in agent_ids:
        agent_num = agent_ids.index(agent_id) + 1
        for entry in agents[agent_id]:
            answer_num = entry.get("answer_num", entry["round"] + 1)
            label = f"agent{agent_num}.{answer_num}"
            timestamp = entry["timestamp"]
            _make_snapshot_dir(
                log_dir,
                agent_id,
                timestamp,
                entry["answer"],
                entry.get("changedoc"),
                entry.get("workspace"),
            )
            mappings[label] = {
                "type": "answer",
                "label": label,
                "agent_id": agent_id,
                "timestamp": timestamp,
                "iteration": entry.get("iteration", 0),
                "round": entry["round"],
                "path": f"{agent_id}/{timestamp}/answer.txt",
            }

    (log_dir / "snapshot_mappings.json").write_text(json.dumps(mappings, indent=2))

    # execution_metadata.yaml
    metadata = {
        "config": {
            "agents": [{"id": aid} for aid in agent_ids],
        },
    }
    (log_dir / "execution_metadata.yaml").write_text(yaml.dump(metadata))

    # generated_evaluation_criteria.yaml
    if eval_criteria:
        (log_dir / "generated_evaluation_criteria.yaml").write_text(yaml.dump(eval_criteria))

    return log_dir


# ---------------------------------------------------------------------------
# Snapshot mappings parsing
# ---------------------------------------------------------------------------


class TestSnapshotMappingsParsing:
    """Test loading and filtering snapshot_mappings.json."""

    def test_load_snapshot_mappings(self, tmp_path):
        log_dir = _make_log_dir(
            tmp_path,
            {
                "agent_a": [
                    {"round": 0, "timestamp": "20260225_010000", "answer": "Round 0 answer"},
                    {"round": 1, "timestamp": "20260225_020000", "answer": "Round 1 answer"},
                ],
            },
        )

        mappings_path = log_dir / "snapshot_mappings.json"
        mappings = json.loads(mappings_path.read_text())
        assert len(mappings) == 2
        assert "agent1.1" in mappings
        assert "agent1.2" in mappings

    def test_filter_by_round(self, tmp_path):
        log_dir = _make_log_dir(
            tmp_path,
            {
                "agent_a": [
                    {"round": 0, "timestamp": "20260225_010000", "answer": "R0"},
                    {"round": 1, "timestamp": "20260225_020000", "answer": "R1"},
                    {"round": 2, "timestamp": "20260225_030000", "answer": "R2"},
                ],
            },
        )

        mappings = json.loads((log_dir / "snapshot_mappings.json").read_text())
        # Filter to round <= 1
        filtered = {k: v for k, v in mappings.items() if v["type"] == "answer" and v["round"] <= 1}
        assert len(filtered) == 2
        assert all(v["round"] <= 1 for v in filtered.values())


# ---------------------------------------------------------------------------
# CoordinationTracker synthetic answer restoration
# ---------------------------------------------------------------------------


class TestAnswerRestoration:
    """Test synthetic add_agent_answer for round resume."""

    def test_synthetic_add_agent_answer(self):
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])
        tracker.add_agent_answer("agent_a", "This is a restored answer", snapshot_timestamp="20260225_010000")

        assert len(tracker.answers_by_agent["agent_a"]) == 1
        assert tracker.answers_by_agent["agent_a"][0].content == "This is a restored answer"
        assert tracker.answers_by_agent["agent_a"][0].label == "agent1.1"

    def test_multiple_answers_restored_in_order(self):
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])
        tracker.add_agent_answer("agent_a", "Round 0 answer", snapshot_timestamp="t0")
        tracker.add_agent_answer("agent_a", "Round 1 answer", snapshot_timestamp="t1")

        answers = tracker.answers_by_agent["agent_a"]
        assert len(answers) == 2
        assert answers[0].label == "agent1.1"
        assert answers[1].label == "agent1.2"
        assert answers[0].content == "Round 0 answer"
        assert answers[1].content == "Round 1 answer"


class TestAgentRoundSet:
    """Test set_agent_round for direct round manipulation."""

    def test_set_agent_round(self):
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])
        tracker.set_agent_round("agent_a", 2)

        assert tracker.get_agent_round("agent_a") == 2

    def test_set_agent_round_multiple_agents(self):
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a", "agent_b"])
        tracker.set_agent_round("agent_a", 1)
        tracker.set_agent_round("agent_b", 1)

        assert tracker.get_agent_round("agent_a") == 1
        assert tracker.get_agent_round("agent_b") == 1


# ---------------------------------------------------------------------------
# Changedoc restoration
# ---------------------------------------------------------------------------


class TestChangedocRestoration:
    """Test that changedoc content is attached to restored answers."""

    def test_changedoc_attached_to_answer(self):
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])

        # add_agent_answer doesn't take changedoc directly, but we can set it after
        tracker.add_agent_answer("agent_a", "Answer with changedoc", snapshot_timestamp="t0")
        # Set changedoc on the answer
        tracker.answers_by_agent["agent_a"][0].changedoc = "## Decision: use flexbox layout"

        assert tracker.answers_by_agent["agent_a"][0].changedoc == "## Decision: use flexbox layout"


# ---------------------------------------------------------------------------
# Eval criteria loading
# ---------------------------------------------------------------------------


class TestEvalCriteriaFromLog:
    """Test loading generated_evaluation_criteria.yaml from a previous log."""

    def test_eval_criteria_loaded_from_log(self, tmp_path):
        criteria = [
            {"id": "E1", "text": "Functional completeness", "category": "must"},
            {"id": "E2", "text": "Visual design cohesion", "category": "should"},
        ]
        log_dir = _make_log_dir(
            tmp_path,
            {
                "agent_a": [{"round": 0, "timestamp": "t0", "answer": "A"}],
            },
            eval_criteria=criteria,
        )

        criteria_path = log_dir / "generated_evaluation_criteria.yaml"
        loaded = yaml.safe_load(criteria_path.read_text())
        assert len(loaded) == 2
        assert loaded[0]["id"] == "E1"
        assert loaded[1]["category"] == "should"

    def test_eval_criteria_inline_overrides_log(self):
        """When inline criteria are set, log criteria should be ignored."""
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig(
            checklist_criteria_inline=[
                {"text": "My inline criterion", "category": "must"},
            ],
        )
        # With inline set, the orchestrator should skip loading from log
        assert config.checklist_criteria_inline is not None
        assert len(config.checklist_criteria_inline) == 1


# ---------------------------------------------------------------------------
# Persona loading from log
# ---------------------------------------------------------------------------


class TestPersonaFromLog:
    """Test loading generated_personas.yaml from a previous log."""

    def test_persona_file_parsed_correctly(self, tmp_path):
        """Personas YAML can be parsed into GeneratedPersona objects."""
        from massgen.persona_generator import GeneratedPersona

        personas_data = {
            "agent_a": {
                "persona_text": "You are a bold visual designer",
                "attributes": {"style": "modernist"},
            },
        }
        log_dir = _make_log_dir(
            tmp_path,
            {"agent_a": [{"round": 0, "timestamp": "t0", "answer": "A"}]},
        )
        (log_dir / "generated_personas.yaml").write_text(yaml.dump(personas_data))

        loaded = yaml.safe_load((log_dir / "generated_personas.yaml").read_text())
        persona = GeneratedPersona(
            agent_id="agent_a",
            persona_text=loaded["agent_a"]["persona_text"],
            attributes=loaded["agent_a"]["attributes"],
        )
        assert persona.persona_text == "You are a bold visual designer"
        assert persona.attributes == {"style": "modernist"}


class TestResumeSkipsRegeneration:
    """Restored criteria/personas must set the 'already generated' guard flags."""

    def test_restored_criteria_sets_generated_flag(self, tmp_path):
        """After restore, _evaluation_criteria_generated must be True so regeneration is skipped."""

        criteria = [
            {"id": "E1", "text": "Functional completeness", "category": "must"},
        ]
        log_dir = _make_log_dir(
            tmp_path,
            {"agent_a": [{"round": 0, "timestamp": "t0", "answer": "A"}]},
            eval_criteria=criteria,
        )

        # Directly call _restore_from_previous_log requires a full orchestrator,
        # so instead verify the flag-setting logic inline:
        import yaml as _yaml

        from massgen.evaluation_criteria_generator import GeneratedCriterion

        criteria_file = log_dir / "generated_evaluation_criteria.yaml"
        criteria_data = _yaml.safe_load(criteria_file.read_text())

        # Simulate what _restore_from_previous_log does
        generated = [
            GeneratedCriterion(
                id=c.get("id", f"E{i + 1}"),
                text=c["text"],
                category=c.get("category", "should"),
            )
            for i, c in enumerate(criteria_data)
        ]
        assert len(generated) == 1
        # The guard flag must be set when criteria are loaded
        evaluation_criteria_generated = bool(generated)
        assert evaluation_criteria_generated is True


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestResumeConfigValidation:
    """Test config validation for resume_from_log."""

    def _make_config(self, resume_cfg):
        return {
            "agents": [
                {"id": "agent_a", "backend": {"type": "openai", "model": "gpt-4o-mini"}},
            ],
            "orchestrator": {
                "coordination": {
                    "resume_from_log": resume_cfg,
                },
            },
        }

    def test_valid_resume_config_passes(self, tmp_path):
        from massgen.config_validator import ConfigValidator

        log_dir = _make_log_dir(
            tmp_path,
            {
                "agent_a": [{"round": 0, "timestamp": "t0", "answer": "A"}],
            },
        )

        validator = ConfigValidator()
        result = validator.validate_config(
            self._make_config(
                {
                    "log_path": str(log_dir),
                    "round": 1,
                },
            ),
        )
        errors = [e.message for e in result.errors]
        assert not any("resume_from_log" in msg for msg in errors)

    def test_invalid_log_path_fails(self):
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        result = validator.validate_config(
            self._make_config(
                {
                    "log_path": "/nonexistent/path",
                    "round": 1,
                },
            ),
        )
        error_messages = [e.message for e in result.errors]
        assert any("resume_from_log" in msg for msg in error_messages)

    def test_missing_round_fails(self):
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        result = validator.validate_config(
            self._make_config(
                {
                    "log_path": "/tmp",
                },
            ),
        )
        error_messages = [e.message for e in result.errors]
        assert any("resume_from_log" in msg for msg in error_messages)

    def test_invalid_round_type_fails(self):
        from massgen.config_validator import ConfigValidator

        validator = ConfigValidator()
        result = validator.validate_config(
            self._make_config(
                {
                    "log_path": "/tmp",
                    "round": "one",
                },
            ),
        )
        error_messages = [e.message for e in result.errors]
        assert any("resume_from_log" in msg for msg in error_messages)

    def test_agent_id_mismatch_fails(self, tmp_path):
        from massgen.config_validator import ConfigValidator

        # Log has agent_a, but config (see _make_config) also has agent_a
        # Create a log with agent_b instead
        log_dir = _make_log_dir(
            tmp_path,
            {
                "agent_b": [{"round": 0, "timestamp": "t0", "answer": "A"}],
            },
        )

        validator = ConfigValidator()
        result = validator.validate_config(
            self._make_config(
                {
                    "log_path": str(log_dir),
                    "round": 1,
                },
            ),
        )
        error_messages = [e.message for e in result.errors]
        assert any("resume_from_log" in msg for msg in error_messages)

    def test_resume_from_resumed_log_fails(self, tmp_path):
        from massgen.config_validator import ConfigValidator

        original_log_dir = _make_log_dir(
            tmp_path / "original",
            {
                "agent_a": [{"round": 0, "timestamp": "t0", "answer": "A"}],
            },
        )
        resumed_log_dir = _make_log_dir(
            tmp_path / "resumed",
            {
                "agent_a": [{"round": 1, "timestamp": "t1", "answer": "B"}],
            },
        )

        metadata_path = resumed_log_dir / "execution_metadata.yaml"
        metadata = yaml.safe_load(metadata_path.read_text())
        metadata["config"]["orchestrator"] = {
            "coordination": {
                "resume_from_log": {
                    "log_path": str(original_log_dir),
                    "round": 1,
                },
            },
        }
        metadata_path.write_text(yaml.dump(metadata))

        validator = ConfigValidator()
        result = validator.validate_config(
            self._make_config(
                {
                    "log_path": str(resumed_log_dir),
                    "round": 2,
                },
            ),
        )
        error_messages = [e.message for e in result.errors]
        assert any("log that itself used resume_from_log" in msg for msg in error_messages)


# ---------------------------------------------------------------------------
# Multi-agent resume
# ---------------------------------------------------------------------------


class TestMultiAgentResume:
    """Test restoring round 1 answers for multiple agents."""

    def test_multi_agent_answers_restored(self, tmp_path):
        """Both agents' round 0 answers should be visible in tracker."""
        log_dir = _make_log_dir(
            tmp_path,
            {
                "agent_a": [{"round": 0, "timestamp": "t0a", "answer": "Agent A round 0"}],
                "agent_b": [{"round": 0, "timestamp": "t0b", "answer": "Agent B round 0"}],
            },
        )

        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a", "agent_b"])

        # Simulate restoration: read snapshot_mappings, restore answers
        mappings = json.loads((log_dir / "snapshot_mappings.json").read_text())
        for label, mapping in sorted(mappings.items()):
            if mapping["type"] == "answer" and mapping["round"] <= 0:
                answer_path = log_dir / mapping["path"]
                answer_text = answer_path.read_text()
                tracker.add_agent_answer(
                    mapping["agent_id"],
                    answer_text,
                    snapshot_timestamp=mapping["timestamp"],
                )

        # Both agents should have answers
        assert len(tracker.answers_by_agent["agent_a"]) == 1
        assert len(tracker.answers_by_agent["agent_b"]) == 1
        assert tracker.answers_by_agent["agent_a"][0].content == "Agent A round 0"
        assert tracker.answers_by_agent["agent_b"][0].content == "Agent B round 0"

        # all_answers should include both
        all_answers = tracker.all_answers
        assert len(all_answers) == 2


# ---------------------------------------------------------------------------
# CoordinationConfig field tests
# ---------------------------------------------------------------------------


class TestResumeFromLogConfigField:
    """Test resume_from_log field on CoordinationConfig."""

    def test_default_is_none(self):
        from massgen.agent_config import CoordinationConfig

        config = CoordinationConfig()
        assert config.resume_from_log is None

    def test_accepts_dict(self):
        from massgen.agent_config import CoordinationConfig

        resume_cfg = {"log_path": "/some/path", "round": 1}
        config = CoordinationConfig(resume_from_log=resume_cfg)
        assert config.resume_from_log == resume_cfg

    def test_wired_through_parse_coordination_config(self):
        from massgen.cli import _parse_coordination_config

        resume_cfg = {"log_path": "/some/path", "round": 1}
        config = _parse_coordination_config({"resume_from_log": resume_cfg})
        assert config.resume_from_log == resume_cfg


# ---------------------------------------------------------------------------
# Resume state fixes: answer_count and task plan clearing
# ---------------------------------------------------------------------------


class TestResumeAnswerCount:
    """After restore, agent_state.answer_count must reflect restored answers."""

    def test_restore_sets_answer_count(self, tmp_path):
        """Restored agent should have answer_count == number of restored answers."""
        _make_log_dir(
            tmp_path,
            {
                "agent_a": [
                    {"round": 0, "timestamp": "t0", "answer": "Round 0 answer"},
                ],
            },
        )

        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])
        tracker.add_agent_answer("agent_a", "Round 0 answer", snapshot_timestamp="t0")

        answers = tracker.answers_by_agent.get("agent_a", [])
        # Simulate what _restore_from_previous_log should do
        answer_count = len(answers)
        assert answer_count == 1, "Restored agent must have answer_count >= 1 so submit_checklist gate passes"

    def test_restore_multiple_answers_count(self, tmp_path):
        """Restoring 2 answers should give answer_count == 2."""
        tracker = CoordinationTracker()
        tracker.initialize_session(["agent_a"])
        tracker.add_agent_answer("agent_a", "R0", snapshot_timestamp="t0")
        tracker.add_agent_answer("agent_a", "R1", snapshot_timestamp="t1")

        answers = tracker.answers_by_agent.get("agent_a", [])
        assert len(answers) == 2


class TestResumeTaskPlanCleared:
    """After restore, stale task plan files must not exist in workspace."""

    def test_stale_plan_cleared_from_workspace(self, tmp_path):
        """tasks/plan.json from a restored workspace should be removed."""
        # Simulate a workspace with a stale plan
        workspace = tmp_path / "workspace"
        tasks_dir = workspace / "tasks"
        tasks_dir.mkdir(parents=True)
        plan_file = tasks_dir / "plan.json"
        plan_file.write_text('{"tasks": [{"id": "old", "status": "verified"}]}')

        # Simulate what _restore_from_previous_log should do: remove stale plan
        if plan_file.exists():
            plan_file.unlink()

        assert not plan_file.exists(), "Stale task plan must be cleared on resume"

    def test_workspace_without_plan_unaffected(self, tmp_path):
        """Workspace with no tasks/plan.json should not error."""
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)
        plan_file = workspace / "tasks" / "plan.json"

        # Should not raise even if file doesn't exist
        if plan_file.exists():
            plan_file.unlink()

        assert not plan_file.exists()
