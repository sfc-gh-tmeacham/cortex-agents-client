"""Normalisation for agent:run ``variables`` (multi-tenancy session attributes).

Cortex Agents sets each variable as a session attribute before running any
generated SQL, so row access policies can read it with
``SYS_CONTEXT('SNOWFLAKE$SESSION_ATTRIBUTES', '<name>')``. See
https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-multi-tenancy
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def _infer_type(name: str, value: Any) -> str:
    """Returns the REST ``type`` string for a scalar variable value."""
    # bool is a subclass of int, so check it first.
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    raise ValueError(
        f"Variable {name!r} has unsupported value type "
        f"{type(value).__name__}; use str, int, float or bool."
    )


def _check_value(name: str, value: Any) -> None:
    """Rejects values that cannot be sent as a JSON scalar."""
    if value is None:
        raise ValueError(f"Variable {name!r} has no value.")
    if isinstance(value, float) and not math.isfinite(value):
        # NaN and infinity are not valid JSON numbers.
        raise ValueError(f"Variable {name!r} must be a finite number.")
    _infer_type(name, value)


def normalize_variables(
    variables: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]] | None:
    """Converts caller-supplied variables to the agent:run REST shape.

    Each entry may be a bare scalar (shorthand) or a dict in the REST shape
    with a ``value`` key. Both forms default ``is_immutable_session_attribute``
    to ``True`` so generated SQL cannot change a tenant attribute; pass
    ``False`` explicitly in the dict form to opt out. A missing ``type`` is
    inferred from the value.

    Args:
        variables: Mapping of variable name to a scalar or a REST-shape dict,
            or ``None``.

    Returns:
        A new dict in the REST shape, or ``None`` when *variables* is ``None``
        or empty. The input is not mutated.

    Raises:
        ValueError: If *variables* is not a mapping, or on an empty or
            non-string name, a ``None`` value, a non-finite float, a dict
            without ``value``, or an unsupported value type.
    """
    if variables is None:
        return None
    if not isinstance(variables, Mapping):
        raise ValueError(
            f"variables must be a mapping, got {type(variables).__name__}."
        )
    if not variables:
        return None
    result: dict[str, dict[str, Any]] = {}
    for name, spec in variables.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"Variable names must be non-empty strings, got {name!r}.")
        if isinstance(spec, Mapping):
            if "value" not in spec:
                raise ValueError(f"Variable {name!r} dict must include a 'value' key.")
            entry = dict(spec)
            _check_value(name, entry["value"])
            if "type" not in entry:
                entry["type"] = _infer_type(name, entry["value"])
            entry.setdefault("is_immutable_session_attribute", True)
        else:
            _check_value(name, spec)
            entry = {
                "value": spec,
                "type": _infer_type(name, spec),
                "is_immutable_session_attribute": True,
            }
        result[name] = entry
    return result
