from __future__ import annotations

from typing import Literal

CHEM_TIER_METADATA_KEY = "chem_tier"
CHEM_TIMEOUT_METADATA_KEY = "chem_timeout_seconds"
CHEM_ROUTE_HINT_METADATA_KEY = "chem_route_hint"

ChemToolTier = Literal["L1", "L2"]