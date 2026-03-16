# 🚀 Release Highlights — v0.1.64 (2026-03-16)

### 🔌 [Gemini CLI Backend](https://docs.massgen.ai/en/latest/user_guide/backends.html)
- **Gemini CLI as a native backend**: Google's Gemini CLI with subprocess-based streaming
- **Session persistence**: Multi-turn conversations via CLI session IDs
- **MCP tools**: Wired through `.gemini/settings.json` with native hook adapter for tool execution
- **Docker support**: Containerized execution via `gemini_cli_docker.yaml` config

### ⚡ [WebSocket Streaming](https://docs.massgen.ai/en/latest/reference/yaml_schema.html#orchestrator-configuration)
- **Persistent WebSocket transport**: `wss://` connection to OpenAI Response API for real-time event streaming
- **Auto-reconnection**: Configurable retry logic with exponential backoff
- **YAML config**: Enable with `websocket_mode: true` on OpenAI backend

### 🔍 [Execution Trace Analyzer](https://github.com/massgen/MassGen/blob/main/massgen/subagent_types/execution_trace_analyzer/SUBAGENT.md)
- **New subagent type**: Mechanistic analysis of agent execution traces to extract durable learnings
- **7-dimension evaluation**: Error learning, effort allocation, approach effectiveness, tool strategy, reasoning patterns, context health, verification completeness
- **Output**: `process_report.md` (narrative) and `process_verdict.json` (structured scores)

### 🐳 Copilot Docker Mode
- **Containerized tool execution**: `command_line_execution_mode: "docker"` for Copilot backend
- **Configuration**: Docker sudo support, network mode selection (bridge/host)

### ✅ Fixes
- **Response API duplicates**: Prevent duplicate item errors in recursive tool loops ([#1000](https://github.com/massgen/MassGen/pull/1000))

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  pip install massgen==0.1.64
  # Try the Gemini CLI backend
  uv run massgen --config @examples/providers/gemini/gemini_cli_local "Explain quantum computing"
  ```
