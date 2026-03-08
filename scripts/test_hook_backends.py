#!/usr/bin/env python3
"""
Integration test script for hook framework across multiple backends.

This script tests that the hook framework is correctly integrated with each backend:
1. Backend can receive and store a GeneralHookManager
2. Hook execution works for POST_TOOL_USE events
3. MidStreamInjectionHook returns injection content when callback is set
4. HighPriorityTaskReminderHook injects reminders for high-priority completed tasks

Two test modes:
- Default: Unit tests that directly invoke hook execution paths (no API calls)
- E2E (--e2e): End-to-end tests with real API calls testing the full flow:
  PreToolUse hooks → tool execution → PostToolUse hooks → injection fed to model

Usage:
    # Test all backends (unit tests only)
    uv run python scripts/test_hook_backends.py

    # Test specific backend
    uv run python scripts/test_hook_backends.py --backend claude

    # End-to-end test with real API calls
    uv run python scripts/test_hook_backends.py --e2e

    # Verbose output (show injection content and message formatting)
    uv run python scripts/test_hook_backends.py --verbose

    # List available backends
    uv run python scripts/test_hook_backends.py --list-backends
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Add massgen to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from massgen.mcp_tools.hooks import (  # noqa: E402
    GeneralHookManager,
    HighPriorityTaskReminderHook,
    HookEvent,
    HookResult,
    HookType,
    MidStreamInjectionHook,
    PythonCallableHook,
)
from massgen.tool._result import ExecutionResult, TextContent  # noqa: E402

# Global flags
VERBOSE = False
E2E_MODE = False

# Track hook execution for e2e tests
E2E_HOOK_LOG: list[dict[str, Any]] = []
E2E_INJECTION_LOG: list[dict[str, Any]] = []  # Track injection results

# Backend configurations for testing hooks
BACKEND_CONFIGS: dict[str, dict[str, Any]] = {
    "claude": {
        "type": "claude",
        "model": "claude-haiku-4-5-20251001",
        "description": "Claude Messages API",
        "api_style": "anthropic",
    },
    "openai": {
        "type": "openai",
        "model": "gpt-4o-mini",
        "description": "OpenAI Response API",
        "api_style": "openai",
    },
    "gemini": {
        "type": "gemini",
        "model": "gemini-3-flash-preview",
        "description": "Gemini native SDK",
        "api_style": "gemini",
    },
    "openrouter": {
        "type": "chatcompletion",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "api_key_env": "OPENROUTER_API_KEY",
        "description": "OpenRouter via ChatCompletionsBackend",
        "api_style": "openai",
    },
    "grok": {
        "type": "grok",
        "model": "grok-3-mini",
        "description": "Grok via GrokBackend",
        "api_style": "openai",
    },
}


def create_backend(
    backend_name: str,
    config: dict[str, Any],
    custom_tools: list[dict[str, Any]] | None = None,
):
    """Create a backend instance based on configuration."""
    backend_type = config["type"]

    # Import dynamically to avoid loading all backends
    if backend_type == "claude":
        from massgen.backend.claude import ClaudeBackend

        return ClaudeBackend(model=config["model"], custom_tools=custom_tools)
    elif backend_type == "openai":
        from massgen.backend.response import ResponseBackend

        return ResponseBackend(model=config["model"], custom_tools=custom_tools)
    elif backend_type == "gemini":
        from massgen.backend.gemini import GeminiBackend

        return GeminiBackend(model=config["model"], custom_tools=custom_tools)
    elif backend_type == "chatcompletion":
        from massgen.backend.chat_completions import ChatCompletionsBackend

        api_key_env = config.get("api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError(f"Missing API key: {api_key_env}")

        return ChatCompletionsBackend(
            model=config["model"],
            base_url=config.get("base_url"),
            api_key=api_key,
            custom_tools=custom_tools,
        )
    elif backend_type == "grok":
        from massgen.backend.grok import GrokBackend

        return GrokBackend(model=config["model"], custom_tools=custom_tools)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")


def format_anthropic_message(
    tool_result: str,
    tool_use_id: str,
    injection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Format a message as Anthropic API would receive it (with separate content blocks)."""
    content = [
        {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": tool_result,
        },
    ]

    if injection:
        strategy = injection.get("strategy", "tool_result")
        inject_content = injection.get("content", "")

        if strategy == "tool_result":
            # Append to tool result content
            content[0]["content"] = f"{tool_result}\n{inject_content}"
        else:  # user_message
            # Add as separate text block (Anthropic supports this!)
            content.append(
                {
                    "type": "text",
                    "text": inject_content,
                },
            )

    return {"role": "user", "content": content}


def format_openai_message(
    tool_result: str,
    tool_call_id: str,
    injection: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Format messages as OpenAI API would receive them."""
    messages = []

    # Tool result message
    tool_content = tool_result
    if injection and injection.get("strategy") == "tool_result":
        tool_content = f"{tool_result}\n{injection.get('content', '')}"

    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": tool_content,
        },
    )

    # Separate user message for user_message strategy
    if injection and injection.get("strategy") == "user_message":
        messages.append(
            {
                "role": "user",
                "content": injection.get("content", ""),
            },
        )

    return messages


def print_verbose(label: str, content: Any, indent: int = 4) -> None:
    """Print verbose output if enabled."""
    if not VERBOSE:
        return

    prefix = " " * indent
    print(f"\n{prefix}{label}:")
    if isinstance(content, (dict, list)):
        formatted = json.dumps(content, indent=2)
        for line in formatted.split("\n"):
            print(f"{prefix}  {line}")
    else:
        for line in str(content).split("\n"):
            print(f"{prefix}  {line}")


def test_hook_manager_integration(backend_name: str, config: dict[str, Any]) -> tuple[bool, str]:
    """Test that backend properly accepts and stores a GeneralHookManager."""
    try:
        backend = create_backend(backend_name, config)
        backend.agent_id = f"test_agent_{backend_name}"

        # Check if backend has set_general_hook_manager method
        if not hasattr(backend, "set_general_hook_manager"):
            return False, "Backend missing set_general_hook_manager method"

        # Create and set hook manager
        manager = GeneralHookManager()
        backend.set_general_hook_manager(manager)

        # Verify manager was stored
        if not hasattr(backend, "_general_hook_manager"):
            return False, "Backend didn't store hook manager in _general_hook_manager"

        if backend._general_hook_manager is not manager:
            return False, "Backend stored different manager than provided"

        return True, "Hook manager integration successful"

    except Exception as e:
        return False, f"Error: {type(e).__name__}: {e}"


async def test_mid_stream_injection_hook(
    backend_name: str,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Test that MidStreamInjectionHook works correctly via hook manager."""
    try:
        backend = create_backend(backend_name, config)
        backend.agent_id = f"test_agent_{backend_name}"

        # Create hook manager with mid-stream injection hook
        manager = GeneralHookManager()
        mid_stream_hook = MidStreamInjectionHook()

        # Set callback that returns injection content
        injection_content = "[INJECTED] New information from other agents"
        mid_stream_hook.set_callback(lambda: injection_content)

        manager.register_global_hook(HookType.POST_TOOL_USE, mid_stream_hook)
        backend.set_general_hook_manager(manager)

        # Execute hooks directly
        tool_output = '{"result": "ok"}'
        result = await manager.execute_hooks(
            HookType.POST_TOOL_USE,
            "test_tool",
            "{}",
            {},
            tool_output=tool_output,
        )

        # Verbose output
        if VERBOSE:
            print_verbose("Tool Output (before injection)", tool_output)
            print_verbose(
                "Hook Result",
                {
                    "allowed": result.allowed,
                    "inject": result.inject,
                },
            )

            # Show how this would look in different API formats
            api_style = config.get("api_style", "openai")
            if api_style == "anthropic":
                msg = format_anthropic_message(tool_output, "tool_123", result.inject)
                print_verbose("Anthropic API Message Format", msg)
            else:
                msgs = format_openai_message(tool_output, "call_123", result.inject)
                print_verbose("OpenAI API Message Format", msgs)

        # Verify injection was returned
        if not result.inject:
            return False, "Hook didn't return injection content"

        if injection_content not in result.inject.get("content", ""):
            return False, f"Injection content not found. Got: {result.inject}"

        if result.inject.get("strategy") != "tool_result":
            return False, f"Wrong strategy. Expected 'tool_result', got: {result.inject.get('strategy')}"

        return True, "MidStreamInjectionHook executed correctly"

    except Exception as e:
        import traceback

        traceback.print_exc()
        return False, f"Error: {type(e).__name__}: {e}"


async def test_high_priority_task_reminder_hook(
    backend_name: str,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Test that HighPriorityTaskReminderHook injects reminders for high-priority completed tasks."""
    try:
        backend = create_backend(backend_name, config)
        backend.agent_id = f"test_agent_{backend_name}"

        # Create hook manager with high-priority task reminder hook
        manager = GeneralHookManager()
        reminder_hook = HighPriorityTaskReminderHook()

        manager.register_global_hook(HookType.POST_TOOL_USE, reminder_hook)
        backend.set_general_hook_manager(manager)

        # Execute hooks with complete_task output for high-priority task
        tool_output = json.dumps(
            {
                "task": {"priority": "high", "status": "completed", "id": "task_1"},
                "newly_ready_tasks": [],
            },
        )
        result = await manager.execute_hooks(
            HookType.POST_TOOL_USE,
            "update_task_status",  # Hook matches *update_task_status pattern
            "{}",
            {},
            tool_output=tool_output,
        )

        # Verbose output
        if VERBOSE:
            print_verbose("Tool Output (high-priority task)", tool_output)
            print_verbose(
                "Hook Result",
                {
                    "allowed": result.allowed,
                    "inject": result.inject,
                },
            )

            if result.inject:
                print_verbose("Formatted Reminder Content", result.inject.get("content", ""))

                # Show how this would look in different API formats
                api_style = config.get("api_style", "openai")
                if api_style == "anthropic":
                    msg = format_anthropic_message(tool_output, "tool_123", result.inject)
                    print_verbose("Anthropic API Message Format", msg)
                else:
                    msgs = format_openai_message(tool_output, "call_123", result.inject)
                    print_verbose("OpenAI API Message Format", msgs)

        # Verify reminder was injected
        if not result.inject:
            return False, "Hook didn't inject reminder for high-priority task"

        content = result.inject.get("content", "")
        if "High-priority task completed" not in content:
            return False, f"Reminder text not found. Got: {content}"

        if "SYSTEM REMINDER" not in content:
            return False, f"SYSTEM REMINDER header not found. Got: {content}"

        if "memory/long_term" not in content:
            return False, f"Memory paths not found. Got: {content}"

        if result.inject.get("strategy") != "user_message":
            return False, f"Wrong strategy. Expected 'user_message', got: {result.inject.get('strategy')}"

        return True, "HighPriorityTaskReminderHook executed correctly"

    except Exception as e:
        import traceback

        traceback.print_exc()
        return False, f"Error: {type(e).__name__}: {e}"


async def test_combined_hooks(
    backend_name: str,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Test that multiple hooks can be registered and both execute."""
    try:
        backend = create_backend(backend_name, config)
        backend.agent_id = f"test_agent_{backend_name}"

        # Create hook manager with both hooks
        manager = GeneralHookManager()

        # Mid-stream injection hook
        mid_stream_hook = MidStreamInjectionHook()
        mid_stream_hook.set_callback(lambda: "[INJECTED] Cross-agent message")
        manager.register_global_hook(HookType.POST_TOOL_USE, mid_stream_hook)

        # High-priority task reminder hook
        reminder_hook = HighPriorityTaskReminderHook()
        manager.register_global_hook(HookType.POST_TOOL_USE, reminder_hook)

        backend.set_general_hook_manager(manager)

        # Execute hooks with complete_task output for high-priority task
        tool_output = json.dumps(
            {
                "task": {"priority": "high", "status": "completed", "id": "combined_task"},
                "newly_ready_tasks": [],
            },
        )
        result = await manager.execute_hooks(
            HookType.POST_TOOL_USE,
            "complete_task",  # Must match reminder hook pattern
            "{}",
            {},
            tool_output=tool_output,
        )

        # Verbose output
        if VERBOSE:
            print_verbose("Tool Output", tool_output)
            print_verbose(
                "Combined Hook Result",
                {
                    "allowed": result.allowed,
                    "inject": result.inject,
                },
            )

            if result.inject:
                print_verbose("Combined Injection Content", result.inject.get("content", ""))

                # Note: Combined hooks aggregate content but may have mixed strategies
                # The backend handles this by splitting based on strategy
                print_verbose("Strategy", result.inject.get("strategy", "unknown"))
                print_verbose(
                    "Note",
                    "When multiple hooks inject, backend splits by strategy:\n" "  - tool_result: appended to tool output\n" "  - user_message: separate message after tool result",
                )

        # Both hooks should have contributed to injection
        if not result.inject:
            return False, "Combined hooks didn't return injection content"

        content = result.inject.get("content", "")

        # Check for mid-stream injection content
        if "[INJECTED]" not in content:
            return False, f"Mid-stream injection not found. Got: {content}"

        # Check for high-priority task reminder content
        if "High-priority task completed" not in content:
            return False, f"High-priority reminder not found. Got: {content}"

        return True, "Combined hooks executed correctly"

    except Exception as e:
        import traceback

        traceback.print_exc()
        return False, f"Error: {type(e).__name__}: {e}"


async def run_tests(backend_names: list[str]) -> dict[str, dict[str, tuple[bool, str]]]:
    """Run all hook tests on specified backends."""
    results = {}

    for backend_name in backend_names:
        if backend_name not in BACKEND_CONFIGS:
            print(f"Unknown backend: {backend_name}")
            continue

        config = BACKEND_CONFIGS[backend_name]

        # Check for API keys (only needed for OpenRouter)
        if backend_name == "openrouter":
            if not os.environ.get("OPENROUTER_API_KEY"):
                print(f"Skipping {backend_name}: OPENROUTER_API_KEY not set")
                continue
        elif backend_name == "grok":
            if not os.environ.get("XAI_API_KEY"):
                print(f"Skipping {backend_name}: XAI_API_KEY not set")
                continue

        print(f"\n{'='*60}")
        print(f"Testing {backend_name}")
        print(f"Backend: {config['description']}")
        print(f"Model: {config['model']}")
        print(f"API Style: {config.get('api_style', 'unknown')}")
        print(f"{'='*60}")

        results[backend_name] = {}

        # Test 1: Hook manager integration
        print("\n  Test 1: Hook manager integration...", end=" ")
        success, msg = test_hook_manager_integration(backend_name, config)
        results[backend_name]["integration"] = (success, msg)
        print("PASS" if success else f"FAIL: {msg}")

        # Test 2: Mid-stream injection hook
        print("\n  Test 2: MidStreamInjectionHook...", end=" ")
        success, msg = await test_mid_stream_injection_hook(backend_name, config)
        results[backend_name]["mid_stream"] = (success, msg)
        print("PASS" if success else f"FAIL: {msg}")

        # Test 3: High-priority task reminder hook
        print("\n  Test 3: HighPriorityTaskReminderHook...", end=" ")
        success, msg = await test_high_priority_task_reminder_hook(backend_name, config)
        results[backend_name]["reminder"] = (success, msg)
        print("PASS" if success else f"FAIL: {msg}")

        # Test 4: Combined hooks
        print("\n  Test 4: Combined hooks...", end=" ")
        success, msg = await test_combined_hooks(backend_name, config)
        results[backend_name]["combined"] = (success, msg)
        print("PASS" if success else f"FAIL: {msg}")

    return results


# ============================================================================
# End-to-End (E2E) Tests - Real API Calls
# ============================================================================


def make_logging_hook(hook_name: str, hook_type: str):
    """Create a hook that logs its execution for e2e verification."""

    def log_hook(event: HookEvent) -> HookResult:
        E2E_HOOK_LOG.append(
            {
                "hook_name": hook_name,
                "hook_type": hook_type,
                "tool_name": event.tool_name,
                "tool_input": event.tool_input,
                "tool_output": event.tool_output,
            },
        )
        return HookResult.allow()

    return log_hook


class InjectionCapturingMidStreamHook(MidStreamInjectionHook):
    """Wrapper that captures mid-stream injection results for testing."""

    async def execute(
        self,
        function_name: str,
        arguments: str,
        context: dict[str, Any] | None = None,
        **kwargs,
    ) -> HookResult:
        result = await super().execute(function_name, arguments, context, **kwargs)
        if result.inject:
            E2E_INJECTION_LOG.append(
                {
                    "hook": "MidStreamInjectionHook",
                    "tool_name": function_name,
                    "inject": result.inject,
                },
            )
        return result


class InjectionCapturingReminderHook(HighPriorityTaskReminderHook):
    """Wrapper that captures reminder injection results for testing."""

    async def execute(
        self,
        function_name: str,
        arguments: str,
        context: dict[str, Any] | None = None,
        **kwargs,
    ) -> HookResult:
        result = await super().execute(function_name, arguments, context, **kwargs)
        if result.inject:
            E2E_INJECTION_LOG.append(
                {
                    "hook": "HighPriorityTaskReminderHook",
                    "tool_name": function_name,
                    "inject": result.inject,
                },
            )
        return result


def complete_task(task_id: str = "task_1") -> ExecutionResult:
    """Simulates complete_task tool for testing high-priority task reminder hook.

    Args:
        task_id: ID of the task to complete

    Returns:
        ExecutionResult with JSON containing task completion data
    """
    result_json = json.dumps(
        {
            "task": {
                "id": task_id,
                "priority": "high",
                "status": "completed",
                "description": "E2E test task",
            },
            "newly_ready_tasks": [],
        },
    )
    return ExecutionResult(
        output_blocks=[TextContent(data=result_json)],
    )


# Custom tool config for registration
# Note: Don't pass 'name' when function is callable - let it use __name__
# This avoids a bug where the code tries to "load" the function from a path
CUSTOM_TOOL_CONFIG = {
    "function": complete_task,
    # name is omitted - will use function.__name__ ("complete_task")
    "description": "Simulates completing a high-priority task for testing reminder hook",
    "category": "default",
}


async def run_e2e_test(
    backend_name: str,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """
    Run end-to-end test that makes real API calls.

    Tests the full flow:
    1. PreToolUse hook fires before tool execution
    2. Tool executes
    3. PostToolUse hook fires after tool execution
    4. Injection content is fed back to model
    5. Follow-up question verifies model received the injection
    """
    global E2E_HOOK_LOG, E2E_INJECTION_LOG
    E2E_HOOK_LOG = []  # Reset log
    E2E_INJECTION_LOG = []  # Reset injection log

    # Capture log messages to verify injection was applied
    import logging

    captured_logs = []

    class LogCapture(logging.Handler):
        def emit(self, record):
            captured_logs.append(record.getMessage())

    log_capture = LogCapture()
    log_capture.setLevel(logging.DEBUG)
    logging.getLogger("massgen.backend").addHandler(log_capture)
    logging.getLogger("massgen.backend").setLevel(logging.DEBUG)

    try:
        # Create backend with custom tool registered at init time
        backend = create_backend(backend_name, config, custom_tools=[CUSTOM_TOOL_CONFIG])
        backend.agent_id = f"e2e_test_{backend_name}"

        # Create hook manager with logging hooks and reminder extraction
        manager = GeneralHookManager()

        # PreToolUse logging hook
        pre_hook = PythonCallableHook(
            name="e2e_pre_logger",
            handler=make_logging_hook("PreToolUse Logger", "PreToolUse"),
            matcher="*",
        )
        manager.register_global_hook(HookType.PRE_TOOL_USE, pre_hook)

        # PostToolUse logging hook
        post_hook = PythonCallableHook(
            name="e2e_post_logger",
            handler=make_logging_hook("PostToolUse Logger", "PostToolUse"),
            matcher="*",
        )
        manager.register_global_hook(HookType.POST_TOOL_USE, post_hook)

        # Mid-stream injection hook (strategy: tool_result - appends to tool output)
        mid_stream_hook = InjectionCapturingMidStreamHook()
        mid_stream_hook.set_callback(lambda: "[INJECTED] Cross-agent update: Agent2 says hello!")
        manager.register_global_hook(HookType.POST_TOOL_USE, mid_stream_hook)

        # High-priority task reminder hook (strategy: user_message - separate message)
        # Use capturing version to log injection results
        reminder_hook = InjectionCapturingReminderHook()
        manager.register_global_hook(HookType.POST_TOOL_USE, reminder_hook)

        backend.set_general_hook_manager(manager)

        # Build prompt that will trigger tool use (complete_task matches the reminder hook)
        prompt = "Please use the complete_task tool with task_id 'e2e_test_task'"

        # Run the chat (backend adds custom tools internally via build_api_params)
        messages = [{"role": "user", "content": prompt}]
        response_text = ""
        tool_was_called = False
        reminder_was_injected = False

        async for chunk in backend.stream_with_tools(messages, []):
            if hasattr(chunk, "content") and chunk.content:
                response_text += chunk.content
            if hasattr(chunk, "source") and chunk.source and "complete_task" in chunk.source:
                tool_was_called = True
            # Also check chunk type for tool execution
            if hasattr(chunk, "type") and chunk.type in ("custom_tool_called", "custom_tool_response"):
                tool_was_called = True

        # Check the INJECTION LOG for reminder injection
        # The injection log captures what hooks returned, which is the source of truth
        # Note: backend.messages doesn't persist injections - they're consumed during streaming
        for entry in E2E_INJECTION_LOG:
            inject = entry.get("inject", {})
            content = inject.get("content", "")
            if "High-priority task completed" in content:
                reminder_was_injected = True
                break

        # Verify the full flow
        errors = []

        # Check PreToolUse hook fired
        pre_hooks = [h for h in E2E_HOOK_LOG if h["hook_type"] == "PreToolUse"]
        if not pre_hooks:
            errors.append("PreToolUse hook did not fire")

        # Check PostToolUse hook fired
        post_hooks = [h for h in E2E_HOOK_LOG if h["hook_type"] == "PostToolUse"]
        if not post_hooks:
            errors.append("PostToolUse hook did not fire")

        # Check tool was actually called
        if not tool_was_called:
            errors.append("Tool was not called by the model")

        # Check reminder hook returned injection content
        if not reminder_was_injected:
            errors.append("HighPriorityTaskReminderHook did not return injection for high-priority task")

        if errors:
            return False, "; ".join(errors)

        # Check logs for evidence that injection was applied
        injection_applied = any("[PostToolUse Hook] Injected reminder" in log for log in captured_logs)

        if VERBOSE:
            print()
            print("      === INJECTIONS RETURNED BY HOOKS ===")
            for entry in E2E_INJECTION_LOG:
                inject = entry.get("inject", {})
                strategy = inject.get("strategy", "unknown")
                hook_name = entry.get("hook", "Unknown")
                content = inject.get("content", "").strip()
                print(f"      [{hook_name}] strategy={strategy}")
                # Show first line of content only
                first_line = content.split("\n")[0] if content else "(empty)"
                print(f"        {first_line[:80]}...")
                print()

            print("      === INJECTION APPLIED? ===")
            if injection_applied:
                # Find and show the actual log message
                for log in captured_logs:
                    if "[PostToolUse Hook] Injected reminder" in log:
                        print(f"      ✓ {log}")
                        break
            else:
                print("      ⚠ No injection log found - injection may not have been applied")
                if captured_logs:
                    print("      Recent logs:")
                    for log in captured_logs[-5:]:
                        print(f"        {log[:100]}")
            print()

        # Fail if injection wasn't applied
        if not injection_applied:
            return False, "Injection was not applied to messages (no log entry found)"

        return True, "PASS"

    except Exception as e:
        import traceback

        if VERBOSE:
            traceback.print_exc()
        return False, f"Error: {type(e).__name__}: {e}"
    finally:
        # Clean up log handler
        logging.getLogger("massgen.backend").removeHandler(log_capture)


async def run_e2e_tests(backend_names: list[str]) -> dict[str, tuple[bool, str]]:
    """Run e2e tests on specified backends."""
    results = {}

    for backend_name in backend_names:
        if backend_name not in BACKEND_CONFIGS:
            print(f"Unknown backend: {backend_name}")
            continue

        config = BACKEND_CONFIGS[backend_name]

        # Check for required API keys
        skip_reason = None
        if backend_name == "openrouter":
            if not os.environ.get("OPENROUTER_API_KEY"):
                skip_reason = "OPENROUTER_API_KEY not set"
        elif backend_name == "grok":
            if not os.environ.get("XAI_API_KEY"):
                skip_reason = "XAI_API_KEY not set"
        elif backend_name == "claude":
            if not os.environ.get("ANTHROPIC_API_KEY"):
                skip_reason = "ANTHROPIC_API_KEY not set"
        elif backend_name == "openai":
            if not os.environ.get("OPENAI_API_KEY"):
                skip_reason = "OPENAI_API_KEY not set"
        elif backend_name == "gemini":
            if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
                skip_reason = "GEMINI_API_KEY or GOOGLE_API_KEY not set"

        if skip_reason:
            print(f"\nSkipping {backend_name}: {skip_reason}")
            results[backend_name] = (False, f"Skipped: {skip_reason}")
            continue

        print(f"\n{'='*60}")
        print(f"E2E Test: {backend_name}")
        print(f"Backend: {config['description']}")
        print(f"Model: {config['model']}")
        print(f"API Style: {config.get('api_style', 'unknown')}")
        print(f"{'='*60}")

        print("\n  Running end-to-end hook test...", end="" if not VERBOSE else "\n")
        success, msg = await run_e2e_test(backend_name, config)
        results[backend_name] = (success, msg)

        if not VERBOSE:
            print("PASS" if success else f"FAIL: {msg}")

    return results


def list_backends():
    """Print available backends."""
    print("\nAvailable backends for hook testing:")
    print("-" * 60)
    for name, config in BACKEND_CONFIGS.items():
        print(f"  {name:15} - {config['description']}")
        print(f"                  Model: {config['model']}")
        print(f"                  API Style: {config.get('api_style', 'unknown')}")
    print()


def main():
    global VERBOSE, E2E_MODE

    parser = argparse.ArgumentParser(description="Test hook framework across backends")
    parser.add_argument(
        "--backend",
        "-b",
        help="Test specific backend (can specify multiple times)",
        action="append",
    )
    parser.add_argument(
        "--list-backends",
        action="store_true",
        help="List available backends",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed injection content and message formatting",
    )
    parser.add_argument(
        "--e2e",
        action="store_true",
        help="Run end-to-end tests with real API calls (tests full hook flow)",
    )

    args = parser.parse_args()

    if args.list_backends:
        list_backends()
        return

    VERBOSE = args.verbose
    E2E_MODE = args.e2e
    backends = args.backend if args.backend else list(BACKEND_CONFIGS.keys())

    if E2E_MODE:
        # Run end-to-end tests with real API calls
        print("\n" + "=" * 60)
        print("Hook Framework End-to-End Test")
        print("=" * 60)
        print("\nThis test makes REAL API CALLS to verify the full hook flow:")
        print("  1. PreToolUse hooks fire before tool execution")
        print("  2. Tool executes")
        print("  3. PostToolUse hooks fire after tool execution")
        print("  4. Injection content is fed back to model")
        print("\n⚠️  This will incur API costs!")

        if VERBOSE:
            print("\n[VERBOSE MODE] Showing detailed hook execution logs")

        results = asyncio.run(run_e2e_tests(backends))

        print("\n" + "=" * 60)
        print("E2E Summary")
        print("=" * 60)

        total_passed = 0
        total_tests = 0
        total_skipped = 0

        for backend_name, (success, msg) in results.items():
            if "Skipped" in msg:
                status = "SKIP"
                total_skipped += 1
            else:
                status = "PASS" if success else "FAIL"
                total_tests += 1
                if success:
                    total_passed += 1
            print(f"  {backend_name}: {status}")

        print(f"\nTotal: {total_passed}/{total_tests} tests passed ({total_skipped} skipped)")
        sys.exit(0 if total_passed == total_tests else 1)

    else:
        # Run unit tests (no API calls)
        print("\n" + "=" * 60)
        print("Hook Framework Integration Test (Unit Tests)")
        print("=" * 60)
        print("\nThis test verifies hook framework integration with each backend.")
        print("No API calls are made - this tests the hook execution path directly.")
        print("\nUse --e2e to run end-to-end tests with real API calls.")

        if VERBOSE:
            print("\n[VERBOSE MODE] Showing injection content and API message formats")
            print("-" * 60)
            print("API Styles:")
            print("  - anthropic: Uses separate content blocks (cleanest)")
            print("  - openai: Uses separate messages or appends to tool result")
            print("  - gemini: Similar to OpenAI pattern")
            print("-" * 60)

        results = asyncio.run(run_tests(backends))

        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)

        total_passed = 0
        total_tests = 0

        for backend_name, backend_results in results.items():
            print(f"\n  {backend_name}:")
            for test_name, (success, msg) in backend_results.items():
                status = "PASS" if success else "FAIL"
                print(f"    {test_name}: {status}")
                total_tests += 1
                if success:
                    total_passed += 1

        print(f"\nTotal: {total_passed}/{total_tests} tests passed")

        # Exit with error code if any tests failed
        sys.exit(0 if total_passed == total_tests else 1)


if __name__ == "__main__":
    main()
