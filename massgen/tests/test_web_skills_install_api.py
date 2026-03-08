"""Tests for Web UI skills install API."""

from fastapi.testclient import TestClient

from massgen.frontend.web.server import create_app
from massgen.utils import skills_installer


def test_skills_install_api_supports_remotion(monkeypatch):
    """API should install remotion via openskills-backed installer path."""
    calls = []

    monkeypatch.setattr(
        skills_installer,
        "install_openskills_cli",
        lambda: calls.append("openskills") or True,
    )
    monkeypatch.setattr(
        skills_installer,
        "install_remotion_skill",
        lambda: calls.append("remotion") or True,
    )

    app = create_app()
    client = TestClient(app)

    response = client.post("/api/skills/install", json={"package": "remotion"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert calls == ["openskills", "remotion"]
