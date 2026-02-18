# -*- coding: utf-8 -*-
"""
Read media files and analyze them using understand_* tools.

This is the primary tool for multimodal input in MassGen. It delegates to
understand_image, understand_audio, or understand_video based on file type.
These tools make external API calls to analyze the media content.

Supports batch mode for parallel analysis of multiple media files, including
multi-image prompts where multiple images are sent to the model together.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from massgen.logger_config import logger
from massgen.tool._decorators import context_params
from massgen.tool._result import ExecutionResult, TextContent


def _error_result(error: str) -> ExecutionResult:
    """Create an error ExecutionResult."""
    return ExecutionResult(
        output_blocks=[
            TextContent(
                data=json.dumps({"success": False, "operation": "read_media", "error": error}, indent=2),
            ),
        ],
    )


# Supported media types and their extensions
MEDIA_TYPE_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp"},
    "audio": {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".gif"},
}


def _detect_media_type(file_path: str) -> Optional[str]:
    """Detect media type from file extension.

    Args:
        file_path: Path to the media file

    Returns:
        Media type string ("image", "audio", "video") or None if unsupported
    """
    ext = Path(file_path).suffix.lower()
    for media_type, extensions in MEDIA_TYPE_EXTENSIONS.items():
        if ext in extensions:
            return media_type
    return None


def _validate_path_access(path: Path, allowed_paths: Optional[List[Path]] = None) -> None:
    """Validate that a path is within allowed directories.

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


@context_params(
    "backend_type",
    "model",
    "agent_cwd",
    "allowed_paths",
    "multimodal_config",
    "task_context",
)
async def read_media(
    file_path: Optional[str] = None,
    prompt: Optional[str] = None,
    inputs: Optional[List[Dict[str, Any]]] = None,
    max_concurrent: int = 4,
    agent_cwd: Optional[str] = None,
    allowed_paths: Optional[List[str]] = None,
    backend_type: Optional[str] = None,
    model: Optional[str] = None,
    multimodal_config: Optional[Dict[str, Any]] = None,
    task_context: Optional[str] = None,
) -> ExecutionResult:
    """
    Read and analyze media file(s) using external API calls.

    This tool delegates to understand_image, understand_audio, or understand_video
    based on the file type. These tools make external API calls to analyze the
    media content and return text descriptions.

    Supports batch mode: provide `inputs` (list of dicts) to analyze multiple
    media items in parallel, including multi-image prompts where multiple images
    are sent to the model together for comparison/analysis.

    Supports:
    - Images: png, jpg, jpeg, gif, webp, bmp
    - Audio: mp3, wav, m4a, ogg, flac, aac
    - Video: mp4, mov, avi, mkv, webm

    CRITICAL - Be Skeptical When Evaluating Work:
        When using this tool to evaluate your own or others' work, you MUST be
        critical and skeptical, not charitable. Look for flaws, not just strengths:

        - What's MISSING or incomplete?
        - What looks broken, misaligned, or poorly implemented?
        - Does it actually meet the requirements, or just look superficially OK?
        - What would a demanding user complain about?

        Include critique-focused language in your prompt, e.g.:
        - "What flaws, issues, or missing elements do you see?"
        - "What would a critical reviewer complain about?"
        - "Does this fully meet requirements or are there gaps?"

        Do NOT just ask "describe this" - that yields overly charitable analysis.

    Args:
        file_path: Path to a single media file (relative or absolute).
                   Use for simple single-file analysis.
        prompt: Optional prompt/question about the media content.
                For evaluation: include critical/skeptical framing in your prompt.
        inputs: List of input specs for batch/multi-image analysis.
                Each input is a dict with:
                - "files": Dict mapping names to paths, e.g. {"before": "a.png", "after": "b.png"}
                - "prompt": Optional prompt for this input (reference images by name)
                Multiple inputs are processed in parallel.
        max_concurrent: Maximum concurrent analyses for batch mode (default: 4).
        agent_cwd: Agent's current working directory (automatically injected).
        allowed_paths: List of allowed base paths for validation (optional).
        backend_type: Backend type (automatically injected from ExecutionContext).
        model: Model name (automatically injected from ExecutionContext).
        multimodal_config: Optional config overrides per modality.

    Returns:
        ExecutionResult containing text description/analysis of the media.
        For batch mode, returns results array with per-input status.

    Examples:
        # Simple single file analysis
        read_media(file_path="screenshot.png", prompt="Describe this")
        → Returns description of the image

        # Batch with multi-image comparison (parallel processing)
        read_media(
            inputs=[
                {"files": {"before": "v1.png", "after": "v2.png"}, "prompt": "Compare before and after"},
                {"files": {"error": "error.png"}, "prompt": "What error is shown?"}
            ],
            max_concurrent=2
        )
        → Returns batch results with each input processed in parallel

        # Critical evaluation
        read_media(file_path="website.png",
                   prompt="What flaws or issues do you see? Be critical.")
        → Returns critique-focused analysis
    """
    # Validate file_path / inputs - exactly one must be provided
    if file_path and inputs:
        return _error_result("Provide either 'file_path' or 'inputs', not both")
    if not file_path and not inputs:
        return _error_result("Must provide either 'file_path' or 'inputs'")

    # Validate inputs structure if provided
    if inputs:
        for i, inp in enumerate(inputs):
            if not isinstance(inp, dict):
                return _error_result(f"inputs[{i}] must be a dict, got {type(inp).__name__}")
            if "files" not in inp:
                return _error_result(f"inputs[{i}] missing required 'files' key")
            if not isinstance(inp["files"], dict) or not inp["files"]:
                return _error_result(f"inputs[{i}]['files'] must be a non-empty dict mapping names to paths")

    try:
        # Load task_context dynamically from CONTEXT.md (it may be created during execution)
        from massgen.context.task_context import load_task_context_with_warning

        task_context, context_warning = load_task_context_with_warning(agent_cwd, task_context)

        # Require CONTEXT.md for external API calls
        if not task_context:
            context_search_path = agent_cwd or "None (no agent_cwd provided)"
            return _error_result(
                f"CONTEXT.md not found in workspace: {context_search_path}. "
                "Before using read_media, create a CONTEXT.md file with task context. "
                "This helps external APIs understand what you're working on. "
                "See system prompt for instructions and examples.",
            )

        # Helper to add context warning to result dict if present
        def _add_warning(result_dict: Dict[str, Any]) -> Dict[str, Any]:
            if context_warning:
                result_dict["warning"] = context_warning
            return result_dict

        # Convert allowed_paths from strings to Path objects
        allowed_paths_list = [Path(p) for p in allowed_paths] if allowed_paths else None
        base_dir = Path(agent_cwd) if agent_cwd else Path.cwd()

        # Extract config overrides
        image_config = (multimodal_config or {}).get("image", {})
        audio_config = (multimodal_config or {}).get("audio", {})
        video_config = (multimodal_config or {}).get("video", {})

        # ------------------------------------------------------------------
        # SINGLE FILE MODE (backwards compatible)
        # ------------------------------------------------------------------
        if file_path:
            if Path(file_path).is_absolute():
                media_path = Path(file_path).resolve()
            else:
                media_path = (base_dir / file_path).resolve()

            _validate_path_access(media_path, allowed_paths_list)

            if not media_path.exists():
                return _error_result(f"File does not exist: {media_path}")

            media_type = _detect_media_type(file_path)
            if not media_type:
                return _error_result(
                    f"Unsupported file type: {media_path.suffix}. " "Supported: images (png, jpg, webp), audio (mp3, wav, m4a, ogg), video (mp4, mov, avi, mkv, webm, gif)",
                )

            logger.info(f"Using understand_{media_type} for {media_type} analysis")
            default_prompt = prompt or f"Please analyze this {media_type} and describe its contents."

            if media_type == "image":
                from massgen.tool._multimodal_tools.understand_image import (
                    understand_image,
                )

                image_kwargs: Dict[str, Any] = {
                    "image_path": str(media_path),
                    "prompt": default_prompt,
                    "agent_cwd": agent_cwd,
                    "allowed_paths": allowed_paths,
                    "task_context": task_context,
                }
                if image_config.get("model"):
                    image_kwargs["model"] = image_config["model"]

                result = await understand_image(**image_kwargs)
                # Add warning if present
                if context_warning:
                    for block in result.output_blocks:
                        if isinstance(block, TextContent):
                            try:
                                data = json.loads(block.data)
                                data["warning"] = context_warning
                                block.data = json.dumps(data, indent=2)
                            except (json.JSONDecodeError, AttributeError):
                                pass
                return result

            elif media_type == "audio":
                from massgen.tool._multimodal_tools.understand_audio import (
                    understand_audio,
                )

                result = await understand_audio(
                    audio_paths=[str(media_path)],
                    prompt=default_prompt,
                    backend_type=audio_config.get("backend") or backend_type,
                    model=audio_config.get("model"),
                    agent_cwd=agent_cwd,
                    allowed_paths=allowed_paths,
                    task_context=task_context,
                )
                if context_warning:
                    for block in result.output_blocks:
                        if isinstance(block, TextContent):
                            try:
                                data = json.loads(block.data)
                                data["warning"] = context_warning
                                block.data = json.dumps(data, indent=2)
                            except (json.JSONDecodeError, AttributeError):
                                pass
                return result

            elif media_type == "video":
                from massgen.tool._multimodal_tools.understand_video import (
                    understand_video,
                )

                result = await understand_video(
                    video_path=str(media_path),
                    prompt=default_prompt,
                    backend_type=video_config.get("backend") or backend_type,
                    model=video_config.get("model"),
                    agent_cwd=agent_cwd,
                    allowed_paths=allowed_paths,
                    task_context=task_context,
                )
                if context_warning:
                    for block in result.output_blocks:
                        if isinstance(block, TextContent):
                            try:
                                data = json.loads(block.data)
                                data["warning"] = context_warning
                                block.data = json.dumps(data, indent=2)
                            except (json.JSONDecodeError, AttributeError):
                                pass
                return result

        # ------------------------------------------------------------------
        # BATCH MODE with multi-image support
        # ------------------------------------------------------------------
        async def _process_one_input(idx: int, inp: Dict[str, Any], semaphore: asyncio.Semaphore) -> Dict[str, Any]:
            """Process a single input spec with concurrency control."""
            async with semaphore:
                try:
                    files_dict: Dict[str, str] = inp["files"]
                    input_prompt = inp.get("prompt") or prompt or "Please analyze and describe what you see."

                    # Determine media type from first file
                    first_path = next(iter(files_dict.values()))
                    media_type = _detect_media_type(first_path)

                    if not media_type:
                        return {
                            "input_index": idx,
                            "success": False,
                            "error": f"Unsupported file type for '{first_path}'",
                        }

                    # For now, only images support multi-file in single call
                    # Audio/video process first file only
                    if media_type == "image":
                        from massgen.tool._multimodal_tools.understand_image import (
                            understand_image,
                        )

                        image_kwargs: Dict[str, Any] = {
                            "images": files_dict,
                            "prompt": input_prompt,
                            "agent_cwd": agent_cwd,
                            "allowed_paths": allowed_paths,
                            "task_context": task_context,
                        }
                        if image_config.get("model"):
                            image_kwargs["model"] = image_config["model"]

                        result = await understand_image(**image_kwargs)

                        # Parse result
                        for block in result.output_blocks:
                            if isinstance(block, TextContent):
                                try:
                                    data = json.loads(block.data)
                                    data["input_index"] = idx
                                    return data
                                except json.JSONDecodeError as e:
                                    logger.error(
                                        f"[read_media] Failed to parse image result JSON at index {idx}: {e}. " f"Block data: {block.data[:200]}",
                                    )
                                    continue

                    elif media_type == "audio":
                        from massgen.tool._multimodal_tools.understand_audio import (
                            understand_audio,
                        )

                        # Audio: use all files
                        audio_paths = list(files_dict.values())
                        result = await understand_audio(
                            audio_paths=audio_paths,
                            prompt=input_prompt,
                            backend_type=audio_config.get("backend") or backend_type,
                            model=audio_config.get("model"),
                            agent_cwd=agent_cwd,
                            allowed_paths=allowed_paths,
                            task_context=task_context,
                        )
                        for block in result.output_blocks:
                            if isinstance(block, TextContent):
                                try:
                                    data = json.loads(block.data)
                                    data["input_index"] = idx
                                    return data
                                except json.JSONDecodeError as e:
                                    logger.error(
                                        f"[read_media] Failed to parse audio result JSON at index {idx}: {e}. " f"Block data: {block.data[:200]}",
                                    )
                                    continue

                    elif media_type == "video":
                        from massgen.tool._multimodal_tools.understand_video import (
                            understand_video,
                        )

                        # Video: use first file only
                        result = await understand_video(
                            video_path=first_path,
                            prompt=input_prompt,
                            backend_type=video_config.get("backend") or backend_type,
                            model=video_config.get("model"),
                            agent_cwd=agent_cwd,
                            allowed_paths=allowed_paths,
                            task_context=task_context,
                        )
                        for block in result.output_blocks:
                            if isinstance(block, TextContent):
                                try:
                                    data = json.loads(block.data)
                                    data["input_index"] = idx
                                    return data
                                except json.JSONDecodeError as e:
                                    logger.error(
                                        f"[read_media] Failed to parse video result JSON at index {idx}: {e}. " f"Block data: {block.data[:200]}",
                                    )
                                    continue

                    return {"input_index": idx, "success": False, "error": "No result returned"}

                except Exception as e:
                    logger.exception(f"Error processing input {idx}")
                    return {"input_index": idx, "success": False, "error": str(e)}

        # Execute all inputs in parallel with concurrency control
        semaphore = asyncio.Semaphore(max_concurrent)
        tasks = [_process_one_input(i, inp, semaphore) for i, inp in enumerate(inputs)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert any exceptions to error results
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append({"input_index": i, "success": False, "error": str(result)})
            else:
                final_results.append(result)

        # Calculate success/failure counts
        succeeded = sum(1 for r in final_results if r.get("success"))
        failed = len(final_results) - succeeded

        response_data = _add_warning(
            {
                "success": succeeded > 0,
                "operation": "read_media",
                "batch": True,
                "total": len(final_results),
                "succeeded": succeeded,
                "failed": failed,
                "results": final_results,
            },
        )

        return ExecutionResult(
            output_blocks=[TextContent(data=json.dumps(response_data, indent=2))],
        )

    except ValueError as ve:
        return _error_result(str(ve))

    except Exception as e:
        return _error_result(f"Failed to read media: {str(e)}")
