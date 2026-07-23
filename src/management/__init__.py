"""Direct DSSAT water--nitrogen management optimisation for greenhouse eggplant."""

from .formal_design import (
    FormalManagementDesign,
    SpringSeason,
    aggregate_policy_evidence,
    load_formal_design,
)

__all__ = [
    "FormalManagementDesign",
    "SpringSeason",
    "aggregate_policy_evidence",
    "load_formal_design",
]
