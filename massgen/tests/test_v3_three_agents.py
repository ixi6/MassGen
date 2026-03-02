#!/usr/bin/env python3
"""
Test script for MassGen three-agent coordination with terminal display.
Tests orchestrator coordination between three agents with diverse expertise.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from massgen.backend.response import ResponseBackend  # noqa: E402
from massgen.chat_agent import SingleAgent  # noqa: E402
from massgen.frontend.coordination_ui import CoordinationUI  # noqa: E402
from massgen.orchestrator import Orchestrator  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.live_api]


async def test_three_agents_coordination():
    """Test three-agent coordination with diverse expertise areas."""
    print("🚀 MassGen - Three Agents Coordination Test")
    print("=" * 60)

    # Check if API key is available
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found in environment variables")
        print("⚠️  Set OPENAI_API_KEY to test three-agent coordination")
        return False

    try:
        # Create backend
        backend = ResponseBackend(api_key=api_key)

        # Create three agents with different expertise
        researcher = SingleAgent(
            backend=backend,
            agent_id="researcher",
            system_message="You are a thorough researcher who excels at gathering comprehensive information and identifying key facts. Focus on accuracy and completeness.",
        )

        analyst = SingleAgent(
            backend=backend,
            agent_id="analyst",
            system_message="You are a critical analyst who specializes in evaluating information, identifying patterns, and drawing insights. Focus on analysis and interpretation.",
        )

        communicator = SingleAgent(
            backend=backend,
            agent_id="communicator",
            system_message="You are a skilled communicator who excels at synthesizing complex information into clear, engaging presentations. Focus on clarity and accessibility.",
        )

        # Create orchestrator with three agents
        agents = {
            "researcher": researcher,
            "analyst": analyst,
            "communicator": communicator,
        }

        orchestrator = Orchestrator(agents=agents)

        # Create UI for coordination display
        ui = CoordinationUI(display_type="terminal", logging_enabled=True)

        print("👥 Created three-agent system:")
        print("   🔍 Researcher - Comprehensive information gathering")
        print("   📊 Analyst - Critical analysis and pattern recognition")
        print("   💬 Communicator - Clear synthesis and presentation")
        print()

        # Test question that benefits from all three perspectives
        test_question = "What are the main challenges and opportunities in developing sustainable cities, and what strategies show the most promise?"

        print(f"📝 Question: {test_question}")
        print("\n🎭 Starting three-agent coordination...")
        print("=" * 60)

        # Coordinate with UI (returns final response)
        final_response = await ui.coordinate(orchestrator, test_question)

        print("\n" + "=" * 60)
        print("✅ Three-agent coordination completed successfully!")
        print(f"📄 Final response length: {len(final_response)} characters")

        return True

    except Exception as e:
        print(f"❌ Three-agent coordination test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_three_agents_simple():
    """Simple three-agent test without UI for basic functionality verification."""
    print("\n🧪 Simple Three-Agent Test (No UI)")
    print("-" * 40)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found - skipping simple test")
        return False

    try:
        backend = ResponseBackend(api_key=api_key)

        # Create minimal agents with different roles
        planner = SingleAgent(
            backend=backend,
            agent_id="planner",
            system_message="You are a strategic planner. Focus on planning and organization.",
        )

        executor = SingleAgent(
            backend=backend,
            agent_id="executor",
            system_message="You are an executor. Focus on implementation and practical steps.",
        )

        evaluator = SingleAgent(
            backend=backend,
            agent_id="evaluator",
            system_message="You are an evaluator. Focus on assessment and quality control.",
        )

        orchestrator = Orchestrator(agents={"planner": planner, "executor": executor, "evaluator": evaluator})

        print("📤 Testing simple three-agent coordination...")

        messages = [
            {
                "role": "user",
                "content": "How can we improve team productivity in a remote work environment?",
            },
        ]

        response_content = ""
        async for chunk in orchestrator.chat(messages):
            if chunk.type == "content" and chunk.content:
                response_content += chunk.content
                print(chunk.content, end="", flush=True)
            elif chunk.type == "error":
                print(f"\n❌ Error: {chunk.error}")
                return False
            elif chunk.type == "done":
                break

        print(f"\n✅ Simple test completed. Response length: {len(response_content)} characters")
        return True

    except Exception as e:
        print(f"❌ Simple three-agent test failed: {e}")
        return False


async def test_three_agents_consensus():
    """Test consensus building with three agents having different viewpoints."""
    print("\n🤝 Three-Agent Consensus Test")
    print("-" * 40)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not found - skipping consensus test")
        return False

    try:
        backend = ResponseBackend(api_key=api_key)

        # Create agents with potentially different perspectives
        optimist = SingleAgent(
            backend=backend,
            agent_id="optimist",
            system_message="You are an optimistic viewpoint agent. Focus on opportunities and positive outcomes.",
        )

        realist = SingleAgent(
            backend=backend,
            agent_id="realist",
            system_message="You are a realistic viewpoint agent. Focus on practical considerations and balanced perspectives.",
        )

        skeptic = SingleAgent(
            backend=backend,
            agent_id="skeptic",
            system_message="You are a skeptical viewpoint agent. Focus on potential challenges and risks.",
        )

        orchestrator = Orchestrator(agents={"optimist": optimist, "realist": realist, "skeptic": skeptic})

        print("📤 Testing consensus building with diverse viewpoints...")

        # Question that might generate different perspectives
        messages = [
            {
                "role": "user",
                "content": "What is the future outlook for artificial intelligence in healthcare?",
            },
        ]

        response_content = ""
        async for chunk in orchestrator.chat(messages):
            if chunk.type == "content" and chunk.content:
                response_content += chunk.content
                print(chunk.content, end="", flush=True)
            elif chunk.type == "error":
                print(f"\n❌ Error: {chunk.error}")
                return False
            elif chunk.type == "done":
                break

        print(f"\n✅ Consensus test completed. Response length: {len(response_content)} characters")
        return True

    except Exception as e:
        print(f"❌ Consensus test failed: {e}")
        return False


async def main():
    """Run three-agent coordination tests."""
    print("🚀 MassGen - Three Agents Test Suite")
    print("=" * 60)

    results = []

    # Run simple test first
    results.append(await test_three_agents_simple())

    # Run consensus test
    if results[0]:
        results.append(await test_three_agents_consensus())
    else:
        print("⚠️  Skipping consensus test due to simple test failure")
        results.append(False)

    # Run full coordination test (most complex)
    if sum(results) >= 1:  # Run if at least one previous test passes
        results.append(await test_three_agents_coordination())
    else:
        print("⚠️  Skipping full coordination test due to previous failures")
        results.append(False)

    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Results:")
    print(f"✅ Passed: {sum(results)}")
    print(f"❌ Failed: {len(results) - sum(results)}")

    if all(results):
        print("🎉 All three-agent tests passed!")
        print("✅ Three-agent coordination is working correctly")
    elif sum(results) >= 2:
        print("✅ Most three-agent tests passed - system is functional")
    else:
        print("⚠️  Multiple tests failed - check API key and network connection")


if __name__ == "__main__":
    asyncio.run(main())
