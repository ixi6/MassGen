"""
Configurable video frame extraction strategies.

Supports two modes:
- **uniform**: FPS-based (default 1 FPS) or fixed count extraction, evenly spaced
- **scene**: PySceneDetect-based scene change detection with per-scene sampling

All modes enforce a hard frame cap (max_frames, absolute max 60) for cost control.
Scene mode gracefully falls back to uniform when PySceneDetect is not installed.
"""

import base64
import enum
from dataclasses import dataclass
from pathlib import Path

from massgen.logger_config import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_EXTRACTION_MODE = "scene"
DEFAULT_MAX_FRAMES = 30
ABSOLUTE_MAX_FRAMES = 60
DEFAULT_FPS = 1.0
DEFAULT_NUM_FRAMES = 8  # Legacy fallback
DEFAULT_SCENE_THRESHOLD = 0.3
DEFAULT_FRAMES_PER_SCENE = 3

# Image resize limits (matching OpenAI Vision API constraints)
_MAX_SHORT_SIDE = 768
_MAX_LONG_SIDE = 2000


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class ExtractionMode(enum.Enum):
    UNIFORM = "uniform"
    SCENE = "scene"


@dataclass
class VideoExtractionConfig:
    """Configuration for video frame extraction."""

    extraction_mode: ExtractionMode
    max_frames: int
    fps: float
    threshold: float
    frames_per_scene: int
    num_frames: int | None  # If set, overrides fps-based calc in uniform mode

    @classmethod
    def from_video_config(
        cls,
        video_config: dict | None,
        legacy_num_frames: int | None = None,
    ) -> "VideoExtractionConfig":
        """Parse a VideoExtractionConfig from a video config dict.

        Args:
            video_config: Dict from multimodal_config["video"], may be None.
            legacy_num_frames: Legacy num_frames parameter from understand_video
                signature. Config value takes priority if both are set.
        """
        cfg = video_config or {}

        # Parse extraction mode with fallback to scene
        mode_str = cfg.get("extraction_mode", DEFAULT_EXTRACTION_MODE)
        try:
            extraction_mode = ExtractionMode(mode_str)
        except ValueError:
            logger.warning(
                f"[video_extraction] Unknown extraction_mode '{mode_str}', " f"falling back to '{DEFAULT_EXTRACTION_MODE}'",
            )
            extraction_mode = ExtractionMode(DEFAULT_EXTRACTION_MODE)

        # max_frames: configurable but capped at ABSOLUTE_MAX_FRAMES
        max_frames = min(
            cfg.get("max_frames", DEFAULT_MAX_FRAMES),
            ABSOLUTE_MAX_FRAMES,
        )

        # num_frames: config value takes priority over legacy param
        num_frames = cfg.get("num_frames") or legacy_num_frames

        return cls(
            extraction_mode=extraction_mode,
            max_frames=max_frames,
            fps=cfg.get("fps", DEFAULT_FPS),
            threshold=cfg.get("threshold", DEFAULT_SCENE_THRESHOLD),
            frames_per_scene=cfg.get("frames_per_scene", DEFAULT_FRAMES_PER_SCENE),
            num_frames=num_frames,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_frames(video_path: Path, config: VideoExtractionConfig) -> list[str]:
    """Extract frames from a video using the configured strategy.

    Args:
        video_path: Path to the video file.
        config: Extraction configuration.

    Returns:
        List of base64-encoded JPEG frame strings.
    """
    if config.extraction_mode == ExtractionMode.SCENE:
        return _extract_scene_frames(video_path, config)
    else:
        return _extract_uniform_frames(video_path, config)


# ---------------------------------------------------------------------------
# Uniform extraction
# ---------------------------------------------------------------------------


def _extract_uniform_frames(
    video_path: Path,
    config: VideoExtractionConfig,
) -> list[str]:
    """Extract evenly spaced frames using FPS-based or fixed count logic.

    Priority: num_frames (if set) > fps-based calculation.
    Always capped at config.max_frames.
    """
    import cv2

    video = cv2.VideoCapture(str(video_path))
    if not video.isOpened():
        raise RuntimeError(f"Failed to open video file: {video_path}")

    try:
        total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
        video_fps = video.get(cv2.CAP_PROP_FPS) or 25.0

        if total_frames == 0:
            raise RuntimeError(f"Video file has no frames: {video_path}")

        # Determine target frame count
        if config.num_frames is not None:
            target = config.num_frames
        else:
            duration_sec = total_frames / video_fps
            target = int(duration_sec * config.fps)

        # Cap and handle edge cases
        target = max(1, min(target, config.max_frames, total_frames))

        # Compute evenly spaced indices
        if target >= total_frames:
            indices = list(range(total_frames))
        else:
            step = total_frames / target
            indices = [int(i * step) for i in range(target)]

        return _read_frames_at_indices(video, indices)
    finally:
        video.release()


# ---------------------------------------------------------------------------
# Scene-based extraction
# ---------------------------------------------------------------------------


def _detect_scenes(video_path: Path, threshold: float) -> list:
    """Run PySceneDetect on the video and return the scene list.

    Returns a list of (start_timecode, end_timecode) tuples.
    Raises ImportError if scenedetect is not available.
    """
    from scenedetect import ContentDetector, SceneManager, open_video

    video = open_video(str(video_path))
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold))
    scene_manager.detect_scenes(video)
    return scene_manager.get_scene_list()


def _extract_scene_frames(
    video_path: Path,
    config: VideoExtractionConfig,
) -> list[str]:
    """Extract frames based on scene change detection.

    Falls back to uniform extraction if:
    - PySceneDetect is not installed
    - No scenes are detected
    """
    try:
        scene_list = _detect_scenes(video_path, config.threshold)
    except (ImportError, Exception) as exc:
        if isinstance(exc, ImportError):
            logger.info(
                "[video_extraction] PySceneDetect not installed, " "falling back to uniform extraction. " "Install with: pip install massgen[video]",
            )
        else:
            logger.warning(
                f"[video_extraction] Scene detection failed ({exc}), " "falling back to uniform extraction",
            )
        return _extract_uniform_frames(video_path, config)

    if not scene_list:
        logger.info(
            "[video_extraction] No scenes detected, falling back to uniform extraction",
        )
        return _extract_uniform_frames(video_path, config)

    # Compute frame indices per scene
    all_indices: list[int] = []
    scene_durations: list[int] = []

    for start, end in scene_list:
        start_frame = start.get_frames()
        end_frame = end.get_frames()
        duration = max(1, end_frame - start_frame)
        scene_durations.append(duration)

        # Sample frames_per_scene evenly within this scene
        n = min(config.frames_per_scene, duration)
        if n >= duration:
            indices = list(range(start_frame, end_frame))
        else:
            step = duration / n
            indices = [int(start_frame + i * step) for i in range(n)]
        all_indices.extend(indices)

    total_requested = len(all_indices)

    # Cap at max_frames if needed
    if len(all_indices) > config.max_frames:
        logger.info(
            f"[video_extraction] Detected {len(scene_list)} scenes, " f"extracting {config.max_frames} frames " f"(capped from {total_requested})",
        )
        # Keep at least 1 frame per scene, distribute remainder proportionally
        all_indices = _cap_scene_indices(
            scene_list,
            scene_durations,
            config.max_frames,
        )
    else:
        logger.info(
            f"[video_extraction] Detected {len(scene_list)} scenes, " f"extracting {len(all_indices)} frames",
        )

    # Read the actual frames
    import cv2

    video = cv2.VideoCapture(str(video_path))
    if not video.isOpened():
        raise RuntimeError(f"Failed to open video file: {video_path}")

    try:
        return _read_frames_at_indices(video, all_indices)
    finally:
        video.release()


def _cap_scene_indices(
    scene_list: list,
    scene_durations: list[int],
    max_frames: int,
) -> list[int]:
    """Distribute max_frames across scenes proportionally by duration.

    Each scene gets at least 1 frame. Remaining frames are distributed
    proportionally by scene duration.
    """
    num_scenes = len(scene_list)
    if max_frames <= num_scenes:
        # One frame per scene (or fewer scenes than budget)
        indices = []
        for i, (start, end) in enumerate(scene_list[:max_frames]):
            mid = (start.get_frames() + end.get_frames()) // 2
            indices.append(mid)
        return indices

    # Each scene gets 1 base frame, distribute remainder proportionally
    total_duration = sum(scene_durations)
    remainder = max_frames - num_scenes
    indices: list[int] = []

    for i, (start, end) in enumerate(scene_list):
        start_frame = start.get_frames()
        end_frame = end.get_frames()
        duration = scene_durations[i]

        # 1 base + proportional share
        extra = round(remainder * duration / total_duration) if total_duration > 0 else 0
        n = 1 + extra
        n = min(n, duration)

        if n >= (end_frame - start_frame):
            scene_indices = list(range(start_frame, end_frame))
        else:
            step = (end_frame - start_frame) / n
            scene_indices = [int(start_frame + j * step) for j in range(n)]

        indices.extend(scene_indices)

    # Final trim in case rounding produced too many
    return indices[:max_frames]


# ---------------------------------------------------------------------------
# Shared frame reading
# ---------------------------------------------------------------------------


def _read_frames_at_indices(video, indices: list[int]) -> list[str]:
    """Read and encode frames at the given indices from an open cv2.VideoCapture.

    Resizes frames to fit within 768×2000 limits and encodes as JPEG q=85.
    Returns list of base64-encoded strings.
    """
    import cv2

    frames_base64: list[str] = []

    for frame_idx in indices:
        video.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = video.read()
        if not ret:
            continue

        # Resize if needed
        height, width = frame.shape[:2]
        short_side = min(width, height)
        long_side = max(width, height)

        if short_side > _MAX_SHORT_SIDE or long_side > _MAX_LONG_SIDE:
            short_scale = _MAX_SHORT_SIDE / short_side if short_side > _MAX_SHORT_SIDE else 1.0
            long_scale = _MAX_LONG_SIDE / long_side if long_side > _MAX_LONG_SIDE else 1.0
            scale_factor = min(short_scale, long_scale) * 0.95

            new_width = int(width * scale_factor)
            new_height = int(height * scale_factor)
            frame = cv2.resize(
                frame,
                (new_width, new_height),
                interpolation=cv2.INTER_LANCZOS4,
            )

        # Encode as JPEG quality 85
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
        ret, buffer = cv2.imencode(".jpg", frame, encode_param)
        if not ret:
            continue

        frames_base64.append(base64.b64encode(buffer).decode("utf-8"))

    if not frames_base64:
        raise RuntimeError("Failed to extract any frames from video")

    return frames_base64
