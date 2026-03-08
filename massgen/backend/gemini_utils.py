"""
Gemini-specific structured output models for coordination actions (voting and answer submission).
"""

import enum

try:
    from pydantic import BaseModel, Field
except ImportError:
    BaseModel = None
    Field = None


class ActionType(enum.Enum):
    """Action types for structured output."""

    VOTE = "vote"
    NEW_ANSWER = "new_answer"
    ASK_OTHERS = "ask_others"


class DecompositionActionType(enum.Enum):
    """Action types for decomposition mode structured output."""

    STOP = "stop"
    NEW_ANSWER = "new_answer"


class VoteOnlyActionType(enum.Enum):
    """Action type for vote-only mode (when agent has reached answer limit)."""

    VOTE = "vote"


class PostEvaluationActionType(enum.Enum):
    """Action types for post-evaluation structured output."""

    SUBMIT = "submit"
    RESTART = "restart"


class VoteAction(BaseModel):
    """Structured output for voting action."""

    action: ActionType = Field(default=ActionType.VOTE, description="Action type")
    agent_id: str = Field(description="Anonymous agent ID to vote for (e.g., 'agent1', 'agent2')")
    reason: str = Field(description="Brief reason why this agent has the best answer")


class NewAnswerAction(BaseModel):
    """Structured output for new answer action."""

    action: ActionType = Field(default=ActionType.NEW_ANSWER, description="Action type")
    content: str = Field(description="Your improved answer. If any builtin tools like search or code execution were used, include how they are used here.")


class AskOthersAction(BaseModel):
    """Structured output for ask_others action (broadcast question to other agents)."""

    action: ActionType = Field(default=ActionType.ASK_OTHERS, description="Action type")
    question: str = Field(
        description="Your specific, actionable question with ALL relevant context included. "
        "Other agents cannot see your files or workspace, so include requirements, "
        "constraints, and any important details they need to give a useful answer.",
    )
    wait: bool = Field(default=True, description="Whether to wait for responses before continuing")


class CoordinationResponse(BaseModel):
    """Structured response for coordination actions."""

    action_type: ActionType = Field(description="Type of action to take")
    vote_data: VoteAction | None = Field(default=None, description="Vote data if action is vote")
    answer_data: NewAnswerAction | None = Field(default=None, description="Answer data if action is new_answer")
    ask_others_data: AskOthersAction | None = Field(default=None, description="Ask others data if action is ask_others")


class VoteOnlyVoteAction(BaseModel):
    """Structured output for voting action in vote-only mode."""

    action: VoteOnlyActionType = Field(default=VoteOnlyActionType.VOTE, description="Action type (must be vote)")
    agent_id: str = Field(description="Anonymous agent ID to vote for (e.g., 'agent1', 'agent2')")
    reason: str = Field(description="Brief reason why this agent has the best answer")


class VoteOnlyCoordinationResponse(BaseModel):
    """Structured response for vote-only mode (when agent has reached answer limit).

    In vote-only mode, agents can ONLY vote - they cannot submit new answers.
    This is used when max_new_answers_per_agent limit has been reached.
    """

    action_type: VoteOnlyActionType = Field(description="Type of action to take (must be vote)")
    vote_data: VoteOnlyVoteAction = Field(description="Vote data - REQUIRED in vote-only mode")


class StopAction(BaseModel):
    """Structured output for stop action (decomposition mode)."""

    action: DecompositionActionType = Field(default=DecompositionActionType.STOP, description="Action type")
    summary: str = Field(description="What you accomplished and how it connects to other agents' work")
    status: str = Field(description="Whether your subtask is complete or blocked ('complete' or 'blocked')")


class DecompositionNewAnswerAction(BaseModel):
    """Structured output for new answer action in decomposition mode."""

    action: DecompositionActionType = Field(default=DecompositionActionType.NEW_ANSWER, description="Action type")
    content: str = Field(description="Your improved answer for your subtask.")


class DecompositionCoordinationResponse(BaseModel):
    """Structured response for decomposition mode coordination.

    In decomposition mode, agents call stop (not vote) when their subtask is complete.
    """

    action_type: DecompositionActionType = Field(description="Type of action to take")
    stop_data: StopAction | None = Field(default=None, description="Stop data if action is stop")
    answer_data: DecompositionNewAnswerAction | None = Field(default=None, description="Answer data if action is new_answer")


class SubmitAction(BaseModel):
    """Structured output for submit action (post-evaluation)."""

    action: PostEvaluationActionType = Field(default=PostEvaluationActionType.SUBMIT, description="Action type")
    confirmed: bool = Field(default=True, description="Confirmation that answer is satisfactory")


class RestartAction(BaseModel):
    """Structured output for restart action (post-evaluation)."""

    action: PostEvaluationActionType = Field(default=PostEvaluationActionType.RESTART, description="Action type")
    reason: str = Field(description="Clear explanation of why the answer is insufficient")
    instructions: str = Field(description="Detailed, actionable guidance for agents on the next attempt")


class PostEvaluationResponse(BaseModel):
    """Structured response for post-evaluation actions."""

    action_type: PostEvaluationActionType = Field(description="Type of post-evaluation action to take")
    submit_data: SubmitAction | None = Field(default=None, description="Submit data if action is submit")
    restart_data: RestartAction | None = Field(default=None, description="Restart data if action is restart")
