"""Data models for Cortex Agent objects.

Represents agents, their tools, tool resources, and configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentProfile:
    """Display profile for an agent.

    Attributes:
        display_name: Human-readable name shown in UIs.
    """

    display_name: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentProfile:
        """Creates an AgentProfile from a dict.

        Args:
            data: Dict with optional ``display_name`` key.

        Returns:
            A populated AgentProfile instance.
        """
        return cls(display_name=data.get("display_name", ""))

    def to_dict(self) -> dict[str, Any]:
        """Serialises the profile to a dict for API requests.

        Returns:
            Dict representation of the profile.
        """
        return {"display_name": self.display_name}


@dataclass
class AgentInstructions:
    """Natural-language instructions that guide agent behaviour.

    Attributes:
        response: Instructions for response generation style and tone.
        orchestration: Instructions for tool selection and planning.
        sample_questions: Example questions users can ask the agent.
    """

    response: str = ""
    orchestration: str = ""
    sample_questions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentInstructions:
        """Creates AgentInstructions from a dict.

        Args:
            data: Dict with optional instruction fields.

        Returns:
            A populated AgentInstructions instance.
        """
        raw_questions = data.get("sample_questions") or []
        questions = [
            q.get("question", q) if isinstance(q, dict) else q
            for q in raw_questions
        ]
        return cls(
            response=data.get("response", ""),
            orchestration=data.get("orchestration", ""),
            sample_questions=questions,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialises instructions to a dict for API requests.

        Returns:
            Dict with non-empty instruction fields only.
        """
        result: dict[str, Any] = {}
        if self.response:
            result["response"] = self.response
        if self.orchestration:
            result["orchestration"] = self.orchestration
        if self.sample_questions:
            result["sample_questions"] = [
                {"question": q} for q in self.sample_questions
            ]
        return result


@dataclass
class BudgetConfig:
    """Budget constraints for agent orchestration.

    If more than one constraint is specified, whichever is first reached
    will end the run.

    Attributes:
        seconds: Maximum time budget in seconds.
        tokens: Maximum token budget for orchestration.
    """

    seconds: int | None = None
    tokens: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BudgetConfig:
        """Creates a BudgetConfig from a dict.

        Args:
            data: Dict with optional ``seconds`` and ``tokens`` keys.

        Returns:
            A populated BudgetConfig instance.
        """
        return cls(seconds=data.get("seconds"), tokens=data.get("tokens"))

    def to_dict(self) -> dict[str, Any]:
        """Serialises the budget config to a dict.

        Returns:
            Dict with non-None budget fields.
        """
        return {k: v for k, v in {"seconds": self.seconds, "tokens": self.tokens}.items() if v is not None}


@dataclass
class OrchestrationConfig:
    """Configuration for the agent's orchestration loop.

    Attributes:
        budget: Optional budget constraints.
    """

    budget: BudgetConfig | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrchestrationConfig:
        """Creates an OrchestrationConfig from a dict.

        Args:
            data: Dict with optional ``budget`` key.

        Returns:
            A populated OrchestrationConfig instance.
        """
        budget_data = data.get("budget")
        return cls(budget=BudgetConfig.from_dict(budget_data) if budget_data else None)

    def to_dict(self) -> dict[str, Any]:
        """Serialises the config to a dict for API requests.

        Returns:
            Dict with non-empty fields only.
        """
        result: dict[str, Any] = {}
        if self.budget:
            result["budget"] = self.budget.to_dict()
        return result


@dataclass
class ModelConfig:
    """Model configuration for an agent.

    Attributes:
        orchestration: Model name for orchestration. Use ``"auto"`` to let
            Snowflake select the best available model.
    """

    orchestration: str = "auto"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelConfig:
        """Creates a ModelConfig from a dict.

        Args:
            data: Dict with optional ``orchestration`` key.

        Returns:
            A populated ModelConfig instance.
        """
        return cls(orchestration=data.get("orchestration", "auto"))

    def to_dict(self) -> dict[str, Any]:
        """Serialises the model config to a dict.

        Returns:
            Dict representation.
        """
        return {"orchestration": self.orchestration}


@dataclass
class ToolSpec:
    """Specification of a tool's type, name, and input schema.

    Attributes:
        type: Tool type (e.g. ``"cortex_analyst_text_to_sql"``,
            ``"cortex_search"``, ``"generic"``).
        name: Unique name for this tool instance.
        description: Human-readable description used by the agent for
            tool selection.
        input_schema: JSON Schema for the tool's input parameters.
            Required for ``"generic"`` tools.
    """

    type: str = ""
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolSpec:
        """Creates a ToolSpec from a dict.

        Args:
            data: Dict with tool spec fields.

        Returns:
            A populated ToolSpec instance.
        """
        return cls(
            type=data.get("type", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            input_schema=data.get("input_schema"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialises the tool spec to a dict.

        Returns:
            Dict with non-empty fields only.
        """
        result: dict[str, Any] = {"type": self.type, "name": self.name}
        if self.description:
            result["description"] = self.description
        if self.input_schema:
            result["input_schema"] = self.input_schema
        return result


@dataclass
class Tool:
    """A tool available to the agent.

    Attributes:
        tool_spec: Specification of the tool.
    """

    tool_spec: ToolSpec = field(default_factory=ToolSpec)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tool:
        """Creates a Tool from a dict.

        Args:
            data: Dict with a ``tool_spec`` key.

        Returns:
            A populated Tool instance.
        """
        return cls(tool_spec=ToolSpec.from_dict(data.get("tool_spec") or {}))

    def to_dict(self) -> dict[str, Any]:
        """Serialises the tool to a dict.

        Returns:
            Dict with ``tool_spec`` key.
        """
        return {"tool_spec": self.tool_spec.to_dict()}


@dataclass
class Agent:
    """A Cortex Agent object.

    Represents the full configuration of a persisted agent.

    Attributes:
        name: Agent name (Snowflake identifier).
        database_name: Database containing the agent.
        schema_name: Schema containing the agent.
        owner: Role that owns the agent.
        comment: Optional comment.
        created_on: ISO 8601 creation timestamp.
        profile: Display profile.
        instructions: Orchestration and response instructions.
        models: Model configuration.
        orchestration: Orchestration budget and settings.
        tools: List of configured tools.
        tool_resources: Dict mapping tool name to resource configuration.
    """

    name: str = ""
    database_name: str = ""
    schema_name: str = ""
    owner: str = ""
    comment: str = ""
    created_on: str = ""
    profile: AgentProfile = field(default_factory=AgentProfile)
    instructions: AgentInstructions = field(default_factory=AgentInstructions)
    models: ModelConfig = field(default_factory=ModelConfig)
    orchestration: OrchestrationConfig = field(default_factory=OrchestrationConfig)
    tools: list[Tool] = field(default_factory=list)
    tool_resources: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Agent:
        """Creates an Agent from an API response dict.

        The API may return tool config as an escaped JSON string in
        ``agent_spec`` for describe responses, or as structured fields
        for list responses.

        Args:
            data: Dict from a describe or list API response.

        Returns:
            A populated Agent instance.
        """
        import json as _json

        # The describe endpoint returns agent_spec as an escaped JSON string.
        spec_raw = data.get("agent_spec")
        spec: dict[str, Any] = {}
        if isinstance(spec_raw, str):
            try:
                spec = _json.loads(spec_raw)
            except _json.JSONDecodeError:
                spec = {}
        elif isinstance(spec_raw, dict):
            spec = spec_raw

        tools_raw = spec.get("tools") or data.get("tools") or []
        tool_resources = spec.get("tool_resources") or data.get("tool_resources") or {}

        instructions_raw = spec.get("instructions") or data.get("instructions") or {}
        models_raw = spec.get("models") or data.get("models") or {}
        orchestration_raw = spec.get("orchestration") or data.get("orchestration") or {}
        profile_raw = data.get("profile") or {}

        return cls(
            name=data.get("name", ""),
            database_name=data.get("database_name", data.get("database", "")),
            schema_name=data.get("schema_name", data.get("schema", "")),
            owner=data.get("owner", ""),
            comment=data.get("comment", ""),
            created_on=str(data.get("created_on", "")),
            profile=AgentProfile.from_dict(profile_raw),
            instructions=AgentInstructions.from_dict(instructions_raw),
            models=ModelConfig.from_dict(models_raw),
            orchestration=OrchestrationConfig.from_dict(orchestration_raw),
            tools=[Tool.from_dict(t) for t in tools_raw],
            tool_resources=tool_resources,
        )
