"""Frozen external invariant protocol and parameter boundary enforcement.

Mathematical Theorem (Structural Rank Deficiency Under Co-Calibration):
    CNC parameters (CNC_A, CNC_B, CNC_W0) must NEVER be co-calibrated with
    physiological crop parameters (PROLFI, PGEFF, LFMAX).
    Sensitivity collinearity between CNC_A and PROLFI is r = -0.9948,
    causing condition number explosion kappa(J) ~ 8.77 x 10^16.

Protocol:
    CNC_A (4.85), CNC_B (0.38), and CNC_W0 (1.00) must remain strictly
    frozen external invariants (status: fixed).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd


# Rigid parameter registry definitions
CNC_PHYSICAL_BOUNDS: dict[str, tuple[float, float]] = {
    "CNC_A": (2.0, 8.0),       # Maximum seedling critical N percentage envelope (%)
    "CNC_B": (0.10, 0.70),     # Dilution exponent slope envelope
    "CNC_W0": (0.20, 3.00),    # Canopy closure dry biomass threshold (t DM/ha)
    "CNC_NC_INF": (0.50, 3.00),# Asymptotic lower-bound nitrogen concentration (%)
    "CNC_C_INF": (0.50, 3.00), # Standard alias for CNC_NC_INF
    "CNC_GAMMA": (0.05, 2.50), # Scheme B photosynthetic sensitivity slope
    "CNC_NNIMIN": (0.10, 0.60),# Scheme B minimum photosynthetic floor
}

CNC_FROZEN_INVARIANTS: dict[str, float] = {
    "CNC_A": 4.85,
    "CNC_B": 0.38,
    "CNC_W0": 1.00,
    "CNC_NC_INF": 1.70,
    "CNC_C_INF": 1.70,
    "CNC_GAMMA": 0.65,
    "CNC_NNIMIN": 0.30,
}

CNC_PARAMETER_GROUP: str = "cnc_dilution"


class InvariantViolationError(ValueError):
    """Raised when an external invariant parameter is illegally marked active."""
    pass


def validate_no_active_cnc_params(
    bounds_df_or_path: Union[pd.DataFrame, str, Path],
) -> list[str]:
    """Verify that no CNC parameter is marked 'active' in a parameter bounds table.

    Returns list of verified invariant parameter names.
    Raises InvariantViolationError if any CNC parameter is active.
    """
    if isinstance(bounds_df_or_path, (str, Path)):
        df = pd.read_csv(bounds_df_or_path)
    else:
        df = bounds_df_or_path

    if "name" not in df.columns or "status" not in df.columns:
        return []

    cnc_params = set(CNC_PHYSICAL_BOUNDS.keys())
    active_cnc: list[str] = []
    found_invariants: list[str] = []

    for _, row in df.iterrows():
        p_name = str(row["name"]).strip().upper()
        status = str(row["status"]).strip().lower()
        if p_name in cnc_params:
            if status == "active":
                active_cnc.append(p_name)
            else:
                found_invariants.append(p_name)

    if active_cnc:
        raise InvariantViolationError(
            f"CNC parameters {active_cnc} are marked 'active' for calibration! "
            f"Theorem Section 4.1 forbids joint estimation due to collinearity (r = -0.9948, "
            f"kappa ~ 8.77e16). CNC parameters must remain status: fixed."
        )

    return found_invariants


def create_frozen_cnc_records(crop: str = "eggplant") -> list[dict[str, Union[str, float]]]:
    """Generate standardized frozen bounds rows for CNC parameters."""
    records = []
    for name, init_val in CNC_FROZEN_INVARIANTS.items():
        phys_lo, phys_hi = CNC_PHYSICAL_BOUNDS[name]
        records.append(
            {
                "name": name,
                "init": init_val,
                "lower": phys_lo,
                "upper": phys_hi,
                "status": "fixed",
                "pargp": CNC_PARAMETER_GROUP,
                "location": "SPE",
                "file": "TMGRO048.SPE.base",
                "cultivar": "TM0008",
                "ecotype": "TM0001",
                "mode": "both",
            }
        )
    return records


def register_cnc_into_param_registry() -> bool:
    """Optionally register CNC physical bounds into src.common.param_registry.

    Safe, non-destructive runtime injection if param_registry is imported.
    """
    try:
        from src.common import param_registry
        for k, v in CNC_PHYSICAL_BOUNDS.items():
            if k not in param_registry.PHYSICAL_BOUNDS:
                param_registry.PHYSICAL_BOUNDS[k] = v
        return True
    except (ImportError, AttributeError):
        return False


def unregister_cnc_from_param_registry() -> bool:
    """Revert CNC parameter registration from src.common.param_registry."""
    try:
        from src.common import param_registry
        for k in CNC_PHYSICAL_BOUNDS:
            param_registry.PHYSICAL_BOUNDS.pop(k, None)
        return True
    except (ImportError, AttributeError):
        return False
