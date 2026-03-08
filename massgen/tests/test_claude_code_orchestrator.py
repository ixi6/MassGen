#!/usr/bin/env python3
"""
Test ClaudeCodeBackend with MassGen Orchestrator.
This test demonstrates a workflow with Claude Code backend.

Note: This is an integration test that requires ANTHROPIC_API_KEY.
"""

import asyncio
import os
import sys
import tempfile

import pytest

from massgen.agent_config import AgentConfig
from massgen.backend.claude_code import ClaudeCodeBackend
from massgen.chat_agent import ConfigurableAgent
from massgen.frontend.coordination_ui import CoordinationUI
from massgen.orchestrator import Orchestrator

sys.path.insert(0, "/workspaces/MassGen")


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_claude_code_with_orchestrator():
    """Test Claude Code backend with MassGen Orchestrator."""

    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not found in environment")

    print("🚀 Testing Claude Code Backend with MassGen Orchestrator")
    print("=" * 60)

    # Create Claude Code backend with temporary workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        backend = ClaudeCodeBackend(cwd=tmpdir)

    print(f"✅ Backend initialized: {backend.get_provider_name()}")
    print(f"📊 Stateful backend: {backend.is_stateful()}")
    print(f"🛠️  Supported tools: {len(backend.get_supported_builtin_tools())} tools")

    # Create agent configuration
    agent_config = AgentConfig(
        agent_id="claude_code_agent",
        # custom_system_instruction="You are a helpful AI assistant. Provide clear, accurate answers.",
        backend_params={
            "model": "claude-sonnet-4-20250514",
        },
    )

    # Create configurable agent
    agent = ConfigurableAgent(config=agent_config, backend=backend)

    print(f"✅ Agent created: {agent.agent_id}")
    print(f"📋 Agent status: {agent.get_status()}")

    # Create orchestrator
    orchestrator = Orchestrator(agents={agent.agent_id: agent})
    print(f"✅ Orchestrator created with {len(orchestrator.agents)} agent(s)")

    # Create coordination UI
    ui = CoordinationUI(display_type="rich_terminal", logging_enabled=True)
    print(f"✅ Coordination UI created: {ui.display_type}")

    # Test question
    question = "2+2=?"

    print(f"\n📝 Test Question: {question}")
    print("\n🔄 Starting orchestrator coordination...")
    print("=" * 60)

    try:
        # Run orchestrator coordination
        final_response = await ui.coordinate(orchestrator, question)

        print("\n" + "=" * 60)
        print("✅ Orchestrator coordination completed!")
        print(f"📊 Final response length: {len(final_response)} characters")

        # Display backend statistics
        token_usage = backend.get_token_usage()
        print("\n📈 Backend Statistics:")
        print(f"   Input tokens: {token_usage.input_tokens}")
        print(f"   Output tokens: {token_usage.output_tokens}")
        print(f"   Estimated cost: ${token_usage.estimated_cost:.4f}")
        print(f"   Session ID: {backend.get_current_session_id()}")

        # Display final response
        if final_response:
            print("\n📄 Final Response:")
            print("-" * 40)
            print(final_response)
            print("-" * 40)
        assert final_response
    except Exception as e:
        pytest.fail(f"Error during orchestrator test: {e}")

    print("\n✅ Orchestrator test completed successfully!")


@pytest.mark.integration
@pytest.mark.live_api
@pytest.mark.asyncio
async def test_stateful_behavior():
    """Test the stateful behavior of Claude Code backend."""

    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not found in environment")

    print("\n" + "=" * 60)
    print("🚀 Testing Stateful Behavior")
    print("=" * 60)

    # Create backend and agent
    backend = ClaudeCodeBackend(model="claude-sonnet-4-20250514")
    config = AgentConfig(
        agent_id="stateful_agent",
        backend_params={
            "model": "claude-sonnet-4-20250514",
            "append_system_prompt": "You are a helpful assistant. Remember our conversation context.",
        },
    )
    agent = ConfigurableAgent(config=config, backend=backend)

    print(f"✅ Stateful agent created: {backend.is_stateful()}")
    print(f"🔗 Initial session ID: {backend.get_current_session_id()}")

    # Test conversation continuity
    messages1 = [{"role": "user", "content": "My favorite color is blue. Please remember this."}]
    messages2 = [{"role": "user", "content": "What did I just tell you about my favorite color?"}]

    try:
        print("\n📝 Turn 1: Setting context...")
        response1 = ""
        async for chunk in agent.chat(messages1):
            if chunk.type == "content" and chunk.content:
                response1 += chunk.content

        print(f"✅ Turn 1 completed. Session: {backend.get_current_session_id()}")
        print(f"📄 Response 1 preview: {response1[:100]}...")

        print("\n📝 Turn 2: Testing memory...")
        response2 = ""
        async for chunk in agent.chat(messages2):
            if chunk.type == "content" and chunk.content:
                response2 += chunk.content

        print(f"✅ Turn 2 completed. Session: {backend.get_current_session_id()}")
        print(f"📄 Response 2 preview: {response2[:100]}...")

        # Check if context was maintained
        if "blue" in response2.lower():
            print("✅ Stateful behavior confirmed - context maintained!")
        else:
            print("⚠️  Context may not have been maintained")

        print(f"\n📊 Token usage after 2 turns: {backend.get_token_usage()}")

    except Exception as e:
        print(f"❌ Error during stateful test: {e}")
        import traceback

        traceback.print_exc()
        return

    print("\n✅ Stateful behavior test completed!")


async def main():
    """Run all Claude Code tests."""
    print("🧪 Claude Code Backend + Orchestrator Tests")
    print("=" * 60)

    await test_claude_code_with_orchestrator()
    # await test_stateful_behavior()

    print("\n🎉 All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
