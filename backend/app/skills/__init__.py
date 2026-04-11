"""
app.skills — top-level skills capability for ChemAgent.

Public API is in ``app.skills.manager``.
"""

from app.skills.manager import load_required_skill_markdown  # noqa: F401

__all__ = ["load_required_skill_markdown"]
