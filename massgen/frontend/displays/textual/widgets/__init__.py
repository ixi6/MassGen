"""
Textual widgets for the MassGen TUI.

This module exports all widgets including:
- Modal base classes (BaseModal, BaseDataModal)
- Extracted modal components organized by function
- Re-exports from the existing textual_widgets directory for backwards compatibility
"""

# Base modal classes
from .modal_base import MODAL_BASE_CSS, BaseDataModal, BaseModal

# Extracted modals - organized by function
from .modals import (  # Browser modals; Status modals; Coordination modals; Content modals; Input modals; Review modal; Shortcuts modal; Workspace modals; Agent output modal
    AgentOutputModal,
    AgentSelectorModal,
    AnswerBrowserModal,
    BroadcastPromptModal,
    BrowserTabsModal,
    ChunkAdvanceModal,
    ContextModal,
    ConversationHistoryModal,
    CoordinationTableModal,
    CostBreakdownModal,
    DecompositionGenerationModal,
    DecompositionSubtasksModal,
    EvaluationCriteriaModal,
    FileInspectionModal,
    GitDiffReviewModal,
    KeyboardShortcutsModal,
    MCPStatusModal,
    MetricsModal,
    OrchestratorEventsModal,
    SkillsModal,
    StructuredBroadcastPromptModal,
    SystemStatusModal,
    TextContentModal,
    TimelineModal,
    TurnDetailModal,
    VoteResultsModal,
    WorkspaceBrowserModal,
)

__all__ = [
    # Base classes
    "BaseModal",
    "BaseDataModal",
    "MODAL_BASE_CSS",
    # Browser modals
    "AnswerBrowserModal",
    "BrowserTabsModal",
    "TimelineModal",
    "WorkspaceBrowserModal",
    # Status modals
    "CostBreakdownModal",
    "MCPStatusModal",
    "MetricsModal",
    "SystemStatusModal",
    # Coordination modals
    "AgentSelectorModal",
    "CoordinationTableModal",
    "OrchestratorEventsModal",
    "VoteResultsModal",
    # Content modals
    "ContextModal",
    "ConversationHistoryModal",
    "EvaluationCriteriaModal",
    "TextContentModal",
    "TurnDetailModal",
    # Input modals
    "BroadcastPromptModal",
    "ChunkAdvanceModal",
    "DecompositionGenerationModal",
    "DecompositionSubtasksModal",
    "StructuredBroadcastPromptModal",
    # Review modal
    "GitDiffReviewModal",
    # Shortcuts modal
    "KeyboardShortcutsModal",
    # Skills modals
    "SkillsModal",
    # Workspace modals
    "FileInspectionModal",
    # Agent output modal
    "AgentOutputModal",
]
