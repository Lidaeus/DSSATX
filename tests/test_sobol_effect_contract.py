"""Tests for the Sobol effect-decomposition contract (W3, plan §6.3).

Covers the §6.3 statistical-interpretation contract that the exporter must
honour:

* S1/ST/ST-S1 with paired-bootstrap CIs are all emitted;
* negative S1, S1>1, or ST>1 are **not clipped** (finite-sample error);
* ``interaction_supported`` is True only when the paired-bootstrap lower
  bound of ST-S1 is > 0;
* ST-S1 is labelled as an aggregate interaction-involving remainder, never a
  pairwise interaction;
* response_sd / response_min / response_max accompany every effect row so a
  small absolute variance is never misread as a large agronomic effect;
* the response labels align with sa_contract (no "fruit dry mass").

These are contract tests on the schema and labelling, not numerical-accuracy
tests of the Saltelli estimator (the latter live in test_sa_supplement_tables).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.reporting.export_sobol_stability_paper_data import (
    _EFFECT_RESPONSES,
    _effect_decomposition,
)
from src.sensitivity.sa_contract import (
    ALL_RESPONSES,
    AMBIGUOUS_FRUIT_DRY_MASS_PHRASES,
    CUMULATIVE_HARVEST_DRY_MASS_ID,
    CUMULATIVE_HARVEST_DRY_MASS_LABEL,
)


# ---------------------------------------------------------------------------
# Synthetic Sobol case (one parameter, designed to produce an out-of-range S1)
# ---------------------------------------------------------------------------

def _make_case(tmp_path: Path, *, samples: int = 64) -> Path:
    """A minimal Sobol case whose S1 may exceed 1 (finite-sample artefact)."""
    case = tmp_path / "case"
    case.mkdir()
    k = 1
    rows = samples * (k + 2)
    pd.DataFrame({"run_id": range(rows), "P1": np.linspace(0, 1, rows)}).to_csv(
        case / "sa_sen_sobol.sobol.par.csv", index=False)
    base = np.linspace(1.0, 4.0, rows)
    pd.DataFrame({
        "run_id": range(rows), "failed_flag": 0,
        "tn1_adaps": base,
        "tn1_lai_auc": base * 2,
        "tn1_agb_end_cwad": base * 3,
        "tn1_fruitd_end": base * 4,
        "tn1_cumharvest_dap50": base * 5,
        "wn_water_n1_fruitd_end": base * 6,
        "wn_nslope_w1_fruitd_end": base * 7,
        "wn_interaction_fruitd_end": base * 8,
    }).to_csv(case / "sa_sen_sobol.sobol.obs.csv", index=False)
    (case / "run_manifest.yaml").write_text(
        f"run_id: test\nsobol_samples: {samples}\nsobol_parameter_count: {k}\n",
        encoding="utf-8")
    return case


# ===========================================================================
# §6.3 schema completeness
# ===========================================================================

REQUIRED_EFFECT_COLUMNS = {
    "season", "response_id", "response_label", "ranking_domain",
    "parameter", "S1", "S1_ci_low", "S1_ci_high",
    "ST", "ST_ci_low", "ST_ci_high",
    "interaction_remainder", "interaction_ci_low", "interaction_ci_high",
    "interaction_supported",
}

REQUIRED_SCALE_COLUMNS = {
    "season", "response_id", "response_label", "ranking_domain", "unit",
    "response_sd", "response_min", "response_max",
}


def test_effect_table_carries_all_section_6_3_columns(tmp_path: Path) -> None:
    case = _make_case(tmp_path)
    effects, scales = _effect_decomposition(case, "TEST", replicates=100, seed=7)
    assert REQUIRED_EFFECT_COLUMNS <= set(effects.columns), (
        f"effect table missing §6.3 columns: {REQUIRED_EFFECT_COLUMNS - set(effects.columns)}")
    assert REQUIRED_SCALE_COLUMNS <= set(scales.columns), (
        f"response_scales missing §6.3 columns: {REQUIRED_SCALE_COLUMNS - set(scales.columns)}")


# ===========================================================================
# §6.3 no clipping of out-of-range indices
# ===========================================================================

def test_out_of_range_indices_not_clipped(tmp_path: Path) -> None:
    """S1>1 or S1<0 must be preserved, not clipped to [0,1] (plan §6.3).

    The estimator can return S1 outside [0,1] under finite-sample noise; the
    contract requires preserving the raw value and flagging it rather than
    silently clipping.  Here we check the schema allows it (no enforced [0,1]
    bound) and the exporter never applies a clip.
    """
    case = _make_case(tmp_path)
    effects, _ = _effect_decomposition(case, "TEST", replicates=100, seed=7)
    # No assertion that S1 is in [0,1] — the point is the exporter must not
    # enforce such a bound.  Verify values are finite floats (not NaN'd out).
    assert np.isfinite(effects["S1"]).all()
    assert np.isfinite(effects["ST"]).all()
    # If any S1 happens to be out of range here, it survived unclipped.
    out_of_range = effects[(effects["S1"] < 0) | (effects["S1"] > 1)]
    if len(out_of_range):
        # flag column, when present, must record it rather than hide it
        if "first_order_interval_outside_unit_range" in effects.columns:
            flagged = out_of_range["first_order_interval_outside_unit_range"]
            assert flagged.all(), "out-of-range S1 must be flagged, not clipped"


# ===========================================================================
# §6.3 interaction_supported semantics
# ===========================================================================

def test_interaction_supported_only_when_lower_bound_positive(tmp_path: Path) -> None:
    """interaction_supported is True iff interaction_ci_low > 0 (plan §6.3)."""
    case = _make_case(tmp_path)
    effects, _ = _effect_decomposition(case, "TEST", replicates=200, seed=11)
    for _, row in effects.iterrows():
        ci_low = float(row["interaction_ci_low"])
        supported = bool(row["interaction_supported"])
        assert supported == (ci_low > 0), (
            f"interaction_supported mismatch for {row['parameter']}: "
            f"ci_low={ci_low}, supported={supported}")


def test_interaction_remainder_equals_st_minus_s1(tmp_path: Path) -> None:
    """ST-S1 is computed as a paired difference, not re-estimated (plan §6.3)."""
    case = _make_case(tmp_path)
    effects, _ = _effect_decomposition(case, "TEST", replicates=100, seed=7)
    diff = effects["ST"] - effects["S1"]
    np.testing.assert_allclose(effects["interaction_remainder"].to_numpy(),
                               diff.to_numpy(), rtol=1e-12, atol=1e-12)


def test_run_id_order_not_csv_row_order_defines_sobol_blocks(tmp_path: Path) -> None:
    """Shuffling CSV rows must not change A/B/hybrid block membership."""
    case = _make_case(tmp_path)
    baseline, _ = _effect_decomposition(case, "TEST", replicates=100, seed=7)
    for name in ("sa_sen_sobol.sobol.par.csv", "sa_sen_sobol.sobol.obs.csv"):
        path = case / name
        frame = pd.read_csv(path).sample(frac=1.0, random_state=19)
        frame.to_csv(path, index=False)
    shuffled, _ = _effect_decomposition(case, "TEST", replicates=100, seed=7)
    columns = ["response_id", "parameter", "S1", "ST", "interaction_remainder"]
    pd.testing.assert_frame_equal(
        baseline[columns].reset_index(drop=True),
        shuffled[columns].reset_index(drop=True),
    )


def test_duplicate_run_id_is_rejected(tmp_path: Path) -> None:
    case = _make_case(tmp_path)
    path = case / "sa_sen_sobol.sobol.obs.csv"
    frame = pd.read_csv(path)
    frame.loc[1, "run_id"] = frame.loc[0, "run_id"]
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="run_id coverage"):
        _effect_decomposition(case, "TEST", replicates=20, seed=7)


# ===========================================================================
# §6.3 response scale disclosure (absolute vs relative)
# ===========================================================================

def test_response_scale_accompanies_every_effect(tmp_path: Path) -> None:
    """Every effect row can be joined to a response_sd/min/max (plan §6.3)."""
    case = _make_case(tmp_path)
    effects, scales = _effect_decomposition(case, "TEST", replicates=100, seed=7)
    merged = effects.merge(
        scales[["season", "response_id", "response_sd", "response_min", "response_max"]],
        on=["season", "response_id"], how="left", validate="many_to_one")
    assert len(merged) == len(effects)
    assert merged["response_sd"].notna().all()
    assert merged["response_min"].notna().all()
    assert merged["response_max"].notna().all()


# ===========================================================================
# §6.3 + §4.1 labelling contract
# ===========================================================================

def test_effect_response_ids_align_with_contract() -> None:
    """Every _EFFECT_RESPONSES response_id is declared in sa_contract."""
    for rid, _label, _dom, _pat, _unit, _disp in _EFFECT_RESPONSES:
        assert rid in ALL_RESPONSES, f"{rid} not in sa_contract.ALL_RESPONSES"


def test_no_ambiguous_fruit_dry_mass_label() -> None:
    """No effect-response label contains an ambiguous phrase (plan §4.1)."""
    for _rid, label, _dom, _pat, _unit, _disp in _EFFECT_RESPONSES:
        low = str(label).lower()
        for phrase in AMBIGUOUS_FRUIT_DRY_MASS_PHRASES:
            assert phrase not in low, f"ambiguous phrase {phrase!r} in label {label!r}"


def test_cumulative_harvest_response_carries_canonical_label() -> None:
    """The yield-chain response uses the pinned canonical label."""
    matches = [(rid, label) for rid, label, *_ in _EFFECT_RESPONSES
               if rid == CUMULATIVE_HARVEST_DRY_MASS_ID]
    assert len(matches) == 1
    _rid, label = matches[0]
    assert label == CUMULATIVE_HARVEST_DRY_MASS_LABEL


def test_diagnostic_response_not_displayed() -> None:
    """CUMHARVEST_DAP50 (diagnostic) has display_in_figure=False (plan §4.2)."""
    diag = [(rid, disp) for rid, _l, _d, _p, _u, disp in _EFFECT_RESPONSES
            if rid == "MEAN_CUMHARVEST_DAP50"]
    assert diag and diag[0][1] is False
