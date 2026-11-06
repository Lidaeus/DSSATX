"""Direct DSSAT water--nitrogen management optimisation for greenhouse eggplant.

Two tracks:

* v1 DEMO (single-year, LHS-as-result): :mod:`src.management.core`,
  :mod:`src.management.batch_search`, :mod:`src.management.report`.
* v2 formal (two-spring robust NSGA-III): :mod:`src.management.formal_design`
  (config + gates + aggregation), :mod:`src.management.dap_policy` (DAP-based
  policy materialiser), :mod:`src.management.nsga3_search` (LHS seeding +
  NSGA-III), :mod:`src.management.robust_orchestrator` (two-year DSSAT loop +
  parameter science gate).
"""

from .dap_policy import (
    CalendarStage,
    CandidatePolicy,
    DapStage,
    HardConstraints,
    build_calendar_stages,
    load_dap_stages,
    materialize_dap_scenario,
    read_final_chfpw,
)
from .formal_design import (
    FormalManagementDesign,
    SpringSeason,
    aggregate_policy_evidence,
    load_formal_design,
)
from .nsga3_search import (
    DecisionBounds,
    TwoYearRobustProblem,
    build_nsga3,
    decode_to_candidate,
    evaluate_objectives,
    maximin_lhs_initial_population,
)
from .robust_orchestrator import (
    evaluate_policy_two_years,
    run_formal_nsga3,
)

__all__ = [
    # formal design contract
    "FormalManagementDesign",
    "SpringSeason",
    "aggregate_policy_evidence",
    "load_formal_design",
    # DAP policy
    "CalendarStage",
    "CandidatePolicy",
    "DapStage",
    "HardConstraints",
    "build_calendar_stages",
    "load_dap_stages",
    "materialize_dap_scenario",
    "read_final_chfpw",
    # NSGA-III search
    "DecisionBounds",
    "TwoYearRobustProblem",
    "build_nsga3",
    "decode_to_candidate",
    "evaluate_objectives",
    "maximin_lhs_initial_population",
    # orchestration
    "evaluate_policy_two_years",
    "run_formal_nsga3",
]
