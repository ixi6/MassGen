"""
Context Window Compression

Provides algorithmic compression that removes old messages from conversation
history when context window fills up.

Note: A proactive "agent-driven" compression approach was designed but not
implemented due to API limitations (providers only report token usage after
requests complete). See docs/dev_notes/proactive_compression_design.md.
"""

from collections.abc import Callable
from typing import Any

from ..logger_config import logger
from ..structured_logging import log_context_compression
from ..token_manager.token_manager import TokenCostCalculator
from ._conversation import ConversationMemory
from ._persistent import PersistentMemoryBase


class CompressionStats:
    """Statistics about a compression operation."""

    def __init__(
        self,
        messages_removed: int = 0,
        tokens_removed: int = 0,
        messages_kept: int = 0,
        tokens_kept: int = 0,
    ):
        self.messages_removed = messages_removed
        self.tokens_removed = tokens_removed
        self.messages_kept = messages_kept
        self.tokens_kept = tokens_kept


class ContextCompressor:
    """
    Compresses conversation history when context window fills up.

    Strategy:
    - Removes old messages from conversation_memory
    - Preserves system messages (always kept)
    - Keeps most recent messages that fit within token budget

    Features:
    - Token-aware compression (not just message count)
    - Preserves system messages
    - Keeps most recent messages
    - Detailed compression logging

    Example:
        >>> compressor = ContextCompressor(
        ...     token_calculator=TokenCostCalculator(),
        ...     conversation_memory=conversation_memory,
        ...     persistent_memory=persistent_memory
        ... )
        >>>
        >>> stats = await compressor.compress_if_needed(
        ...     messages=messages,
        ...     current_tokens=96000,
        ...     target_tokens=51200
        ... )
    """

    def __init__(
        self,
        token_calculator: TokenCostCalculator,
        conversation_memory: ConversationMemory,
        persistent_memory: PersistentMemoryBase | None = None,
        on_compress: Callable[[CompressionStats], None] | None = None,
        agent_id: str | None = None,
    ):
        """
        Initialize context compressor.

        Args:
            token_calculator: Calculator for token estimation
            conversation_memory: Conversation memory to compress
            persistent_memory: Optional persistent memory (for logging purposes)
            on_compress: Optional callback called after compression
            agent_id: Optional agent ID for observability logging
        """
        self.token_calculator = token_calculator
        self.conversation_memory = conversation_memory
        self.persistent_memory = persistent_memory
        self.on_compress = on_compress
        self.agent_id = agent_id or "unknown"

        # Stats tracking
        self.total_compressions = 0
        self.total_messages_removed = 0
        self.total_tokens_removed = 0

    async def compress_if_needed(
        self,
        messages: list[dict[str, Any]],
        current_tokens: int,
        target_tokens: int,
        should_compress: bool = None,
    ) -> CompressionStats | None:
        """
        Compress messages if needed.

        Args:
            messages: Current conversation messages
            current_tokens: Current token count
            target_tokens: Target token count after compression
            should_compress: Optional explicit compression flag
                           If None, compresses only if current_tokens > target_tokens

        Returns:
            CompressionStats if compression occurred, None otherwise
        """
        # Determine if we need to compress
        if should_compress is None:
            should_compress = current_tokens > target_tokens

        if not should_compress:
            return None

        # Select messages to keep
        messages_to_keep = self._select_messages_to_keep(
            messages=messages,
            target_tokens=target_tokens,
        )

        if len(messages_to_keep) >= len(messages):
            # No compression needed (already under target)
            logger.debug("All messages fit within target, skipping compression")
            return None

        # Calculate stats
        messages_removed = len(messages) - len(messages_to_keep)
        messages_to_remove = [msg for msg in messages if msg not in messages_to_keep]
        tokens_removed = self.token_calculator.estimate_tokens(messages_to_remove)
        tokens_kept = self.token_calculator.estimate_tokens(messages_to_keep)

        # Update conversation memory
        try:
            await self.conversation_memory.clear()
            await self.conversation_memory.add(messages_to_keep)
        except Exception as e:
            logger.error(
                f"Failed to update conversation memory during compression: {e}. " "Memory may be in inconsistent state.",
                exc_info=True,
            )
            # Return None to signal failure - caller should handle gracefully
            # Note: clear() may have succeeded, leaving memory empty
            return None

        # Log compression result
        if self.persistent_memory:
            logger.info(
                f"📦 Context compressed: Removed {messages_removed} old messages "
                f"({tokens_removed:,} tokens) from active context.\n"
                f"   Kept {len(messages_to_keep)} recent messages ({tokens_kept:,} tokens).\n"
                f"   Old messages remain accessible via semantic search.",
            )
        else:
            logger.warning(
                f"⚠️  Context compressed: Removed {messages_removed} old messages "
                f"({tokens_removed:,} tokens) from active context.\n"
                f"   Kept {len(messages_to_keep)} recent messages ({tokens_kept:,} tokens).\n"
                f"   No persistent memory - old messages NOT retrievable.",
            )

        # Update stats
        self.total_compressions += 1
        self.total_messages_removed += messages_removed
        self.total_tokens_removed += tokens_removed

        # Create stats object
        stats = CompressionStats(
            messages_removed=messages_removed,
            tokens_removed=tokens_removed,
            messages_kept=len(messages_to_keep),
            tokens_kept=tokens_kept,
        )

        # Log to Logfire for observability
        # Calculate original char count from all messages
        original_char_count = sum(len(str(msg.get("content", ""))) for msg in messages)
        compressed_char_count = sum(len(str(msg.get("content", ""))) for msg in messages_to_keep)
        compression_ratio = compressed_char_count / original_char_count if original_char_count > 0 else 0

        log_context_compression(
            agent_id=self.agent_id,
            reason="context_length_exceeded",
            original_message_count=len(messages),
            compressed_message_count=len(messages_to_keep),
            original_char_count=original_char_count,
            compressed_char_count=compressed_char_count,
            compression_ratio=compression_ratio,
            success=True,
        )

        # Trigger callback if provided
        if self.on_compress:
            self.on_compress(stats)

        return stats

    def _select_messages_to_keep(
        self,
        messages: list[dict[str, Any]],
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        """
        Select which messages to keep in active context.

        Strategy:
        1. Always keep system messages at the start
        2. Keep most recent messages that fit in target_tokens
        3. Remove everything in between

        Args:
            messages: All messages in conversation
            target_tokens: Target token budget for kept messages

        Returns:
            List of messages to keep in conversation_memory
        """
        if not messages:
            return []

        # Separate system messages from others
        system_messages = []
        non_system_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_messages.append(msg)
            else:
                non_system_messages.append(msg)

        # Start with system messages in kept list
        messages_to_keep = system_messages.copy()
        tokens_so_far = self.token_calculator.estimate_tokens(system_messages)

        # Work backwards from most recent, adding messages until we hit target
        recent_messages_to_keep = []
        for msg in reversed(non_system_messages):
            msg_tokens = self.token_calculator.estimate_tokens([msg])
            if tokens_so_far + msg_tokens <= target_tokens:
                tokens_so_far += msg_tokens
                recent_messages_to_keep.insert(0, msg)  # Maintain order
            else:
                # Hit token limit, stop here
                break

        # Combine: system messages + recent messages
        messages_to_keep.extend(recent_messages_to_keep)

        return messages_to_keep

    def get_stats(self) -> dict[str, Any]:
        """Get compression statistics."""
        return {
            "total_compressions": self.total_compressions,
            "total_messages_removed": self.total_messages_removed,
            "total_tokens_removed": self.total_tokens_removed,
        }
