"""Live tests: multi-tenancy session attributes (``variables``).

Requires ``LIVE_AGENT_MULTITENANCY`` and the objects from
``tests/live/seed/07_multitenancy.sql``: a table whose rows are filtered by a
row access policy reading the ``region`` session attribute, a semantic view
over it, and an agent that answers from the view.

Each test asks for revenue by region and reads the region names out of the
returned table rows, not the assistant's prose, because only the rows prove
what the policy let through. The fixed data totals North 300 and South 700.

Skipped automatically if ``LIVE_AGENT_MULTITENANCY`` is not set.
"""
from __future__ import annotations

import time

import pytest

from streamlit_cortex_agents.client.core import CortexAgentsClient, Thread
from streamlit_cortex_agents.client.models.events import SSEEvent, TableEvent

_QUERY = "What is the total revenue by region?"
_REGIONS = {"North", "South", "East", "West"}


def _regions_in(events: list[SSEEvent]) -> set[str]:
    """Returns the region names present in returned table rows.

    Args:
        events: Events yielded by a run.

    Returns:
        Set of region names found in any ``TableEvent`` result set. Empty when
        the policy let no rows through.
    """
    found: set[str] = set()
    for event in events:
        if isinstance(event, TableEvent):
            for row in event.result_set.get("data", []):
                found.update(cell for cell in row if cell in _REGIONS)
    return found


@pytest.mark.live
class TestTenantIsolation:
    """Each tenant sees only its own rows."""

    def test_no_variables_returns_no_rows(
        self,
        live_client: CortexAgentsClient,
        agent_path_multitenancy: str,
    ) -> None:
        """Omitting variables must fail closed, not return every tenant's rows."""
        events = list(live_client.stream(agent_path_multitenancy, _QUERY))
        assert _regions_in(events) == set()

    @pytest.mark.parametrize("region", ["North", "South"])
    def test_tenant_sees_only_own_region(
        self,
        live_client: CortexAgentsClient,
        agent_path_multitenancy: str,
        region: str,
    ) -> None:
        """Shorthand scalar form scopes the run to one region."""
        events = list(
            live_client.stream(
                agent_path_multitenancy, _QUERY, variables={"region": region}
            )
        )
        assert _regions_in(events) == {region}

    def test_full_rest_form_scopes_run(
        self,
        live_client: CortexAgentsClient,
        agent_path_multitenancy: str,
    ) -> None:
        """The explicit REST shape is accepted alongside the shorthand."""
        events = list(
            live_client.stream(
                agent_path_multitenancy,
                _QUERY,
                variables={
                    "region": {
                        "value": "North",
                        "type": "string",
                        "is_immutable_session_attribute": True,
                    }
                },
            )
        )
        assert _regions_in(events) == {"North"}

    def test_numeric_attribute_accepted(
        self,
        live_client: CortexAgentsClient,
        agent_path_multitenancy: str,
    ) -> None:
        """A ``number`` attribute is accepted; the public doc shows only strings."""
        events = list(
            live_client.stream(
                agent_path_multitenancy,
                _QUERY,
                variables={"region": "North", "tenant_num": 7},
            )
        )
        assert _regions_in(events) == {"North"}


@pytest.mark.live
class TestScopePersistsAcrossRequests:
    """Scope holds for every request of a turn, and across a resume."""

    def test_second_turn_on_same_thread_still_scoped(
        self,
        live_thread: Thread,
        agent_path_multitenancy: str,
    ) -> None:
        """A follow-up turn carries its own variables and stays scoped."""
        variables = {"region": "South"}
        list(live_thread.chat(agent_path_multitenancy, _QUERY, variables=variables))
        events = list(
            live_thread.chat(
                agent_path_multitenancy,
                "Show it again, by region.",
                variables=variables,
            )
        )
        assert _regions_in(events) == {"South"}

    def test_background_run_resumed_keeps_scope(
        self,
        live_client: CortexAgentsClient,
        agent_path_multitenancy: str,
    ) -> None:
        """Attributes persist for the interaction, so resume needs no variables.

        ``stream_run`` sends no request body. This test is why the library does
        not take ``variables`` on resume or cancel.
        """
        thread = live_client.create_thread(origin_application="cac_live")
        result = live_client.run(
            agent_path_multitenancy,
            _QUERY,
            thread=thread,
            background=True,
            variables={"region": "North"},
        )
        assert result.run_id, f"no run_id (status={result.status!r})"
        time.sleep(2)
        events = list(live_client.stream_run(result.run_id))
        assert _regions_in(events) == {"North"}
