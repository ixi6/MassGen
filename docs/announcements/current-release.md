# MassGen v0.1.61 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.61 — Round Evaluator Paradigm! 🚀 New specialized subagent type that automatically spawns evaluator subagents after each new answer to provide detailed feedback as input to the next round. Major orchestrator refactoring with improved evaluation prompts, task plan injection, and subagent fixes.

## Install

```bash
pip install massgen==0.1.61
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.61
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.61 — Round Evaluator Paradigm! 🚀 New specialized subagent type that automatically spawns evaluator subagents after each new answer to provide detailed feedback as input to the next round. Major orchestrator refactoring with improved evaluation prompts, task plan injection, and subagent fixes.

**Key Improvements:**

🔄 **Round Evaluator Paradigm** - Delegated evaluation for deeper quality assessment:
- New `round_evaluator` subagent type that delegates evaluation to specialized evaluator subagents
- Major orchestrator refactoring (+1,189 lines) to support the round evaluation workflow
- New `round_evaluator_example.yaml` config for easy adoption

📝 **Evaluation Improvements** - Better prompts and task plan integration:
- Improved evaluation prompts for clearer, more actionable feedback
- Task plan injection into evaluation workflow for context-aware assessment
- Simplified config handling for evaluation parameters

🔧 **Fixes** - Reliability and correctness improvements:
- Session resumption fix for already-resumed logs
- SUBAGENT.md generality improvements for broader subagent compatibility
- Round evaluation prompt clarity enhancements

**Getting Started:**

```bash
pip install massgen==0.1.61
# Try the round evaluator paradigm
uv run massgen --config @examples/features/round_evaluator_example.yaml "Create a website for an AI startup with polished visuals and interactive elements"
```

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.61

Feature highlights:

<!-- Paste feature-highlights.md content here -->
