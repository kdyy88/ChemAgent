"""
Plan sub-agent — pipeline architect with HITL support.

Responsibilities:
- Complex multi-step task decomposition
- Human-in-the-loop clarification gates
- Plan revision on partial failures
- Dependency ordering between sub-tasks

Uses tool_ask_human for clarification gates and tool_update_task_status
for plan tracking.  Supports LangGraph interrupt() for HITL suspension.
"""
from __future__ import annotations
