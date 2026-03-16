# MassGen v0.1.64 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.64 — Gemini CLI Backend! 🚀 MassGen now supports Google's Gemini CLI as a first-class backend with session persistence, MCP tools, and Docker support. Plus: WebSocket streaming for OpenAI Response API, execution trace analyzer subagent, and Copilot Docker mode.

## Install

```bash
pip install massgen==0.1.64
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.64
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.64 — Gemini CLI Backend! 🚀 MassGen now supports Google's Gemini CLI as a first-class backend with session persistence, MCP tools, and Docker support. Plus: WebSocket streaming for OpenAI Response API, execution trace analyzer subagent, and Copilot Docker mode.

**Key Improvement:**

🔌 **Gemini CLI Backend** - Google's Gemini CLI as a native MassGen backend:
- Subprocess-based integration with Gemini 2.5 and 3.x model families
- Session persistence via CLI session IDs for multi-turn conversations
- MCP tools wired through `.gemini/settings.json` configuration
- Docker support for containerized execution

**Plus:**
- ⚡ **WebSocket streaming** — persistent `wss://` transport for OpenAI Response API with auto-reconnection and real-time event streaming
- 🔍 **Execution trace analyzer** — new subagent type for mechanistic analysis of agent execution traces with 7-dimension evaluation framework
- 🐳 **Copilot Docker mode** — containerized tool execution for Copilot backend with sudo and network configuration
- 🔧 **Response API fix** — prevent duplicate item errors in recursive tool loops

**Getting Started:**

```bash
pip install massgen==0.1.64
# Try the Gemini CLI backend
uv run massgen --config @examples/providers/gemini/gemini_cli_local "Explain quantum computing"
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.64

Feature highlights:

<!-- Paste feature-highlights.md content here -->
