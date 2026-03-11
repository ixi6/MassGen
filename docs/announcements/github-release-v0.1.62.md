# 🚀 Release Highlights — v0.1.62 (2026-03-11)

### 🧩 [MassGen Skill](https://github.com/massgen/skills)
- **Multi-agent collaboration as a skill**: Install with `npx skills add massgen/skills --all` and use MassGen directly from Claude Code, Cursor, Copilot, and 40+ other AI agents
- **Four modes**: General (any task), Evaluate (critique existing work), Plan (structured project plans), Spec (requirements specifications)
- **Auto-distributed**: Skill automatically syncs to a [dedicated repository](https://github.com/massgen/skills) for easy installation

### 👁️ [Session Viewer](https://docs.massgen.ai/en/latest/reference/cli.html)
- **Watch automation runs in real-time**: New `massgen viewer` command opens a TUI to observe running or completed sessions
- **Session picker**: `--pick` flag for browsing and selecting specific sessions, `--web` for browser-based viewing

### ⚡ [Backend & Quickstart Improvements](https://docs.massgen.ai/en/latest/user_guide/backends.html)
- **Claude Code backend**: Background task execution and native MCP support via the SDK
- **Codex backend**: Native filesystem access and MCP tool integration
- **Copilot backend**: Runtime model discovery with automatic capability detection
- **Headless quickstart**: Non-interactive setup via `--quickstart --headless` for CI/CD pipelines
- **Web quickstart**: Browser-based setup via `--web-quickstart`

### ✅ Fixes
- **Evaluation criteria**: Removed should/could criteria that caused agents to produce overly similar outputs
- **Planning prompts**: Improved planning prompts with configurable thoroughness levels

---

### 📖 Getting Started
- [**Quick Start Guide**](https://github.com/massgen/MassGen?tab=readme-ov-file#1--installation)
- **Try It**:
  ```bash
  # Install the MassGen Skill for your AI agent
  npx skills add massgen/skills --all
  # Then use MassGen from Claude Code, Cursor, Copilot, etc.

  # Or install MassGen directly and try the Session Viewer
  pip install massgen==0.1.62
  uv run massgen viewer --pick
  ```
