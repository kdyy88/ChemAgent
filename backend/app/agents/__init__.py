"""
ChemAgent agent package.

Primary entrypoint: ``create_chem_team(llm_config)``

Returns ``(user_proxy, pattern, ctx, agent_models)`` — a 4-agent DefaultPattern team:

  user_proxy (outside group)
      ↓ a_run_group_chat()
  DefaultPattern
      ├── planner              (coordinator — submit_plan_for_approval / finish_workflow)
      ├── data_specialist      (PubChem + web search, self-executes tools)
      ├── computation_specialist (all RDKit tools, self-executes tools)
      └── reviewer             (quality control, no tools)

Backwards compatibility
───────────────────────
``create_agent_pair`` is kept as a shim; it returns ``(user_proxy, pattern)``
so legacy code that only unpacks two values still works.
"""

from __future__ import annotations

from app.agents.manager import create_chem_team

__all__ = ["create_chem_team", "create_agent_pair"]


def create_agent_pair(
    *,
    model: str | None = None,
    llm_config=None,
) -> tuple:
    """Backwards-compat shim — returns (user_proxy, pattern).

    New code should use ``create_chem_team`` and unpack all four values.
    """
    user_proxy, pattern, _ctx, _agent_models = create_chem_team(
        llm_config=llm_config, model=model
    )
    return user_proxy, pattern
