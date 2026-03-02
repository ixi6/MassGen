"""Tests for per-modality multimedia skills structure and content accuracy."""

import re
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).parent.parent / "skills"

# Expected skill directories and their required reference files
EXPECTED_SKILLS = {
    "image-generation": {
        "references": ["backends.md", "extra_params.md", "editing.md"],
    },
    "video-generation": {
        "references": ["backends.md", "editing.md"],
    },
    "audio-generation": {
        "references": ["voices.md", "music_and_sfx.md", "advanced.md"],
    },
}


class TestSkillStructure:
    """Verify each modality skill has the correct directory structure."""

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_skill_directory_exists(self, skill_name: str) -> None:
        skill_dir = SKILLS_DIR / skill_name
        assert skill_dir.is_dir(), f"Skill directory missing: {skill_dir}"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_skill_md_exists(self, skill_name: str) -> None:
        skill_md = SKILLS_DIR / skill_name / "SKILL.md"
        assert skill_md.is_file(), f"SKILL.md missing: {skill_md}"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_references_directory_exists(self, skill_name: str) -> None:
        refs_dir = SKILLS_DIR / skill_name / "references"
        assert refs_dir.is_dir(), f"references/ directory missing: {refs_dir}"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_reference_files_exist(self, skill_name: str) -> None:
        refs_dir = SKILLS_DIR / skill_name / "references"
        expected_refs = EXPECTED_SKILLS[skill_name]["references"]
        for ref_file in expected_refs:
            ref_path = refs_dir / ref_file
            assert ref_path.is_file(), f"Reference file missing: {ref_path}"


class TestSkillFrontmatter:
    """Verify YAML frontmatter is valid and contains required fields."""

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_frontmatter_has_name(self, skill_name: str) -> None:
        frontmatter = _parse_frontmatter(SKILLS_DIR / skill_name / "SKILL.md")
        assert "name" in frontmatter, f"Missing 'name' in {skill_name} frontmatter"
        assert frontmatter["name"] == skill_name

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_frontmatter_has_description(self, skill_name: str) -> None:
        frontmatter = _parse_frontmatter(SKILLS_DIR / skill_name / "SKILL.md")
        assert "description" in frontmatter, f"Missing 'description' in {skill_name} frontmatter"
        assert len(frontmatter["description"]) > 20, "Description too short"
        assert len(frontmatter["description"]) <= 1024, "Description exceeds 1024 char limit"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_frontmatter_name_is_hyphen_case(self, skill_name: str) -> None:
        frontmatter = _parse_frontmatter(SKILLS_DIR / skill_name / "SKILL.md")
        name = frontmatter["name"]
        assert re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", name), f"Skill name '{name}' is not valid hyphen-case"


class TestSkillInternalLinks:
    """Verify markdown links in SKILL.md point to existing files."""

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_internal_links_resolve(self, skill_name: str) -> None:
        skill_dir = SKILLS_DIR / skill_name
        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text()

        # Find all markdown links to local files (not http)
        links = re.findall(r"\[.*?\]\(([^)]+)\)", content)
        local_links = [link for link in links if not link.startswith(("http://", "https://", "#"))]

        for link in local_links:
            target = skill_dir / link
            assert target.exists(), f"Broken link in {skill_name}/SKILL.md: {link} -> {target}"


class TestSkillContentAccuracy:
    """Verify skill content matches actual code behavior."""

    def test_image_skill_mentions_all_backends(self) -> None:
        content = (SKILLS_DIR / "image-generation" / "SKILL.md").read_text()
        for backend in ["google", "openai", "grok", "openrouter"]:
            assert backend.lower() in content.lower(), f"Image skill missing backend: {backend}"

    def test_video_skill_mentions_all_backends(self) -> None:
        content = (SKILLS_DIR / "video-generation" / "SKILL.md").read_text()
        for backend in ["grok", "google", "openai"]:
            assert backend.lower() in content.lower(), f"Video skill missing backend: {backend}"

    def test_audio_skill_mentions_all_backends(self) -> None:
        content = (SKILLS_DIR / "audio-generation" / "SKILL.md").read_text()
        for backend in ["elevenlabs", "openai"]:
            assert backend.lower() in content.lower(), f"Audio skill missing backend: {backend}"

    def test_image_skill_mentions_generate_media(self) -> None:
        content = (SKILLS_DIR / "image-generation" / "SKILL.md").read_text()
        assert "generate_media" in content

    def test_video_skill_mentions_generate_media(self) -> None:
        content = (SKILLS_DIR / "video-generation" / "SKILL.md").read_text()
        assert "generate_media" in content

    def test_audio_skill_mentions_generate_media(self) -> None:
        content = (SKILLS_DIR / "audio-generation" / "SKILL.md").read_text()
        assert "generate_media" in content

    def test_audio_skill_references_elevenlabs_repo(self) -> None:
        """Audio skill should link to ElevenLabs public skills repo."""
        content = (SKILLS_DIR / "audio-generation" / "SKILL.md").read_text()
        refs_content = (SKILLS_DIR / "audio-generation" / "references" / "advanced.md").read_text()
        combined = content + refs_content
        assert "github.com/elevenlabs/skills" in combined, "Audio skill should reference ElevenLabs skills repo"


class TestSymlinks:
    """Verify skill symlinks exist in .claude/skills/."""

    CLAUDE_SKILLS_DIR = Path(__file__).parent.parent.parent / ".claude" / "skills"

    def _require_claude_skills_dir(self) -> None:
        """Skip symlink checks when local Claude skills dir is not provisioned."""
        if not self.CLAUDE_SKILLS_DIR.exists():
            pytest.skip(
                f"Skipping symlink checks: local skills dir not found at {self.CLAUDE_SKILLS_DIR}",
            )

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_symlink_exists(self, skill_name: str) -> None:
        self._require_claude_skills_dir()
        symlink = self.CLAUDE_SKILLS_DIR / skill_name
        assert symlink.exists(), f"Symlink missing: {symlink}. " f"Run: ln -sf '../../massgen/skills/{skill_name}' " f"'.claude/skills/{skill_name}'"

    @pytest.mark.parametrize("skill_name", EXPECTED_SKILLS.keys())
    def test_symlink_target_resolves(self, skill_name: str) -> None:
        self._require_claude_skills_dir()
        symlink = self.CLAUDE_SKILLS_DIR / skill_name
        if symlink.is_symlink():
            target = symlink.resolve()
            assert target.is_dir(), f"Symlink target does not resolve to directory: {target}"


def _parse_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter from a markdown file."""
    content = path.read_text()
    if not content.startswith("---"):
        pytest.fail(f"No YAML frontmatter found in {path}")
    parts = content.split("---", 2)
    if len(parts) < 3:
        pytest.fail(f"Malformed YAML frontmatter in {path}")
    return yaml.safe_load(parts[1])
