"""Models package for the Cortex Agents library."""

from cortex_agents_client.models.agent import (
    Agent,
    AgentInstructions,
    AgentProfile,
    BudgetConfig,
    ModelConfig,
    OrchestrationConfig,
    Tool,
    ToolSpec,
)
from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    MetadataEvent,
    SSEEvent,
    StatusEvent,
    TableEvent,
    TextAnnotationEvent,
    TextDeltaEvent,
    TextEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    ToolResultEvent,
    ToolResultStatusEvent,
    ToolUseEvent,
    UnknownEvent,
    WarningEvent,
)
from cortex_agents_client.models.thread import (
    StoredMessage,
    ThreadDetail,
    ThreadMessage,
    ThreadMetadata,
)

__all__ = [
    # Agent models
    "Agent",
    "AgentProfile",
    "AgentInstructions",
    "BudgetConfig",
    "ModelConfig",
    "OrchestrationConfig",
    "Tool",
    "ToolSpec",
    # Event models
    "SSEEvent",
    "TextDeltaEvent",
    "TextEvent",
    "TextAnnotationEvent",
    "ThinkingDeltaEvent",
    "ThinkingEvent",
    "ToolUseEvent",
    "ToolResultEvent",
    "ToolResultStatusEvent",
    "AnalystDeltaEvent",
    "TableEvent",
    "ChartEvent",
    "StatusEvent",
    "WarningEvent",
    "ErrorEvent",
    "MetadataEvent",
    "UnknownEvent",
    # Thread models
    "ThreadMetadata",
    "ThreadMessage",
    "ThreadDetail",
    "StoredMessage",
]
