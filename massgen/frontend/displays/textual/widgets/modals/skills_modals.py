"""Skill management modals for Textual TUI."""

from __future__ import annotations

from typing import Any

try:
    from textual.app import ComposeResult
    from textual.containers import Container, Horizontal, VerticalScroll
    from textual.widgets import Button, Checkbox, Label, Static

    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

from ..modal_base import BaseModal


class SkillsModal(BaseModal):
    """Modal for viewing and toggling available skills for the current session."""

    LOCATION_ORDER: tuple[str, ...] = ("builtin", "project", "user", "previous_session")
    LOCATION_LABELS: dict[str, str] = {
        "builtin": "Built-in Skills",
        "project": "Project Skills",
        "user": "User Skills (~/.agent/skills)",
        "previous_session": "Evolving Skills (Previous Sessions)",
    }

    def __init__(
        self,
        *,
        skills_by_location: dict[str, list[dict[str, Any]]],
        enabled_skill_names: list[str] | None,
        include_previous_session_skills: bool,
        registry_content: str | None = None,
    ) -> None:
        super().__init__()
        self._skills_by_location = {location: list(skills_by_location.get(location, [])) for location in self.LOCATION_ORDER}
        self._enabled_skill_names = enabled_skill_names
        self._include_previous_session_skills = include_previous_session_skills
        self._registry_content = registry_content
        self._checkbox_to_meta: dict[str, dict[str, str]] = {}
        self._previous_session_checkbox_ids: set[str] = set()

    def _is_enabled(self, name: str) -> bool:
        """Return whether a skill should render as enabled."""
        if self._enabled_skill_names is None:
            return True
        enabled = {s.lower() for s in self._enabled_skill_names}
        return name.lower() in enabled

    @staticmethod
    def _build_tags(skill: dict[str, Any], location: str) -> list[str]:
        """Build compact label tags for a skill row."""
        tags: list[str] = [location.replace("_", " ")]
        if location in {"project", "user"} or bool(skill.get("is_custom")):
            tags.append("custom")
        if location == "previous_session" or bool(skill.get("is_evolving")):
            tags.append("evolving")
        return tags

    @staticmethod
    def _build_detail(skill: dict[str, Any]) -> str:
        """Build detail line shown under each skill row."""
        description = str(skill.get("description", "") or "").strip()
        origin = str(skill.get("origin", "") or "").strip()
        if description and origin:
            return f"{description} • origin: {origin}"
        if description:
            return description
        if origin:
            return f"origin: {origin}"
        return ""

    def compose(self) -> ComposeResult:
        total = sum(len(skills) for skills in self._skills_by_location.values())
        with Container(id="skills_modal_container"):
            yield Label("Skills Manager", id="skills_modal_header")
            yield Label(
                f"{total} skill(s) discovered • grouped by source • session-only toggles",
                id="skills_modal_summary",
            )
            if self._registry_content:
                yield Static(
                    self._registry_content,
                    id="skills_modal_registry",
                    classes="modal-registry-section",
                )
            yield Checkbox(
                "Include evolving skills from previous sessions",
                value=self._include_previous_session_skills,
                id="include_previous_skills_checkbox",
            )

            with VerticalScroll(id="skills_modal_scroll"):
                for location in self.LOCATION_ORDER:
                    location_skills = self._skills_by_location.get(location, [])
                    yield Label(self.LOCATION_LABELS.get(location, location), classes="modal-section-header")
                    if location_skills:
                        for idx, skill in enumerate(location_skills):
                            name = str(skill.get("name", "") or "").strip() or f"{location}-{idx}"
                            tags = ", ".join(self._build_tags(skill, location))
                            label = f"{name} [{tags}]"
                            checkbox_id = f"skill_{location}_{idx}"
                            self._checkbox_to_meta[checkbox_id] = {"name": name, "location": location}
                            if location == "previous_session":
                                self._previous_session_checkbox_ids.add(checkbox_id)
                            yield Checkbox(
                                label,
                                value=self._is_enabled(name),
                                id=checkbox_id,
                            )
                            detail = self._build_detail(skill)
                            if detail:
                                yield Static(
                                    f"[dim]{detail}[/]",
                                    markup=True,
                                    classes="modal-list-item",
                                )
                    else:
                        empty_msg = "[dim]No evolving skills found in previous sessions[/]" if location == "previous_session" else "[dim]None found[/]"
                        yield Static(empty_msg, markup=True, classes="modal-list-item")

            with Horizontal(id="skills_modal_actions"):
                yield Button("Enable All", id="enable_all_skills_btn")
                yield Button("Disable All", id="disable_all_skills_btn")
                yield Button("Enable Custom", id="enable_custom_skills_btn")
                yield Button("Apply", id="apply_skills_btn", variant="primary")
                yield Button("Cancel", id="skills_cancel_button")

    def on_mount(self) -> None:
        """Sync evolving-skill checkbox state after widgets mount."""
        self._sync_previous_session_skill_state()

    def _include_previous_sessions(self) -> bool:
        """Read the current previous-session inclusion toggle."""
        try:
            include_checkbox = self.query_one("#include_previous_skills_checkbox", Checkbox)
            return bool(include_checkbox.value)
        except Exception:
            return bool(self._include_previous_session_skills)

    def _set_all_checkboxes(self, value: bool) -> None:
        """Set all selectable skill checkboxes to the given value."""
        include_previous = self._include_previous_sessions()
        for checkbox_id, meta in self._checkbox_to_meta.items():
            if not include_previous and meta.get("location") == "previous_session":
                continue
            try:
                cb = self.query_one(f"#{checkbox_id}", Checkbox)
                if not cb.disabled:
                    cb.value = value
            except Exception:
                continue

    def _set_custom_checkboxes(self) -> None:
        """Enable custom skills and disable built-ins for quick targeting."""
        include_previous = self._include_previous_sessions()
        for checkbox_id, meta in self._checkbox_to_meta.items():
            location = meta.get("location", "")
            try:
                cb = self.query_one(f"#{checkbox_id}", Checkbox)
            except Exception:
                continue
            if cb.disabled:
                continue
            if location == "builtin":
                cb.value = False
            elif location in {"project", "user"}:
                cb.value = True
            elif location == "previous_session":
                cb.value = include_previous

    def _collect_enabled_names(self) -> list[str]:
        """Collect selected skill names from checkbox state."""
        selected: list[str] = []
        include_previous = self._include_previous_sessions()
        for checkbox_id, meta in self._checkbox_to_meta.items():
            location = meta.get("location", "")
            if location == "previous_session" and not include_previous:
                continue
            name = meta.get("name", "")
            if not name:
                continue
            try:
                cb = self.query_one(f"#{checkbox_id}", Checkbox)
                if cb.value and not cb.disabled:
                    selected.append(name)
            except Exception:
                continue
        return selected

    def _sync_previous_session_skill_state(self) -> None:
        """Enable/disable previous-session skill rows based on inclusion toggle."""
        include_previous = self._include_previous_sessions()
        for checkbox_id in self._previous_session_checkbox_ids:
            try:
                cb = self.query_one(f"#{checkbox_id}", Checkbox)
                cb.disabled = not include_previous
                if not include_previous:
                    cb.value = False
            except Exception:
                continue

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle toggles in the modal."""
        if event.checkbox.id == "include_previous_skills_checkbox":
            self._sync_previous_session_skill_state()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "enable_all_skills_btn":
            self._set_all_checkboxes(True)
            return
        if event.button.id == "disable_all_skills_btn":
            self._set_all_checkboxes(False)
            return
        if event.button.id == "enable_custom_skills_btn":
            self._set_custom_checkboxes()
            return
        if event.button.id == "apply_skills_btn":
            self.dismiss(
                {
                    "enabled_skill_names": self._collect_enabled_names(),
                    "include_previous_session_skills": self._include_previous_sessions(),
                },
            )
            event.stop()
            return
        if event.button.id == "skills_cancel_button":
            self.dismiss(None)
            event.stop()
            return
