# MassGen v0.1.58 Roadmap

## Overview

Version 0.1.58 focuses on adding ElevenLabs as a provider for text-to-speech and speech-to-text, integrated with MassGen's existing multimodal tools.

- **ElevenLabs TTS & STT Support** (Required): Add ElevenLabs support for TTS and speech-to-text in generate/read media

## Key Technical Priorities

1. **ElevenLabs Integration**: Add ElevenLabs as a provider for high-quality voice synthesis and transcription
   **Use Case**: High-quality voice synthesis and transcription via ElevenLabs API within multi-agent workflows

## Key Milestones

### Milestone 1: ElevenLabs TTS & STT Support (REQUIRED)

**Goal**: Add ElevenLabs as a provider for text-to-speech and speech-to-text

**Owner**: @ncrispino (nickcrispino on Discord)

**Issue**: [#942](https://github.com/massgen/MassGen/issues/942)

#### 1.1 Text-to-Speech Integration
- [ ] Add ElevenLabs TTS provider in `massgen/generation/` module
- [ ] Integrate with existing `generate_media` tool for audio output
- [ ] Support voice selection and configuration options
- [ ] Handle API key management and rate limiting

#### 1.2 Speech-to-Text Integration
- [ ] Add ElevenLabs STT provider for audio transcription
- [ ] Integrate with existing `read_media` tool for audio input
- [ ] Support multiple audio formats and languages

#### 1.3 Testing & Documentation
- [ ] Add unit tests for ElevenLabs TTS provider
- [ ] Add unit tests for ElevenLabs STT provider
- [ ] Add integration tests with `generate_media` and `read_media`
- [ ] Update multimodal documentation with ElevenLabs configuration examples
- [ ] Add example configs in `massgen/configs/`

**Success Criteria**:
- ElevenLabs TTS working via `generate_media`
- ElevenLabs STT working via `read_media`
- Proper error handling for missing API keys and rate limits

---

## Timeline

**Target Release**: March 2, 2026

### Phase 1 (Feb 28 - Mar 1)
- ElevenLabs TTS Integration (Milestone 1.1)
- ElevenLabs STT Integration (Milestone 1.2)

### Phase 2 (Mar 1-2)
- Testing & Documentation (Milestone 1.3)

---

## Success Metrics

- **TTS Quality**: ElevenLabs TTS produces correct audio output via `generate_media`
- **STT Accuracy**: ElevenLabs STT correctly transcribes audio via `read_media`
- **Integration**: Both tools work within multi-agent coordination workflows

---

## Resources

- **Issue #942**: [ElevenLabs TTS & STT Support](https://github.com/massgen/MassGen/issues/942)
- **Owner**: @ncrispino (nickcrispino on Discord)
- **Related PRs**: TBD

---

## Related Tracks

This release builds on previous work:
- **v0.1.49**: Fairness Gate, Checklist Voting, Log Analysis TUI (#869)
- **v0.1.50**: Chunked Plan Execution (#877), Skill Lifecycle Management (#878)
- **v0.1.51**: Change Documents (#896), Changedoc Evaluation, Drift Conflict Policy
- **v0.1.52**: Final Answer Modal (#901), Substantive Gate, Novelty Injection, Agent Identity
- **v0.1.53**: Background Tools & Specialized Subagents (#917)
- **v0.1.54**: Copilot SDK Backend (#862), Subagent Messaging (#926), Gemini 3.1 Pro
- **v0.1.55**: Specialized Subagent Types (#938), Dynamic Evaluation Criteria, Native Image Routing
- **v0.1.56**: Critic Subagent (#945), Spec Plan Mode, Audio Multimodal, ask_others Targeting
- **v0.1.57**: Delegation Protocol (#955), Builder Subagent, Substantiveness Tracking, Claude Code Reasoning

And sets the foundation for:
- **v0.1.59**: Nano Banana 2 Default Image Generation (#951)
- **v0.1.60**: Improve skill use and exploration (#873)
