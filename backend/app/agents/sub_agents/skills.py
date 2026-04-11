"""
Backward-compatibility shim.

Skills logic has been promoted to the top-level ``app.skills`` package.
New code should import from ``app.skills.manager`` directly.
"""

from app.skills.manager import load_required_skill_markdown  # noqa: F401

__all__ = ["load_required_skill_markdown"]
