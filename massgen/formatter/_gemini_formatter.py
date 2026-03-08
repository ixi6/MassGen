"""
Gemini formatter for message formatting, coordination prompts, and structured output parsing.
"""

import json
import logging
import re
from typing import Any

from ._formatter_base import FormatterBase

logger = logging.getLogger(__name__)


class GeminiFormatter(FormatterBase):
    def format_messages(self, messages: list[dict[str, Any]]) -> str:
        """
        Build conversation content string from message history.

        Behavior mirrors the formatting used previously in the Gemini backend:
        - System messages buffered separately then prepended.
        - User => "User: {content}"
        - Assistant => "Assistant: {content}"
        - Tool => "Tool Result: {content}"
        """
        conversation_content = ""
        system_message = ""

        for msg in messages:
            role = msg.get("role")
            if role == "system":
                system_message = msg.get("content", "")
            elif role == "user":
                conversation_content += f"User: {msg.get('content', '')}\n"
            elif role == "assistant":
                conversation_content += f"Assistant: {msg.get('content', '')}\n"
            elif role == "tool":
                tool_output = msg.get("content", "")
                conversation_content += f"Tool Result: {tool_output}\n"

        # Combine system message and conversation
        full_content = ""
        if system_message:
            full_content += f"{system_message}\n\n"
        full_content += conversation_content
        return full_content

    def format_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Gemini uses SDK-native tool format, not reformatting.
        """
        return tools or []

    def format_mcp_tools(
        self,
        mcp_functions: dict[str, Any],
        return_sdk_objects: bool = True,
    ) -> list[Any]:
        """
        Convert MCP Function objects to Gemini FunctionDeclaration format.

        """
        if not mcp_functions:
            return []

        # Step 1: Convert MCP Function objects to Gemini dictionary format
        gemini_dicts = []

        for mcp_function in mcp_functions.values():
            try:
                # Extract attributes from Function object
                name = getattr(mcp_function, "name", "")
                description = getattr(mcp_function, "description", "")
                parameters = getattr(mcp_function, "parameters", {})

                # Build Gemini-compatible dictionary
                gemini_dict = {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                }
                gemini_dicts.append(gemini_dict)

                logger.debug(f"[GeminiFormatter] Converted MCP tool '{name}' to dictionary format")

            except Exception as e:
                logger.error(f"[GeminiFormatter] Failed to convert MCP tool: {e}")
                # Continue processing remaining tools instead of failing completely
                continue

        if not return_sdk_objects:
            return gemini_dicts

        # Step 2: Convert dictionaries to SDK FunctionDeclaration objects
        function_declarations = self._convert_to_function_declarations(gemini_dicts)

        # Log successful conversion
        for func_decl in function_declarations:
            if hasattr(func_decl, "name"):
                logger.debug(
                    f"[GeminiFormatter] Converted MCP tool '{func_decl.name}' to FunctionDeclaration",
                )

        return function_declarations

    # Coordination helpers

    def has_coordination_tools(self, tools: list[dict[str, Any]]) -> bool:
        """Detect if tools contain vote/stop/new_answer coordination tools.

        Returns True if:
        - Both vote AND new_answer are present (normal coordination mode)
        - Only vote is present (vote-only mode - agent reached answer limit)
        - stop is present (decomposition mode)
        """
        if not tools:
            return False

        tool_names = set()
        for tool in tools:
            if tool.get("type") == "function":
                if "function" in tool:
                    tool_names.add(tool["function"].get("name", ""))
                elif "name" in tool:
                    tool_names.add(tool.get("name", ""))

        # Normal mode: both vote and new_answer present
        # Vote-only mode: only vote present (new_answer removed when agent reached limit)
        # Decomposition mode: stop replaces vote
        return "vote" in tool_names or "stop" in tool_names

    def has_post_evaluation_tools(self, tools: list[dict[str, Any]]) -> bool:
        """Detect if tools contain submit/restart_orchestration post-evaluation tools."""
        if not tools:
            return False

        tool_names = set()
        for tool in tools:
            if tool.get("type") == "function":
                if "function" in tool:
                    tool_names.add(tool["function"].get("name", ""))
                elif "name" in tool:
                    tool_names.add(tool.get("name", ""))

        return "submit" in tool_names and "restart_orchestration" in tool_names

    def build_structured_output_prompt(
        self,
        base_content: str,
        valid_agent_ids: list[str] | None = None,
        broadcast_enabled: bool = False,
        vote_only: bool = False,
        decomposition_mode: bool = False,
    ) -> str:
        """Build prompt that encourages structured output for coordination.

        Args:
            base_content: The base prompt content
            valid_agent_ids: List of valid agent IDs for voting
            broadcast_enabled: Whether ask_others is available
            vote_only: If True, only include vote option (agent reached answer limit)
            decomposition_mode: If True, use stop instead of vote
        """
        agent_list = ""
        if valid_agent_ids:
            agent_list = f"Valid agents: {', '.join(valid_agent_ids)}"

        # In vote-only mode, only show vote option
        if vote_only:
            return f"""{base_content}

You must respond with a structured JSON decision at the end of your response.

You must VOTE for the best existing agent's answer:
{{
  "action_type": "vote",
  "vote_data": {{
    "action": "vote",
    "agent_id": "agent1",  // Choose from: {agent_list or "agent1, agent2, agent3, etc."}
    "reason": "Brief reason for your vote"
  }}
}}

Make your decision about which agent to vote for and include the vote JSON at the very end of your response."""

        # In decomposition mode, use stop instead of vote
        if decomposition_mode:
            return f"""{base_content}

IMPORTANT: You must respond with a structured JSON decision at the end of your response.

If you want to signal your subtask is COMPLETE (or blocked):
{{
  "action_type": "stop",
  "stop_data": {{
    "action": "stop",
    "summary": "What you accomplished and how it connects to other agents' work",
    "status": "complete"
  }}
}}

If you want to provide a NEW or IMPROVED ANSWER for your subtask:
{{
  "action_type": "new_answer",
  "answer_data": {{
    "action": "new_answer",
    "content": "Your complete improved answer here"
  }}
}}

Make your decision and include the JSON at the very end of your response."""

        # Build ask_others section conditionally
        ask_others_section = ""
        if broadcast_enabled:
            ask_others_section = """

If you want to ASK OTHER AGENTS a question (for collaborative problem-solving):
PREFERRED - Use structured questions with options (limit to 5-7 questions max, 2-5 options each):
{
  "action_type": "ask_others",
  "ask_others_data": {
    "action": "ask_others",
    "questions": [
      {
        "text": "Which framework should we use?",
        "options": [
          {"id": "react", "label": "React", "description": "Component-based UI"},
          {"id": "vue", "label": "Vue", "description": "Progressive framework"}
        ],
        "multiSelect": false,
        "allowOther": true
      }
    ],
    "wait": true
  }
}

FALLBACK - Simple text question (only when options don't make sense):
{
  "action_type": "ask_others",
  "ask_others_data": {
    "action": "ask_others",
    "question": "Your open-ended question with ALL relevant context",
    "wait": true
  }
}"""

        return f"""{base_content}

IMPORTANT: You must respond with a structured JSON decision at the end of your response.

If you want to VOTE for an existing agent's answer:
{{
  "action_type": "vote",
  "vote_data": {{
    "action": "vote",
    "agent_id": "agent1",  // Choose from: {agent_list or "agent1, agent2, agent3, etc."}
    "reason": "Brief reason for your vote"
  }}
}}

If you want to provide a NEW ANSWER:
{{
  "action_type": "new_answer",
  "answer_data": {{
    "action": "new_answer",
    "content": "Your complete improved answer here"
  }}
}}{ask_others_section}

Make your decision and include the JSON at the very end of your response."""

    def build_post_evaluation_prompt(self, base_content: str) -> str:
        """Build prompt that encourages structured output for post-evaluation."""
        return f"""{base_content}

IMPORTANT: You must respond with a structured JSON decision at the end of your response.

If you want to SUBMIT the answer (it's complete and satisfactory):
{{
  "action_type": "submit",
  "submit_data": {{
    "action": "submit",
    "confirmed": true
  }}
}}

If you want to RESTART with improvements:
{{
  "action_type": "restart",
  "restart_data": {{
    "action": "restart",
    "reason": "Clear explanation of why the answer is insufficient",
    "instructions": "Detailed, actionable guidance for the next attempt"
  }}
}}

Make your decision and include the JSON at the very end of your response."""

    def extract_structured_response(self, response_text: str) -> dict[str, Any] | None:
        """Extract structured JSON response from model output."""
        try:
            # Strategy 0: Look for JSON inside markdown code blocks first
            markdown_json_pattern = r"```json\s*(\{.*?\})\s*```"
            markdown_matches = re.findall(markdown_json_pattern, response_text, re.DOTALL)

            for match in reversed(markdown_matches):
                try:
                    parsed = json.loads(match.strip())
                    if isinstance(parsed, dict) and "action_type" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    continue

            # Strategy 1: Look for complete JSON blocks with proper braces
            json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
            json_matches = re.findall(json_pattern, response_text, re.DOTALL)

            # Try parsing each match (in reverse order - last one first)
            for match in reversed(json_matches):
                try:
                    cleaned_match = match.strip()
                    parsed = json.loads(cleaned_match)
                    if isinstance(parsed, dict) and "action_type" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    continue

            # Strategy 2: Look for JSON blocks with nested braces (more complex)
            brace_count = 0
            json_start = -1

            for i, char in enumerate(response_text):
                if char == "{":
                    if brace_count == 0:
                        json_start = i
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0 and json_start >= 0:
                        # Found a complete JSON block
                        json_block = response_text[json_start : i + 1]
                        try:
                            parsed = json.loads(json_block)
                            if isinstance(parsed, dict) and "action_type" in parsed:
                                return parsed
                        except json.JSONDecodeError:
                            pass
                        json_start = -1

            # Strategy 3: Line-by-line approach (fallback)
            lines = response_text.strip().split("\n")
            json_candidates = []

            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("{") and stripped.endswith("}"):
                    json_candidates.append(stripped)
                elif stripped.startswith("{"):
                    # Multi-line JSON - collect until closing brace
                    json_text = stripped
                    for j in range(i + 1, len(lines)):
                        json_text += "\n" + lines[j].strip()
                        if lines[j].strip().endswith("}"):
                            json_candidates.append(json_text)
                            break

            # Try to parse each candidate
            for candidate in reversed(json_candidates):
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and "action_type" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    continue

            return None

        except Exception:
            return None

    def convert_structured_to_tool_calls(self, structured_response: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert structured response to tool call format."""
        action_type = structured_response.get("action_type")

        # Coordination tools
        if action_type == "vote":
            vote_data = structured_response.get("vote_data", {})
            return [
                {
                    "call_id": f"vote_{abs(hash(str(vote_data))) % 10000 + 1}",
                    "name": "vote",
                    "arguments": json.dumps(
                        {
                            "agent_id": vote_data.get("agent_id", ""),
                            "reason": vote_data.get("reason", ""),
                        },
                    ),
                },
            ]

        elif action_type == "stop":
            stop_data = structured_response.get("stop_data", {})
            return [
                {
                    "call_id": f"stop_{abs(hash(str(stop_data))) % 10000 + 1}",
                    "name": "stop",
                    "arguments": json.dumps(
                        {
                            "summary": stop_data.get("summary", ""),
                            "status": stop_data.get("status", "complete"),
                        },
                    ),
                },
            ]

        elif action_type == "new_answer":
            answer_data = structured_response.get("answer_data", {})
            return [
                {
                    "call_id": f"new_answer_{abs(hash(str(answer_data))) % 10000 + 1}",
                    "name": "new_answer",
                    "arguments": json.dumps(
                        {
                            "content": answer_data.get("content", ""),
                        },
                    ),
                },
            ]

        elif action_type == "ask_others":
            ask_others_data = structured_response.get("ask_others_data", {})
            # Build arguments - prefer 'questions' (structured) over 'question' (simple)
            args = {"wait": ask_others_data.get("wait", True)}
            if "questions" in ask_others_data and ask_others_data["questions"]:
                args["questions"] = ask_others_data["questions"]
            else:
                args["question"] = ask_others_data.get("question", "")
            return [
                {
                    "call_id": f"ask_others_{abs(hash(str(ask_others_data))) % 10000 + 1}",
                    "name": "ask_others",
                    "arguments": json.dumps(args),
                },
            ]

        # Post-evaluation tools
        elif action_type == "submit":
            submit_data = structured_response.get("submit_data", {})
            return [
                {
                    "id": f"submit_{abs(hash(str(submit_data))) % 10000 + 1}",
                    "type": "function",
                    "function": {
                        "name": "submit",
                        "arguments": {"confirmed": submit_data.get("confirmed", True)},
                    },
                },
            ]

        elif action_type == "restart":
            restart_data = structured_response.get("restart_data", {})
            return [
                {
                    "id": f"restart_{abs(hash(str(restart_data))) % 10000 + 1}",
                    "type": "function",
                    "function": {
                        "name": "restart_orchestration",
                        "arguments": {
                            "reason": restart_data.get("reason", ""),
                            "instructions": restart_data.get("instructions", ""),
                        },
                    },
                },
            ]

        return []

    # Custom tools formatting for Gemini

    def format_custom_tools(
        self,
        custom_tools: list[dict[str, Any]],
        return_sdk_objects: bool = True,
    ) -> list[Any]:
        """
        Convert custom tools from OpenAI Chat Completions format to Gemini format.

        Can return either SDK FunctionDeclaration objects (default) or Gemini-format dictionaries.

        OpenAI format:
            [{"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}]

        Gemini dictionary format:
            [{"name": ..., "description": ..., "parameters": {...}}]

        Gemini SDK format:
            [FunctionDeclaration(name=..., description=..., parameters=Schema(...))]

        Args:
            custom_tools: List of tools in OpenAI Chat Completions format
            return_sdk_objects: If True, return FunctionDeclaration objects;
                               if False, return Gemini-format dictionaries

        Returns:
            List of tools in Gemini SDK format (default) or dictionary format
        """
        if not custom_tools:
            return []

        # Step 1: Convert to Gemini dictionary format
        gemini_dicts = self._convert_to_gemini_dict_format(custom_tools)

        if not return_sdk_objects:
            return gemini_dicts

        # Step 2: Convert dictionaries to SDK FunctionDeclaration objects
        return self._convert_to_function_declarations(gemini_dicts)

    def _convert_to_gemini_dict_format(self, custom_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Convert OpenAI format to Gemini dictionary format (intermediate step).

        Args:
            custom_tools: List of tools in OpenAI Chat Completions format

        Returns:
            List of tools in Gemini-compatible dictionary format
        """
        if not custom_tools:
            return []

        converted_tools = []

        for tool in custom_tools:
            # Handle OpenAI Chat Completions format with type="function" wrapper
            if isinstance(tool, dict) and tool.get("type") == "function" and "function" in tool:
                func_def = tool["function"]
                converted_tool = {
                    "name": func_def.get("name", ""),
                    "description": func_def.get("description", ""),
                    "parameters": func_def.get("parameters", {}),
                }
                converted_tools.append(converted_tool)
            # Handle already-converted Gemini format (idempotent)
            elif isinstance(tool, dict) and "name" in tool and "parameters" in tool:
                # Already in Gemini format, pass through
                converted_tools.append(tool)
            else:
                # Skip unrecognized formats
                logger.warning(f"[GeminiFormatter] Skipping unrecognized tool format: {tool}")

        return converted_tools

    def _convert_to_function_declarations(self, tools_dicts: list[dict[str, Any]]) -> list[Any]:
        """
        Convert Gemini-format tool dictionaries to FunctionDeclaration objects.

        Args:
            tools_dicts: List of tool dictionaries in Gemini format
                [{"name": ..., "description": ..., "parameters": {...}}]

        Returns:
            List of google.genai.types.FunctionDeclaration objects
        """
        if not tools_dicts:
            return []

        try:
            from google.genai import types
        except ImportError:
            logger.error("[GeminiFormatter] Cannot import google.genai.types for FunctionDeclaration")
            logger.error("[GeminiFormatter] Falling back to dictionary format")
            return tools_dicts  # Fallback to dict format

        function_declarations = []

        for tool_dict in tools_dicts:
            try:
                # Create Schema object for parameters
                params = tool_dict.get("parameters", {})

                # Convert parameters to Schema object (recursive)
                schema = self._build_schema_recursive(params)

                # Create FunctionDeclaration object
                func_decl = types.FunctionDeclaration(
                    name=tool_dict.get("name", ""),
                    description=tool_dict.get("description", ""),
                    parameters=schema,
                )

                function_declarations.append(func_decl)

                logger.debug(
                    f"[GeminiFormatter] Converted tool '{tool_dict.get('name')}' " f"to FunctionDeclaration",
                )

            except Exception as e:
                logger.error(
                    f"[GeminiFormatter] Failed to convert tool to FunctionDeclaration: {e}",
                )
                logger.error(f"[GeminiFormatter] Tool dict: {tool_dict}")
                # Continue processing other tools instead of failing completely
                continue

        return function_declarations

    def _build_schema_recursive(self, param_schema: dict[str, Any]) -> Any:
        """
        Recursively build a Gemini Schema object from JSON Schema format.

        Handles nested objects, arrays, and all standard JSON Schema types.

        Args:
            param_schema: JSON Schema dictionary (may be nested)

        Returns:
            google.genai.types.Schema object
        """
        try:
            from google.genai import types
        except ImportError:
            logger.error("[GeminiFormatter] Cannot import google.genai.types")
            return None

        # Get the type (default to "object" for top-level parameters)
        param_type = param_schema.get("type", "object")
        gemini_type = self._convert_json_type_to_gemini_type(param_type)

        # Build base schema kwargs
        schema_kwargs = {
            "type": gemini_type,
        }

        # Add description if present
        if "description" in param_schema:
            schema_kwargs["description"] = param_schema["description"]

        # Handle object type with nested properties
        if param_type == "object" and "properties" in param_schema:
            schema_kwargs["properties"] = {prop_name: self._build_schema_recursive(prop_schema) for prop_name, prop_schema in param_schema["properties"].items()}

            # Add required fields if present
            if "required" in param_schema:
                schema_kwargs["required"] = param_schema["required"]

        # Handle array type with items
        elif param_type == "array" and "items" in param_schema:
            schema_kwargs["items"] = self._build_schema_recursive(param_schema["items"])

        # Handle enum if present (for string/number types)
        if "enum" in param_schema:
            schema_kwargs["enum"] = param_schema["enum"]

        # Handle format if present (e.g., "date-time", "email", etc.)
        if "format" in param_schema:
            schema_kwargs["format"] = param_schema["format"]

        # Handle nullable if present
        if "nullable" in param_schema:
            schema_kwargs["nullable"] = param_schema["nullable"]

        return types.Schema(**schema_kwargs)

    def _convert_json_type_to_gemini_type(self, json_type: str) -> Any:
        """
        Convert JSON Schema type string to Gemini Type enum.

        Args:
            json_type: JSON Schema type like "string", "number", "integer", etc.

        Returns:
            Corresponding google.genai.types.Type enum value
        """
        try:
            from google.genai import types
        except ImportError:
            # If we can't import, return string as fallback
            # This shouldn't happen in practice since _build_schema_recursive checks first
            return "STRING"

        # Map JSON Schema types to Gemini Type enum
        type_mapping = {
            "string": types.Type.STRING,
            "number": types.Type.NUMBER,
            "integer": types.Type.INTEGER,
            "boolean": types.Type.BOOLEAN,
            "array": types.Type.ARRAY,
            "object": types.Type.OBJECT,
        }

        # Return mapped type or default to STRING
        gemini_type = type_mapping.get(json_type.lower(), types.Type.STRING)

        if json_type.lower() not in type_mapping:
            logger.warning(
                f"[GeminiFormatter] Unknown JSON type '{json_type}', defaulting to STRING",
            )

        return gemini_type
