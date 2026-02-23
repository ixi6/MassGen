"""
Per-backend image calling functions for understand_image.

Each function takes a list of LoadedImage objects, a prompt, and a model name,
and returns the response text from the respective API.

This module handles only the API call layer. Image loading, validation, and
result formatting are handled by understand_image.py.
"""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from massgen.logger_config import logger

if TYPE_CHECKING:
    from massgen.tool._multimodal_tools.understand_image import LoadedImage


async def call_openai(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str,
) -> str:
    """Call OpenAI Responses API for image understanding.

    Refactored from the inline code previously in understand_image().
    """
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in environment")

    client = AsyncOpenAI(api_key=api_key)

    content: list[dict] = [{"type": "input_text", "text": prompt}]
    for img in loaded_images:
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{img.mime_type};base64,{img.base64_data}",
            },
        )

    logger.info(f"[image_backends] Using OpenAI {model} for {len(loaded_images)} image(s)")

    response = await client.responses.create(
        model=model,
        input=[{"role": "user", "content": content}],
    )

    return response.output_text if hasattr(response, "output_text") else str(response.output)


async def call_claude(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str,
) -> str:
    """Call Anthropic Claude API for image understanding.

    Uses the same content block format as understand_video._process_with_anthropic.
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not found in environment")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    content: list[dict] = []
    for img in loaded_images:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.mime_type,
                    "data": img.base64_data,
                },
            },
        )
    content.append({"type": "text", "text": prompt})

    logger.info(f"[image_backends] Using Claude {model} for {len(loaded_images)} image(s)")

    response = await client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    return response.content[0].text


async def call_gemini(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str,
) -> str:
    """Call Google Gemini API for image understanding.

    Uses the same Part.from_bytes format as understand_video._process_with_gemini.
    """
    from google import genai

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY not found in environment")

    client = genai.Client(api_key=api_key)

    contents = []
    for img in loaded_images:
        contents.append(
            genai.types.Part.from_bytes(
                data=base64.b64decode(img.base64_data),
                mime_type=img.mime_type,
            ),
        )
    contents.append(prompt)

    logger.info(f"[image_backends] Using Gemini {model} for {len(loaded_images)} image(s)")

    response = client.models.generate_content(model=model, contents=contents)

    return response.text


async def call_grok(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str,
) -> str:
    """Call xAI Grok API for image understanding.

    Uses OpenAI-compatible chat completions format, same as understand_video._process_with_grok.
    """
    from openai import AsyncOpenAI

    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        raise ValueError("XAI_API_KEY not found in environment")

    client = AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in loaded_images:
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img.mime_type};base64,{img.base64_data}",
                },
            },
        )

    logger.info(f"[image_backends] Using Grok {model} for {len(loaded_images)} image(s)")

    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
    )

    return response.choices[0].message.content


async def call_claude_code(
    loaded_images: list[LoadedImage],
    prompt: str,
    model: str | None = None,
    agent_cwd: str | None = None,
) -> str:
    """Call Claude Code SDK for image understanding.

    Copies images to a temporary directory and uses the Claude Code SDK
    query() function with Read-only permissions.
    """
    from claude_agent_sdk import (  # type: ignore
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        image_refs = []
        for img in loaded_images:
            dest = Path(tmpdir) / img.path.name
            shutil.copy2(img.path, dest)
            image_refs.append(dest.name)

        image_list = ", ".join(image_refs)
        full_prompt = f"Read and analyze the image(s) in this directory: {image_list}\n\n{prompt}"

        options_kwargs: dict = {
            "allowed_tools": ["Read"],
            "max_turns": 2,
            "cwd": tmpdir,
            # Unset CLAUDECODE to allow launching from within a Claude Code session
            # (the nested-session guard checks this env var)
            "env": {"CLAUDECODE": ""},
        }
        if model:
            options_kwargs["model"] = model

        options = ClaudeAgentOptions(**options_kwargs)
        client = ClaudeSDKClient(options)

        logger.info(f"[image_backends] Using Claude Code for {len(loaded_images)} image(s)")

        try:
            await client.connect()
            await client.query(full_prompt)

            response_text = ""
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            response_text += block.text
                elif isinstance(msg, ResultMessage):
                    break
        finally:
            await client.disconnect()

    return response_text


async def call_codex(
    loaded_images: list[LoadedImage],
    prompt: str,
    agent_cwd: str | None = None,
) -> str:
    """Call OpenAI Codex CLI for image understanding.

    Copies images to a temporary directory and uses the Codex CLI with -i flag.

    Sandboxing:
    - ``--skip-git-repo-check``: temp dir is not a git repo
    - ``--disable shell_tool``: prevent shell/bash execution
    - ``-c web_search="disabled"``: disable web search
    - ``cwd=tmpdir``: isolate filesystem access to temp dir with only copied images

    Auth: Creates a ``.codex/`` dir inside the temp dir with ``auth.json``
    copied from ``~/.codex/`` and sets ``CODEX_HOME`` to point there,
    matching the pattern used by ``massgen/backend/codex.py``.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        image_paths = []
        for img in loaded_images:
            dest = Path(tmpdir) / img.path.name
            shutil.copy2(img.path, dest)
            image_paths.append(str(dest))

        image_arg = ",".join(image_paths)

        # Set up CODEX_HOME with auth — same pattern as massgen/backend/codex.py
        codex_home = Path(tmpdir) / ".codex"
        codex_home.mkdir(parents=True, exist_ok=True)
        host_auth = Path.home() / ".codex" / "auth.json"
        if host_auth.exists():
            shutil.copy2(str(host_auth), str(codex_home / "auth.json"))
        host_config = Path.home() / ".codex" / "config.toml"
        if host_config.exists():
            shutil.copy2(str(host_config), str(codex_home / "config.toml"))

        logger.info(f"[image_backends] Using Codex CLI for {len(loaded_images)} image(s)")

        cmd = [
            "codex",
            "exec",
            "--full-auto",
            "--skip-git-repo-check",
            "--disable",
            "shell_tool",
            "-c",
            'web_search="disabled"',
            "-i",
            image_arg,
            prompt,
        ]

        env = {**os.environ, "NO_COLOR": "1", "CODEX_HOME": str(codex_home)}

        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            cwd=tmpdir,
            env=env,
            timeout=120,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Codex CLI failed (exit {result.returncode}): {result.stderr}")

    return result.stdout
