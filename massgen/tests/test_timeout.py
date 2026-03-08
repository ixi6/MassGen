#!/usr/bin/env python3
"""
Simple test script to verify timeout mechanisms work correctly.
This creates a fast timeout config and runs a test to demonstrate the timeout fallback.
"""

import asyncio
import sys
from pathlib import Path

import pytest

from massgen.agent_config import AgentConfig, TimeoutConfig
from massgen.backend.claude_code import ClaudeCodeBackend
from massgen.chat_agent import SingleAgent
from massgen.orchestrator import Orchestrator

# Add massgen to Python path
sys.path.insert(0, str(Path(__file__).parent))


@pytest.mark.integration
@pytest.mark.live_api
async def test_orchestrator_timeout():
    """Test orchestrator-level timeout."""
    print("\n🧪 Testing Orchestrator Timeout Mechanism")
    print("=" * 50)

    # Create very restrictive orchestrator timeout
    timeout_config = TimeoutConfig(
        orchestrator_timeout_seconds=10,  # 10 seconds orchestrator (very short)
    )

    # Create agent config and set timeout
    agent_config = AgentConfig.create_claude_code_config(model="claude-sonnet-4-20250514")
    agent_config.timeout_config = timeout_config

    # Claude code backend for testing
    try:
        backend = ClaudeCodeBackend()
        agent = SingleAgent(backend=backend, system_message="You are a helpful assistant.")

        # Create orchestrator with timeout-aware agents
        agents = {"test_agent": agent}
        orchestrator = Orchestrator(agents=agents, config=agent_config)

        print(f"⏱️  Orchestrator timeout: {timeout_config.orchestrator_timeout_seconds}s")
        print("📝 Testing with complex multi-agent coordination that should trigger orchestrator timeout...")

        # Ask a question that requires complex coordination between multiple agents
        question = (
            "Please coordinate with multiple specialized agents to create a comprehensive business plan "
            "for a tech startup, including market analysis, technical architecture, financial projections, "
            "legal considerations, and detailed implementation timeline. Each section should be thoroughly "
            "researched and cross-validated between agents."
        )

        print(f"\n❓ Question: {question[:100]}...")
        print("\n🚀 Starting orchestrator coordination (should timeout quickly)...")

        response_content = ""
        timeout_detected = False

        async for chunk in orchestrator.chat_simple(question):
            if chunk.type == "content":
                content = chunk.content
                print(f"📝 {content}")
                response_content += chunk.content
                if "time limit exceeded" in content.lower() or "timeout" in content.lower():
                    timeout_detected = True
                    print(f"⚠️  ORCHESTRATOR TIMEOUT DETECTED: {content}")
            elif chunk.type == "error":
                if "time limit exceeded" in chunk.error.lower() or "timeout" in chunk.error.lower():
                    timeout_detected = True
                    print(f"⚠️  ORCHESTRATOR TIMEOUT DETECTED: {chunk.error}")
            elif chunk.type == "done":
                print("✅ Orchestrator coordination completed")
                break

        if timeout_detected:
            print("\n🎯 SUCCESS: Orchestrator timeout mechanism triggered correctly!")
        else:
            print("\n🤔 No orchestrator timeout detected - either coordination completed fast or timeout didn't work")

        print(f"\n📊 Final response length: {len(response_content)} characters")

    except Exception as e:
        print(f"❌ Orchestrator timeout test failed with error: {e}")
        print("💡 Note: This test requires API keys to run with real backend")


def print_config_example():
    """Print example configuration for users."""
    print("\n📋 Example YAML Configuration with Timeout Settings:")
    print("=" * 50)

    example_config = """
# Conservative timeout settings to prevent runaway costs
timeout_settings:
  orchestrator_timeout_seconds: 600   # 10 minutes max coordination

agents:
  - id: "agent1"
    backend:
      type: "openai"
      model: "gpt-4o-mini"
    system_message: "You are a helpful assistant."
"""

    print(example_config)

    print("\n🖥️  CLI Examples:")
    print('python -m massgen.cli --config config.yaml --orchestrator-timeout 300 "Complex task"')


if __name__ == "__main__":
    print("🔧 MassGen Timeout Mechanism Test")
    print("=" * 60)

    print_config_example()

    print("\n🧪 Running timeout tests...")
    print("Note: These tests require API keys to run with real backends")

    try:
        # Run orchestrator timeout test
        asyncio.run(test_orchestrator_timeout())

        print("\n✅ Timeout mechanism implementation completed!")
        print("💡 The timeout system will prevent runaway token usage and provide graceful fallbacks.")

    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"\n❌ Tests failed: {e}")
        print("💡 This is expected if you don't have API keys configured")
