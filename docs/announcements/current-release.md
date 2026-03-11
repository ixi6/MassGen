# MassGen v0.1.62 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.62 — MassGen Skill & Viewer! 🚀 New general-purpose MassGen Skill (https://github.com/massgen/skills) with 4 modes (general, evaluate, plan, spec) for use from Claude Code and other AI agents. Session viewer for real-time observation of automation runs. Backend improvements and quickstart enhancements.

## Install

```bash
pip install massgen==0.1.62
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.62
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.62 — MassGen Skill & Viewer! 🚀 New general-purpose MassGen Skill (https://github.com/massgen/skills) with 4 modes (general, evaluate, plan, spec) for use from Claude Code and other AI agents. Session viewer for real-time observation of automation runs. Backend improvements and quickstart enhancements.

**Key Improvements:**

🧩 **MassGen Skill** - General-purpose multi-agent skill for AI coding agents:
- 4 modes: general (any task), evaluate (critique existing work), plan (create project plans), spec (create requirements)
- Usable from Claude Code, Codex, and other AI agents
- Auto-installation and auto-sync to a separate skills repository
- Comprehensive reference documentation for each mode

👁️ **Session Viewer** - Real-time observation of automation sessions:
- New `massgen viewer` command for watching sessions in the TUI
- Pick specific sessions interactively with `--pick` flag
- Web viewing mode with `--web` flag

⚡ **Backend & Quickstart Improvements** - Smoother setup and broader compatibility:
- Claude Code backend improvements with background task execution support
- Codex backend enhancements with native filesystem access and MCP support
- Copilot model discovery with runtime model fetching
- Headless quickstart (`--quickstart --headless`) for CI/CD integration
- Web quickstart (`--web-quickstart`) for browser-based setup

**Getting Started:**

```bash
# Install the MassGen Skill for your AI agent
npx skills add massgen/skills --all
# Then in Claude Code, Cursor, Copilot, etc.:
#   /massgen "Your complex task"

# Or install MassGen directly
pip install massgen==0.1.62
# Try the Session Viewer
uv run massgen viewer --pick
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.62

Feature highlights:

<!-- Paste feature-highlights.md content here -->
