"""
ChemAgent specialist agents — DefaultPattern multi-agent topology.

Exports:
  create_planner              — coordinator/orchestrator, uses control tools
  create_data_specialist      — PubChem + web search only
  create_computation_specialist — all RDKit computation tools
  create_reviewer             — result validator, no tools
  make_session_context        — factory for per-session ContextVariables
  make_routing_tools          — factory for typed routing tool closures
  submit_plan_for_approval    — HITL control tool (Phase 1 termination)
  finish_workflow             — workflow termination control tool
"""
from app.agents.specialists.planner import create_planner
from app.agents.specialists.data_specialist import create_data_specialist
from app.agents.specialists.computation_specialist import create_computation_specialist
from app.agents.specialists.reviewer import create_reviewer
from app.agents.specialists.context import make_session_context, make_routing_tools
from app.agents.specialists.control_tools import make_submit_plan_for_approval, make_finish_workflow

__all__ = [
    "create_planner",
    "create_data_specialist",
    "create_computation_specialist",
    "create_reviewer",
    "make_session_context",
    "make_routing_tools",
    "make_submit_plan_for_approval",
    "make_finish_workflow",
]
