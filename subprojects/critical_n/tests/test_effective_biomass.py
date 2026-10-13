"""Unit tests for cumulative effective biomass and sawtooth jump elimination."""

import pytest

from subprojects.critical_n.core.dilution_curve import SENTINEL_VALUE
from subprojects.critical_n.core.effective_biomass import (
    CumulativeStateTracker,
    actual_cumulative_n_conc,
    effective_biomass,
    verify_sawtooth_elimination,
)


def test_effective_biomass_additive():
    """Verify W_eff = (CWAD + CUMHARVEST) / 1000.0."""
    # 2000 kg standing, 500 kg harvested fruit -> 2.5 t DM/ha
    assert effective_biomass(2000.0, 500.0) == pytest.approx(2.5, rel=1e-5)
    # Zero standing, zero harvest -> 0.0
    assert effective_biomass(0.0, 0.0) == 0.0


def test_actual_cumulative_n_conc_calculation():
    """Verify N_act,cum = 100 * (CNAD + CUMHARVEST_N) / (CWAD + CUMHARVEST)."""
    # 2000 kg DM + 500 kg DM = 2500 kg DM. Total N = 80 + 10 = 90 kg N.
    # 90 / 2500 * 100 = 3.6%
    val = actual_cumulative_n_conc(
        cwad=2000.0, cnad=80.0, cum_harvest_dm=500.0, cum_harvest_n=10.0
    )
    assert val == pytest.approx(3.6, rel=1e-5)

    # With chpdtn explicitly supplied
    val_explicit = actual_cumulative_n_conc(
        cwad=2000.0, cnad=80.0, cum_harvest_dm=500.0, chpdtn=10.0
    )
    assert val_explicit == pytest.approx(3.6, rel=1e-5)

    # Pre-emergence (< 50 kg/ha DM) returns sentinel
    sentinel_val = actual_cumulative_n_conc(cwad=10.0, cnad=0.4)
    assert sentinel_val == SENTINEL_VALUE

    # NaN returns sentinel
    assert actual_cumulative_n_conc(cwad=float("nan"), cnad=10.0) == SENTINEL_VALUE
    assert actual_cumulative_n_conc(cwad=100.0, cnad=float("nan")) == SENTINEL_VALUE
    assert actual_cumulative_n_conc(cwad=100.0, cnad=1.0, chpdtn=float("nan")) == SENTINEL_VALUE


def test_sawtooth_elimination_across_empirical_harvest():
    """Verify that cumulative formulation eliminates harvest jumps in W_eff, Nc, and NNI."""
    # Empirical numbers from tomato/eggplant multi-harvest:
    # Pre-harvest: CWAD = 3802 kg/ha, CNAD = 173.6 kg N/ha
    # Harvest: 563 kg/ha fruit removed, 10 kg N/ha removed
    # Post-harvest: CWAD = 3239 kg/ha, CNAD = 163.6 kg N/ha
    res = verify_sawtooth_elimination(
        pre_harvest_cwad=3802.0,
        pre_harvest_cnad=173.6,
        fruit_dm=563.0,
        fruit_n=10.0,
        post_harvest_cwad=3239.0,
        post_harvest_cnad=163.6,
    )

    # 1. Standing raw metrics suffer large jump:
    assert res["standing_delta_w"] < -0.5  # Biomass drops by > 0.5 t/ha
    assert res["standing_delta_nni"] > 0.05  # NNI falsely jumps by > 0.05!

    # 2. Cumulative effective metrics are strictly continuous:
    assert abs(res["cum_delta_w"]) < 1e-9
    assert abs(res["cum_delta_n_act"]) < 1e-9
    assert abs(res["cum_delta_nc"]) < 1e-9
    assert abs(res["cum_delta_nni"]) < 1e-9


def test_cumulative_state_tracker_multi_step():
    """Verify state tracker behavior over sequential growth and harvest steps."""
    tracker = CumulativeStateTracker(cnc_a=4.85, cnc_b=0.38, cnc_w0=1.0)

    # Step 1: Emergence (small biomass) -> is_valid False, sentinels
    s1 = tracker.step(das=8, cwad=15.0, cnad=0.6)
    assert not s1.is_valid
    assert s1.nni_val == SENTINEL_VALUE

    # Step 2: Vegetative growth
    s2 = tracker.step(das=30, cwad=500.0, cnad=20.0)
    assert s2.is_valid
    assert s2.w_eff == pytest.approx(0.5, rel=1e-5)
    assert s2.nni_val > 0.0

    # Step 3: Day before harvest
    s3 = tracker.step(das=60, cwad=3000.0, cnad=120.0)
    assert s3.w_eff == pytest.approx(3.0, rel=1e-5)

    # Step 4: Harvest day with direct CHPDT=400 kg/ha (standing drops to 2800)
    s4 = tracker.step(das=61, cwad=2800.0, cnad=112.0, direct_chpdt=400.0)
    assert s4.cum_harvest_dm == 400.0
    # Effective biomass remains smooth: 2800 + 400 = 3200 kg/ha = 3.2 t/ha
    assert s4.w_eff == pytest.approx(3.2, rel=1e-5)
    assert s4.w_eff > s3.w_eff, "Cumulative effective biomass must grow monotonically"

    # Step 5: Reset for new treatment
    tracker.reset()
    assert tracker.cum_harvest_dm == 0.0
    assert tracker.cum_harvest_n == 0.0


def test_tracker_preserves_zero_harvest_during_vegetative_drop():
    """Verify that when direct_chpdt=0 is explicitly supplied, vegetative leaf drop does not create false harvest."""
    tracker = CumulativeStateTracker(cnc_a=4.85, cnc_b=0.38, cnc_w0=1.0)
    # Day 20: 500 kg/ha, no harvest
    s1 = tracker.step(das=20, cwad=500.0, cnad=20.0, direct_chpdt=0.0)
    assert s1.cum_harvest_dm == 0.0
    assert s1.cum_harvest_n == 0.0

    # Day 21: Leaf drop causes CWAD to drop to 450 kg/ha, but direct_chpdt is still 0.0
    s2 = tracker.step(das=21, cwad=450.0, cnad=18.0, direct_chpdt=0.0)
    assert s2.cum_harvest_dm == 0.0
    assert s2.cum_harvest_n == 0.0
    assert s2.w_eff == pytest.approx(0.45, rel=1e-5)


def test_explicit_chpdtn_strict_continuity_at_harvest():
    """Verify Delta W_eff == 0, Delta N_act,cum == 0, Delta NNI_cum == 0 at harvest day."""
    tracker = CumulativeStateTracker(cnc_a=4.85, cnc_b=0.38, cnc_w0=1.0, cnc_nc_inf=1.70)

    # Pre-harvest state: standing canopy has 3800 kg DM/ha, 170 kg N/ha
    s_pre = tracker.step(das=70, cwad=3800.0, cnad=170.0, direct_chpdt=0.0, direct_chpdtn=0.0)
    assert s_pre.chpdtn == 0.0

    # Harvest event on day 71: 600 kg DM mature fruit removed containing 12.0 kg N
    # Standing canopy drops to: CWAD = 3200 kg DM/ha, CNAD = 158.0 kg N/ha
    # Cumulative harvested amounts: direct_chpdt = 600.0 kg/ha, direct_chpdtn = 12.0 kg N/ha
    s_post = tracker.step(das=71, cwad=3200.0, cnad=158.0, direct_chpdt=600.0, direct_chpdtn=12.0)
    assert s_post.chpdtn == 12.0

    # 1. Delta W_eff must be strictly 0
    delta_w_eff = s_post.w_eff - s_pre.w_eff
    assert abs(delta_w_eff) < 1e-12, f"Delta W_eff must be 0, got {delta_w_eff}"

    # 2. Delta N_act,cum must be strictly 0
    delta_n_act = s_post.n_act_cum - s_pre.n_act_cum
    assert abs(delta_n_act) < 1e-12, f"Delta N_act,cum must be 0, got {delta_n_act}"

    # 3. Delta NNI_cum must be strictly 0
    delta_nni = s_post.nni_val - s_pre.nni_val
    assert abs(delta_nni) < 1e-12, f"Delta NNI_cum must be 0, got {delta_nni}"
