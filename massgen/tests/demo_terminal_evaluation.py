#!/usr/bin/env python3
"""
Demo script for terminal evaluation feature.

This script demonstrates the run_massgen_with_recording tool in action:
1. Creates a minimal test config
2. Records a MassGen session with VHS
3. Analyzes the terminal display with understand_video
4. Prints the evaluation results

Usage:
    uv run python massgen/tests/demo_terminal_evaluation.py

Prerequisites:
    - VHS installed: brew install vhs
    - OpenAI API key in .env file
"""

import asyncio
import json
import sys
from pathlib import Path


def check_prerequisites():
    """Check if prerequisites are met."""
    import os
    import subprocess

    # Check VHS
    try:
        result = subprocess.run(
            ["vhs", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            print("❌ VHS is not installed")
            print("   Install: brew install vhs (macOS)")
            return False
        print("✅ VHS is installed")
    except (subprocess.SubprocessError, FileNotFoundError):
        print("❌ VHS is not installed")
        print("   Install: brew install vhs (macOS)")
        return False

    # Check OpenAI API key
    from dotenv import load_dotenv

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY not found in .env file")
        return False
    print("✅ OpenAI API key configured")

    return True


async def run_demo():
    """Run the terminal evaluation demo."""
    print("\n" + "=" * 60)
    print("MassGen Terminal Evaluation Demo")
    print("=" * 60 + "\n")

    # Check prerequisites
    if not check_prerequisites():
        print("\n❌ Prerequisites not met. Please install required tools.")
        return

    # Import the tools
    from massgen.tool._multimodal_tools.run_massgen_with_recording import (
        run_massgen_with_recording,
    )
    from massgen.tool._multimodal_tools.understand_video import understand_video

    # Create workspace in tests directory so we can see the video
    tests_dir = Path(__file__).parent
    demo_workspace = tests_dir / "demo_terminal_evaluation_workspace"
    demo_workspace.mkdir(exist_ok=True)

    temp_path = demo_workspace

    # Create a very simple config for quick testing
    config_content = """
agents:
  - id: "demo_agent"
    backend:
      type: "openai"
      model: "gpt-5-nano"
      cwd: "workspace_demo"
    system_message: |
      You are a demo agent for terminal evaluation.
      When asked "What is 2+2?", simply respond: "2 + 2 = 4"
      Be concise.

orchestrator:
  snapshot_storage: "snapshots_demo"
  agent_temporary_workspace: "temp_workspaces_demo"

ui:
  display_type: "rich_terminal"
  logging_enabled: false
"""

    config_path = temp_path / "demo_config.yaml"
    config_path.write_text(config_content)

    print(f"📝 Created test config: {config_path}")
    print(f"📁 Working directory: {temp_path}\n")

    # Run the terminal recording
    print("🎥 Starting terminal recording...")
    print("   This will:")
    print("   1. Record MassGen session with VHS")
    print("   2. Save video to workspace")
    print("   3. Analyze terminal display with GPT-4.1")
    print("   (This may take 30-60 seconds)\n")

    try:
        # Step 1: Record the MassGen session
        print("Step 1/2: Recording MassGen session...")
        record_result = await run_massgen_with_recording(
            config_path=str(config_path),
            question="What is 2+2?",
            output_format="mp4",  # Use MP4 for better quality
            timeout_seconds=30,  # Quick timeout for demo
            width=1920,
            height=1080,
            agent_cwd=str(temp_path),
        )

        # Parse recording results
        record_data = json.loads(record_result.output_blocks[0].data)

        if not record_data["success"]:
            print(f"\n❌ Recording failed: {record_data.get('error', 'Unknown error')}\n")
            if "vhs_stderr" in record_data:
                print("VHS STDERR:")
                print(record_data["vhs_stderr"])
            return

        print(f"✅ Recording complete! Video saved to: {record_data['video_path']}\n")

        # Step 2: Analyze the video
        print("Step 2/2: Analyzing terminal display with GPT-4.1...")
        eval_result = await understand_video(
            video_path=record_data["video_path"],
            prompt=("Evaluate this terminal display recording. " "Focus on: 1) Visual clarity, 2) Information organization, " "3) Status indicators. Be concise."),
            num_frames=6,  # Fewer frames for faster processing
            agent_cwd=str(temp_path),
        )

        # Parse evaluation results
        eval_data = json.loads(eval_result.output_blocks[0].data)

        # Combine results for display
        output_data = {
            **record_data,
            "evaluation": eval_data if eval_data["success"] else {"error": eval_data.get("error")},
        }

        print("\n" + "=" * 60)
        print("Results")
        print("=" * 60 + "\n")

        print("✅ Recording and evaluation successful!\n")
        print(f"📹 Video: {output_data['video_path']}")
        print(f"📊 Format: {output_data['video_format']}")
        print(f"📏 Size: {output_data['video_size_bytes'] / 1024:.1f} KB")
        print(f"⏱️  Duration: {output_data['recording_duration_seconds']}s")

        if "evaluation" in output_data and output_data["evaluation"].get("success"):
            print(f"🖼️  Frames analyzed: {output_data['evaluation']['num_frames_extracted']}\n")

            print("=" * 60)
            print("Terminal Display Evaluation")
            print("=" * 60 + "\n")
            print(output_data["evaluation"]["response"])
            print()
        else:
            print("\n⚠️  Video evaluation skipped or failed")
            if "evaluation" in output_data and "error" in output_data["evaluation"]:
                print(f"   Error: {output_data['evaluation']['error']}")
            print()

        print("=" * 60)
        print(f"📂 All files saved to: {temp_path}")
        print(f"   - Video: {output_data['video_path']}")
        print(f"   - Config: {config_path}")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\n❌ Demo failed: {e}")
        import traceback

        traceback.print_exc()


def main():
    """Main entry point."""
    try:
        asyncio.run(run_demo())
    except KeyboardInterrupt:
        print("\n\n⚠️  Demo interrupted by user")
        sys.exit(1)


if __name__ == "__main__":
    main()
