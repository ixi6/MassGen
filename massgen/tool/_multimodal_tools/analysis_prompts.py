"""Prompts for vision model analysis in read_media.

Contains the always-on system prompt and improved default prompt template.
Kept in a separate module for testability and easy modification.
"""

VISION_SYSTEM_PROMPT = (
    "You are reviewing this work critically. Be honest about what you see "
    "— name specific problems, explain their impact, and distinguish between "
    "issues that need a fundamental rethink vs issues that are easy fixes. "
    "Don't sugarcoat."
)

DEFAULT_MEDIA_PROMPT_TEMPLATE = "Analyze this {media_type}. What works, what's broken, and what would " "a demanding user complain about? Be specific and critical."
