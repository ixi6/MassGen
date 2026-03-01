#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


class CloudJobError(RuntimeError):
    """Raised when a cloud job fails or returns invalid output."""


@dataclass
class CloudJobRequest:
    """Payload for launching a cloud run."""

    prompt: str
    config_yaml: str
    timeout_seconds: int
    env: Dict[str, str]
    output_filename: str = "final_answer.txt"


@dataclass
class CloudJobResult:
    """Result returned from the cloud launcher."""

    final_answer: str
    artifacts_dir: Path
    local_log_dir: Optional[Path]
    local_events_path: Optional[Path]
    remote_log_dir: Optional[str]
    raw_stdout: str
    raw_stderr: str


class CloudJobLauncher:
    """Interface for launching cloud jobs."""

    RESULT_MARKER = "__MASSGEN_CLOUD_JOB_RESULT__"
    _DEFAULT_ENV_KEYS = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "XAI_API_KEY",
        "OPENROUTER_API_KEY",
        "TOGETHER_API_KEY",
        "FIREWORKS_API_KEY",
        "GROQ_API_KEY",
        "NEBIUS_API_KEY",
        "CEREBRAS_API_KEY",
        "POE_API_KEY",
        "QWEN_API_KEY",
        "AZURE_OPENAI_API_KEY",
    )

    def __init__(self, workspace_root: Optional[Path] = None):
        base = workspace_root or (Path.cwd() / ".massgen" / "cloud_jobs")
        self.workspace_root = base
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def launch(self, request: CloudJobRequest) -> CloudJobResult:
        raise NotImplementedError

    @classmethod
    def _extract_marker_payload(cls, stdout: str) -> Optional[Dict[str, object]]:
        for line in reversed(stdout.splitlines()):
            if line.startswith(cls.RESULT_MARKER):
                raw = line[len(cls.RESULT_MARKER) :].strip()
                return json.loads(raw)
        return None

    @classmethod
    def collect_cloud_env(cls) -> Dict[str, str]:
        """Collect API-key style env vars for forwarding to cloud runtime."""
        env: Dict[str, str] = {}
        for key in cls._DEFAULT_ENV_KEYS:
            value = os.getenv(key)
            if value:
                env[key] = value
        return env
