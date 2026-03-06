# MassGen v0.1.60 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.60 — Multimodal Tools, Subagent Enhancements & GPT-5.4! 🚀 Rewritten `read_media` tool with clearer schema and new `MediaCallLedgerHook` for tracking media calls. Subagents gain `inherit_spawning_agent_backend` and `final_answer_strategy` options. GPT-5.4 added as the default OpenAI flagship. Plus: decomp mode cooperates with checklist workflow, Codex prompt caching calculation fix for pricing accuracy, and checklist/prompt injection fixes.

## Install

```bash
pip install massgen==0.1.60
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.60
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.60 — Multimodal Tools, Subagent Enhancements & GPT-5.4! 🚀 Rewritten `read_media` tool with clearer schema and new `MediaCallLedgerHook` for tracking media calls. Subagents gain `inherit_spawning_agent_backend` and `final_answer_strategy` options. GPT-5.4 added as the default OpenAI flagship. Plus: decomp mode cooperates with checklist workflow, Codex prompt caching calculation fix for pricing accuracy, and checklist/prompt injection fixes.

**Key Improvements:**

🛠️ **Multimodal Tool Improvements** - Clearer, more reliable media tools:
- Rewritten `read_media` tool with clearer schema and better error handling
- New `MediaCallLedgerHook` for tracking read/generate media calls via the hook framework

🤖 **Subagent Enhancements** - More flexible subagent configuration:
- `inherit_spawning_agent_backend` — subagents automatically inherit the spawning agent's backend
- `final_answer_strategy` — configurable child orchestrator final-answer policy (winner_reuse, winner_present, synthesize)
- Per-agent `subagent_agents` override and robust orchestrator config file support

🧠 **GPT-5.4 Support** - New default OpenAI flagship model:
- GPT-5.4 added to the model registry for immediate use across all coordination modes

🔄 **Decomposition + Checklist Cooperation** - Unified quality workflow:
- Decomp mode now cooperates with the checklist workflow for quality-gated subtask iteration
- Improved verification round time with better verification_latest prompts

✅ **Fixes** - Quality and accuracy improvements:
- Checklist & proposal injection improvements for more reliable behavior
- System prompt refocused on evaluating entire output quality
- Codex prompt caching calculation fix for pricing accuracy
- Task plan refresh fix and skill prefix handling fixes

**Getting Started:**

```bash
pip install massgen==0.1.60
massgen --automation --config massgen/configs/basic/basic.yaml "Your task here"
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.60

Feature highlights:

<!-- Paste feature-highlights.md content here -->
