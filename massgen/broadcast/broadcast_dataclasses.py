"""Data structures for broadcast communication system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class BroadcastStatus(Enum):
    """Status of a broadcast request."""

    PENDING = "pending"  # Just created, not yet sent to agents
    COLLECTING = "collecting"  # Sent to agents, collecting responses
    COMPLETE = "complete"  # All responses collected
    TIMEOUT = "timeout"  # Timeout reached before all responses collected


@dataclass
class QuestionOption:
    """A single option for a structured question.

    Args:
        id: Unique identifier for this option (used in responses)
        label: Display text for this option
        description: Optional longer description of the option
    """

    id: str
    label: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QuestionOption":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            label=data["label"],
            description=data.get("description", ""),
        )


@dataclass
class StructuredQuestion:
    """A structured question with predefined options.

    Args:
        text: The question text to display
        options: List of available options
        multi_select: Whether multiple options can be selected (default False)
        allow_other: Whether to allow free-form "Other" response (default True)
        required: Whether a response is required - cannot skip (default False)
    """

    text: str
    options: list[QuestionOption]
    multi_select: bool = False
    allow_other: bool = True
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "text": self.text,
            "options": [opt.to_dict() for opt in self.options],
            "multiSelect": self.multi_select,
            "allowOther": self.allow_other,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructuredQuestion":
        """Create from dictionary (e.g., from tool arguments)."""
        options = [QuestionOption.from_dict(opt) if isinstance(opt, dict) else opt for opt in data.get("options", [])]
        return cls(
            text=data["text"],
            options=options,
            multi_select=data.get("multiSelect", False),
            allow_other=data.get("allowOther", True),
            required=data.get("required", False),
        )


@dataclass
class StructuredResponse:
    """Response to a single structured question.

    Args:
        question_index: Index of the question this responds to (0-based)
        selected_options: List of selected option IDs
        other_text: Free-form text if "Other" was selected/used
    """

    question_index: int
    selected_options: list[str]
    other_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "questionIndex": self.question_index,
            "selectedOptions": self.selected_options,
            "otherText": self.other_text,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StructuredResponse":
        """Create from dictionary."""
        return cls(
            question_index=data["questionIndex"],
            selected_options=data["selectedOptions"],
            other_text=data.get("otherText"),
        )


@dataclass
class BroadcastRequest:
    """Represents a broadcast question from one agent to others.

    Args:
        id: Unique identifier for this broadcast request
        sender_agent_id: ID of the agent sending the broadcast
        question: The question or message being broadcast. Can be:
            - A simple string (backward compatible)
            - A list of StructuredQuestion objects (for structured questions with options)
        timestamp: When the broadcast was created
        status: Current status of the broadcast
        timeout: Maximum time to wait for responses (seconds)
        responses_received: Number of responses collected so far
        expected_response_count: Expected number of responses (num agents + human if applicable)
        target_agents: Optional list of specific agents to query (anonymous IDs like ['agent1', 'agent2']).
            If None, broadcasts to all other agents. If provided, only queries specified agents.
        response_mode: How the broadcast should be handled ("inline" only for now; other modes like "background" could be added in future)
        metadata: Additional metadata for the broadcast
    """

    id: str
    sender_agent_id: str
    question: str | list[StructuredQuestion]
    timestamp: datetime
    status: BroadcastStatus = BroadcastStatus.PENDING
    timeout: int = 300
    responses_received: int = 0
    expected_response_count: int = 0
    target_agents: list[str] | None = None
    response_mode: str = "inline"  # Always "inline" for now. Could support other modes (e.g., "background") in future if needed.
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_structured(self) -> bool:
        """Check if this broadcast contains structured questions."""
        return isinstance(self.question, list)

    @property
    def question_text(self) -> str:
        """Get display text for the question(s).

        For simple questions, returns the string directly.
        For structured questions, returns the text of the first question
        or a summary if there are multiple questions.
        """
        if isinstance(self.question, str):
            return self.question
        elif isinstance(self.question, list) and len(self.question) > 0:
            if len(self.question) == 1:
                return self.question[0].text
            return f"{self.question[0].text} (and {len(self.question) - 1} more questions)"
        return ""

    @property
    def question_count(self) -> int:
        """Get the number of questions in this broadcast."""
        if isinstance(self.question, str):
            return 1
        return len(self.question)

    @property
    def structured_questions(self) -> list[StructuredQuestion]:
        """Get the list of structured questions (empty list if simple question)."""
        if isinstance(self.question, list):
            return self.question
        return []

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        # Serialize question appropriately
        if isinstance(self.question, str):
            question_data = self.question
        else:
            question_data = [q.to_dict() for q in self.question]

        return {
            "id": self.id,
            "sender_agent_id": self.sender_agent_id,
            "question": question_data,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status.value,
            "timeout": self.timeout,
            "responses_received": self.responses_received,
            "expected_response_count": self.expected_response_count,
            "response_mode": self.response_mode,
            "metadata": self.metadata,
        }


@dataclass
class BroadcastResponse:
    """Represents a response to a broadcast request.

    Args:
        request_id: ID of the broadcast request this responds to
        responder_id: ID of the agent or "human" responding
        content: The response content. Can be:
            - A simple string (for simple questions)
            - A list of StructuredResponse objects (for structured questions)
        timestamp: When the response was created
        is_human: Whether this response is from a human
        metadata: Additional metadata for the response
    """

    request_id: str
    responder_id: str
    content: str | list[StructuredResponse]
    timestamp: datetime
    is_human: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_structured(self) -> bool:
        """Check if this is a structured response."""
        return isinstance(self.content, list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        # Serialize content appropriately
        if isinstance(self.content, str):
            content_data = self.content
        else:
            content_data = [r.to_dict() for r in self.content]

        return {
            "request_id": self.request_id,
            "responder_id": self.responder_id,
            "content": content_data,
            "timestamp": self.timestamp.isoformat(),
            "is_human": self.is_human,
            "metadata": self.metadata,
        }
