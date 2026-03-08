#!/usr/bin/env python3
"""
MassGen Example: Three Agent Coordination

This example demonstrates three-agent coordination using the
multi-region coordination UI. Three agents with different specialties work
together on a question that benefits from multiple perspectives.

Features:
- Three agents with distinct specialties
- Multi-region terminal display
- Real coordination with voting and consensus
- Cost-effective with gpt-4o-mini model

Note: Requires OPENAI_API_KEY in environment.
"""

import asyncio
import os
import sys

from massgen import Orchestrator, ResponseBackend, create_simple_agent
from massgen.frontend.coordination_ui import coordinate_with_terminal_ui

# Add project root to path
project_root = os.path.dirname(__file__)
sys.path.insert(0, project_root)


async def three_agent_example():
    """Demonstrate three agent coordination with multi-region UI."""

    print("🎯 MassGen: Three Agent Coordination")
    print("=" * 50)

    # Check API key
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY not found")
        return False

    print("✅ OpenAI API key found")

    try:
        # Create backend
        backend = ResponseBackend(model="gpt-4o-mini")
        print("✅ OpenAI backend created")

        # Create three agents with different specialties
        scientist = create_simple_agent(
            backend=backend,
            system_message="You are a scientist who focuses on scientific accuracy and evidence-based explanations.",
        )
        engineer = create_simple_agent(
            backend=backend,
            system_message="You are an engineer who focuses on practical applications and real-world implementation.",
        )
        educator = create_simple_agent(
            backend=backend,
            system_message="You are an educator who focuses on clear, accessible explanations for learning.",
        )

        print("✅ Created 3 agents:")
        print("  • scientist: Scientific accuracy")
        print("  • engineer: Practical applications")
        print("  • educator: Clear explanations")

        # Create orchestrator
        orchestrator = Orchestrator(agents={"scientist": scientist, "engineer": engineer, "educator": educator})
        print("✅ orchestrator ready")

        # Question that benefits from multiple perspectives
        question = "How does solar energy work and why is it important?"
        print(f"\n💬 Question: {question}")
        print("🔄 Starting three-agent coordination...\n")

        # Use coordination UI
        result = await coordinate_with_terminal_ui(
            orchestrator,
            question,
            enable_final_presentation=True,
            logging_enabled=False,
        )

        print("\n✅ Three agent coordination completed!")

        # Show results
        orchestrator_status = orchestrator.get_status()
        selected_agent = orchestrator_status.get("selected_agent")
        vote_results = orchestrator_status.get("vote_results", {})

        print("\n📊 Results:")
        print(f"🏆 Selected agent: {selected_agent}")
        if vote_results.get("vote_counts"):
            for agent, votes in vote_results["vote_counts"].items():
                print(f"🗳️ {agent}: {votes} vote(s)")

        return result

    except Exception as e:
        print(f"❌ Failed: {e}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    result = asyncio.run(three_agent_example())
    if result:
        print("\n🚀 Three agent coordination successful!")
        print("💡 Demonstrated multi-agent collaboration with diverse expertise")
    else:
        print("\n⚠️ Check error above")

    print("\n📝 Three agent example completed!")
