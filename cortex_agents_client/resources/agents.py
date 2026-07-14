"""Resource class for Cortex Agent CRUD operations and feedback.

Provides create, describe, update, list, delete, and feedback operations
against the ``/api/v2/databases/{db}/schemas/{schema}/agents`` endpoint family.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from cortex_agents_client.http import HttpClient
from cortex_agents_client.models.agent import Agent


class AgentsResource:
    """Manages Cortex Agent objects in a Snowflake account.

    All methods accept ``database`` and ``schema`` as required positional
    arguments unless defaults were set on the parent
    :class:`cortex_agents_client.client.CortexAgentsClient`.

    Args:
        http: Authenticated HTTP client.
        default_database: Default database name used when ``database`` is
            not supplied to individual methods.
        default_schema: Default schema name used when ``schema`` is not
            supplied to individual methods.

    Example::

        agent = client.agents.create(
            database="MY_DB",
            schema="MY_SCHEMA",
            name="MY_AGENT",
            instructions={"response": "Be concise."},
        )
    """

    def __init__(
        self,
        http: HttpClient,
        default_database: str | None = None,
        default_schema: str | None = None,
    ) -> None:
        """Initialises the agents resource.

        Args:
            http: Authenticated HTTP client.
            default_database: Optional default database.
            default_schema: Optional default schema.
        """
        self._http = http
        self._default_database = default_database
        self._default_schema = default_schema

    def _path(self, database: str, schema: str, name: str | None = None) -> str:
        """Builds the API path for an agent endpoint.

        Args:
            database: Database identifier.
            schema: Schema identifier.
            name: Optional agent name for single-resource paths.

        Returns:
            Relative API path string.
        """
        base = f"/api/v2/databases/{quote(database, safe='')}/schemas/{quote(schema, safe='')}/agents"
        return f"{base}/{quote(name, safe='')}" if name else base

    def _resolve(
        self, database: str | None, schema: str | None
    ) -> tuple[str, str]:
        """Resolves database and schema using defaults if needed.

        Args:
            database: Explicit database or ``None`` to use default.
            schema: Explicit schema or ``None`` to use default.

        Returns:
            Tuple of ``(database, schema)`` strings.

        Raises:
            ValueError: If database or schema is not provided and no default
                was set.
        """
        db = database or self._default_database
        sc = schema or self._default_schema
        if not db:
            raise ValueError(
                "database is required. Pass it explicitly or set default_database "
                "on CortexAgentsClient."
            )
        if not sc:
            raise ValueError(
                "schema is required. Pass it explicitly or set default_schema "
                "on CortexAgentsClient."
            )
        return db, sc

    def create(
        self,
        name: str,
        *,
        database: str | None = None,
        schema: str | None = None,
        comment: str | None = None,
        profile: dict[str, Any] | None = None,
        models: dict[str, Any] | None = None,
        instructions: dict[str, Any] | None = None,
        orchestration: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_resources: dict[str, Any] | None = None,
        create_mode: str = "errorIfExists",
    ) -> Agent:
        """Creates a new Cortex Agent object.

        Args:
            name: Agent name (Snowflake identifier, uppercase recommended).
            database: Database to create the agent in. Uses
                ``default_database`` if not provided.
            schema: Schema to create the agent in. Uses
                ``default_schema`` if not provided.
            comment: Optional description of the agent.
            profile: Dict with ``display_name`` and optional ``avatar``,
                ``color`` fields.
            models: Dict with optional ``orchestration`` model name.
                Defaults to automatic model selection.
            instructions: Dict with optional ``response`` and
                ``orchestration`` instruction strings.
            orchestration: Dict with optional ``budget`` config.
            tools: List of tool dicts, each with a ``tool_spec`` key.
            tool_resources: Dict mapping tool name to resource configuration.
            create_mode: One of ``"errorIfExists"`` (default), ``"orReplace"``,
                or ``"ifNotExists"``.

        Returns:
            The created :class:`~cortex_agents_client.models.agent.Agent`.

        Raises:
            ValueError: If database or schema is missing.
            cortex_agents_client.exceptions.AuthError: On authentication failure.
            cortex_agents_client.exceptions.CortexPermissionError: On missing privileges.
            cortex_agents_client.exceptions.CortexAgentError: On other API errors.

        Example::

            agent = client.agents.create(
                "MY_AGENT",
                database="DB",
                schema="SCHEMA",
                instructions={"response": "Be concise."},
                tools=[{
                    "tool_spec": {
                        "type": "cortex_analyst_text_to_sql",
                        "name": "Analyst1",
                    }
                }],
                tool_resources={
                    "Analyst1": {
                        "semantic_view": "DB.SCHEMA.REVENUE_VIEW",
                        "execution_environment": {
                            "type": "warehouse",
                            "warehouse": "MY_WH",
                        },
                    }
                },
            )
        """
        db, sc = self._resolve(database, schema)
        body: dict[str, Any] = {"name": name}
        if comment is not None:
            body["comment"] = comment
        if profile:
            body["profile"] = profile
        if models:
            body["models"] = models
        if instructions:
            body["instructions"] = instructions
        if orchestration:
            body["orchestration"] = orchestration
        if tools:
            body["tools"] = tools
        if tool_resources:
            body["tool_resources"] = tool_resources

        result = self._http.request(
            "POST",
            self._path(db, sc),
            params={"createMode": create_mode},
            json=body,
            resource="agent",
        )
        # The create endpoint returns a status message; describe to get the
        # full Agent object.
        return self.get(name, database=db, schema=sc)

    def get(
        self,
        name: str,
        *,
        database: str | None = None,
        schema: str | None = None,
    ) -> Agent:
        """Describes a Cortex Agent and returns its configuration.

        Args:
            name: Agent name.
            database: Database containing the agent. Uses default if not set.
            schema: Schema containing the agent. Uses default if not set.

        Returns:
            A populated :class:`~cortex_agents_client.models.agent.Agent`.

        Raises:
            cortex_agents_client.exceptions.AgentNotFoundError: If the agent does
                not exist.
            cortex_agents_client.exceptions.AuthError: On authentication failure.
        """
        db, sc = self._resolve(database, schema)
        data = self._http.request("GET", self._path(db, sc, name), resource="agent")
        return Agent.from_dict(data)

    def update(
        self,
        name: str,
        *,
        database: str | None = None,
        schema: str | None = None,
        comment: str | None = None,
        profile: dict[str, Any] | None = None,
        models: dict[str, Any] | None = None,
        instructions: dict[str, Any] | None = None,
        orchestration: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_resources: dict[str, Any] | None = None,
    ) -> None:
        """Updates an existing Cortex Agent.

        Only provided fields are included in the update request. Fields not
        supplied are left unchanged.

        Args:
            name: Agent name.
            database: Database containing the agent.
            schema: Schema containing the agent.
            comment: New comment string.
            profile: New profile dict.
            models: New model configuration dict.
            instructions: New instructions dict.
            orchestration: New orchestration configuration dict.
            tools: New tools list (replaces existing tools).
            tool_resources: New tool resources dict.

        Raises:
            cortex_agents_client.exceptions.AgentNotFoundError: If agent does not
                exist.
            cortex_agents_client.exceptions.AuthError: On authentication failure.
        """
        db, sc = self._resolve(database, schema)
        body: dict[str, Any] = {}
        if comment is not None:
            body["comment"] = comment
        if profile is not None:
            body["profile"] = profile
        if models is not None:
            body["models"] = models
        if instructions is not None:
            body["instructions"] = instructions
        if orchestration is not None:
            body["orchestration"] = orchestration
        if tools is not None:
            body["tools"] = tools
        if tool_resources is not None:
            body["tool_resources"] = tool_resources

        self._http.request("PUT", self._path(db, sc, name), json=body, resource="agent")

    def list(
        self,
        *,
        database: str | None = None,
        schema: str | None = None,
        like: str | None = None,
        from_name: str | None = None,
        limit: int | None = None,
    ) -> list[Agent]:
        """Lists all agents in the given database and schema.

        Args:
            database: Database to list agents in.
            schema: Schema to list agents in.
            like: SQL LIKE pattern to filter by agent name
                (e.g. ``"MY_%"``).
            from_name: Start listing agents whose name follows this string
                (case-sensitive cursor for pagination).
            limit: Maximum number of agents to return (1–10000).

        Returns:
            List of :class:`~cortex_agents_client.models.agent.Agent` objects.
        """
        db, sc = self._resolve(database, schema)
        params: dict[str, Any] = {}
        if like:
            params["like"] = like
        if from_name:
            params["fromName"] = from_name
        if limit is not None:
            params["showLimit"] = limit

        data = self._http.request("GET", self._path(db, sc), params=params or None, resource="agent")
        if isinstance(data, list):
            return [Agent.from_dict(item) for item in data]
        return []

    def delete(
        self,
        name: str,
        *,
        database: str | None = None,
        schema: str | None = None,
        if_exists: bool = False,
    ) -> None:
        """Deletes a Cortex Agent.

        Args:
            name: Agent name.
            database: Database containing the agent.
            schema: Schema containing the agent.
            if_exists: If ``True``, does not raise an error if the agent
                does not exist.

        Raises:
            cortex_agents_client.exceptions.AgentNotFoundError: If the agent does
                not exist and ``if_exists`` is ``False``.
        """
        db, sc = self._resolve(database, schema)
        params = {"ifExists": "true" if if_exists else "false"}
        self._http.request(
            "DELETE",
            self._path(db, sc, name),
            params=params,
            resource="agent",
        )

    def feedback(
        self,
        name: str,
        *,
        positive: bool,
        request_id: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        thread_id: int | None = None,
        feedback_message: str | None = None,
        categories: list[str] | None = None,
    ) -> None:
        """Submits user feedback for an agent response.

        Feedback helps improve agent quality over time and can be reviewed
        in the Snowsight agent monitoring interface.

        Two feedback modes are supported:

        - **Request-level feedback** (pass ``request_id``): tied to a specific
          run. Use the request ID from the ``X-Snowflake-Request-ID`` response
          header or from a
          :class:`~cortex_agents_client.models.events.MetadataEvent`.
        - **Agent-level feedback** (omit ``request_id``): logged against the
          agent as a whole, not a specific response.

        Args:
            name: Agent name.
            positive: ``True`` for positive feedback, ``False`` for negative.
            request_id: Optional. The ``orig_request_id`` — the request ID of
                the specific run being rated. If omitted, the feedback is
                recorded at the agent level.
            database: Database containing the agent.
            schema: Schema containing the agent.
            thread_id: Thread ID associated with this interaction.
            feedback_message: Optional free-text comment from the user.
            categories: Optional list of feedback category labels.

        Raises:
            cortex_agents_client.exceptions.AgentNotFoundError: If the agent
                does not exist.
        """
        db, sc = self._resolve(database, schema)
        body: dict[str, Any] = {"positive": positive}
        if request_id is not None:
            body["orig_request_id"] = request_id
        if thread_id is not None:
            body["thread_id"] = thread_id  # integer, not string
        if feedback_message is not None:
            body["feedback_message"] = feedback_message
        if categories:
            body["categories"] = categories

        path = f"/api/v2/databases/{quote(db, safe='')}/schemas/{quote(sc, safe='')}/agents/{quote(name, safe='')}:feedback"
        self._http.request("POST", path, json=body, resource="agent")
