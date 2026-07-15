"""Tests for the Python-to-R paper data boundary."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.reporting.figure_data import (
    adapt_legacy_comparison_outputs,
    performance_metrics,
    read_phi_ensemble,
    validate_comparison_table,
)
from src.reporting.export_paper_data import main


def _write_legacy_files(directory, prefix="case"):
    pd.DataFrame(
        {
            "RUN": [1, 1, 2, 2],
            "TN": [2, 2, 13, 13],
            "DATE": [25080, 25120, 25080, 25120],
            "OBS_LAID": [0.2, 2.0, 0.3, 3.0],
            "SIM_LAID": [0.25, 1.8, 0.4, 2.7],
            "OBS_LWAD": [10, 200, 12, 250],
            "SIM_LWAD": [11, 190, 14, 230],
            "OBS_SWAD": [9, 300, 10, 320],
            "SIM_SWAD": [8, 280, 12, 300],
        }
    ).to_csv(directory / f"{prefix}_deterministic_process_compare.csv", index=False)
    pd.DataFrame(
        {
            "RUN": [1, 1, 2, 2],
            "TN": [2, 2, 13, 13],
            "HNO": [1, 2, 1, 2],
            "DATE": [25140, 25150, 25140, 25150],
            "OBS_FRESH_INC": [100, 200, 120, 220],
            "SIM_FRESH_INC": [90, 210, 130, 200],
        }
    ).to_csv(directory / f"{prefix}_deterministic_harvest_compare.csv", index=False)


def test_legacy_adapter_produces_tidy_contract_and_metrics(tmp_path):
    _write_legacy_files(tmp_path)
    data = adapt_legacy_comparison_outputs(tmp_path, "case")
    assert set(data["variable"]) == {"LAID", "LWAD", "SWAD", "FRESH_INC"}
    assert set(data["data_status"]) == {"legacy_unvalidated"}
    assert set(data["time"].dropna()) == {80.0, 120.0, 140.0, 150.0}
    metrics = performance_metrics(data[data["variable"] == "LAID"])
    assert metrics["n"] == 4
    assert metrics["rmse"] > 0


def test_phi_reader_uses_realizations_not_only_reported_mean(tmp_path):
    path = tmp_path / "case.phi.actual.csv"
    pd.DataFrame(
        {
            "iteration": [0, 1],
            "total_runs": [3, 3],
            "mean": [11, 6],
            "standard_deviation": [1, 1],
            "min": [10, 5],
            "max": [12, 7],
            "r1": [10, 5],
            "r2": [11, 6],
            "r3": [12, 7],
        }
    ).to_csv(path, index=False)
    long = read_phi_ensemble(path)
    assert len(long) == 6
    assert long.groupby("iteration")["phi"].median().to_dict() == {0: 11.0, 1: 6.0}


def test_profile_has_print_safe_minima():
    profile = json.loads(Path("configs/figures/publication.json").read_text(encoding="utf-8"))
    assert profile["renderer"] == "R"
    assert profile["font_size_pt"] >= 5
    assert profile["raster_dpi"] >= 300
    assert {"pdf", "svg", "png"}.issubset(set(profile["formats"]))


def test_comparison_contract_rejects_unknown_dataset_role(tmp_path):
    _write_legacy_files(tmp_path)
    data = adapt_legacy_comparison_outputs(tmp_path, "case")
    data.loc[0, "dataset_role"] = "random_split"
    with pytest.raises(ValueError, match="dataset_role"):
        validate_comparison_table(data)


def test_export_cli_requires_demo_opt_in_and_writes_data_only(tmp_path):
    _write_legacy_files(tmp_path)
    out_dir = tmp_path / "figures"
    common = [
        "--run-id",
        "case",
        "--legacy-results-dir",
        str(tmp_path),
        "--out-dir",
        str(out_dir),
    ]
    with pytest.raises(SystemExit):
        main(common)
    assert main([*common, "--allow-unvalidated-demo"]) == 0
    manifest = json.loads((out_dir / "paper_data_manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_status"] == "legacy_layout_demo"
    assert manifest["renderer_contract"] == "r_paper_figures_v1"
    assert (out_dir / "comparison.csv").is_file()
    assert not list(out_dir.glob("*.png"))


def test_validated_bundle_keeps_formal_status_without_demo_flag(tmp_path):
    _write_legacy_files(tmp_path)
    data = adapt_legacy_comparison_outputs(tmp_path, "case")
    data["data_status"] = "science_validated"
    data["dataset_role"] = "calibration"
    comparison = tmp_path / "validated.csv"
    data.to_csv(comparison, index=False)
    out_dir = tmp_path / "formal"

    assert main([
        "--run-id", "formal_case",
        "--comparison-csv", str(comparison),
        "--out-dir", str(out_dir),
    ]) == 0
    manifest = json.loads((out_dir / "paper_data_manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_status"] == "science_validated"


def test_r_is_the_only_paper_renderer():
    root = Path("paper/R")
    expected = {
        "common.R",
        "make_all.R",
        "fig_model_performance.R",
        "fig_selected_dynamics.R",
        "fig_phi_convergence.R",
    }
    assert expected.issubset({path.name for path in root.glob("*.R")})
    exporter = Path("src/reporting/export_paper_data.py").read_text(encoding="utf-8")
    assert "matplotlib" not in exporter
    assert not Path("src/reporting/paper_figures.py").exists()
    entry = (root / "make_all.R").read_text(encoding="utf-8")
    assert "science_validated" in entry
    assert "DEMO" in entry
