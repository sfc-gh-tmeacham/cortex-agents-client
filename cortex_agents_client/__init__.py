"""Cortex Agents Python client library.

A Python client for the Snowflake Cortex Agents REST API, with first-class
support for Streamlit applications.

Basic usage::

    from cortex_agents_client import CortexAgentsClient

    client = CortexAgentsClient(
        account_url="https://myorg-myaccount.snowflakecomputing.com",
        auth="v2:my_pat_token",
    )

    thread = client.create_thread()
    for event in thread.chat("DB.SCHEMA.MY_AGENT", "What is total revenue?"):
        print(event)

Streamlit usage::

    from cortex_agents_client.st import StreamlitChatbot

    bot = StreamlitChatbot(
        account_url=st.secrets["SNOWFLAKE_ACCOUNT_URL"],
        auth=st.secrets["SNOWFLAKE_PAT"],
        agent_path="DB.SCHEMA.MY_AGENT",
    )
    bot.render()
"""

from cortex_agents_client.auth import JWTAuth, OAuthAuth, PATAuth, SiSContainerAuth
from cortex_agents_client.auth import account_url_from_env, AuthProvider
from cortex_agents_client.client import CortexAgentsClient, Thread
from cortex_agents_client.exceptions import (
    AgentNotFoundError,
    AuthError,
    CortexAgentError,
    CortexConnectionError,
    CortexPermissionError,
    CortexTimeoutError,
    NotFoundError,
    PermissionError,   # deprecated alias for CortexPermissionError
    RateLimitError,
    RunError,
    ServerError,
    ThreadNotFoundError,
    TimeoutError,      # deprecated alias for CortexTimeoutError
)
from cortex_agents_client.models.agent import Agent
from cortex_agents_client.models.thread import StoredMessage, ThreadDetail, ThreadMessage, ThreadMetadata
from cortex_agents_client.models.events import (
    AnalystDeltaEvent,
    ChartEvent,
    ErrorEvent,
    InputTokens,
    MetadataEvent,
    OutputTokens,
    ResponseEvent,
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
from cortex_agents_client.resources.runs import RunResult

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
    # Deprecated exception aliases
    "PermissionError",
    "TimeoutError",
    # Models
    "Agent",
    "StoredMessage",
    "ThreadDetail",
    "ThreadMessage",
    "ThreadMetadata",
    "RunResult",
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
