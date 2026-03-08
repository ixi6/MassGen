"""
Generate captions/subtitles for videos using AI analysis.

This tool analyzes videos frame-by-frame and generates SRT/VTT caption files
with timestamps aligned to the video content.
"""

import json
from pathlib import Path

from massgen.tool._result import ExecutionResult, TextContent


def _validate_path_access(path: Path, allowed_paths: list[Path] | None = None) -> None:
    """
    Validate that a path is within allowed directories.

    Args:
        path: Path to validate
        allowed_paths: List of allowed base paths (optional)

    Raises:
        ValueError: If path is not within allowed directories
    """
    if not allowed_paths:
        return  # No restrictions

    for allowed_path in allowed_paths:
        try:
            path.relative_to(allowed_path)
            return  # Path is within this allowed directory
        except ValueError:
            continue

    raise ValueError(f"Path not in allowed directories: {path}")


def _generate_srt(captions: list[dict]) -> str:
    """
    Generate SRT (SubRip Subtitle) format content.

    Args:
        captions: List of caption dicts with 'start_time', 'end_time', 'text'

    Returns:
        SRT formatted string
    """
    srt_content = []

    for idx, caption in enumerate(captions, 1):
        start = caption["start_time"]
        end = caption["end_time"]
        text = caption["text"]

        # Convert seconds to SRT timestamp format (HH:MM:SS,mmm)
        def format_time(seconds):
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

        srt_content.append(f"{idx}\n")
        srt_content.append(f"{format_time(start)} --> {format_time(end)}\n")
        srt_content.append(f"{text}\n\n")

    return "".join(srt_content)


def _generate_vtt(captions: list[dict]) -> str:
    """
    Generate VTT (WebVTT) format content.

    Args:
        captions: List of caption dicts with 'start_time', 'end_time', 'text'

    Returns:
        VTT formatted string
    """
    vtt_content = ["WEBVTT\n\n"]

    for caption in captions:
        start = caption["start_time"]
        end = caption["end_time"]
        text = caption["text"]

        # Convert seconds to VTT timestamp format (HH:MM:SS.mmm)
        def format_time(seconds):
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int((seconds % 1) * 1000)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

        vtt_content.append(f"{format_time(start)} --> {format_time(end)}\n")
        vtt_content.append(f"{text}\n\n")

    return "".join(vtt_content)


async def generate_captions(
    video_path: str,
    num_captions: int = 10,
    caption_style: str = "technical",
    output_format: str = "both",
    allowed_paths: list[str] | None = None,
    agent_cwd: str | None = None,
) -> ExecutionResult:
    """
    Generate captions/subtitles for a video using AI analysis.

    This tool analyzes a video file by extracting frames and using AI vision to generate
    timestamped captions describing what's happening in the video. Useful for creating
    accessible content and documentation.

    Args:
        video_path: Path to the video file (MP4, GIF, etc.)
                   - Relative path: Resolved relative to workspace
                   - Absolute path: Must be within allowed directories
        num_captions: Number of captions to generate (default: 10)
                     - Higher values = more detailed captions
                     - Each caption covers video_duration / num_captions seconds
        caption_style: Style of captions (default: "technical")
                      - "technical": Technical descriptions (for demos, tutorials)
                      - "descriptive": General descriptions (for accessibility)
                      - "action": Action-focused (what's happening on screen)
        output_format: Output format (default: "both")
                      - "srt": SubRip Subtitle format
                      - "vtt": WebVTT format
                      - "both": Generate both SRT and VTT files
        allowed_paths: List of allowed base paths for validation (optional)
        agent_cwd: Agent's current working directory (automatically injected, optional)

    Returns:
        ExecutionResult containing:
        - success: Whether operation succeeded
        - operation: "generate_captions"
        - video_path: Path to the video file
        - num_captions: Number of captions generated
        - srt_file: Path to SRT file (if generated)
        - vtt_file: Path to VTT file (if generated)
        - captions: List of caption dicts with timestamps and text
        - errors: Any errors encountered

    Examples:
        # Generate captions for a MassGen demo video
        generate_captions(
            "massgen_terminal.mp4",
            num_captions=12,
            caption_style="technical"
        )
        → Generates technical captions for the demo

        # Create accessibility captions
        generate_captions(
            "demo.mp4",
            num_captions=20,
            caption_style="descriptive",
            output_format="vtt"
        )
        → Generates descriptive VTT captions

    Prerequisites:
        - understand_video tool dependencies (opencv-python, OpenAI API key)
        - Video file must exist and be readable

    Security:
        - Video file must be within allowed directories
        - Caption files saved to agent workspace

    Note:
        - Captions are evenly distributed across video duration
        - AI analyzes frames at caption timestamps for context
        - Combines frame analysis to create coherent narrative
    """
    try:
        # Import understand_video for frame analysis
        from massgen.tool._multimodal_tools.understand_video import understand_video

        # Convert allowed_paths from strings to Path objects
        allowed_paths_list = [Path(p) for p in allowed_paths] if allowed_paths else None

        # Resolve base directory
        base_dir = Path(agent_cwd) if agent_cwd else Path.cwd()

        # Resolve video path
        if Path(video_path).is_absolute():
            vid_path = Path(video_path).resolve()
        else:
            vid_path = (base_dir / video_path).resolve()

        # Validate video path
        _validate_path_access(vid_path, allowed_paths_list)

        if not vid_path.exists():
            result = {
                "success": False,
                "operation": "generate_captions",
                "error": f"Video file does not exist: {vid_path}",
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )

        # Get video duration using opencv
        try:
            import cv2

            video = cv2.VideoCapture(str(vid_path))
            if not video.isOpened():
                raise Exception(f"Failed to open video file: {vid_path}")

            fps = video.get(cv2.CAP_PROP_FPS)
            frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0
            video.release()

            if duration == 0:
                raise Exception("Could not determine video duration")

        except ImportError:
            result = {
                "success": False,
                "operation": "generate_captions",
                "error": "opencv-python is required. Install with: pip install opencv-python",
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )
        except Exception as e:
            result = {
                "success": False,
                "operation": "generate_captions",
                "error": f"Failed to analyze video: {str(e)}",
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )

        # Generate analysis prompts based on caption style
        style_prompts = {
            "technical": "Describe what's happening in this MassGen terminal session. Focus on: agent status, coordination events, tool usage, and progress indicators. Be concise and technical.",
            "descriptive": "Describe what's visible on screen in detail. Focus on text content, visual elements, and any changes happening.",
            "action": "Describe the specific actions and events occurring. Focus on what the system is doing at this moment.",
        }

        analysis_prompt = style_prompts.get(caption_style, style_prompts["technical"])

        # Analyze video with understand_video to get comprehensive understanding
        video_analysis = await understand_video(
            video_path=str(vid_path),
            prompt=f"{analysis_prompt}\n\nVideo duration is {duration:.1f} seconds. Provide a chronological description covering the entire video.",
            num_frames=num_captions,  # One frame per caption
            allowed_paths=allowed_paths,
            agent_cwd=agent_cwd,
        )

        # Parse analysis results
        analysis_data = json.loads(video_analysis.output_blocks[0].data)

        if not analysis_data["success"]:
            result = {
                "success": False,
                "operation": "generate_captions",
                "error": f"Video analysis failed: {analysis_data.get('error', 'Unknown error')}",
            }
            return ExecutionResult(
                output_blocks=[TextContent(data=json.dumps(result, indent=2))],
            )

        # Extract AI response and split into caption segments
        ai_response = analysis_data["response"]

        # Generate captions with timestamps
        captions = []
        caption_duration = duration / num_captions

        # Parse AI response to extract segments (this is a simple approach)
        # For better results, we'd ask AI to structure the response with timestamps
        segments = ai_response.split("\n\n")  # Split by paragraphs
        if len(segments) < num_captions:
            segments = ai_response.split(". ")  # Split by sentences if needed

        for i in range(num_captions):
            start_time = i * caption_duration
            end_time = (i + 1) * caption_duration

            # Get caption text (cycle through segments if we don't have enough)
            caption_text = segments[i % len(segments)].strip() if segments else f"Frame {i + 1}"

            # Limit caption length (SRT best practice: ~42 characters per line, 2 lines max)
            if len(caption_text) > 84:
                caption_text = caption_text[:81] + "..."

            captions.append(
                {
                    "index": i + 1,
                    "start_time": start_time,
                    "end_time": end_time,
                    "text": caption_text,
                },
            )

        # Generate caption files
        srt_file_path = None
        vtt_file_path = None

        if output_format in ["srt", "both"]:
            srt_content = _generate_srt(captions)
            srt_file_path = base_dir / f"{vid_path.stem}.srt"
            srt_file_path.write_text(srt_content)

        if output_format in ["vtt", "both"]:
            vtt_content = _generate_vtt(captions)
            vtt_file_path = base_dir / f"{vid_path.stem}.vtt"
            vtt_file_path.write_text(vtt_content)

        # Compile result
        result = {
            "success": True,
            "operation": "generate_captions",
            "video_path": str(vid_path),
            "video_duration_seconds": round(duration, 2),
            "num_captions": len(captions),
            "caption_style": caption_style,
            "output_format": output_format,
            "captions": captions,
        }

        if srt_file_path:
            result["srt_file"] = str(srt_file_path)

        if vtt_file_path:
            result["vtt_file"] = str(vtt_file_path)

        return ExecutionResult(
            output_blocks=[TextContent(data=json.dumps(result, indent=2))],
        )

    except Exception as e:
        result = {
            "success": False,
            "operation": "generate_captions",
            "error": f"Failed to generate captions: {str(e)}",
        }
        return ExecutionResult(
            output_blocks=[TextContent(data=json.dumps(result, indent=2))],
        )
