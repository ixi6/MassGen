# MassGen v0.1.54 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.54, adding Subagent Messaging & Copilot SDK Backend! 🚀 Send messages to running agents mid-execution to steer their work in real time — target specific agents or broadcast to all, with queued message management. Works for both main agents and subagents. Plus: new `copilot` backend powered by `github-copilot-sdk`, Gemini 3.1 Pro model support, and MCP hooks improvements.

## Install

```bash
pip install massgen==0.1.54
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.54
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.54, adding Subagent Messaging & Copilot SDK Backend! 🚀 Send messages to running agents mid-execution to steer their work in real time — target specific agents or broadcast to all, with queued message management. Works for both main agents and subagents. Plus: new `copilot` backend powered by `github-copilot-sdk`, Gemini 3.1 Pro model support, and MCP hooks improvements.

**Key Features:**

**Copilot SDK Backend** - New backend using `github-copilot-sdk`:
- Native MCP server integration and custom tool handling
- Session management with cache invalidation
- Auth via GitHub subscription

**Subagent Runtime Messaging** - Steer running subagents mid-execution:
- New `send_message_to_subagent` tool for runtime messaging to background subagents
- Supports per-agent targeting within subagent orchestrators

**Also in this release:**
- Gemini 3.1 Pro support: `gemini-3.1-pro-preview` model added to capabilities registry
- Per-agent injection targeting: Injections can target specific agents or broadcast to all
- MCP hooks improvements: Hook middleware for subagent MCP servers, `InjectionDeliveryStatus` enum
- Type annotation modernization: Codebase-wide migration to modern `dict/list/X | None` syntax

**Bug Fixes:**
- MCP hooks issue fix
- Subagent message sending fix
- fstmcp version fix

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.54

Feature highlights:

<!-- Paste feature-highlights.md content here -->
