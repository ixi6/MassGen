"""
LiteLLM Custom Provider for MassGen

This module provides integration with LiteLLM, allowing MassGen to be used
as a custom LLM provider within the LiteLLM ecosystem.

Usage:
    import litellm
    from massgen import register_with_litellm

    # Register MassGen as a provider
    register_with_litellm()

    # Use with example config
    response = litellm.completion(
        model="massgen/basic_multi",
        messages=[{"role": "user", "content": "Your question"}]
    )

    # Quick single-agent mode
    response = litellm.completion(
        model="massgen/model:gpt-4o-mini",
        messages=[{"role": "user", "content": "What is 2+2?"}]
    )

    # Build config on-the-fly with multiple models (slash format)
    response = litellm.completion(
        model="massgen/build",
        messages=[{"role": "user", "content": "Compare approaches"}],
        optional_params={
            "models": ["openai/gpt-5", "anthropic/claude-sonnet-4.5", "groq/llama-3.3-70b"],
        }
    )

    # Auto-detect backends from model names
    response = litellm.completion(
        model="massgen/build",
        messages=[{"role": "user", "content": "Your question"}],
        optional_params={
            "models": ["gpt-5", "claude-sonnet-4-5"],  # backends auto-detected
        }
    )

    # Same model for multiple agents
    response = litellm.completion(
        model="massgen/build",
        messages=[{"role": "user", "content": "Your question"}],
        optional_params={
            "model": "gpt-5",
            "num_agents": 3,
        }
    )

    # With explicit config path
    response = litellm.completion(
        model="massgen/path:/path/to/config.yaml",
        messages=[{"role": "user", "content": "Your question"}]
    )
"""

import time
from typing import Any

# Type hints for litellm - actual import happens at runtime
try:
    from litellm import CustomLLM
    from litellm.types.utils import Choices, Message, ModelResponse, Usage

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    CustomLLM = object  # Fallback for type hints
    ModelResponse = dict
    Choices = None
    Message = None
    Usage = None


class MassGenLLM(CustomLLM if LITELLM_AVAILABLE else object):
    """LiteLLM custom provider for MassGen multi-agent system.

    Model string format:
        - "massgen/<example-name>" - Use built-in example config (e.g., "massgen/basic_multi")
        - "massgen/model:<model-name>" - Quick single-agent mode (e.g., "massgen/model:gpt-4o")
        - "massgen/path:<config-path>" - Explicit config file path

    Examples:
        >>> # With built-in example
        >>> response = litellm.completion(
        ...     model="massgen/basic_multi",
        ...     messages=[{"role": "user", "content": "Compare AI approaches"}]
        ... )

        >>> # Quick single-agent
        >>> response = litellm.completion(
        ...     model="massgen/model:gpt-4o-mini",
        ...     messages=[{"role": "user", "content": "What is 2+2?"}]
        ... )
    """

    def __init__(self):
        """Initialize MassGen LiteLLM provider."""
        if not LITELLM_AVAILABLE:
            raise ImportError(
                "litellm is required for MassGenLLM. " "Install it with: pip install litellm",
            )
        super().__init__()

    def completion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        api_base: str | None = None,
        custom_llm_provider: str | None = None,
        model_response: Any | None = None,
        print_verbose: callable | None = None,
        encoding: Any | None = None,
        api_key: str | None = None,
        logging_obj: Any | None = None,
        optional_params: dict[str, Any] | None = None,
        acompletion: bool = False,
        litellm_params: dict[str, Any] | None = None,
        logger_fn: callable | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        client: Any | None = None,
        **kwargs,
    ) -> ModelResponse:
        """Synchronous completion using MassGen.

        Args:
            model: Model string in format "massgen/<spec>"
            messages: List of message dicts with 'role' and 'content'
            optional_params: Optional dict with MassGen-specific params:
                - models: List of model names for multi-agent (e.g., ["gpt-4o", "claude-sonnet-4-20250514"])
                - model: Single model name for all agents
                - num_agents: Number of agents when using single model
                - use_docker: Enable Docker execution mode
                - enable_filesystem: Enable filesystem/MCP tools (default: True)
                - context_paths: List of paths with permissions. Each entry can be:
                    - str: Path with default "write" permission
                    - dict: {"path": "/path", "permission": "read" or "write"}
                - enable_logging: Enable logging
                - output_file: Write final answer to file
            **kwargs: Additional arguments (passed to MassGen)

        Returns:
            ModelResponse: LiteLLM-compatible response object
        """
        # Parse model string to get config
        config, model_name, is_build_mode = self._parse_model(model)

        # Extract query from messages (last user message)
        query = self._extract_query(messages)

        # Extract optional params
        # LiteLLM may nest params as {'optional_params': {...actual params...}}
        opts = optional_params or {}
        if "optional_params" in opts and isinstance(opts["optional_params"], dict):
            opts = opts["optional_params"]
        enable_logging = opts.get("enable_logging", False)
        output_file = opts.get("output_file")
        verbose = opts.get("verbose", False)  # Default to quiet mode for LiteLLM

        # Extract conversation history (for multi-turn support)
        conversation_history = self._extract_conversation_history(messages)

        # Build run() kwargs
        run_kwargs = {
            "query": query,
            "enable_logging": enable_logging,
            "output_file": output_file,
            "verbose": verbose,
        }

        # Pass conversation history if available
        if conversation_history:
            run_kwargs["conversation_history"] = conversation_history

        if is_build_mode:
            # Dynamic config building from optional_params
            # Support: models (list), model (single), num_agents, use_docker, context_path
            # Also: backend (single), backends (list) for explicit backend specification
            if "models" in opts:
                run_kwargs["models"] = opts["models"]
                if "backends" in opts:
                    run_kwargs["backends"] = opts["backends"]
            elif "model" in opts:
                run_kwargs["model"] = opts["model"]
                if "backend" in opts:
                    run_kwargs["backend"] = opts["backend"]
                if "num_agents" in opts:
                    run_kwargs["num_agents"] = opts["num_agents"]

            if "use_docker" in opts:
                run_kwargs["use_docker"] = opts["use_docker"]
            if "enable_filesystem" in opts:
                run_kwargs["enable_filesystem"] = opts["enable_filesystem"]
            if "context_paths" in opts:
                run_kwargs["context_paths"] = opts["context_paths"]
        else:
            # Standard mode: use parsed config/model
            if config:
                run_kwargs["config"] = config
            if model_name:
                run_kwargs["model"] = model_name

        # Run MassGen synchronously (lazy import to avoid circular import)
        from massgen import run
        from massgen.utils import run_async_safely

        result = run_async_safely(run(**run_kwargs))

        # Build LiteLLM-compatible response
        return self._build_response(model, result)

    async def acompletion(
        self,
        model: str,
        messages: list[dict[str, Any]],
        api_base: str | None = None,
        custom_llm_provider: str | None = None,
        model_response: Any | None = None,
        print_verbose: callable | None = None,
        encoding: Any | None = None,
        api_key: str | None = None,
        logging_obj: Any | None = None,
        optional_params: dict[str, Any] | None = None,
        litellm_params: dict[str, Any] | None = None,
        logger_fn: callable | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        client: Any | None = None,
        **kwargs,
    ) -> ModelResponse:
        """Async completion using MassGen.

        Args:
            model: Model string in format "massgen/<spec>"
            messages: List of message dicts with 'role' and 'content'
            optional_params: Optional dict with MassGen-specific params:
                - models: List of model names for multi-agent (e.g., ["gpt-4o", "claude-sonnet-4-20250514"])
                - model: Single model name for all agents
                - num_agents: Number of agents when using single model
                - use_docker: Enable Docker execution mode
                - enable_filesystem: Enable filesystem/MCP tools (default: True)
                - context_paths: List of paths with permissions. Each entry can be:
                    - str: Path with default "write" permission
                    - dict: {"path": "/path", "permission": "read" or "write"}
                - enable_logging: Enable logging
                - output_file: Write final answer to file
            **kwargs: Additional arguments (passed to MassGen)

        Returns:
            ModelResponse: LiteLLM-compatible response object
        """
        # Parse model string to get config
        config, model_name, is_build_mode = self._parse_model(model)

        # Extract query from messages (last user message)
        query = self._extract_query(messages)

        # Extract optional params
        # LiteLLM may nest params as {'optional_params': {...actual params...}}
        opts = optional_params or {}
        if "optional_params" in opts and isinstance(opts["optional_params"], dict):
            opts = opts["optional_params"]
        enable_logging = opts.get("enable_logging", False)
        output_file = opts.get("output_file")
        verbose = opts.get("verbose", False)  # Default to quiet mode for LiteLLM

        # Extract conversation history (for multi-turn support)
        conversation_history = self._extract_conversation_history(messages)

        # Build run() kwargs
        run_kwargs = {
            "query": query,
            "enable_logging": enable_logging,
            "output_file": output_file,
            "verbose": verbose,
        }

        # Pass conversation history if available
        if conversation_history:
            run_kwargs["conversation_history"] = conversation_history

        if is_build_mode:
            # Dynamic config building from optional_params
            # Support: models (list), model (single), num_agents, use_docker, context_path
            # Also: backend (single), backends (list) for explicit backend specification
            if "models" in opts:
                run_kwargs["models"] = opts["models"]
                if "backends" in opts:
                    run_kwargs["backends"] = opts["backends"]
            elif "model" in opts:
                run_kwargs["model"] = opts["model"]
                if "backend" in opts:
                    run_kwargs["backend"] = opts["backend"]
                if "num_agents" in opts:
                    run_kwargs["num_agents"] = opts["num_agents"]

            if "use_docker" in opts:
                run_kwargs["use_docker"] = opts["use_docker"]
            if "enable_filesystem" in opts:
                run_kwargs["enable_filesystem"] = opts["enable_filesystem"]
            if "context_paths" in opts:
                run_kwargs["context_paths"] = opts["context_paths"]
        else:
            # Standard mode: use parsed config/model
            if config:
                run_kwargs["config"] = config
            if model_name:
                run_kwargs["model"] = model_name

        # Run MassGen asynchronously (lazy import to avoid circular import)
        from massgen import run

        result = await run(**run_kwargs)

        # Build LiteLLM-compatible response
        return self._build_response(model, result)

    def _parse_model(self, model: str) -> tuple:
        """Parse model string like 'massgen/basic_multi' or 'massgen/model:gpt-4o'.

        Args:
            model: Full model string including 'massgen/' prefix

        Returns:
            tuple: (config_path, model_name, is_build_mode)
                - config_path: Path to config file or example name
                - model_name: Model name for single-agent mode
                - is_build_mode: True if using massgen/build for dynamic config
        """
        # Remove 'massgen/' prefix
        spec = model.replace("massgen/", "", 1)

        if spec == "build":
            # Dynamic config building mode: massgen/build
            # Config will be built from optional_params
            return None, None, True
        elif spec.startswith("model:"):
            # Quick single-agent mode: massgen/model:gpt-4o
            return None, spec.replace("model:", "", 1), False
        elif spec.startswith("path:"):
            # Explicit config path: massgen/path:/path/to/config.yaml
            return spec.replace("path:", "", 1), None, False
        else:
            # Assume it's an example config name: massgen/basic_multi
            return f"@examples/{spec}", None, False

    def _extract_query(self, messages: list[dict[str, Any]]) -> str:
        """Extract query from messages list (last user message).

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            str: The last user message content
        """
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                # Handle both string and list content (multimodal)
                if isinstance(content, list):
                    # Extract text from multimodal content
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            return part.get("text", "")
                    return ""
                return content
        return ""

    def _extract_conversation_history(self, messages: list[dict[str, Any]]) -> list[dict[str, str]] | None:
        """Extract conversation history from messages (excluding last user message).

        If there are prior messages in the conversation, return them as history
        that can be preloaded into the MassGen session.

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            List of prior messages if conversation has history, None otherwise
        """
        if len(messages) <= 1:
            return None

        history = []
        # Process all messages except the last one (which is the current query)
        for msg in messages[:-1]:
            role = msg.get("role", "")
            content = msg.get("content", "")

            # Handle multimodal content
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                content = " ".join(text_parts)

            if role in ("user", "assistant") and content:
                history.append({"role": role, "content": content})

        return history if history else None

    def _build_response(self, model: str, result: dict[str, Any]) -> ModelResponse:
        """Build LiteLLM-compatible ModelResponse.

        Args:
            model: The model string used
            result: MassGen result dict

        Returns:
            ModelResponse: LiteLLM-compatible response
        """
        # Create the response
        response = ModelResponse(
            id=f"massgen-{result.get('session_id', 'unknown')}",
            choices=[
                Choices(
                    finish_reason="stop",
                    index=0,
                    message=Message(
                        content=result.get("final_answer", ""),
                        role="assistant",
                    ),
                ),
            ],
            created=int(time.time()),
            model=model,
            usage=Usage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
            ),
        )

        # Add MassGen-specific metadata to response
        response._hidden_params = {
            # Basic metadata
            "massgen_config_used": result.get("config_used"),
            "massgen_session_id": result.get("session_id"),
            # Log directory pointers
            "massgen_log_directory": result.get("log_directory"),
            "massgen_final_answer_path": result.get("final_answer_path"),
            # Coordination metadata (multi-agent only, uses anonymous agent_a, agent_b names)
            "massgen_selected_agent": result.get("selected_agent"),
            "massgen_vote_results": result.get("vote_results"),
            # Answers with labels (answerX.Y format), paths, and content
            "massgen_answers": result.get("answers"),
            # Mapping from anonymous names to real agent IDs
            "massgen_agent_mapping": result.get("agent_mapping"),
        }

        return response


def register_with_litellm() -> None:
    """Register MassGen as a LiteLLM custom provider.

    After calling this function, you can use MassGen via litellm.completion():

        import litellm
        from massgen import register_with_litellm

        register_with_litellm()

        response = litellm.completion(
            model="massgen/basic_multi",
            messages=[{"role": "user", "content": "Your question"}]
        )

    Model formats:
        - "massgen/<example>" - Built-in example (e.g., "massgen/basic_multi")
        - "massgen/model:<name>" - Single agent (e.g., "massgen/model:gpt-4o")
        - "massgen/path:<path>" - Config file path

    Raises:
        ImportError: If litellm is not installed
    """
    if not LITELLM_AVAILABLE:
        raise ImportError(
            "litellm is required for register_with_litellm(). " "Install it with: pip install litellm",
        )

    import litellm

    # Create handler instance
    massgen_llm = MassGenLLM()

    # Initialize custom_provider_map if not exists
    if not hasattr(litellm, "custom_provider_map") or litellm.custom_provider_map is None:
        litellm.custom_provider_map = []

    # Check if already registered
    for provider in litellm.custom_provider_map:
        if provider.get("provider") == "massgen":
            return  # Already registered

    # Register the provider
    litellm.custom_provider_map.append(
        {
            "provider": "massgen",
            "custom_handler": massgen_llm,
        },
    )
