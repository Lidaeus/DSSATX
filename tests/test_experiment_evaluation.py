"""Unit tests for src/reporting/experiment_evaluation.py."""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from src.reporting.experiment_evaluation import evaluate_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _comparison(n_per_season=6):
    rows = []
    for season in ("25SP", "25FA"):
        for h in range(1, n_per_season + 1):
            obs = 100 * h
            sim = obs + (5 if season == "25SP" else -5)
            rows.append({
                "experiment_id": "E03",
                "season": season,
                "dataset_role": "calibration",
                "variable": "CHPDT",
                "scale": "raw",
                "treatment": 2,
                "harvest_number": h,
                "observed": obs,
                "simulated": sim,
                "source_file": "x",
            })
    return pd.DataFrame(rows)


def test_evaluate_experiment_produces_three_tables(tmp_path):
    df = _comparison(n_per_season=8)
    csv_path = tmp_path / "comp.csv"
    df.to_csv(csv_path, index=False)
    arts = evaluate_experiment(csv_path, tmp_path / "out")
    assert set(arts.keys()) == {"comparison_raw", "metrics_rawscale", "residual_diagnostics"}
    for p in arts.values():
        assert p.is_file()
    metrics = pd.read_csv(arts["metrics_rawscale"])
    # one row per season (25SP, 25FA)
    assert set(metrics["season"]) == {"25SP", "25FA"}
    # MSE closure in each group
    for _, row in metrics.iterrows():
        if not math.isnan(row["MSE_s"]):
            assert row["MSE"] == pytest.approx(row["MSE_s"] + row["MSE_u"], abs=1e-9)


def test_evaluate_experiment_rejects_hwam(tmp_path):
    df = _comparison(n_per_season=8)
    df.loc[0, "variable"] = "HWAM"
    csv_path = tmp_path / "comp.csv"
    df.to_csv(csv_path, index=False)
    with pytest.raises(ValueError, match="HWAM/PWAD/PWAI"):
        evaluate_experiment(csv_path, tmp_path / "out")


def test_evaluate_experiment_rejects_pwad_and_pwai(tmp_path):
    for forbidden in ("PWAD", "PWAI"):
        df = _comparison(n_per_season=8)
        df.loc[0, "variable"] = forbidden
        csv_path = tmp_path / f"comp_{forbidden}.csv"
        df.to_csv(csv_path, index=False)
        with pytest.raises(ValueError, match="HWAM/PWAD/PWAI"):
            evaluate_experiment(csv_path, tmp_path / "out")


def test_chfpw_flagged_diagnostic_only_not_excluded(tmp_path):
    df = _comparison(n_per_season=8)
    chfpw = pd.DataFrame([{
        "experiment_id": "E03", "season": "25SP", "dataset_role": "diagnostic",
        "variable": "CHFPW", "scale": "raw", "treatment": 2, "harvest_number": 1,
        "observed": 2000, "simulated": 2100, "source_file": "x",
    }])
    df = pd.concat([df, chfpw], ignore_index=True)
    csv_path = tmp_path / "comp.csv"
    df.to_csv(csv_path, index=False)
    arts = evaluate_experiment(csv_path, tmp_path / "out")
    metrics = pd.read_csv(arts["metrics_rawscale"])
    chfpw_row = metrics[metrics["_variable_root"] == "CHFPW"]
    assert not chfpw_row.empty
    assert bool(chfpw_row["is_diagnostic_only"].iloc[0]) is True
    chpdt_row = metrics[metrics["_variable_root"] == "CHPDT"]
    assert bool(chpdt_row["is_diagnostic_only"].iloc[0]) is False


def test_residual_diagnostics_table_has_runs_test_and_bootstrap(tmp_path):
    df = _comparison(n_per_season=10)
    csv_path = tmp_path / "comp.csv"
    df.to_csv(csv_path, index=False)
    arts = evaluate_experiment(csv_path, tmp_path / "out")
    diag = pd.read_csv(arts["residual_diagnostics"])
    # runs-test rows carry n_runs; bootstrap rows carry boot_MBE
    runs_cols = [c for c in diag.columns if c in ("n_runs", "status", "p_value")]
    assert runs_cols  # runs-test columns present
    boot_cols = [c for c in diag.columns if str(c).startswith("boot_")]
    assert boot_cols


def test_unsupported_profile_rejected(tmp_path):
    df = _comparison(n_per_season=8)
    csv_path = tmp_path / "comp.csv"
    df.to_csv(csv_path, index=False)
    with pytest.raises(ValueError, match="unsupported evaluation profile"):
        evaluate_experiment(csv_path, tmp_path / "out", profile="something_else")


def test_cli_smoke_produces_three_tables(tmp_path):
    """CLI end-to-end smoke test: comparison CSV → three result tables.

    Verifies the CLI entry point (argparse, import paths, JSON artefact
    output) works, not just the ``evaluate_experiment`` API.  Catches import
    path regressions that API-level tests miss.
    """
    df = _comparison(n_per_season=8)
    csv_path = tmp_path / "comp.csv"
    df.to_csv(csv_path, index=False)
    out_dir = tmp_path / "cli_out"

    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "reporting" / "evaluate_calibration_experiment.py"),
            "--comparison-csv", str(csv_path),
            "--out-dir", str(out_dir),
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, (
        f"CLI failed (exit {result.returncode}):\n{result.stderr}"
    )
    # CLI prints a JSON dict of artefact paths
    artefacts = json.loads(result.stdout)
    assert set(artefacts.keys()) == {
        "comparison_raw", "metrics_rawscale", "residual_diagnostics",
    }
    for name, path in artefacts.items():
        assert Path(path).is_file(), f"{name} not written: {path}"

    # Verify metrics content: MSE closure holds in every group.
    metrics = pd.read_csv(artefacts["metrics_rawscale"])
    for _, row in metrics.iterrows():
        if not math.isnan(row["MSE_s"]):
            assert row["MSE"] == pytest.approx(
                row["MSE_s"] + row["MSE_u"], abs=1e-9
            )
