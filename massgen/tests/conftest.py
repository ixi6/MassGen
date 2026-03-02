from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest


def _env_flag(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("massgen-triage")
    group.addoption(
        "--run-integration",
        action="store_true",
        default=_env_flag("RUN_INTEGRATION"),
        help="Run tests marked as integration scope (or set RUN_INTEGRATION=1).",
    )
    group.addoption(
        "--run-live-api",
        action="store_true",
        default=_env_flag("RUN_LIVE_API"),
        help="Run tests marked as live_api (real provider calls, may incur cost).",
    )
    group.addoption(
        "--run-docker",
        action="store_true",
        default=_env_flag("RUN_DOCKER"),
        help="Run tests marked as docker (or set RUN_DOCKER=1).",
    )
    group.addoption(
        "--run-expensive",
        action="store_true",
        default=_env_flag("RUN_EXPENSIVE"),
        help="Run tests marked as expensive (or set RUN_EXPENSIVE=1).",
    )
    group.addoption(
        "--xfail-expired-fail",
        action="store_true",
        default=_env_flag("XFAIL_EXPIRED_FAIL"),
        help="Fail the test session if any xfail registry entry is past expiry (or set XFAIL_EXPIRED_FAIL=1).",
    )
    group.addoption(
        "--xfail-registry",
        action="store",
        default=os.getenv("XFAIL_REGISTRY", "massgen/tests/xfail_registry.yml"),
        help="Path to xfail registry YAML (default: massgen/tests/xfail_registry.yml).",
    )


@dataclass(frozen=True)
class _XfailEntry:
    nodeid: str
    reason: str
    link: str | None
    expires: date | None
    strict: bool


_expired_xfails: list[_XfailEntry] = []


@pytest.fixture(scope="session", autouse=True)
def _isolate_test_logs(tmp_path_factory: pytest.TempPathFactory):
    """Route test-created logs to an isolated temp directory."""
    log_base_dir = tmp_path_factory.mktemp("massgen_test_logs")
    previous = os.environ.get("MASSGEN_LOG_BASE_DIR")
    os.environ["MASSGEN_LOG_BASE_DIR"] = str(log_base_dir)

    try:
        import massgen.logger_config as logger_config

        session = logger_config.LoggingSession.create()
        logger_config.set_current_session(session)
        logger_config.reset_logging_session()
    except Exception:
        pass

    try:
        yield
    finally:
        try:
            import massgen.logger_config as logger_config

            logger_config.reset_logging_session()
            logger_config._current_session.set(None)
        except Exception:
            pass

        if previous is None:
            os.environ.pop("MASSGEN_LOG_BASE_DIR", None)
        else:
            os.environ["MASSGEN_LOG_BASE_DIR"] = previous

        shutil.rmtree(log_base_dir, ignore_errors=True)


class MockLLMBackend:
    """Deterministic backend for tests that should not call external APIs."""

    def __init__(
        self,
        responses: list[str] | None = None,
        tool_call_responses: list[list[dict[str, Any]]] | None = None,
        provider_name: str = "mock_provider",
        stateful: bool = False,
        model: str = "mock-model",
    ):
        self.responses = responses or ["Mock response"]
        self.tool_call_responses = tool_call_responses or []
        self._call_count = 0
        self._provider_name = provider_name
        self._stateful = stateful
        self.config: dict[str, Any] = {"model": model}
        self.filesystem_manager = None
        self._current_stage = None
        self._planning_mode = False

    def is_stateful(self) -> bool:
        return self._stateful

    async def clear_history(self) -> None:
        return None

    async def reset_state(self) -> None:
        return None

    def set_stage(self, stage: Any) -> None:
        self._current_stage = stage

    def set_planning_mode(self, enabled: bool) -> None:
        self._planning_mode = enabled

    def get_provider_name(self) -> str:
        return self._provider_name

    def extract_tool_name(self, tool_call: dict[str, Any]) -> str:
        if "name" in tool_call:
            return str(tool_call.get("name", ""))
        if isinstance(tool_call.get("function"), dict):
            return str(tool_call["function"].get("name", ""))
        return ""

    def extract_tool_arguments(self, tool_call: dict[str, Any]) -> Any:
        if "arguments" in tool_call:
            return tool_call.get("arguments", {})
        if isinstance(tool_call.get("function"), dict):
            return tool_call["function"].get("arguments", {})
        return {}

    def create_tool_result_message(self, tool_call: dict[str, Any], result: str) -> dict[str, Any]:
        """Create a tool result message in chat-completions-compatible shape."""
        tool_call_id = str(tool_call.get("id", "mock_tool_call"))
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        }

    def filter_enforcement_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
        unknown_tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Default: return all calls (mock represents a non-Claude backend)."""
        return tool_calls

    async def stream_with_tools(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None, **kwargs):
        from massgen.backend.base import StreamChunk

        _ = (messages, tools, kwargs)
        response = self.responses[self._call_count % len(self.responses)]
        scripted_tool_calls: list[dict[str, Any]] | None = None
        if self._call_count < len(self.tool_call_responses):
            scripted_tool_calls = self.tool_call_responses[self._call_count]
        self._call_count += 1

        if scripted_tool_calls:
            yield StreamChunk(type="tool_calls", tool_calls=scripted_tool_calls)
        yield StreamChunk(type="content", content=response)
        yield StreamChunk(
            type="complete_message",
            complete_message={"role": "assistant", "content": response},
        )
        yield StreamChunk(type="done")


@pytest.fixture
def mock_backend():
    """Factory fixture for a deterministic mock backend."""

    def _factory(
        responses: list[str] | None = None,
        tool_call_responses: list[list[dict[str, Any]]] | None = None,
        provider_name: str = "mock_provider",
        stateful: bool = False,
        model: str = "mock-model",
    ) -> MockLLMBackend:
        return MockLLMBackend(
            responses=responses,
            tool_call_responses=tool_call_responses,
            provider_name=provider_name,
            stateful=stateful,
            model=model,
        )

    return _factory


@pytest.fixture
def mock_agent(mock_backend):
    """Factory fixture for SingleAgent instances backed by MockLLMBackend."""
    from massgen.chat_agent import SingleAgent

    def _factory(
        agent_id: str = "test_agent",
        responses: list[str] | None = None,
        system_message: str = "Test system message",
        backend_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        backend_kwargs = backend_kwargs or {}
        backend = mock_backend(
            responses=responses,
            **backend_kwargs,
        )
        return SingleAgent(
            backend=backend,
            agent_id=agent_id,
            system_message=system_message,
        )

    return _factory


@pytest.fixture
def mock_orchestrator(mock_agent):
    """Factory fixture for Orchestrator instances with deterministic mock agents."""
    from massgen.orchestrator import Orchestrator

    def _factory(
        num_agents: int = 2,
        agent_responses: list[list[str]] | None = None,
        config: Any | None = None,
    ) -> Any:
        agents: dict[str, Any] = {}
        for i in range(num_agents):
            agent_id = f"agent_{chr(ord('a') + i)}"
            responses = None
            if agent_responses and i < len(agent_responses):
                responses = agent_responses[i]
            agents[agent_id] = mock_agent(
                agent_id=agent_id,
                responses=responses,
                system_message=f"You are {agent_id}",
            )

        kwargs: dict[str, Any] = {"agents": agents}
        if config is not None:
            kwargs["config"] = config
        return Orchestrator(**kwargs)

    return _factory


def _parse_iso_date(d: Any) -> date | None:
    if d is None:
        return None
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        s = d.strip()
        if not s:
            return None
        # Support YYYY-MM-DD only; anything else is considered invalid and ignored.
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _load_xfail_registry(path: str) -> dict[str, _XfailEntry]:
    p = Path(path)
    if not p.exists():
        return {}

    try:
        import yaml  # type: ignore
    except Exception:
        # If YAML isn't available, skip registry application rather than breaking all tests.
        return {}

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {}

    entries: dict[str, _XfailEntry] = {}
    for nodeid, cfg in raw.items():
        if not isinstance(nodeid, str) or not nodeid.strip():
            continue
        if not isinstance(cfg, dict):
            continue
        reason = str(cfg.get("reason", "")).strip()
        if not reason:
            continue
        link = cfg.get("link")
        link_s = str(link).strip() if link is not None else None
        expires = _parse_iso_date(cfg.get("expires"))
        strict = bool(cfg.get("strict", True))
        entries[nodeid] = _XfailEntry(
            nodeid=nodeid,
            reason=reason,
            link=link_s,
            expires=expires,
            strict=strict,
        )
    return entries


def _should_skip_marker(item: pytest.Item, marker: str) -> bool:
    return item.get_closest_marker(marker) is not None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_integration = bool(config.getoption("--run-integration"))
    run_live_api = bool(config.getoption("--run-live-api"))
    run_docker = bool(config.getoption("--run-docker"))
    run_expensive = bool(config.getoption("--run-expensive"))
    xfail_registry_path = str(config.getoption("--xfail-registry"))

    # 1) Default policy: skip integration/live_api/docker/expensive unless explicitly enabled.
    skip_integration = pytest.mark.skip(reason="integration test (enable with --run-integration or RUN_INTEGRATION=1)")
    skip_live_api = pytest.mark.skip(reason="live API test (enable with --run-live-api or RUN_LIVE_API=1)")
    skip_docker = pytest.mark.skip(reason="docker test (enable with --run-docker or RUN_DOCKER=1)")
    skip_expensive = pytest.mark.skip(reason="expensive test (enable with --run-expensive or RUN_EXPENSIVE=1)")

    for item in items:
        if (not run_integration) and _should_skip_marker(item, "integration"):
            item.add_marker(skip_integration)
        if (not run_live_api) and _should_skip_marker(item, "live_api"):
            item.add_marker(skip_live_api)
        if (not run_docker) and _should_skip_marker(item, "docker"):
            item.add_marker(skip_docker)
        if (not run_expensive) and _should_skip_marker(item, "expensive"):
            item.add_marker(skip_expensive)

    # 2) Expiring xfail registry: apply known-failure tracking.
    registry = _load_xfail_registry(xfail_registry_path)
    if not registry:
        return

    today = datetime.now(timezone.utc).date()
    for item in items:
        entry = registry.get(item.nodeid)
        if entry is None:
            continue

        reason = entry.reason
        if entry.link:
            reason = f"{reason} ({entry.link})"
        item.add_marker(pytest.mark.xfail(reason=reason, strict=entry.strict))

        if entry.expires is not None and entry.expires < today:
            _expired_xfails.append(entry)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # Optional: fail if any xfail registry entries are expired.
    cfg = session.config
    if not bool(cfg.getoption("--xfail-expired-fail")):
        return
    if not _expired_xfails:
        return

    # Add a visible error summary and force non-zero exit.
    lines = [
        "Expired xfail registry entries detected (set XFAIL_EXPIRED_FAIL=0 to disable, but please fix/remove them):",
        *[f"- {e.nodeid} (expired: {e.expires}) :: {e.reason}" for e in _expired_xfails],
    ]
    session.config.warn("C1", "\n".join(lines))  # type: ignore[attr-defined]
    session.exitstatus = 1
