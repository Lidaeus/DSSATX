"""Scheme B high-level simulation adapter and comparative evaluation driver.

Provides standardized APIs for executing side-by-side simulation experiments
(Native CROPGRO vs. Scheme B Dynamic Photosynthetic Acclimation & Senescence Governor)
across varying nitrogen fertilization levels (N0, N1, N2, N3).
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from subprojects.critical_n.scheme_b.cropgro_proxy import (
    CropGroSimulationEngine,
    SimulationDailyRecord,
)
from subprojects.critical_n.scheme_b.acclimation import (
    AcclimationType,
    DEFAULT_GAMMA,
    DEFAULT_NNI_MIN,
    DEFAULT_S_MAX,
)
from subprojects.critical_n.scheme_b.senescence_limiter import DEFAULT_SENESCENCE_GAMMA


DEFAULT_TREATMENT_N_LEVELS: Dict[str, Dict[str, float]] = {
    "N0_severe_deficit": {
        "initial_soil_n": 2.5,
        "daily_n_fertilizer": 0.02,
    },
    "N1_moderate_deficit": {
        "initial_soil_n": 6.5,
        "daily_n_fertilizer": 0.12,
    },
    "N2_optimal_supply": {
        "initial_soil_n": 15.0,
        "daily_n_fertilizer": 0.28,
    },
    "N3_luxury_excess": {
        "initial_soil_n": 38.0,
        "daily_n_fertilizer": 0.65,
    },
}


@dataclasses.dataclass
class TreatmentComparisonMetrics:
    """Quantitative performance and physiological metrics comparing Native vs Scheme B."""
    treatment_id: str
    # LAI dynamics
    native_final_lai: float
    scheme_b_final_lai: float
    lai_retention_ratio: float           # scheme_b_final_lai / native_final_lai
    native_peak_lai: float
    scheme_b_peak_lai: float
    # Biomass dynamics
    native_final_cwad: float
    scheme_b_final_cwad: float
    native_cum_harvest: float
    scheme_b_cum_harvest: float
    # Senescence & defoliation avalanche
    native_avalanche_days: int           # Count of days where LFSEN > WLDOTN
    scheme_b_avalanche_days: int         # Count of days where LFSEN > WLDOTN after limiter (should be 0)
    total_suppressed_defoliation: float  # Cumulative leaf biomass saved from avalanche (g DM/m^2)
    # Mass conservation verification
    native_max_n_residual: float
    scheme_b_max_n_residual: float
    mass_balance_verified: bool


class SchemeBAdapter:
    """High-level orchestration adapter for Scheme B simulation experiments."""

    def __init__(
        self,
        acclimation_type: AcclimationType = AcclimationType.SIGMOID,
        acclimation_gamma: float = DEFAULT_GAMMA,
        acclimation_min: float = DEFAULT_NNI_MIN,
        acclimation_max: float = DEFAULT_S_MAX,
        senescence_gamma: float = DEFAULT_SENESCENCE_GAMMA,
    ) -> None:
        self.acclimation_type = acclimation_type
        self.acclimation_gamma = acclimation_gamma
        self.acclimation_min = acclimation_min
        self.acclimation_max = acclimation_max
        self.senescence_gamma = senescence_gamma

    def run_treatment_comparison(
        self,
        treatment_id: str,
        initial_soil_n: float,
        daily_n_fertilizer: float,
        duration_days: int = 100,
        harvest_days: Optional[List[int]] = None,
    ) -> Tuple[TreatmentComparisonMetrics, List[SimulationDailyRecord], List[SimulationDailyRecord]]:
        """Run side-by-side Native and Scheme B simulations for a single treatment.

        Returns
        -------
        tuple of (metrics, native_records, scheme_b_records)
        """
        # 1. Native CROPGRO simulation
        engine_native = CropGroSimulationEngine(
            mode="native",
        )
        records_native = engine_native.run_simulation(
            duration_days=duration_days,
            initial_soil_n=initial_soil_n,
            daily_n_fertilizer=daily_n_fertilizer,
            harvest_days=harvest_days,
        )

        # 2. Scheme B simulation
        engine_b = CropGroSimulationEngine(
            mode="scheme_b",
            acclimation_type=self.acclimation_type,
            acclimation_gamma=self.acclimation_gamma,
            acclimation_min=self.acclimation_min,
            acclimation_max=self.acclimation_max,
            senescence_gamma=self.senescence_gamma,
        )
        records_b = engine_b.run_simulation(
            duration_days=duration_days,
            initial_soil_n=initial_soil_n,
            daily_n_fertilizer=daily_n_fertilizer,
            harvest_days=harvest_days,
        )

        # 3. Compute metrics
        native_final = records_native[-1]
        b_final = records_b[-1]

        native_avalanche_days = sum(1 for r in records_native if r.avalanche_flag)
        # For Scheme B, check if governed senescence ever exceeded new leaf growth
        b_avalanche_days = sum(
            1 for r in records_b if (r.governed_lfsen > r.wldotn and r.wldotn > 0.1)
        )
        total_suppressed = sum(
            max(0.0, r.native_lfsen - r.governed_lfsen) for r in records_b
        )

        lai_ratio = (
            b_final.lai / max(0.01, native_final.lai)
            if native_final.lai > 0.0 else 1.0
        )

        native_max_n_res = max(abs(r.n_balance_residual) for r in records_native)
        b_max_n_res = max(abs(r.n_balance_residual) for r in records_b)
        mass_conserved = (native_max_n_res < 1e-4) and (b_max_n_res < 1e-4)

        metrics = TreatmentComparisonMetrics(
            treatment_id=treatment_id,
            native_final_lai=native_final.lai,
            scheme_b_final_lai=b_final.lai,
            lai_retention_ratio=lai_ratio,
            native_peak_lai=max(r.lai for r in records_native),
            scheme_b_peak_lai=max(r.lai for r in records_b),
            native_final_cwad=native_final.cwad,
            scheme_b_final_cwad=b_final.cwad,
            native_cum_harvest=native_final.cum_harvest_dry,
            scheme_b_cum_harvest=b_final.cum_harvest_dry,
            native_avalanche_days=native_avalanche_days,
            scheme_b_avalanche_days=b_avalanche_days,
            total_suppressed_defoliation=total_suppressed,
            native_max_n_residual=native_max_n_res,
            scheme_b_max_n_residual=b_max_n_res,
            mass_balance_verified=mass_conserved,
        )

        return metrics, records_native, records_b

    def run_all_treatments(
        self,
        treatment_profiles: Optional[Dict[str, Dict[str, float]]] = None,
        duration_days: int = 100,
        harvest_days: Optional[List[int]] = None,
    ) -> Dict[str, Tuple[TreatmentComparisonMetrics, List[SimulationDailyRecord], List[SimulationDailyRecord]]]:
        """Execute simulation across all treatment profiles."""
        if treatment_profiles is None:
            treatment_profiles = DEFAULT_TREATMENT_N_LEVELS

        results = {}
        for trt_id, cfg in treatment_profiles.items():
            results[trt_id] = self.run_treatment_comparison(
                treatment_id=trt_id,
                initial_soil_n=cfg["initial_soil_n"],
                daily_n_fertilizer=cfg["daily_n_fertilizer"],
                duration_days=duration_days,
                harvest_days=harvest_days,
            )
        return results

    def build_comparison_dataframe(
        self,
        all_results: Dict[str, Tuple[TreatmentComparisonMetrics, List[SimulationDailyRecord], List[SimulationDailyRecord]]],
    ) -> pd.DataFrame:
        """Construct tidy long-form pandas DataFrame containing daily comparison trajectories."""
        rows = []
        for trt_id, (_, records_nat, records_b) in all_results.items():
            for r in records_nat:
                rows.append({
                    "treatment": trt_id,
                    "model_variant": "Native_CROPGRO",
                    "dap": r.dap,
                    "lai": r.lai,
                    "wtlf": r.wtlf,
                    "cwad": r.cwad,
                    "w_eff": r.w_eff,
                    "pcnl": r.pcnl,
                    "nc": r.nc,
                    "nni": r.nni,
                    "pg": r.pg,
                    "wldotn": r.wldotn,
                    "lfsen": r.governed_lfsen,
                    "avalanche_flag": r.avalanche_flag,
                    "cum_harvest_dry": r.cum_harvest_dry,
                    "n_balance_residual": r.n_balance_residual,
                })
            for r in records_b:
                rows.append({
                    "treatment": trt_id,
                    "model_variant": "Scheme_B_Coupled",
                    "dap": r.dap,
                    "lai": r.lai,
                    "wtlf": r.wtlf,
                    "cwad": r.cwad,
                    "w_eff": r.w_eff,
                    "pcnl": r.pcnl,
                    "nc": r.nc,
                    "nni": r.nni,
                    "pg": r.pg,
                    "wldotn": r.wldotn,
                    "lfsen": r.governed_lfsen,
                    "avalanche_flag": r.avalanche_flag,
                    "cum_harvest_dry": r.cum_harvest_dry,
                    "n_balance_residual": r.n_balance_residual,
                })
        return pd.DataFrame(rows)
