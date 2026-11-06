"""Tests for Scheme B mass balance auditor and algebraic conservation proofs."""

from __future__ import annotations

import pytest

from subprojects.critical_n.scheme_b.mass_balance import (
    MassBalanceAuditor,
    TOLERANCE_ABSOLUTE_N,
)
from subprojects.critical_n.scheme_b.cropgro_proxy import CropGroSimulationEngine


def test_mass_balance_auditor_exact_algebraic_closure():
    """Verify MassBalanceAuditor computes exact residuals and satisfies conservation tolerance."""
    auditor = MassBalanceAuditor(seed_n_initial=0.50)

    # Day 1: Root uptake of 0.20 g N, organ N increases by 0.20 g N
    entry1 = auditor.audit_step(
        day=1,
        daily_n_uptake=0.20,
        standing_leaf_n=0.35,
        standing_stem_n=0.20,
        standing_root_n=0.15,
        standing_fruit_n=0.00,  # Sum = 0.70
        daily_senesced_leaf_n=0.00,
        daily_harvest_fruit_n=0.00,
        daily_leaked_n=0.00,
    )
    # Total inputs = 0.50 + 0.20 = 0.70; standing = 0.70; residual = 0.0
    assert abs(entry1.n_balance_residual) < 1e-12
    assert entry1.is_n_conserved

    # Day 2: Root uptake 0.10 g N, leaf senescence loss of 0.05 g N, harvest 0.10 g N
    entry2 = auditor.audit_step(
        day=2,
        daily_n_uptake=0.10,
        standing_leaf_n=0.30,   # -0.05
        standing_stem_n=0.20,
        standing_root_n=0.15,
        standing_fruit_n=0.00,  # Sum standing = 0.65
        daily_senesced_leaf_n=0.05,
        daily_harvest_fruit_n=0.10,
        daily_leaked_n=0.00,
    )
    # Total inputs = 0.50 + 0.30 = 0.80
    # Accounted = standing(0.65) + senesced(0.05) + harvest(0.10) = 0.80
    assert abs(entry2.n_balance_residual) < 1e-12
    assert entry2.is_n_conserved
    assert auditor.all_n_conserved
    assert auditor.max_n_residual < 1e-12


def test_mass_balance_closure_across_full_cropgro_simulation():
    """Verify exact nitrogen mass conservation throughout an entire 100-day simulation."""
    # Test both Native and Scheme B across contrasting fertilization regimes
    for mode in ["native", "scheme_b"]:
        for soil_n, fert in [(2.0, 0.02), (10.0, 0.20), (35.0, 0.60)]:
            engine = CropGroSimulationEngine(mode=mode)
            records = engine.run_simulation(
                duration_days=100,
                initial_soil_n=soil_n,
                daily_n_fertilizer=fert,
                harvest_days=[40, 60, 80, 95],
            )

            # Assert every single day maintained machine-precision residual
            max_res = max(abs(r.n_balance_residual) for r in records)
            assert max_res < 1e-10, (
                f"Mode {mode} (soil_n={soil_n}, fert={fert}) violated N conservation: "
                f"max residual = {max_res}"
            )


def test_governor_action_preserves_nitrogen_closure():
    """Formal test proving that when the governor suppresses leaf senescence, N mass is preserved."""
    # Run under extreme N deficit where governor strongly suppresses defoliation
    engine_b = CropGroSimulationEngine(mode="scheme_b", senrte=2.2)
    records = engine_b.run_simulation(
        duration_days=80,
        initial_soil_n=3.0,
        daily_n_fertilizer=0.01,
        harvest_days=[45, 65],
    )

    # Verify that governor suppressed defoliation
    total_suppressed = sum(max(0.0, r.native_lfsen - r.governed_lfsen) for r in records)
    assert total_suppressed > 0.0, "Governor must have suppressed some defoliation"

    # And verify that N mass balance is STILL closed to 1e-12!
    for r in records:
        assert abs(r.n_balance_residual) < 1e-10
