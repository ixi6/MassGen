"""Tests for Web UI setup status API."""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from massgen.frontend.web.server import create_app


def test_setup_status_prefers_project_config(monkeypatch, tmp_path) -> None:
    """Project-local quickstart config should satisfy setup checks."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    project_config = tmp_path / ".massgen" / "config.yaml"
    project_config.parent.mkdir(parents=True, exist_ok=True)
    project_config.write_text("agents: []\n", encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    with patch("massgen.utils.docker_diagnostics.diagnose_docker") as mock_diag:
        mock_diag.return_value = SimpleNamespace(
            is_available=False,
            status=SimpleNamespace(value="unavailable"),
            error_message="docker not running",
            resolution_steps=["start docker"],
        )
        response = client.get("/api/setup/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["needs_setup"] is False
    assert payload["has_config"] is True
    assert payload["config_path"] == str(project_config)


def test_providers_endpoint_prioritizes_agent_frameworks_and_marks_them() -> None:
    """Quickstart providers API should surface framework backends first with framework metadata."""
    app = create_app()
    client = TestClient(app)

    response = client.get("/api/providers")

    assert response.status_code == 200
    payload = response.json()
    provider_ids = [provider["id"] for provider in payload["providers"]]

    assert provider_ids[:3] == ["claude_code", "codex", "copilot"]

    providers_by_id = {provider["id"]: provider for provider in payload["providers"]}
    assert providers_by_id["claude_code"]["is_agent_framework"] is True
    assert providers_by_id["codex"]["is_agent_framework"] is True
    assert providers_by_id["copilot"]["is_agent_framework"] is True
    assert providers_by_id["openai"]["is_agent_framework"] is False


def test_setup_status_falls_back_to_global_config(monkeypatch, tmp_path) -> None:
    """Global config should be used when project config is absent."""
    monkeypatch.chdir(tmp_path)
    home_dir = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home_dir))

    global_config = home_dir / ".config" / "massgen" / "config.yaml"
    global_config.parent.mkdir(parents=True, exist_ok=True)
    global_config.write_text("agents: []\n", encoding="utf-8")

    app = create_app()
    client = TestClient(app)

    with patch("massgen.utils.docker_diagnostics.diagnose_docker") as mock_diag:
        mock_diag.return_value = SimpleNamespace(
            is_available=True,
            status=SimpleNamespace(value="available"),
            error_message=None,
            resolution_steps=[],
        )
        response = client.get("/api/setup/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["needs_setup"] is False
    assert payload["has_config"] is True
    assert payload["config_path"] == str(global_config)


def test_save_config_honors_project_location(monkeypatch, tmp_path) -> None:
    """Saving to the project location should write into ./.massgen."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/config/save",
        json={
            "yaml_content": "agents: []\n",
            "filename": "team.yaml",
            "save_location": "project",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    expected_path = tmp_path / ".massgen" / "team.yaml"
    assert payload["path"] == str(expected_path)
    assert expected_path.read_text(encoding="utf-8") == "agents: []\n"


def test_save_config_honors_global_location(monkeypatch, tmp_path) -> None:
    """Saving to the global location should write into ~/.config/massgen."""
    home_dir = tmp_path / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(home_dir))

    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/config/save",
        json={
            "yaml_content": "agents: []\n",
            "filename": "team.yaml",
            "save_location": "global",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    expected_path = home_dir / ".config" / "massgen" / "team.yaml"
    assert payload["path"] == str(expected_path)
    assert expected_path.read_text(encoding="utf-8") == "agents: []\n"


def test_generate_config_preserves_reasoning_and_decomposition(monkeypatch, tmp_path) -> None:
    """Web config generation should carry advanced agent and orchestration settings through to YAML."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/config/generate",
        json={
            "agents": [
                {
                    "id": "agent_a",
                    "provider": "openai",
                    "model": "gpt-5.4",
                    "reasoning_effort": "high",
                },
                {
                    "id": "agent_b",
                    "provider": "claude",
                    "model": "claude-opus-4-6",
                },
            ],
            "use_docker": False,
            "coordination": {
                "coordination_mode": "decomposition",
                "presenter_agent": "agent_b",
                "max_new_answers_per_agent": 2,
                "max_new_answers_global": 6,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["agents"][0]["backend"]["reasoning"] == {
        "effort": "high",
        "summary": "auto",
    }
    assert payload["config"]["orchestrator"]["coordination_mode"] == "decomposition"
    assert payload["config"]["orchestrator"]["presenter_agent"] == "agent_b"
    assert payload["config"]["orchestrator"]["voting_sensitivity"] == "checklist_gated"
    assert "answer_novelty_requirement" not in payload["config"]["orchestrator"]
    assert payload["config"]["orchestrator"]["max_new_answers_per_agent"] == 2
    assert payload["config"]["orchestrator"]["max_new_answers_global"] == 6


def test_quickstart_reasoning_profile_endpoint_supports_codex_xhigh() -> None:
    """Web quickstart should expose the same Codex reasoning choices as terminal quickstart."""
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/quickstart/reasoning-profile",
        params={"provider_id": "codex", "model": "gpt-5.4"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"]["default_effort"] == "high"
    assert [value for _, value in payload["profile"]["choices"]] == [
        "low",
        "medium",
        "high",
        "xhigh",
    ]


def test_quickstart_reasoning_profile_endpoint_uses_copilot_metadata(monkeypatch) -> None:
    """Web quickstart should surface Copilot runtime reasoning metadata through the shared endpoint."""
    monkeypatch.setattr(
        "massgen.config_builder.get_model_metadata_for_provider_sync",
        lambda provider, use_cache=True: [
            {
                "id": "gpt-5.4",
                "name": "GPT-5.4",
                "supported_reasoning_efforts": ["low", "medium", "high", "xhigh"],
                "default_reasoning_effort": "high",
            },
        ],
    )

    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/quickstart/reasoning-profile",
        params={"provider_id": "copilot", "model": "gpt-5.4"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"]["default_effort"] == "high"
    assert [value for _, value in payload["profile"]["choices"]] == [
        "low",
        "medium",
        "high",
        "xhigh",
    ]


def test_quickstart_reasoning_profile_endpoint_supports_claude_code_max() -> None:
    """Web quickstart should expose the same Claude Code reasoning choices as terminal quickstart."""
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/api/quickstart/reasoning-profile",
        params={"provider_id": "claude_code", "model": "claude-opus-4-6"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"]["default_effort"] == "high"
    assert [value for _, value in payload["profile"]["choices"]] == [
        "low",
        "medium",
        "high",
        "max",
    ]


def test_generate_config_preserves_codex_and_claude_code_reasoning(monkeypatch, tmp_path) -> None:
    """Web config generation should preserve quickstart-only xhigh/max reasoning values."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/config/generate",
        json={
            "agents": [
                {
                    "id": "agent_a",
                    "provider": "codex",
                    "model": "gpt-5.4",
                    "reasoning_effort": "xhigh",
                },
                {
                    "id": "agent_b",
                    "provider": "claude_code",
                    "model": "claude-opus-4-6",
                    "reasoning_effort": "max",
                },
            ],
            "use_docker": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["agents"][0]["backend"]["reasoning"] == {
        "effort": "xhigh",
        "summary": "auto",
    }
    assert payload["config"]["agents"][1]["backend"]["reasoning"] == {
        "effort": "max",
        "summary": "auto",
    }
