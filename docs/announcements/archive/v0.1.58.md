# MassGen v0.1.58 Release Announcement

<!--
This is the current release announcement. Copy this + feature-highlights.md to LinkedIn/X.
After posting, update the social links below.
-->

## Release Summary

We're excited to release MassGen v0.1.58 — a Comprehensive Multimodal Revamp! 🚀 Three new media providers for comprehensive set (OpenAI GPT Image/Sora, Google Nano Banana 2/Veo 3.1, Grok Imagine, ElevenLabs) give agents more choices for voice, image, and video generation. New image, video, and audio generation skills provide reusable workflows, and multi-turn image editing lets agents iteratively refine visuals across rounds. Plus: Nvidia NIM backend, quality rethinking subagent, and new CLI mode flags.

## Install

```bash
pip install massgen==0.1.58
```

## Links

- **Release notes:** https://github.com/massgen/MassGen/releases/tag/v0.1.58
- **X post:** [TO BE ADDED AFTER POSTING]
- **LinkedIn post:** [TO BE ADDED AFTER POSTING]

---

## Full Announcement (for LinkedIn)

Copy everything below this line, then append content from `feature-highlights.md`:

---

We're excited to release MassGen v0.1.58 — a Comprehensive Multimodal Revamp! 🚀 Three new media providers for comprehensive set (OpenAI GPT Image/Sora, Google Nano Banana 2/Veo 3.1, Grok Imagine, ElevenLabs) give agents more choices for voice, image, and video generation. New image, video, and audio generation skills provide reusable workflows, and multi-turn image editing lets agents iteratively refine visuals across rounds. Plus: Nvidia NIM backend, quality rethinking subagent, and new CLI mode flags.

**Key Feature: Comprehensive Multimodal Revamp**

MassGen agents can now generate and understand a much wider range of media:

- **ElevenLabs TTS & STT** (#942): High-quality voice synthesis and transcription integrated with `generate_media` and `read_media` tools — agents can now speak and listen via ElevenLabs
- **Nano Banana 2** (#951): New default image generation model with significantly higher quality output
- **Grok Image/Video Generation**: Native Grok multimedia generation via xAI API — images and videos from Grok Imagine
- **Media Generation Skills**: New reusable skills for image, video, and audio generation workflows
- **Multi-Turn Image Editing**: Continuation IDs enable iterative image editing sessions — agents can refine images across multiple turns

**Also in this release:**
- Nvidia NIM Backend (#962): First-class provider integration for NVIDIA Inference Microservices
- Quality Rethinking Subagent (#964): New `quality_rethinking` type for targeted per-element craft improvements
- Smarter Checklists: Explicit improve/preserve listings, better label refresh ordering, evaluation criteria defaults
- CLI Mode Flags: `--quick`, `--single-agent`, `--coordination-mode`, `--personas` mirroring TUI toggles
- Logging Architecture Refactor: Fixed concurrent logging with LoggingSession isolation
- Subagent Hardening: Better '@' parsing, error handling, clearer context

Release notes: https://github.com/massgen/MassGen/releases/tag/v0.1.58

Feature highlights:

<!-- Paste feature-highlights.md content here -->
