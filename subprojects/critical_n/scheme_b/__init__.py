"""Scheme B package: Dynamic Internal Photosynthetic Acclimation Coupling & Senescence Limiter.

Submodules:
- acclimation: Continuous NNI photosynthetic acclimation coupling (Sigmoid, Hill, Michaelis-Menten)
- senescence_limiter: Senescence rate limiter (LFSEN_actual = min(LFSEN, gamma * WLDOTN), gamma in [0.85, 0.95])
- mass_balance: Carbon and nitrogen mass balance auditing
- cropgro_proxy: Dynamic state-space simulation proxy of CropGro C-N allocation
- adapter: High-level comparative simulation adapter
- patch_manager: Sandboxed Fortran patch validation and application
"""

from subprojects.critical_n.scheme_b.acclimation import (
    AcclimationType,
    bounded_sigmoid_acclimation,
    hill_acclimation,
    michaelis_menten_acclimation,
    compute_nni_from_states,
    couple_photosynthesis,
    DEFAULT_GAMMA,
    DEFAULT_NNI_MIN,
    DEFAULT_S_MAX,
    DEFAULT_HILL_COEF,
    DEFAULT_HILL_K_HALF,
    DEFAULT_MM_KM,
)
from subprojects.critical_n.scheme_b.senescence_limiter import (
    SenescenceGovernor,
    SenescenceGovernanceResult,
    apply_senescence_limiter,
    DEFAULT_SENESCENCE_GAMMA,
)
from subprojects.critical_n.scheme_b.mass_balance import (
    MassBalanceAuditor,
    DailyMassBalanceEntry,
)
from subprojects.critical_n.scheme_b.cropgro_proxy import (
    CropGroSimulationEngine,
    SimulationDailyRecord,
)
from subprojects.critical_n.scheme_b.adapter import (
    SchemeBAdapter,
    TreatmentComparisonMetrics,
)
from subprojects.critical_n.scheme_b.patch_manager import (
    validate_fortran_fixed_format,
    apply_patch_in_sandbox,
)

__all__ = [
    "AcclimationType",
    "bounded_sigmoid_acclimation",
    "hill_acclimation",
    "michaelis_menten_acclimation",
    "compute_nni_from_states",
    "couple_photosynthesis",
    "SenescenceGovernor",
    "SenescenceGovernanceResult",
    "apply_senescence_limiter",
    "MassBalanceAuditor",
    "DailyMassBalanceEntry",
    "CropGroSimulationEngine",
    "SimulationDailyRecord",
    "SchemeBAdapter",
    "TreatmentComparisonMetrics",
    "validate_fortran_fixed_format",
    "apply_patch_in_sandbox",
    "DEFAULT_GAMMA",
    "DEFAULT_NNI_MIN",
    "DEFAULT_S_MAX",
    "DEFAULT_HILL_COEF",
    "DEFAULT_HILL_K_HALF",
    "DEFAULT_MM_KM",
    "DEFAULT_SENESCENCE_GAMMA",
]
