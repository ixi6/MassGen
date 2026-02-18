# -*- coding: utf-8 -*-
"""
Unit tests for the general hook framework.

Tests:
- HookEvent and HookResult dataclasses
- PatternHook matching
- PythonCallableHook execution
- GeneralHookManager registration and execution
- Built-in hooks (MidStreamInjection, HighPriorityTaskReminder)
"""

import json
from datetime import datetime, timezone

import pytest

from massgen.mcp_tools.hooks import (
    BackgroundToolCompleteHook,
    GeneralHookManager,
    HighPriorityTaskReminderHook,
    HookEvent,
    HookResult,
    HookType,
    MidStreamInjectionHook,
    PatternHook,
    PythonCallableHook,
)

# =============================================================================
# HookEvent Tests
# =============================================================================


class TestHookEvent:
    """Tests for HookEvent dataclass."""

    def test_basic_creation(self):
        """Test basic HookEvent creation."""
        event = HookEvent(
            hook_type="PreToolUse",
            session_id="session-123",
            orchestrator_id="orch-456",
            agent_id="agent-1",
            timestamp=datetime.now(timezone.utc),
            tool_name="my_tool",
            tool_input={"arg1": "value1"},
        )
        assert event.hook_type == "PreToolUse"
        assert event.tool_name == "my_tool"
        assert event.tool_input == {"arg1": "value1"}
        assert event.tool_output is None

    def test_post_tool_use_with_output(self):
        """Test PostToolUse event with tool output."""
        event = HookEvent(
            hook_type="PostToolUse",
            session_id="session-123",
            orchestrator_id="orch-456",
            agent_id="agent-1",
            timestamp=datetime.now(timezone.utc),
            tool_name="my_tool",
            tool_input={"arg1": "value1"},
            tool_output="Tool result here",
        )
        assert event.tool_output == "Tool result here"

    def test_to_dict(self):
        """Test conversion to dictionary."""
        now = datetime.now(timezone.utc)
        event = HookEvent(
            hook_type="PreToolUse",
            session_id="s123",
            orchestrator_id="o456",
            agent_id="a1",
            timestamp=now,
            tool_name="test",
            tool_input={"key": "val"},
        )
        d = event.to_dict()
        assert d["hook_type"] == "PreToolUse"
        assert d["timestamp"] == now.isoformat()
        assert d["tool_input"] == {"key": "val"}

    def test_to_json(self):
        """Test JSON serialization."""
        event = HookEvent(
            hook_type="PreToolUse",
            session_id="s123",
            orchestrator_id="o456",
            agent_id="a1",
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
            tool_name="test",
            tool_input={},
        )
        j = event.to_json()
        parsed = json.loads(j)
        assert parsed["tool_name"] == "test"


# =============================================================================
# HookResult Tests
# =============================================================================


class TestHookResult:
    """Tests for HookResult dataclass."""

    def test_default_values(self):
        """Test default HookResult values."""
        result = HookResult()
        assert result.allowed is True
        assert result.decision == "allow"
        assert result.inject is None

    def test_deny_result(self):
        """Test deny result creation."""
        result = HookResult.deny(reason="Permission denied")
        assert result.allowed is False
        assert result.decision == "deny"
        assert result.reason == "Permission denied"

    def test_ask_result(self):
        """Test ask result creation."""
        result = HookResult.ask(reason="Need confirmation")
        assert result.allowed is True  # Still allowed until user denies
        assert result.decision == "ask"
        assert result.reason == "Need confirmation"

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "allowed": True,
            "decision": "allow",
            "inject": {"content": "injected", "strategy": "tool_result"},
        }
        result = HookResult.from_dict(data)
        assert result.inject == {"content": "injected", "strategy": "tool_result"}

    def test_sync_decision_allowed(self):
        """Test that allowed syncs with decision."""
        result = HookResult(allowed=False)
        assert result.decision == "deny"

    def test_sync_allowed_decision(self):
        """Test that decision syncs with allowed."""
        result = HookResult(decision="deny")
        assert result.allowed is False


# =============================================================================
# PatternHook Tests
# =============================================================================


class TestPatternHook:
    """Tests for pattern matching in hooks."""

    def test_wildcard_match(self):
        """Test wildcard pattern matching."""

        class TestHook(PatternHook):
            async def execute(self, *args, **kwargs):
                return HookResult.allow()

        hook = TestHook("test", matcher="*")
        assert hook.matches("any_tool_name")
        assert hook.matches("another_tool")

    def test_exact_match(self):
        """Test exact pattern matching."""

        class TestHook(PatternHook):
            async def execute(self, *args, **kwargs):
                return HookResult.allow()

        hook = TestHook("test", matcher="specific_tool")
        assert hook.matches("specific_tool")
        assert not hook.matches("other_tool")

    def test_prefix_match(self):
        """Test prefix pattern matching with *."""

        class TestHook(PatternHook):
            async def execute(self, *args, **kwargs):
                return HookResult.allow()

        hook = TestHook("test", matcher="mcp__*")
        assert hook.matches("mcp__read_file")
        assert hook.matches("mcp__write_file")
        assert not hook.matches("custom_read_file")

    def test_or_pattern(self):
        """Test OR pattern matching with |."""

        class TestHook(PatternHook):
            async def execute(self, *args, **kwargs):
                return HookResult.allow()

        hook = TestHook("test", matcher="read_file|write_file|execute_command")
        assert hook.matches("read_file")
        assert hook.matches("write_file")
        assert hook.matches("execute_command")
        assert not hook.matches("delete_file")


# =============================================================================
# PythonCallableHook Tests
# =============================================================================


class TestPythonCallableHook:
    """Tests for Python callable hooks."""

    @pytest.mark.asyncio
    async def test_sync_callable(self):
        """Test with a sync callable."""

        def my_hook(event: HookEvent) -> HookResult:
            return HookResult.allow()

        hook = PythonCallableHook("test", my_hook)
        result = await hook.execute("tool_name", "{}")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_async_callable(self):
        """Test with an async callable."""

        async def my_hook(event: HookEvent) -> HookResult:
            return HookResult.deny(reason="Test deny")

        hook = PythonCallableHook("test", my_hook)
        result = await hook.execute("tool_name", "{}")
        assert result.allowed is False
        assert result.reason == "Test deny"

    @pytest.mark.asyncio
    async def test_callable_returning_dict(self):
        """Test with a callable returning dict."""

        def my_hook(event: HookEvent) -> dict:
            return {"allowed": True, "inject": {"content": "test"}}

        hook = PythonCallableHook("test", my_hook)
        result = await hook.execute("tool_name", "{}")
        assert result.inject == {"content": "test"}

    @pytest.mark.asyncio
    async def test_pattern_non_match_returns_allow(self):
        """Test that non-matching patterns return allow."""

        def my_hook(event: HookEvent) -> HookResult:
            return HookResult.deny()

        hook = PythonCallableHook("test", my_hook, matcher="specific_tool")
        result = await hook.execute("other_tool", "{}")
        assert result.allowed is True  # Non-match returns allow

    @pytest.mark.asyncio
    async def test_modified_arguments(self):
        """Test hook that modifies arguments."""

        def my_hook(event: HookEvent) -> HookResult:
            return HookResult(
                allowed=True,
                updated_input={"modified": True},
            )

        hook = PythonCallableHook("test", my_hook)
        result = await hook.execute("tool_name", '{"original": true}')
        assert result.updated_input == {"modified": True}

    @pytest.mark.asyncio
    async def test_fail_open_on_error_by_default(self):
        """Test that hooks fail open (allow) on errors by default."""

        def failing_hook(event: HookEvent) -> HookResult:
            raise RuntimeError("Hook crashed!")

        hook = PythonCallableHook("test", failing_hook)
        result = await hook.execute("tool_name", "{}")
        # Default is fail-open: allow execution despite error
        assert result.allowed is True
        assert result.decision == "allow"

    @pytest.mark.asyncio
    async def test_fail_closed_on_error_when_configured(self):
        """Test that hooks fail closed (deny) on errors when fail_closed=True."""

        def failing_hook(event: HookEvent) -> HookResult:
            raise RuntimeError("Hook crashed!")

        hook = PythonCallableHook("test", failing_hook, fail_closed=True)
        result = await hook.execute("tool_name", "{}")
        # fail_closed=True: deny execution on error
        assert result.allowed is False
        assert result.decision == "deny"
        assert "failed" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_fail_closed_on_timeout(self):
        """Test that hooks fail closed on timeout when fail_closed=True."""
        import asyncio

        async def slow_hook(event: HookEvent) -> HookResult:
            await asyncio.sleep(10)  # Will timeout
            return HookResult.allow()

        # Very short timeout to trigger timeout error
        hook = PythonCallableHook("test", slow_hook, timeout=0.01, fail_closed=True)
        result = await hook.execute("tool_name", "{}")
        assert result.allowed is False
        assert result.decision == "deny"
        assert "timed out" in result.reason.lower()


# =============================================================================
# GeneralHookManager Tests
# =============================================================================


class TestGeneralHookManager:
    """Tests for GeneralHookManager."""

    def test_register_global_hook(self):
        """Test global hook registration."""
        manager = GeneralHookManager()

        def my_hook(event):
            return HookResult.allow()

        hook = PythonCallableHook("test", my_hook)
        manager.register_global_hook(HookType.PRE_TOOL_USE, hook)

        hooks = manager.get_hooks_for_agent(None, HookType.PRE_TOOL_USE)
        assert len(hooks) == 1
        assert hooks[0].name == "test"

    def test_register_agent_hook(self):
        """Test agent-specific hook registration."""
        manager = GeneralHookManager()

        def my_hook(event):
            return HookResult.allow()

        hook = PythonCallableHook("test", my_hook)
        manager.register_agent_hook("agent-1", HookType.PRE_TOOL_USE, hook)

        # Agent-1 gets the hook
        hooks = manager.get_hooks_for_agent("agent-1", HookType.PRE_TOOL_USE)
        assert len(hooks) == 1

        # Other agents don't
        hooks = manager.get_hooks_for_agent("agent-2", HookType.PRE_TOOL_USE)
        assert len(hooks) == 0

    def test_agent_override(self):
        """Test agent override disables global hooks."""
        manager = GeneralHookManager()

        def global_hook(event):
            return HookResult.allow()

        def agent_hook(event):
            return HookResult.allow()

        g_hook = PythonCallableHook("global", global_hook)
        a_hook = PythonCallableHook("agent", agent_hook)

        manager.register_global_hook(HookType.PRE_TOOL_USE, g_hook)
        manager.register_agent_hook(
            "agent-1",
            HookType.PRE_TOOL_USE,
            a_hook,
            override=True,
        )

        # Agent-1 only gets agent hook (override)
        hooks = manager.get_hooks_for_agent("agent-1", HookType.PRE_TOOL_USE)
        assert len(hooks) == 1
        assert hooks[0].name == "agent"

        # Other agents get global hook
        hooks = manager.get_hooks_for_agent("agent-2", HookType.PRE_TOOL_USE)
        assert len(hooks) == 1
        assert hooks[0].name == "global"

    @pytest.mark.asyncio
    async def test_execute_hooks_deny_short_circuits(self):
        """Test that deny result short-circuits hook execution."""
        manager = GeneralHookManager()

        def deny_hook(event):
            return HookResult.deny(reason="Denied!")

        def allow_hook(event):
            return HookResult.allow()

        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            PythonCallableHook("deny", deny_hook),
        )
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            PythonCallableHook("allow", allow_hook),
        )

        result = await manager.execute_hooks(
            HookType.PRE_TOOL_USE,
            "tool",
            "{}",
            {},
        )
        assert result.decision == "deny"
        assert "Denied!" in result.reason

    @pytest.mark.asyncio
    async def test_execute_hooks_aggregates_injections(self):
        """Test that PostToolUse hooks aggregate injection content."""
        manager = GeneralHookManager()

        def hook1(event):
            return HookResult(inject={"content": "First", "strategy": "tool_result"})

        def hook2(event):
            return HookResult(inject={"content": "Second", "strategy": "tool_result"})

        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            PythonCallableHook("h1", hook1),
        )
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            PythonCallableHook("h2", hook2),
        )

        result = await manager.execute_hooks(
            HookType.POST_TOOL_USE,
            "tool",
            "{}",
            {},
            tool_output="output",
        )
        assert "First" in result.inject["content"]
        assert "Second" in result.inject["content"]

    def test_register_hooks_from_config(self):
        """Test configuration-based hook registration."""
        manager = GeneralHookManager()

        config = {
            "PreToolUse": [
                {"handler": "massgen.mcp_tools.hooks.HookResult.allow", "matcher": "*"},
            ],
            "PostToolUse": [
                {"handler": "massgen.mcp_tools.hooks.HookResult.allow", "matcher": "*"},
            ],
        }

        manager.register_hooks_from_config(config)

        pre_hooks = manager.get_hooks_for_agent(None, HookType.PRE_TOOL_USE)
        post_hooks = manager.get_hooks_for_agent(None, HookType.POST_TOOL_USE)
        assert len(pre_hooks) == 1
        assert len(post_hooks) == 1

    @pytest.mark.asyncio
    async def test_deny_with_pattern_only_blocks_matching_tools(self):
        """Test that deny hook with pattern only blocks matching tools."""
        manager = GeneralHookManager()

        def deny_dangerous_tools(event):
            return HookResult.deny(reason="Dangerous tool blocked")

        # Register deny hook only for Write and Delete tools
        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            PythonCallableHook("block_writes", deny_dangerous_tools, matcher="Write|Delete"),
        )

        # Write tool should be blocked
        result = await manager.execute_hooks(
            HookType.PRE_TOOL_USE,
            "Write",
            '{"file": "test.txt"}',
            {},
        )
        assert result.decision == "deny"
        assert result.allowed is False
        assert "Dangerous tool blocked" in result.reason

        # Delete tool should be blocked
        result = await manager.execute_hooks(
            HookType.PRE_TOOL_USE,
            "Delete",
            '{"file": "test.txt"}',
            {},
        )
        assert result.decision == "deny"
        assert result.allowed is False

        # Read tool should be allowed (doesn't match pattern)
        result = await manager.execute_hooks(
            HookType.PRE_TOOL_USE,
            "Read",
            '{"file": "test.txt"}',
            {},
        )
        assert result.decision == "allow"
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_deny_propagates_reason_correctly(self):
        """Test that deny reason is properly propagated through hook execution."""
        manager = GeneralHookManager()

        custom_reason = "Access denied: insufficient permissions for /etc/passwd"

        def security_check(event):
            # Check if trying to access sensitive files
            tool_input = event.tool_input
            if tool_input.get("file_path", "").startswith("/etc/"):
                return HookResult.deny(reason=custom_reason)
            return HookResult.allow()

        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            PythonCallableHook("security", security_check, matcher="*"),
        )

        # Access to /etc should be denied with specific reason
        result = await manager.execute_hooks(
            HookType.PRE_TOOL_USE,
            "Read",
            '{"file_path": "/etc/passwd"}',
            {},
        )
        assert result.decision == "deny"
        assert result.reason == custom_reason

        # Access to /home should be allowed
        result = await manager.execute_hooks(
            HookType.PRE_TOOL_USE,
            "Read",
            '{"file_path": "/home/user/file.txt"}',
            {},
        )
        assert result.decision == "allow"


# =============================================================================
# Built-in Hook Tests
# =============================================================================


class TestMidStreamInjectionHook:
    """Tests for MidStreamInjectionHook."""

    @pytest.mark.asyncio
    async def test_no_callback_returns_allow(self):
        """Test hook without callback returns allow."""
        hook = MidStreamInjectionHook()
        result = await hook.execute("tool", "{}")
        assert result.allowed is True
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_callback_returns_none(self):
        """Test hook with callback returning None."""
        hook = MidStreamInjectionHook()
        hook.set_callback(lambda: None)
        result = await hook.execute("tool", "{}")
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_callback_returns_content(self):
        """Test hook with callback returning content."""
        hook = MidStreamInjectionHook()
        hook.set_callback(lambda: "Injected content from other agent")
        result = await hook.execute("tool", "{}")
        assert result.inject is not None
        assert result.inject["content"] == "Injected content from other agent"
        assert result.inject["strategy"] == "tool_result"


class TestHighPriorityTaskReminderHook:
    """Tests for HighPriorityTaskReminderHook."""

    @pytest.mark.asyncio
    async def test_no_output_returns_allow(self):
        """Test hook without tool output returns allow."""
        hook = HighPriorityTaskReminderHook()
        result = await hook.execute("mcp__planning__update_task_status", "{}", {})
        assert result.allowed is True
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_non_matching_tool_returns_allow(self):
        """Test hook with non-matching tool name returns allow without checking output."""
        hook = HighPriorityTaskReminderHook()
        # Even with valid high-priority task output, should not inject for wrong tool
        tool_output = json.dumps(
            {
                "task": {"priority": "high", "status": "completed"},
                "newly_ready_tasks": [],
            },
        )
        result = await hook.execute(
            "other_tool",
            "{}",
            {"tool_output": tool_output},
        )
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_non_json_output_returns_allow(self):
        """Test hook with non-JSON output returns allow."""
        hook = HighPriorityTaskReminderHook()
        result = await hook.execute(
            "mcp__planning__update_task_status",
            "{}",
            {"tool_output": "plain text output"},
        )
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_low_priority_task_returns_allow(self):
        """Test hook with low-priority completed task returns allow."""
        hook = HighPriorityTaskReminderHook()
        tool_output = json.dumps(
            {
                "task": {"priority": "low", "status": "completed"},
                "newly_ready_tasks": [],
            },
        )
        result = await hook.execute(
            "mcp__planning__update_task_status",
            "{}",
            {"tool_output": tool_output},
        )
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_high_priority_incomplete_task_returns_allow(self):
        """Test hook with high-priority but incomplete task returns allow."""
        hook = HighPriorityTaskReminderHook()
        tool_output = json.dumps(
            {
                "task": {"priority": "high", "status": "in_progress"},
                "newly_ready_tasks": [],
            },
        )
        result = await hook.execute(
            "mcp__planning__update_task_status",
            "{}",
            {"tool_output": tool_output},
        )
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_high_priority_completed_task_injects_reminder(self):
        """Test hook injects reminder for high-priority completed task."""
        hook = HighPriorityTaskReminderHook()
        tool_output = json.dumps(
            {
                "task": {"priority": "high", "status": "completed"},
                "newly_ready_tasks": [],
            },
        )
        result = await hook.execute(
            "mcp__planning__update_task_status",
            "{}",
            {"tool_output": tool_output},
        )
        assert result.inject is not None
        # Reminder should be formatted with SYSTEM REMINDER header and borders
        assert "High-priority task completed" in result.inject["content"]
        assert "SYSTEM REMINDER" in result.inject["content"]
        assert "=" * 60 in result.inject["content"]  # Border separator
        assert "memory/long_term" in result.inject["content"]  # Memory paths
        assert result.inject["strategy"] == "user_message"


# =============================================================================
# HookResult Error Tracking Tests
# =============================================================================


class TestHookResultErrorTracking:
    """Tests for HookResult error tracking functionality."""

    def test_add_error(self):
        """Test adding errors to HookResult."""
        result = HookResult.allow()
        result.add_error("First error")
        result.add_error("Second error")
        assert len(result.hook_errors) == 2
        assert "First error" in result.hook_errors
        assert "Second error" in result.hook_errors

    def test_has_errors(self):
        """Test has_errors method."""
        result = HookResult.allow()
        assert not result.has_errors()
        result.add_error("Error occurred")
        assert result.has_errors()

    def test_from_dict_with_errors(self):
        """Test creating HookResult from dict with errors."""
        data = {
            "allowed": True,
            "hook_errors": ["error1", "error2"],
        }
        result = HookResult.from_dict(data)
        assert result.hook_errors == ["error1", "error2"]
        assert result.has_errors()

    def test_default_empty_errors(self):
        """Test that hook_errors defaults to empty list."""
        result = HookResult()
        assert result.hook_errors == []
        assert not result.has_errors()


class TestMidStreamInjectionHookErrorHandling:
    """Tests for MidStreamInjectionHook error handling."""

    @pytest.mark.asyncio
    async def test_callback_exception_tracks_error(self):
        """Test that callback exceptions are tracked in result."""
        hook = MidStreamInjectionHook()

        def failing_callback():
            raise RuntimeError("Callback crashed!")

        hook.set_callback(failing_callback)
        result = await hook.execute("tool", "{}")

        # Should allow (fail-open) but track the error
        assert result.allowed is True
        assert result.has_errors()
        assert any("Callback crashed" in err for err in result.hook_errors)
        assert result.metadata.get("injection_skipped") is True

    @pytest.mark.asyncio
    async def test_async_callback_returns_content(self):
        """Test hook with async callback returning content."""
        import asyncio

        hook = MidStreamInjectionHook()

        async def async_callback():
            await asyncio.sleep(0.01)
            return "Async injected content"

        hook.set_callback(async_callback)
        result = await hook.execute("tool", "{}")
        assert result.inject is not None
        assert result.inject["content"] == "Async injected content"

    @pytest.mark.asyncio
    async def test_async_callback_returns_none(self):
        """Test hook with async callback returning None."""

        async def async_callback():
            return None

        hook = MidStreamInjectionHook()
        hook.set_callback(async_callback)
        result = await hook.execute("tool", "{}")
        assert result.inject is None


class TestGeneralHookManagerErrorTracking:
    """Tests for GeneralHookManager error tracking in execute_hooks."""

    @pytest.mark.asyncio
    async def test_execute_hooks_tracks_errors_on_unexpected_exception(self):
        """Test that unexpected exceptions in hook execution are tracked."""
        manager = GeneralHookManager()

        # Create a hook subclass that raises in execute() to bypass PythonCallableHook's try-except
        class FailingHook(PatternHook):
            async def execute(self, *args, **kwargs):
                raise RuntimeError("Unexpected hook failure!")

        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            FailingHook("failing", matcher="*"),
        )

        result = await manager.execute_hooks(
            HookType.PRE_TOOL_USE,
            "tool",
            "{}",
            {},
        )

        # Should allow (fail-open) but track the error
        assert result.allowed is True
        assert result.has_errors()
        assert any("failing" in err.lower() for err in result.hook_errors)

    @pytest.mark.asyncio
    async def test_execute_hooks_fail_closed_denies_on_error(self):
        """Test that fail_closed hooks deny on error."""
        manager = GeneralHookManager()

        def failing_hook(event):
            raise RuntimeError("Hook crashed!")

        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            PythonCallableHook("failing", failing_hook, fail_closed=True),
        )

        result = await manager.execute_hooks(
            HookType.PRE_TOOL_USE,
            "tool",
            "{}",
            {},
        )

        # Should deny due to fail_closed=True
        assert result.allowed is False
        assert result.decision == "deny"

    @pytest.mark.asyncio
    async def test_execute_hooks_propagates_child_errors(self):
        """Test that errors from hook results are propagated to final result."""
        manager = GeneralHookManager()

        def hook_with_errors(event):
            result = HookResult.allow()
            result.add_error("Error from child hook")
            return result

        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            PythonCallableHook("with_errors", hook_with_errors),
        )

        result = await manager.execute_hooks(
            HookType.PRE_TOOL_USE,
            "tool",
            "{}",
            {},
        )

        # Should propagate errors from child hooks
        assert result.allowed is True
        assert result.has_errors()
        assert "Error from child hook" in result.hook_errors


# =============================================================================
# Native Hook Adapter Tests
# =============================================================================


class TestNativeHookAdapterBase:
    """Tests for NativeHookAdapter base class."""

    def test_create_hook_event_from_native(self):
        """Test creating HookEvent from native input."""
        from massgen.mcp_tools.native_hook_adapters.base import NativeHookAdapter

        native_input = {
            "tool_name": "test_tool",
            "tool_input": {"arg1": "value1"},
            "tool_output": "output result",
        }
        context = {
            "session_id": "sess-123",
            "orchestrator_id": "orch-456",
            "agent_id": "agent-1",
        }

        event = NativeHookAdapter.create_hook_event_from_native(
            native_input,
            HookType.POST_TOOL_USE,
            context,
        )

        assert event.tool_name == "test_tool"
        assert event.tool_input == {"arg1": "value1"}
        assert event.tool_output == "output result"
        assert event.session_id == "sess-123"
        assert event.orchestrator_id == "orch-456"
        assert event.agent_id == "agent-1"
        assert event.hook_type == "PostToolUse"

    def test_create_hook_event_with_empty_input(self):
        """Test creating HookEvent with minimal native input."""
        from massgen.mcp_tools.native_hook_adapters.base import NativeHookAdapter

        native_input = {}
        context = {}

        event = NativeHookAdapter.create_hook_event_from_native(
            native_input,
            HookType.PRE_TOOL_USE,
            context,
        )

        assert event.tool_name == ""
        assert event.tool_input == {}
        assert event.tool_output is None
        assert event.session_id == ""
        assert event.hook_type == "PreToolUse"

    def test_convert_hook_result_to_native_raises(self):
        """Test that base class raises NotImplementedError."""
        from massgen.mcp_tools.native_hook_adapters.base import NativeHookAdapter

        with pytest.raises(NotImplementedError):
            NativeHookAdapter.convert_hook_result_to_native(
                HookResult.allow(),
                HookType.PRE_TOOL_USE,
            )


# Only run Claude SDK adapter tests if SDK is available
try:
    from claude_agent_sdk import HookMatcher

    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False


@pytest.mark.skipif(not CLAUDE_SDK_AVAILABLE, reason="Claude Agent SDK not installed")
class TestClaudeCodeNativeHookAdapter:
    """Tests for ClaudeCodeNativeHookAdapter."""

    def test_supports_pre_and_post_tool_use(self):
        """Test that adapter supports both PreToolUse and PostToolUse."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()
        assert adapter.supports_hook_type(HookType.PRE_TOOL_USE)
        assert adapter.supports_hook_type(HookType.POST_TOOL_USE)

    def test_convert_deny_result_to_claude_format(self):
        """Test converting deny result to Claude SDK format."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()
        result = HookResult.deny(reason="Access denied")

        claude_format = adapter._convert_result_to_claude_format(
            result,
            HookType.PRE_TOOL_USE,
        )

        assert "hookSpecificOutput" in claude_format
        assert claude_format["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "Access denied" in claude_format["hookSpecificOutput"]["permissionDecisionReason"]

    def test_convert_ask_result_to_claude_format(self):
        """Test converting ask result to Claude SDK format."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()
        result = HookResult.ask(reason="Needs confirmation")

        claude_format = adapter._convert_result_to_claude_format(
            result,
            HookType.PRE_TOOL_USE,
        )

        # ask maps to deny with confirmation message
        assert claude_format["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "confirmation" in claude_format["hookSpecificOutput"]["permissionDecisionReason"].lower()

    def test_convert_allow_result_to_claude_format(self):
        """Test converting allow result to Claude SDK format."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()
        result = HookResult.allow()

        claude_format = adapter._convert_result_to_claude_format(
            result,
            HookType.PRE_TOOL_USE,
        )

        # Allow returns empty dict
        assert claude_format == {}

    def test_convert_injection_result_to_claude_format(self):
        """Test converting PostToolUse injection result to Claude SDK format."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()
        result = HookResult(
            allowed=True,
            inject={"content": "Injected content", "strategy": "tool_result"},
        )

        claude_format = adapter._convert_result_to_claude_format(
            result,
            HookType.POST_TOOL_USE,
        )

        assert "hookSpecificOutput" in claude_format
        assert claude_format["hookSpecificOutput"]["modifiedOutput"] == "Injected content"
        assert claude_format["hookSpecificOutput"]["injectionStrategy"] == "tool_result"

    def test_convert_modified_input_to_claude_format(self):
        """Test converting PreToolUse modified input result to Claude SDK format."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()
        result = HookResult(
            allowed=True,
            updated_input={"modified_arg": "new_value"},
        )

        claude_format = adapter._convert_result_to_claude_format(
            result,
            HookType.PRE_TOOL_USE,
        )

        assert "hookSpecificOutput" in claude_format
        assert claude_format["hookSpecificOutput"]["updatedInput"] == {"modified_arg": "new_value"}
        assert claude_format["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_convert_hook_to_native_returns_hook_matcher(self):
        """Test that convert_hook_to_native returns a HookMatcher."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()

        def my_hook(event):
            return HookResult.allow()

        hook = PythonCallableHook("test", my_hook, matcher="Write|Edit")

        native = adapter.convert_hook_to_native(hook, HookType.PRE_TOOL_USE)

        assert isinstance(native, HookMatcher)
        assert native.matcher == "Write|Edit"
        assert len(native.hooks) == 1

    def test_build_native_hooks_config(self):
        """Test building complete native hooks config from GeneralHookManager."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()
        manager = GeneralHookManager()

        def pre_hook(event):
            return HookResult.allow()

        def post_hook(event):
            return HookResult.allow()

        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            PythonCallableHook("pre", pre_hook),
        )
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            PythonCallableHook("post", post_hook),
        )

        config = adapter.build_native_hooks_config(manager)

        assert "PreToolUse" in config
        assert "PostToolUse" in config
        assert len(config["PreToolUse"]) == 1
        assert len(config["PostToolUse"]) == 1

    def test_merge_native_configs(self):
        """Test merging multiple native configs."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()

        def hook1(event):
            return HookResult.allow()

        def hook2(event):
            return HookResult.allow()

        matcher1 = HookMatcher(matcher="*", hooks=[hook1])
        matcher2 = HookMatcher(matcher="Write", hooks=[hook2])

        config1 = {"PreToolUse": [matcher1]}
        config2 = {"PreToolUse": [matcher2], "PostToolUse": [matcher1]}

        merged = adapter.merge_native_configs(config1, config2)

        assert len(merged["PreToolUse"]) == 2
        assert len(merged["PostToolUse"]) == 1

    def test_merge_native_configs_with_empty(self):
        """Test merging with empty configs."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()

        def hook(event):
            return HookResult.allow()

        matcher = HookMatcher(matcher="*", hooks=[hook])
        config = {"PreToolUse": [matcher]}

        merged = adapter.merge_native_configs(config, {}, None)

        assert len(merged["PreToolUse"]) == 1

    @pytest.mark.asyncio
    async def test_hook_wrapper_executes_hook(self):
        """Test that the hook wrapper correctly executes MassGen hooks."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()
        executed = []

        def tracking_hook(event):
            executed.append(event.tool_name)
            return HookResult.allow()

        hook = PythonCallableHook("tracker", tracking_hook, matcher="*")
        native = adapter.convert_hook_to_native(hook, HookType.PRE_TOOL_USE)

        # Call the wrapper directly
        wrapper_func = native.hooks[0]
        input_data = {"tool_name": "TestTool", "tool_input": {"arg": "val"}}

        result = await wrapper_func(input_data, "tool-use-123", None)

        assert "TestTool" in executed
        assert result == {}  # Allow returns empty dict

    @pytest.mark.asyncio
    async def test_hook_wrapper_pattern_mismatch_returns_allow(self):
        """Test that pattern mismatch in wrapper returns allow (empty dict)."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()

        def deny_hook(event):
            return HookResult.deny(reason="Should not be called")

        hook = PythonCallableHook("deny", deny_hook, matcher="SpecificTool")
        native = adapter.convert_hook_to_native(hook, HookType.PRE_TOOL_USE)

        wrapper_func = native.hooks[0]
        input_data = {"tool_name": "OtherTool", "tool_input": {}}

        result = await wrapper_func(input_data, "tool-use-123", None)

        # Pattern didn't match, so should return empty (allow)
        assert result == {}

    @pytest.mark.asyncio
    async def test_hook_wrapper_fail_open_on_error(self):
        """Test that hook wrapper fails open by default."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()

        def failing_hook(event):
            raise RuntimeError("Hook crashed!")

        hook = PythonCallableHook("failing", failing_hook, matcher="*", fail_closed=False)
        native = adapter.convert_hook_to_native(hook, HookType.PRE_TOOL_USE)

        wrapper_func = native.hooks[0]
        input_data = {"tool_name": "TestTool", "tool_input": {}}

        result = await wrapper_func(input_data, "tool-use-123", None)

        # Should return empty dict (allow) on error with fail_closed=False
        assert result == {}

    @pytest.mark.asyncio
    async def test_hook_wrapper_fail_closed_on_error(self):
        """Test that hook wrapper fails closed when configured."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        adapter = ClaudeCodeNativeHookAdapter()

        def failing_hook(event):
            raise RuntimeError("Hook crashed!")

        hook = PythonCallableHook("failing", failing_hook, matcher="*", fail_closed=True)
        native = adapter.convert_hook_to_native(hook, HookType.PRE_TOOL_USE)

        wrapper_func = native.hooks[0]
        input_data = {"tool_name": "TestTool", "tool_input": {}}

        result = await wrapper_func(input_data, "tool-use-123", None)

        # Should return deny on error with fail_closed=True
        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        # Error message format is "Hook {name} failed: {error}"
        assert "failed" in result["hookSpecificOutput"]["permissionDecisionReason"].lower()


# =============================================================================
# SubagentCompleteHook Tests
# =============================================================================


class TestSubagentCompleteHook:
    """Tests for SubagentCompleteHook - injects async subagent results."""

    @pytest.mark.asyncio
    async def test_no_pending_results_returns_allow(self):
        """Test hook returns allow when no pending results."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook

        hook = SubagentCompleteHook()
        result = await hook.execute("some_tool", "{}")

        assert result.allowed is True
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_no_getter_returns_allow(self):
        """Test hook returns allow when no getter is set."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook

        hook = SubagentCompleteHook()
        # Don't set a getter
        result = await hook.execute("some_tool", "{}")

        assert result.allowed is True
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_getter_returns_empty_list_returns_allow(self):
        """Test hook returns allow when getter returns empty list."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook

        hook = SubagentCompleteHook()
        hook.set_pending_results_getter(lambda: [])

        result = await hook.execute("some_tool", "{}")

        assert result.allowed is True
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_single_result_injection(self):
        """Test hook injects a single completed subagent result."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook
        from massgen.subagent.models import SubagentResult

        hook = SubagentCompleteHook()

        # Create a mock pending result
        mock_result = SubagentResult.create_success(
            subagent_id="research-task",
            answer="Here is the research I found...",
            workspace_path="/workspace/research-task",
            execution_time_seconds=45.2,
            token_usage={"input_tokens": 1000, "output_tokens": 500},
        )

        hook.set_pending_results_getter(lambda: [("research-task", mock_result)])

        result = await hook.execute("some_tool", "{}")

        assert result.allowed is True
        assert result.inject is not None
        assert "research-task" in result.inject["content"]
        assert "Here is the research I found" in result.inject["content"]
        assert result.inject["strategy"] == "tool_result"

    @pytest.mark.asyncio
    async def test_multiple_results_batched(self):
        """Test hook batches multiple results into single injection."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook
        from massgen.subagent.models import SubagentResult

        hook = SubagentCompleteHook()

        result1 = SubagentResult.create_success(
            subagent_id="task-1",
            answer="First task completed",
            workspace_path="/workspace/task-1",
            execution_time_seconds=10.0,
        )
        result2 = SubagentResult.create_success(
            subagent_id="task-2",
            answer="Second task completed",
            workspace_path="/workspace/task-2",
            execution_time_seconds=15.0,
        )

        hook.set_pending_results_getter(
            lambda: [("task-1", result1), ("task-2", result2)],
        )

        result = await hook.execute("some_tool", "{}")

        assert result.allowed is True
        assert result.inject is not None
        content = result.inject["content"]
        assert "task-1" in content
        assert "task-2" in content
        assert "First task completed" in content
        assert "Second task completed" in content

    @pytest.mark.asyncio
    async def test_injection_strategy_tool_result(self):
        """Test hook uses tool_result injection strategy by default."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook
        from massgen.subagent.models import SubagentResult

        hook = SubagentCompleteHook(injection_strategy="tool_result")

        mock_result = SubagentResult.create_success(
            subagent_id="test",
            answer="Test answer",
            workspace_path="/workspace",
            execution_time_seconds=1.0,
        )
        hook.set_pending_results_getter(lambda: [("test", mock_result)])

        result = await hook.execute("some_tool", "{}")

        assert result.inject["strategy"] == "tool_result"

    @pytest.mark.asyncio
    async def test_injection_strategy_user_message(self):
        """Test hook uses user_message injection strategy when configured."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook
        from massgen.subagent.models import SubagentResult

        hook = SubagentCompleteHook(injection_strategy="user_message")

        mock_result = SubagentResult.create_success(
            subagent_id="test",
            answer="Test answer",
            workspace_path="/workspace",
            execution_time_seconds=1.0,
        )
        hook.set_pending_results_getter(lambda: [("test", mock_result)])

        result = await hook.execute("some_tool", "{}")

        assert result.inject["strategy"] == "user_message"

    @pytest.mark.asyncio
    async def test_matches_all_tools(self):
        """Test hook matches all tool names (wildcard pattern)."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook

        hook = SubagentCompleteHook()

        assert hook.matches("Read")
        assert hook.matches("Write")
        assert hook.matches("mcp__filesystem__read_file")
        assert hook.matches("any_tool_name")

    @pytest.mark.asyncio
    async def test_timeout_result_injection(self):
        """Test hook injects timeout result with appropriate status."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook
        from massgen.subagent.models import SubagentResult

        hook = SubagentCompleteHook()

        mock_result = SubagentResult.create_timeout_with_recovery(
            subagent_id="timeout-task",
            workspace_path="/workspace/timeout-task",
            timeout_seconds=300.0,
            recovered_answer="Partial work recovered",
            completion_percentage=75,
        )

        hook.set_pending_results_getter(lambda: [("timeout-task", mock_result)])

        result = await hook.execute("some_tool", "{}")

        assert result.allowed is True
        assert result.inject is not None
        assert "timeout-task" in result.inject["content"]
        assert "completed_but_timeout" in result.inject["content"]

    @pytest.mark.asyncio
    async def test_error_result_injection(self):
        """Test hook injects error result."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook
        from massgen.subagent.models import SubagentResult

        hook = SubagentCompleteHook()

        mock_result = SubagentResult.create_error(
            subagent_id="error-task",
            error="Something went wrong",
            workspace_path="/workspace/error-task",
        )

        hook.set_pending_results_getter(lambda: [("error-task", mock_result)])

        result = await hook.execute("some_tool", "{}")

        assert result.allowed is True
        assert result.inject is not None
        assert "error-task" in result.inject["content"]
        assert "error" in result.inject["content"].lower()

    @pytest.mark.asyncio
    async def test_getter_error_fails_open(self):
        """Test hook fails open when getter raises exception."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook

        hook = SubagentCompleteHook()

        def failing_getter():
            raise RuntimeError("Getter crashed!")

        hook.set_pending_results_getter(failing_getter)

        result = await hook.execute("some_tool", "{}")

        # Should fail open (allow) but track the error
        assert result.allowed is True
        assert result.has_errors()

    @pytest.mark.asyncio
    async def test_result_includes_metadata(self):
        """Test hook injection includes execution metadata."""
        from massgen.mcp_tools.hooks import SubagentCompleteHook
        from massgen.subagent.models import SubagentResult

        hook = SubagentCompleteHook()

        mock_result = SubagentResult.create_success(
            subagent_id="meta-task",
            answer="Task completed",
            workspace_path="/workspace/meta-task",
            execution_time_seconds=42.5,
            token_usage={"input_tokens": 1500, "output_tokens": 750},
        )

        hook.set_pending_results_getter(lambda: [("meta-task", mock_result)])

        result = await hook.execute("some_tool", "{}")

        content = result.inject["content"]
        # Should include execution time
        assert "42.5" in content or "42" in content
        # Should include workspace path
        assert "/workspace/meta-task" in content


class TestBackgroundToolCompleteHook:
    """Tests for BackgroundToolCompleteHook - injects completed background tool results."""

    @pytest.mark.asyncio
    async def test_no_getter_returns_allow(self):
        hook = BackgroundToolCompleteHook()
        result = await hook.execute("some_tool", "{}")
        assert result.allowed is True
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_empty_getter_returns_allow(self):
        hook = BackgroundToolCompleteHook()
        hook.set_completed_jobs_getter(lambda: [])
        result = await hook.execute("some_tool", "{}")
        assert result.allowed is True
        assert result.inject is None

    @pytest.mark.asyncio
    async def test_completed_jobs_are_injected(self):
        hook = BackgroundToolCompleteHook()
        hook.set_completed_jobs_getter(
            lambda: [
                {
                    "job_id": "bgtool_1",
                    "tool_name": "custom_tool__generate_media",
                    "status": "completed",
                    "result": "Generated image at /tmp/image.png",
                },
                {
                    "job_id": "bgtool_2",
                    "tool_name": "mcp__command_line__execute_command",
                    "status": "error",
                    "error": "Command timed out",
                },
            ],
        )

        result = await hook.execute("some_tool", "{}")
        assert result.inject is not None
        assert result.inject["strategy"] == "tool_result"
        assert "BACKGROUND TOOL RESULTS" in result.inject["content"]
        assert "bgtool_1" in result.inject["content"]
        assert "bgtool_2" in result.inject["content"]
        assert "custom_tool__generate_media" in result.inject["content"]
        assert "mcp__command_line__execute_command" in result.inject["content"]
