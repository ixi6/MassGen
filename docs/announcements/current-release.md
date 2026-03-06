# MassGen v0.1.60 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.60 — Verification & Decomposition Improvements! 🚀 Decomp mode now cooperates with the checklist workflow, enabling quality-gated subtask iteration with improved verification round time. Plus: GPT-5.4 support, rewritten read_media tool with clearer schema, media call ledger tracking, checklist and prompt injection fixes, and Codex prompt caching for pricing accuracy.

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

We're excited to release MassGen v0.1.60 — Verification & Decomposition Improvements! 🚀 Decomp mode now cooperates with the checklist workflow, enabling quality-gated subtask iteration with improved verification round time. Plus: GPT-5.4 support, rewritten read_media tool with clearer schema, media call ledger tracking, checklist and prompt injection fixes, and Codex prompt caching for pricing accuracy.

**Key Improvements:**

🔄 **Verification & Decomposition** - Unified quality workflow:
- Decomp mode now cooperates with the checklist workflow, enabling quality-gated subtask iteration
- Improved verification round time with better verification_latest prompts

🧠 **GPT-5.4 Support** - New OpenAI flagship model:
- Added GPT-5.4 to the model registry for immediate use across all coordination modes

🛠️ **Multimodal Tool Improvements** - Clearer, more reliable media tools:
- Rewritten read_media tool with clearer schema and better error handling
- Media call ledger tracking for read/generate media calls

✅ **Checklist & Prompt Fixes** - More accurate quality gating:
- Proposal injection improvements for more reliable checklist behavior
- System prompt refocused on evaluating entire output quality

🔧 **Infrastructure** - Under-the-hood improvements:
- Codex prompt caching for accurate pricing tracking
- Hook framework for tool call interception (internal)
- Skill prefix handling fixes

**Getting Started:**

```bash
pip install massgen==0.1.60
massgen --automation --config massgen/configs/basic/basic.yaml "Your task here"
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.60

Feature highlights:

<!-- Paste feature-highlights.md content here -->
