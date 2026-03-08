"""
Textual TUI components for MassGen.

This package contains all Textual-based TUI components:
- widgets/: UI widgets including modals, cards, and input components
- themes/: TCSS theme files (dark, light, midnight, professional)

The main TextualTerminalDisplay class is still in the parent directory
(textual_terminal_display.py) but imports modals from this package.
"""

# Re-export widgets for convenience
from .widgets import (  # Base classes; Browser modals; Status modals; Coordination modals; Content modals; Input modals; Review modal; Shortcuts modal; Workspace modals; Agent output modal
    MODAL_BASE_CSS,
    AgentOutputModal,
    AgentSelectorModal,
    AnswerBrowserModal,
    BaseDataModal,
    BaseModal,
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
