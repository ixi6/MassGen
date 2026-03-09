# MassGen v0.1.61 — Round Evaluator Paradigm

New specialized subagent type that automatically spawns evaluator subagents after each new answer to provide detailed feedback as input to the next round. Major orchestrator refactoring with improved evaluation prompts, task plan injection, and subagent fixes.

## 🔄 Round Evaluator

- New `round_evaluator` subagent type — automatically spawns evaluator subagents after each new answer to provide detailed feedback as input to the next round
- Major orchestrator refactoring (+1,189 lines) to support the round evaluation workflow
- New `round_evaluator_example.yaml` config for easy adoption

## 📝 Evaluation & Prompts

- Improved evaluation prompts for clearer, more actionable feedback
- Task plan injection into evaluation workflow for context-aware assessment
- Simplified config handling for evaluation parameters
- SUBAGENT.md generality improvements for broader subagent compatibility

## 🔧 Fixes

- Session resumption fix for already-resumed logs
- Round evaluation prompt clarity enhancements

## 🚀 Try It

```bash
pip install massgen==0.1.61
uv run massgen --config @examples/features/round_evaluator_example.yaml "Create a website for an AI startup with polished visuals and interactive elements"
```

**Full Changelog:** https://github.com/massgen/MassGen/blob/main/CHANGELOG.md

📖 [Documentation](https://docs.massgen.ai) · 💬 [Discord](https://discord.massgen.ai) · 🐦 [X/Twitter](https://x.massgen.ai)
