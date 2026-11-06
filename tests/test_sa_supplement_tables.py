from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import numpy as np

from src.reporting.export_sa_supplement_tables import build_supplement_tables, build_table_s3, _classify_boundary_source
from src.reporting.export_sobol_stability_paper_data import _effect_decomposition


def test_sensitivity_supplement_tables_are_complete_and_hashed(tmp_path: Path) -> None:
    manifest_path = build_supplement_tables(
        bounds_csv=Path("data/parameter_registry/bounds_frozen/eggplant/eggplant_formal_multiseason_candidate_v4_20260721.csv"),
        sobol_candidates_csv=Path("configs/sa/approved_topk/eggplant_formal_sobol_top23_v1_20260721.csv"),
        out_dir=tmp_path,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["bundle_type"] == "sa_supplementary_tables"
    s1 = pd.read_csv(tmp_path / "Table_S1_morris_sampling_space.csv")
    s2 = pd.read_csv(tmp_path / "Table_S2_sobol_candidate_reduction.csv")
    assert len(s1) == 55
    assert len(s2) == 23
    assert s1["definition"].notna().all() and s1["unit"].notna().all()
    assert s2["candidate_set_role"].str.contains("not a final calibration", regex=False).all()
    for artifact in manifest["artifacts"]:
        path = tmp_path / artifact["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]


def test_sobol_effect_decomposition_uses_scalar_run_level_responses(tmp_path: Path) -> None:
    samples = 32
    rows = samples * 3
    case = tmp_path / "case"
    case.mkdir()
    pd.DataFrame({"run_id": range(rows), "P1": np.linspace(0, 1, rows)}).to_csv(
        case / "sa_sen_sobol.sobol.par.csv", index=False
    )
    base = np.linspace(1.0, 4.0, rows)
    outputs = pd.DataFrame({
        "run_id": range(rows), "failed_flag": 0,
        "tn1_adaps": base,
        "tn1_lai_auc": base * 2,
        "tn1_agb_end_cwad": base * 3,
        "tn1_fruitd_end": base * 4,
        "tn1_cumharvest_dap50": base * 5,
        "wn_water_n1_fruitd_end": base * 6,
        "wn_nslope_w1_fruitd_end": base * 7,
        "wn_interaction_fruitd_end": base * 8,
    })
    outputs.to_csv(case / "sa_sen_sobol.sobol.obs.csv", index=False)
    (case / "run_manifest.yaml").write_text(
        f"run_id: test\nsobol_samples: {samples}\nsobol_parameter_count: 1\n", encoding="utf-8"
    )

    effects, scales = _effect_decomposition(case, "TEST", replicates=100, seed=7)

    assert len(effects) == 8
    assert len(scales) == 8
    assert set(effects["parameter"]) == {"P1"}
    assert effects[["S1", "ST", "interaction_remainder"]].notna().all().all()
    # Diagnostic response (plan §4.2): wide CIs, never displayed for
    # interaction-strength claims.  response_id now follows sa_contract.
    assert scales.loc[scales["response_id"] == "MEAN_CUMHARVEST_DAP50", "display_in_figure"].item() is False
    # W3 contract alignment: response_ids match sa_contract.ALL_RESPONSES.
    from src.sensitivity.sa_contract import ALL_RESPONSES, AMBIGUOUS_FRUIT_DRY_MASS_PHRASES
    assert set(effects["response_id"]) <= set(ALL_RESPONSES)
    # W3 §4.1: no response label may contain an ambiguous "fruit dry mass" phrase.
    for label in pd.concat([effects["response_label"], scales["response_label"]]):
        low = str(label).lower()
        for phrase in AMBIGUOUS_FRUIT_DRY_MASS_PHRASES:
            assert phrase not in low, f"ambiguous phrase {phrase!r} in label {label!r}"
    # The cumulative-harvest response carries the unambiguous contract label.
    fruitd_label = scales.loc[scales["response_id"] == "MEAN_FRUITD_END", "response_label"].iloc[0]
    assert "season-end cumulative harvested dry mass" in fruitd_label.lower()


def test_build_table_s3_carries_full_decomposition_and_scales(tmp_path: Path) -> None:
    """Table S3 includes S1/ST/CIs/remainder/scale and an interpretation note (P1#4)."""
    samples = 32
    rows = samples * 3
    case = tmp_path / "case"
    case.mkdir()
    pd.DataFrame({"run_id": range(rows), "P1": np.linspace(0, 1, rows)}).to_csv(
        case / "sa_sen_sobol.sobol.par.csv", index=False)
    base = np.linspace(1.0, 4.0, rows)
    pd.DataFrame({
        "run_id": range(rows), "failed_flag": 0,
        "tn1_adaps": base, "tn1_lai_auc": base * 2, "tn1_agb_end_cwad": base * 3,
        "tn1_fruitd_end": base * 4, "tn1_cumharvest_dap50": base * 5,
        "wn_water_n1_fruitd_end": base * 6, "wn_nslope_w1_fruitd_end": base * 7,
        "wn_interaction_fruitd_end": base * 8,
    }).to_csv(case / "sa_sen_sobol.sobol.obs.csv", index=False)
    (case / "run_manifest.yaml").write_text(
        f"run_id: test\nsobol_samples: {samples}\nsobol_parameter_count: 1\n", encoding="utf-8")
    s3 = build_table_s3(effect_case=case, season="TEST", out_dir=tmp_path, replicates=100, seed=7)
    df = pd.read_csv(s3)
    # §6.3 columns present
    for col in ("S1", "S1_ci_low", "S1_ci_high", "ST", "ST_ci_low", "ST_ci_high",
                "interaction_remainder", "interaction_ci_low", "interaction_ci_high",
                "interaction_supported", "response_sd", "response_min", "response_max"):
        assert col in df.columns, f"Table S3 missing {col}"
    assert "interpretation_note" in df.columns
    assert (df["table"] == "Table S3").all()


def test_boundary_source_type_classifies_transparently() -> None:
    """Table S1 boundary_source_type distinguishes sources (P2#7), no fabrication."""
    assert _classify_boundary_source(
        "Eggplant literature supports Tb about 10-11 C") == "crop_literature"
    assert _classify_boundary_source(
        "forward checks showed EM-V1 <=37 produced missing anthesis") == "physical_numeric_safety"
    assert _classify_boundary_source(
        "Inherited as a proposal candidate; requires final per-parameter review") == "inherited_pending_review"
    assert _classify_boundary_source("calibration posterior v14") == "historical_calibration"
