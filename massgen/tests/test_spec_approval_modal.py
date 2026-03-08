"""Tests for PlanApprovalModal spec artifact support."""

import json
from pathlib import Path


class TestPlanApprovalModalSpecDetection:
    """Test that PlanApprovalModal correctly detects and renders spec artifacts."""

    def _make_spec_data(self):
        return {
            "feature": "User Auth",
            "overview": "Authentication system",
            "requirements": [
                {
                    "id": "REQ-001",
                    "chunk": "C01_core",
                    "title": "Login endpoint",
                    "priority": "P0",
                    "type": "functional",
                    "ears": "WHEN user submits credentials THE SYSTEM SHALL authenticate",
                    "rationale": "Security",
                    "verification": "Test login flow",
                    "depends_on": [],
                },
                {
                    "id": "REQ-002",
                    "chunk": "C01_core",
                    "title": "Session management",
                    "priority": "P1",
                    "type": "functional",
                    "ears": "WHILE user is authenticated THE SYSTEM SHALL maintain session",
                    "rationale": "UX",
                    "verification": "Test session persistence",
                    "depends_on": ["REQ-001"],
                },
            ],
        }

    def _make_plan_data(self):
        return {
            "tasks": [
                {
                    "id": "T001",
                    "chunk": "C01_core",
                    "name": "Implement login",
                    "priority": "high",
                    "status": "pending",
                    "depends_on": [],
                },
            ],
        }

    def test_is_spec_flag_true_for_requirements(self):
        """Modal should detect spec artifacts with requirements key."""
        from massgen.frontend.displays.textual_widgets.plan_approval_modal import (
            PlanApprovalModal,
        )

        spec_data = self._make_spec_data()
        modal = PlanApprovalModal(
            tasks=spec_data["requirements"],
            plan_path=Path("/tmp/project_spec.json"),
            plan_data=spec_data,
        )
        assert modal._is_spec is True

    def test_is_spec_flag_false_for_tasks(self):
        """Modal should not set _is_spec for regular plan data."""
        from massgen.frontend.displays.textual_widgets.plan_approval_modal import (
            PlanApprovalModal,
        )

        plan_data = self._make_plan_data()
        modal = PlanApprovalModal(
            tasks=plan_data["tasks"],
            plan_path=Path("/tmp/project_plan.json"),
            plan_data=plan_data,
        )
        assert modal._is_spec is False

    def test_spec_loads_requirements_as_tasks(self):
        """Modal should load requirements into self.tasks when spec artifact."""
        from massgen.frontend.displays.textual_widgets.plan_approval_modal import (
            PlanApprovalModal,
        )

        spec_data = self._make_spec_data()
        modal = PlanApprovalModal(
            tasks=spec_data["requirements"],
            plan_path=Path("/tmp/project_spec.json"),
            plan_data=spec_data,
        )
        assert len(modal.tasks) == 2
        assert modal.tasks[0]["id"] == "REQ-001"
        assert modal.tasks[1]["id"] == "REQ-002"

    def test_spec_groups_by_chunk(self):
        """Modal should group spec requirements by chunk."""
        from massgen.frontend.displays.textual_widgets.plan_approval_modal import (
            PlanApprovalModal,
        )

        spec_data = self._make_spec_data()
        modal = PlanApprovalModal(
            tasks=spec_data["requirements"],
            plan_path=Path("/tmp/project_spec.json"),
            plan_data=spec_data,
        )
        assert "C01_core" in modal._chunk_order

    def test_format_task_row_shows_title_and_ears(self):
        """_format_task_row should show title and EARS for spec requirements."""
        from massgen.frontend.displays.textual_widgets.plan_approval_modal import (
            PlanApprovalModal,
        )

        spec_data = self._make_spec_data()
        modal = PlanApprovalModal(
            tasks=spec_data["requirements"],
            plan_path=Path("/tmp/project_spec.json"),
            plan_data=spec_data,
        )
        row = modal._format_task_row(spec_data["requirements"][0])
        row_text = row.plain
        assert "REQ-001" in row_text
        assert "Login endpoint" in row_text
        assert "WHEN user submits credentials" in row_text

    def test_format_task_row_plan_no_ears(self):
        """_format_task_row should not show EARS for regular plan tasks."""
        from massgen.frontend.displays.textual_widgets.plan_approval_modal import (
            PlanApprovalModal,
        )

        plan_data = self._make_plan_data()
        modal = PlanApprovalModal(
            tasks=plan_data["tasks"],
            plan_path=Path("/tmp/project_plan.json"),
            plan_data=plan_data,
        )
        row = modal._format_task_row(plan_data["tasks"][0])
        row_text = row.plain
        assert "T001" in row_text
        assert "Implement login" in row_text

    def test_spec_priority_p0_gets_color(self):
        """P0 priority should map to a color for spec requirements."""
        from massgen.frontend.displays.textual_widgets.plan_approval_modal import (
            PlanApprovalModal,
        )

        assert "p0" in PlanApprovalModal.PRIORITY_COLORS
        assert "p1" in PlanApprovalModal.PRIORITY_COLORS
        assert "p2" in PlanApprovalModal.PRIORITY_COLORS

    def test_json_edit_validates_requirements_key(self):
        """JSON editor should validate requirements key for spec artifacts."""
        from massgen.frontend.displays.textual_widgets.plan_approval_modal import (
            PlanApprovalModal,
        )

        spec_data = self._make_spec_data()
        modal = PlanApprovalModal(
            tasks=spec_data["requirements"],
            plan_path=Path("/tmp/project_spec.json"),
            plan_data=spec_data,
        )
        # Set plan_json_value to JSON with tasks key (wrong for spec) - should fail
        modal._plan_json_value = json.dumps({"tasks": [{"id": "T1"}]})
        result = modal._apply_plan_json_edit()
        assert result is False

        # Set plan_json_value to JSON with requirements key (correct for spec)
        modal._plan_json_value = json.dumps({"requirements": [{"id": "REQ-001", "title": "New req", "chunk": "C01"}]})
        result = modal._apply_plan_json_edit()
        assert result is True
        assert len(modal.tasks) == 1
