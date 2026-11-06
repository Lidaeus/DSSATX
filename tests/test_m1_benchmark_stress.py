"""
tests/test_m1_benchmark_stress.py
=================================
Empirical challenger stress-test suite for Milestone 1 datasets and loaders.
Audits value bounds, physical/biological constraints, deduplication,
relational integrity, and chronological phenological stage ordering.

Author: Challenger 1 (Milestone 1 Empirical Challenger)
Date: 2026-09-20
"""

import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import torch

BENCHMARK_DIR = Path(__file__).resolve().parent.parent / "data" / "benchmark" / "phenology"


@pytest.fixture(scope="module")
def benchmark_tables():
    """Loads all 4 benchmark tables."""
    return {
        "metadata": pd.read_csv(BENCHMARK_DIR / "treatment_season_metadata.csv"),
        "microclimate": pd.read_csv(BENCHMARK_DIR / "microclimate_daily_series.csv"),
        "targets": pd.read_csv(BENCHMARK_DIR / "phenology_benchmark_targets.csv"),
        "literature": pd.read_csv(BENCHMARK_DIR / "literature_solanaceous_benchmarks.csv"),
    }


def test_files_exist_and_nonempty():
    """Verify that all four required benchmark files exist and are non-empty."""
    required_files = [
        "treatment_season_metadata.csv",
        "microclimate_daily_series.csv",
        "phenology_benchmark_targets.csv",
        "literature_solanaceous_benchmarks.csv",
    ]
    for fname in required_files:
        fpath = BENCHMARK_DIR / fname
        assert fpath.exists(), f"Benchmark file missing: {fpath}"
        assert fpath.stat().st_size > 0, f"Benchmark file empty: {fpath}"


def test_no_duplicate_rows(benchmark_tables):
    """Verify that zero duplicate rows exist in any benchmark CSV table."""
    for name, df in benchmark_tables.items():
        dup_count = df.duplicated().sum()
        assert dup_count == 0, f"Table '{name}' has {dup_count} duplicate rows!"


def test_primary_key_uniqueness(benchmark_tables):
    """Verify that primary and composite business keys are strictly unique."""
    meta = benchmark_tables["metadata"]
    assert meta.duplicated(subset=["season_id", "treatment"]).sum() == 0, "Duplicate (season_id, treatment) in metadata"

    clim = benchmark_tables["microclimate"]
    assert clim.duplicated(subset=["date"]).sum() == 0, "Duplicate date in microclimate"

    targets = benchmark_tables["targets"]
    assert targets.duplicated(subset=["season_id", "treatment", "event_type"]).sum() == 0, (
        "Duplicate (season_id, treatment, event_type) in targets"
    )
    assert targets.duplicated(subset=["season_id", "treatment", "target_stage_index"]).sum() == 0, (
        "Duplicate (season_id, treatment, target_stage_index) in targets"
    )

    lit = benchmark_tables["literature"]
    assert lit.duplicated(subset=["study_id"]).sum() == 0, "Duplicate study_id in literature"


def test_no_nan_or_inf_in_tables(benchmark_tables):
    """Verify that no missing values (NaN) exist in any column across all tables."""
    for name, df in benchmark_tables.items():
        nan_counts = df.isna().sum()
        for col, count in nan_counts.items():
            assert count == 0, f"Table '{name}' column '{col}' contains {count} NaNs!"


def test_microclimate_temporal_continuity(benchmark_tables):
    """Verify that microclimate covers exactly 564 continuous days without gaps."""
    clim = benchmark_tables["microclimate"]
    assert len(clim) == 564, f"Expected 564 days, found {len(clim)}"

    dates = pd.to_datetime(clim["date"])
    diffs = dates.diff().iloc[1:]
    assert (diffs == pd.Timedelta(days=1)).all(), "Microclimate date sequence is not strictly continuous by 1 day!"
    assert clim["date"].iloc[0] == "2025-01-01"
    assert clim["date"].iloc[-1] == "2026-07-18"


def test_microclimate_thermal_bounds(benchmark_tables):
    """Verify Tmin <= Tavg <= Tmax and DIF >= 0 for all 564 days."""
    clim = benchmark_tables["microclimate"]

    # Tmin <= Tavg
    tmin_le_tavg = clim["tmin_c"] <= clim["tavg_c"]
    assert tmin_le_tavg.all(), (
        f"Found {(~tmin_le_tavg).sum()} records where Tmin > Tavg:\n"
        f"{clim[~tmin_le_tavg][['date', 'tmin_c', 'tavg_c', 'tmax_c']]}"
    )

    # Tavg <= Tmax
    tavg_le_tmax = clim["tavg_c"] <= clim["tmax_c"]
    assert tavg_le_tmax.all(), (
        f"Found {(~tavg_le_tmax).sum()} records where Tavg > Tmax:\n"
        f"{clim[~tavg_le_tmax][['date', 'tmin_c', 'tavg_c', 'tmax_c']]}"
    )

    # DIF >= 0
    dif_ge_zero = clim["dif_c"] >= 0.0
    assert dif_ge_zero.all(), (
        f"Found {(~dif_ge_zero).sum()} records where DIF < 0:\n"
        f"{clim[~dif_ge_zero][['date', 'dif_c']]}"
    )

    # DIF == Tmax - Tmin within rounding tolerance (0.01 C)
    expected_dif = clim["tmax_c"] - clim["tmin_c"]
    assert np.isclose(clim["dif_c"], expected_dif, atol=0.02).all(), "DIF does not match Tmax - Tmin!"

    # Tavg == (Tmax + Tmin)/2 within rounding tolerance (0.01 C)
    expected_tavg = (clim["tmax_c"] + clim["tmin_c"]) / 2.0
    assert np.isclose(clim["tavg_c"], expected_tavg, atol=0.02).all(), "Tavg does not match (Tmax + Tmin)/2!"


def test_microclimate_radiation_and_daylength_bounds(benchmark_tables):
    """Verify Daylength in [9.0, 15.0] hr, SRAD >= 0, and CH_10 >= 0."""
    clim = benchmark_tables["microclimate"]

    # Daylength
    dayl = clim["daylength_hr"]
    assert (dayl >= 9.0).all() and (dayl <= 15.0).all(), (
        f"Daylength out of bounds [9.0, 15.0]: min={dayl.min()}, max={dayl.max()}"
    )

    # Solar radiation
    srad = clim["srad_mj_m2"]
    assert (srad >= 0.0).all(), f"Solar radiation contains negative values: min={srad.min()}"

    # Chilling exposure CH_10 = max(0, 10 - Tmin) >= 0
    ch10 = clim["chilling_exposure_10c"]
    assert (ch10 >= 0.0).all(), f"Chilling exposure contains negative values: min={ch10.min()}"
    expected_ch10 = np.maximum(0.0, 10.0 - clim["tmin_c"])
    assert np.isclose(ch10, expected_ch10, atol=0.02).all(), "CH_10 does not match max(0, 10 - Tmin)!"

    # Relative humidity
    rhum = clim["rhum_pct"]
    assert (rhum >= 0.0).all() and (rhum <= 100.0).all(), (
        f"Relative humidity out of bounds [0, 100]: min={rhum.min()}, max={rhum.max()}"
    )


def test_spring_phenological_stage_ordering(benchmark_tables):
    """
    Verify phenological stage ordering for 25SP and 26SP:
    transplanting (0.0) < anthesis (1.0) < fruit set (1.25) < first harvest (1.5) < peak harvest (2.0) <= cessation (2.5)
    """
    targets = benchmark_tables["targets"]
    for s_id in ["25SP", "26SP"]:
        season_df = targets[targets["season_id"] == s_id]
        for trt, grp in season_df.groupby("treatment"):
            sorted_grp = grp.sort_values("target_stage_index")
            daps = sorted_grp["dap"].tolist()
            stages = sorted_grp["target_stage_index"].tolist()
            assert len(daps) == 6, f"Expected 6 milestone events, found {len(daps)}"
            assert daps[0] < daps[1] < daps[2] < daps[3] < daps[4] <= daps[5], (
                f"Stage ordering violated in {s_id} treatment {trt}: {list(zip(stages, daps))}"
            )


def test_phenological_stage_ordering_all_treatments(benchmark_tables):
    """
    ADVERSARIAL STRESS TEST:
    Audits phenological stage ordering across ALL treatments and seasons:
    transplanting (0.0) < anthesis (1.0) < fruit set (1.25) < first harvest (1.5) < peak harvest (2.0) <= cessation (2.5)
    
    EXPECTED EMPIRICAL BUG:
    Fails on 25FA treatments 1-12 where peak harvest (stage 2.0, dap 120, date 2025-12-11)
    is recorded AFTER cessation (stage 2.5, dap 109, date 2025-11-30).
    """
    targets = benchmark_tables["targets"]
    violations = []

    for (s_id, trt), grp in targets.groupby(["season_id", "treatment"]):
        sorted_grp = grp.sort_values("target_stage_index")
        daps = sorted_grp["dap"].tolist()
        stages = sorted_grp["target_stage_index"].tolist()
        events = sorted_grp["event_type"].tolist()
        dates = sorted_grp["calendar_date"].tolist()

        # Check: 0.0 < 1.0 < 1.25 < 1.5 < 2.0 <= 2.5
        ordered = (daps[0] < daps[1] < daps[2] < daps[3] < daps[4] <= daps[5])
        if not ordered:
            violations.append({
                "season_id": s_id,
                "treatment": trt,
                "stages": stages,
                "events": events,
                "daps": daps,
                "dates": dates,
            })

    if violations:
        msg = f"Phenological stage ordering violated in {len(violations)} treatments!\n"
        for v in violations:
            msg += (
                f"  Season {v['season_id']} Trt {v['treatment']}: "
                f"Peak harvest (stage {v['stages'][4]}={v['events'][4]}, dap={v['daps'][4]}, date={v['dates'][4]}) "
                f"> Cessation (stage {v['stages'][5]}={v['events'][5]}, dap={v['daps'][5]}, date={v['dates'][5]})\n"
            )
        pytest.fail(msg)


def test_seedling_age_and_calendar_consistency(benchmark_tables):
    """
    Audits consistency between calendar dates (transplant_date - sowing_date)
    and recorded seedling_age_days (22.0d).
    """
    meta = benchmark_tables["metadata"]
    discrepancies = []

    for _, row in meta.drop_duplicates(subset=["season_id", "sowing_date", "transplant_date"]).iterrows():
        d_sow = datetime.datetime.strptime(row["sowing_date"], "%Y-%m-%d").date()
        d_trans = datetime.datetime.strptime(row["transplant_date"], "%Y-%m-%d").date()
        calendar_diff = (d_trans - d_sow).days
        recorded_age = float(row["seedling_age_days"])
        if calendar_diff != int(recorded_age):
            discrepancies.append({
                "season_id": row["season_id"],
                "sowing_date": row["sowing_date"],
                "transplant_date": row["transplant_date"],
                "calendar_diff_days": calendar_diff,
                "recorded_seedling_age": recorded_age,
            })

    assert len(discrepancies) == 0, (
        f"Discrepancy found between (transplant_date - sowing_date) and seedling_age_days: {discrepancies}"
    )


def test_relational_treatment_integrity(benchmark_tables):
    """Verify that treatments in metadata and targets match 1-to-1."""
    meta = benchmark_tables["metadata"]
    targets = benchmark_tables["targets"]

    meta_keys = set(zip(meta["season_id"], meta["treatment"]))
    tgt_keys = set(zip(targets["season_id"], targets["treatment"]))

    assert meta_keys == tgt_keys, f"Mismatch between metadata and target treatments: {meta_keys ^ tgt_keys}"


def test_literature_benchmarks_physiological_validity(benchmark_tables):
    """Verify cardinal temperatures: Tb < Topt1 <= Topt2 < Tmax and positive flowering thermal time."""
    lit = benchmark_tables["literature"]
    assert len(lit) >= 8, f"Expected at least 8 literature benchmarks, found {len(lit)}"

    tb_lt_topt = lit["tb"] < lit["topt1"]
    assert tb_lt_topt.all(), f"Tb >= Topt1 in literature benchmarks: {lit[~tb_lt_topt]}"

    topt1_le_topt2 = lit["topt1"] <= lit["topt2"]
    assert topt1_le_topt2.all(), f"Topt1 > Topt2 in literature benchmarks: {lit[~topt1_le_topt2]}"

    topt2_lt_tmax = lit["topt2"] < lit["tmax"]
    assert topt2_lt_tmax.all(), f"Topt2 >= Tmax in literature benchmarks: {lit[~topt2_lt_tmax]}"

    tt_pos = lit["thermal_time_flowering"] > 0
    assert tt_pos.all(), f"Non-positive thermal time in literature benchmarks: {lit[~tt_pos]}"


def test_dataset_loader_and_tensor_bundle():
    """Verify that dataset loader and get_seasonal_tensor_bundle produce valid finite PyTorch tensors."""
    from src.phenology.dataset import load_benchmark_dataset, get_seasonal_tensor_bundle

    dfs = load_benchmark_dataset()
    assert set(dfs.keys()) == {"metadata", "microclimate", "targets", "literature"}

    bundle = get_seasonal_tensor_bundle()
    assert set(bundle.keys()) == {"25SP", "26SP", "25FA"}

    expected_sizes = {
        "25SP": (11, 124),
        "26SP": (12, 124),
        "25FA": (12, 151),
    }

    tensor_keys_2d = ["tavg", "tmin", "tmax", "dif", "srad", "dli", "daylength", "rhum", "chilling"]
    tensor_keys_1d = ["page", "irrigation_coeff", "n_rate_kg_ha", "treatment"]

    for s_id, data in bundle.items():
        exp_b, exp_t = expected_sizes[s_id]
        assert data["batch_size"] == exp_b
        assert data["seq_len"] == exp_t

        for k in tensor_keys_2d:
            t = data[k]
            assert isinstance(t, torch.Tensor), f"{s_id} key {k} is not a Tensor"
            assert t.shape == (exp_b, exp_t), f"{s_id} key {k} shape {t.shape} != {(exp_b, exp_t)}"
            assert torch.isfinite(t).all(), f"{s_id} key {k} contains non-finite values"

        for k in tensor_keys_1d:
            t = data[k]
            assert isinstance(t, torch.Tensor), f"{s_id} key {k} is not a Tensor"
            assert t.shape == (exp_b,), f"{s_id} key {k} shape {t.shape} != {(exp_b,)}"
            assert torch.isfinite(t).all(), f"{s_id} key {k} contains non-finite values"
