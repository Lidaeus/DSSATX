"""Tests for Scheme B simulation adapter and comparative multi-treatment evaluation."""

from __future__ import annotations

import math
import pandas as pd
import pytest

from subprojects.critical_n.scheme_b.adapter import (
    SchemeBAdapter,
    DEFAULT_TREATMENT_N_LEVELS,
)
from subprojects.critical_n.scheme_b.acclimation import AcclimationType


def test_scheme_b_adapter_single_treatment_comparison():
    """Verify single treatment comparison between Native and Scheme B."""
    adapter = SchemeBAdapter()
    metrics, recs_nat, recs_b = adapter.run_treatment_comparison(
        treatment_id="N0_test",
        initial_soil_n=2.0,
        daily_n_fertilizer=0.01,
        duration_days=60,
    )

    assert len(recs_nat) == 60
    assert len(recs_b) == 60
    assert metrics.treatment_id == "N0_test"
    assert metrics.mass_balance_verified
    assert metrics.scheme_b_max_n_residual < 1e-10

    # Governor must suppress defoliation under severe N stress
    assert metrics.total_suppressed_defoliation > 0.0


def test_scheme_b_adapter_all_treatments_and_dataframe_export():
    """Verify execution across all default treatments and DataFrame generation."""
    adapter = SchemeBAdapter(acclimation_type=AcclimationType.SIGMOID)
    results = adapter.run_all_treatments(duration_days=50)

    assert len(results) == len(DEFAULT_TREATMENT_N_LEVELS)
    for trt_id, (metrics, recs_nat, recs_b) in results.items():
        assert metrics.mass_balance_verified
        assert len(recs_nat) == 50
        assert len(recs_b) == 50

    # Test DataFrame conversion
    df = adapter.build_comparison_dataframe(results)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 50 * 2 * len(DEFAULT_TREATMENT_N_LEVELS)

    expected_cols = [
        "treatment",
        "model_variant",
        "dap",
        "lai",
        "wtlf",
        "cwad",
        "w_eff",
        "pcnl",
        "nc",
        "nni",
        "pg",
        "wldotn",
        "lfsen",
        "avalanche_flag",
        "cum_harvest_dry",
        "n_balance_residual",
    ]
    for col in expected_cols:
        assert col in df.columns

    # Verify both variants are present
    variants = set(df["model_variant"].unique())
    assert variants == {"Native_CROPGRO", "Scheme_B_Coupled"}


def test_scheme_b_acclimation_functional_types():
    """Verify simulation adapter works with Hill and Michaelis-Menten functional types."""
    for ftype in [AcclimationType.HILL, AcclimationType.MICHAELIS_MENTEN]:
        adapter = SchemeBAdapter(acclimation_type=ftype)
        metrics, _, recs_b = adapter.run_treatment_comparison(
            treatment_id=f"test_{ftype.value}",
            initial_soil_n=10.0,
            daily_n_fertilizer=0.20,
            duration_days=40,
        )
        assert metrics.mass_balance_verified
        assert len(recs_b) == 40


def test_scheme_b_simulation_adversarial_stress():
    """Verify Scheme B stability under extreme zero-N starvation and extreme luxury excess."""
    adapter = SchemeBAdapter()

    # 1. Zero-N complete starvation
    metrics_starve, recs_nat_s, recs_b_s = adapter.run_treatment_comparison(
        treatment_id="extreme_starvation",
        initial_soil_n=0.0,
        daily_n_fertilizer=0.0,
        duration_days=50,
    )
    assert metrics_starve.mass_balance_verified
    assert metrics_starve.scheme_b_max_n_residual < 1e-10
    # Canopy must not collapse to NaN or zero
    assert recs_b_s[-1].lai > 0.0
    assert not any(math.isnan(r.lai) for r in recs_b_s)
    assert not any(math.isnan(r.pg) for r in recs_b_s)

    # 2. Extreme luxury excess (100 g N/m^2 initial + 5 g N/d)
    metrics_excess, _, recs_b_e = adapter.run_treatment_comparison(
        treatment_id="extreme_excess",
        initial_soil_n=100.0,
        daily_n_fertilizer=5.0,
        duration_days=50,
    )
    assert metrics_excess.mass_balance_verified
    assert metrics_excess.scheme_b_max_n_residual < 1e-10
    # Peak LAI must be bounded and not explode to infinity
    assert recs_b_e[-1].lai < 50.0
    assert not any(math.isinf(r.lai) for r in recs_b_e)

