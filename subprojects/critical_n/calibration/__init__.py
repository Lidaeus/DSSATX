"""Calibration extensions, invariant protocols, and runner adapters."""

from subprojects.critical_n.calibration.bounds_protocol import (
    CNC_FROZEN_INVARIANTS,
    CNC_PARAMETER_GROUP,
    CNC_PHYSICAL_BOUNDS,
    InvariantViolationError,
    create_frozen_cnc_records,
    register_cnc_into_param_registry,
    validate_no_active_cnc_params,
)
from subprojects.critical_n.calibration.cnc_builder import (
    STANDARD_TARGET_NNI,
    attach_cnc_to_pst,
    build_cnc_observation_targets,
    select_phenological_subsampling_dates,
)
from subprojects.critical_n.calibration.runner_adapter import (
    post_process_dssat_cnc,
    wrap_dssat_execution,
)

__all__ = [
    "CNC_PHYSICAL_BOUNDS",
    "CNC_FROZEN_INVARIANTS",
    "CNC_PARAMETER_GROUP",
    "InvariantViolationError",
    "validate_no_active_cnc_params",
    "create_frozen_cnc_records",
    "register_cnc_into_param_registry",
    "STANDARD_TARGET_NNI",
    "select_phenological_subsampling_dates",
    "build_cnc_observation_targets",
    "attach_cnc_to_pst",
    "post_process_dssat_cnc",
    "wrap_dssat_execution",
]
