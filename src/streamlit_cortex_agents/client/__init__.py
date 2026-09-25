"""Python client for the Snowflake Cortex Agents REST API.

Used by the Streamlit chat component in :mod:`streamlit_cortex_agents.chat`,
and usable on its own::

    from streamlit_cortex_agents import CortexAgentsClient

    client = CortexAgentsClient(
        account_url="https://myorg-myaccount.snowflakecomputing.com",
        auth="v2:my_pat_token",
    )

    thread = client.create_thread()
    for event in thread.chat("DB.SCHEMA.MY_AGENT", "What is total revenue?"):
        print(event)
"""

from streamlit_cortex_agents.client.auth import JWTAuth, OAuthAuth, PATAuth, SiSContainerAuth
from streamlit_cortex_agents.client.auth import account_url_from_env, AuthProvider
from streamlit_cortex_agents.client.core import CortexAgentsClient, Thread
from streamlit_cortex_agents.client.exceptions import (
    AgentNotFoundError,
    AuthError,
    ConflictError,
    CortexAgentError,
    CortexConnectionError,
    CortexPermissionError,
    CortexTimeoutError,
    NotFoundError,
    PermissionError as PermissionError,  # deprecated alias; kept out of __all__
    RateLimitError,
    RunError,
    RunNotActiveError,
    ServerError,
    ThreadNotFoundError,
    TimeoutError as TimeoutError,  # deprecated alias; kept out of __all__
)
from streamlit_cortex_agents.client.models.agent import Agent
from streamlit_cortex_agents.client.models.thread import StoredMessage, ThreadDetail, ThreadMessage, ThreadMetadata
from streamlit_cortex_agents.client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    InputTokens,
    MetadataEvent,
    OutputTokens,
    ResponseEvent,
    RunMetadata,
    SSEEvent,
    StatusEvent,
    SuggestedQueriesEvent,
    TableEvent,
    TextAnnotationEvent,
    TextDeltaEvent,
    TextEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    TokensConsumed,
    ToolResultEvent,
    ToolResultStatusEvent,
    ToolUseEvent,
    UnknownEvent,
    WarningEvent,
)
from streamlit_cortex_agents.client.resources.runs import RunResult

__all__ = [
    # Core client
    "CortexAgentsClient",
    "Thread",
    # Auth
    "PATAuth",
    "JWTAuth",
    "OAuthAuth",
    "SiSContainerAuth",
    "account_url_from_env",
    "AuthProvider",
    # Exceptions
    "CortexAgentError",
    "AuthError",
    "CortexConnectionError",
    "CortexPermissionError",
    "CortexTimeoutError",
    "NotFoundError",
    "RateLimitError",
    "RunError",
    "ServerError",
    "AgentNotFoundError",
    "ThreadNotFoundError",
    "ConflictError",
    "RunNotActiveError",
    # PermissionError and TimeoutError (deprecated aliases) stay importable
    # by name but are left out of __all__ so a star import cannot shadow the
    # builtins of the same name.
    # Models
    "Agent",
    "StoredMessage",
    "ThreadDetail",
    "ThreadMessage",
    "ThreadMetadata",
    "RunResult",
    "RunMetadata",
    # SSE events
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
    "SuggestedQueriesEvent",
    "WarningEvent",
    "ErrorEvent",
    "MetadataEvent",
    "ResponseEvent",
    "UnknownEvent",
    # ResponseEvent usage models
    "TokensConsumed",
    "InputTokens",
    "OutputTokens",
]
