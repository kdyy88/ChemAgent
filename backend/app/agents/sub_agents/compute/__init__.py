"""
Compute sub-agent — heavy computation execution engine.

Responsibilities:
- 3D conformer generation
- PDBQT/docking preparation
- Partial charge calculation
- Batch descriptor computation
- Format conversions with large outputs

Tool permission: ToolPermission.COMPUTE (full tool access).
Designed for long-running tasks that may be offloaded to the ARQ worker.
"""
from __future__ import annotations
