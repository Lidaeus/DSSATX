"""Tests for the Python-to-R paper data boundary."""

import json
from pathlib import Path

import pandas as pd
import pytest

from src.reporting.figure_data import (
    adapt_legacy_comparison_outputs,
    align_comparison_to_trajectory,
    performance_metrics,
    read_dssat_trajectories,
    read_phi_ensemble,
    validate_treatment_metadata,
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
            "OBS_FRESH_CUM": [100, 300, 120, 340],
            "SIM_FRESH_CUM": [90, 300, 130, 330],
        }
    ).to_csv(directory / f"{prefix}_deterministic_harvest_compare.csv", index=False)


def test_legacy_adapter_produces_tidy_contract_and_metrics(tmp_path):
    _write_legacy_files(tmp_path)
    data = adapt_legacy_comparison_outputs(tmp_path, "case")
    assert set(data["variable"]) == {"LAID", "LWAD", "SWAD", "FRESH_INC", "FRESH_CUM"}
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
    assert set(profile["nitrogen_colors"]) == {"N3", "N2", "N1", "N0"}
    assert set(profile["water_shapes"]) == {"W3", "W2", "W1", "CK"}


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
    assert manifest["renderer_contract"] == "r_paper_figures_v2"
    assert manifest["schema_version"] == 2
    assert (out_dir / "comparison.csv").is_file()
    assert not list(out_dir.glob("*.png"))


def _write_passing_upstream_artifacts(run_dir: Path, run_id: str) -> tuple[Path, Path]:
    """Write matching manifest, engineering report and finalize authority."""
    manifest = run_dir / "run_manifest.yaml"
    manifest.write_text(
        f'run_id: "{run_id}"\nrun_type: "calibration"\ngit_commit: "abc123"\n'
        'input_manifest_sha256: "1111111111111111111111111111111111111111111111111111111111111111"\n'
        'bounds_sha256: "2222222222222222222222222222222222222222222222222222222222222222"\n'
        'observation_policy_sha256: "3333333333333333333333333333333333333333333333333333333333333333"\n'
        'validation_split_sha256: "4444444444444444444444444444444444444444444444444444444444444444"\n',
        encoding="utf-8",
    )
    report = {
        "schema_version": 1,
        "run_type": "calibration",
        "run_id": run_id,
        "generated_at": "2026-07-16T00:00:00Z",
        "process_completed": True,
        "science_validated": True,
        "status": "pass",
        "checks": [
            {"check_id": "process_completed", "status": "pass", "message": "ok"},
        ],
    }
    quality = run_dir / "quality_report.json"
    quality.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    finalize_dir = run_dir / "calibration_finalize"
    finalize_dir.mkdir(exist_ok=True)
    (finalize_dir / "calibration_finalize.json").write_text(
        json.dumps({
            "case": run_id,
            "engineering_status": "engineering_validated",
            "science_status": "science_validated",
            "scientific_status": "validated",
        }, indent=2) + "\n", encoding="utf-8"
    )
    return manifest, quality


def _validated_comparison_frame(tmp_path, run_id="formal_case"):
    """Build a comparison frame whose run_id matches the export run_id."""
    _write_legacy_files(tmp_path)
    data = adapt_legacy_comparison_outputs(tmp_path, "case")
    data["run_id"] = run_id
    data["data_status"] = "science_validated"
    data["dataset_role"] = "calibration"
    comparison = tmp_path / "validated.csv"
    data.to_csv(comparison, index=False)
    return comparison


def test_validated_bundle_requires_upstream_manifest_and_quality_report(tmp_path):
    """science_validated no longer trusts the CSV's data_status alone.

    A formal export now requires a run_manifest.yaml and quality_report.json
    from the same run, with the quality report passing. This is the corrected
    trust model: writing a string into a CSV is not research validation.
    """
    comparison = _validated_comparison_frame(tmp_path, "formal_case")
    out_dir = tmp_path / "formal"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    manifest, quality = _write_passing_upstream_artifacts(run_dir, "formal_case")

    # 1. Without upstream artifacts, even a self-reported science_validated CSV
    #    is rejected (the old, too-permissive behaviour is gone).
    with pytest.raises(SystemExit):
        main([
            "--run-id", "formal_case",
            "--comparison-csv", str(comparison),
            "--out-dir", str(out_dir),
        ])

    # 2. With matching, passing upstream artifacts the formal export succeeds.
    assert main([
        "--run-id", "formal_case",
        "--comparison-csv", str(comparison),
        "--run-manifest", str(manifest),
        "--quality-report", str(quality),
        "--out-dir", str(out_dir),
    ]) == 0
    payload = json.loads((out_dir / "paper_data_manifest.json").read_text(encoding="utf-8"))
    assert payload["data_status"] == "science_validated"
    assert payload["upstream_validation"]["run_manifest"]["run_id"] == "formal_case"
    assert payload["upstream_validation"]["quality_report"]["science_validated"] is True
    assert set(payload["upstream_validation"]["frozen_run_inputs"]) == {
        "input_manifest_sha256", "bounds_sha256", "observation_policy_sha256", "validation_split_sha256",
    }


def test_paper_export_rejects_mixed_run_ids_and_failing_quality_report(tmp_path):
    """Reject (a) a run_id mismatch and (b) a quality report that fails."""
    comparison = _validated_comparison_frame(tmp_path, "formal_case")
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # (a) Manifest run_id differs from --run-id -> rejected.
    manifest_a, quality_a = _write_passing_upstream_artifacts(run_dir, "DIFFERENT_RUN")
    with pytest.raises(SystemExit):
        main([
            "--run-id", "formal_case",
            "--comparison-csv", str(comparison),
            "--run-manifest", str(manifest_a),
            "--quality-report", str(quality_a),
            "--out-dir", str(tmp_path / "out_a"),
        ])

    # (b) Matching run_id but the quality report carries a failing check.
    manifest_b, quality_b = _write_passing_upstream_artifacts(run_dir, "formal_case")
    failing = json.loads(quality_b.read_text(encoding="utf-8"))
    failing["checks"] = [
        {"check_id": "process_completed", "status": "fail", "message": "run aborted"},
    ]
    failing["science_validated"] = False
    failing["status"] = "fail"
    quality_b.write_text(json.dumps(failing, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main([
            "--run-id", "formal_case",
            "--comparison-csv", str(comparison),
            "--run-manifest", str(manifest_b),
            "--quality-report", str(quality_b),
            "--out-dir", str(tmp_path / "out_b"),
        ])


def test_paper_export_rejects_mixed_run_id_in_comparison_table(tmp_path):
    """A comparison table carrying a different run_id than --run-id is rejected,
    even when upstream artifacts match, because figures must never blend runs."""
    # Comparison table self-reports run_id 'other_run'.
    comparison = _validated_comparison_frame(tmp_path, "other_run")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    manifest, quality = _write_passing_upstream_artifacts(run_dir, "formal_case")
    with pytest.raises(SystemExit):
        main([
            "--run-id", "formal_case",
            "--comparison-csv", str(comparison),
            "--run-manifest", str(manifest),
            "--quality-report", str(quality),
            "--out-dir", str(tmp_path / "out"),
        ])


def test_formal_export_rejects_missing_frozen_run_hash(tmp_path):
    comparison = _validated_comparison_frame(tmp_path, "formal_case")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    manifest, quality = _write_passing_upstream_artifacts(run_dir, "formal_case")
    manifest.write_text(
        "\n".join(line for line in manifest.read_text(encoding="utf-8").splitlines()
                  if not line.startswith("bounds_sha256:")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        main([
            "--run-id", "formal_case",
            "--comparison-csv", str(comparison),
            "--run-manifest", str(manifest),
            "--quality-report", str(quality),
            "--out-dir", str(tmp_path / "out"),
        ])


def test_r_is_the_only_paper_renderer():
    root = Path("paper/R")
    expected = {
        "common.R",
        "make_all.R",
        "fig_model_performance.R",
        "fig_selected_dynamics.R",
        "fig_residual_diagnostics.R",
        "fig_all_treatment_dynamics.R",
        "fig_phi_convergence.R",
    }
    assert expected.issubset({path.name for path in root.glob("*.R")})
    exporter = Path("src/reporting/export_paper_data.py").read_text(encoding="utf-8")
    assert "matplotlib" not in exporter
    assert not Path("src/reporting/paper_figures.py").exists()
    entry = (root / "make_all.R").read_text(encoding="utf-8")
    assert "science_validated" in entry
    assert "DEMO" in entry


def test_t4_demo_figures_use_a_hash_gated_r_only_bundle():
    """T4 layout QA must not let R inspect DSSAT/PEST++ run artefacts."""
    entry = Path("paper/R/make_all.R").read_text(encoding="utf-8")
    common = Path("paper/R/common.R").read_text(encoding="utf-8")
    assert "read_t4_demo_bundle" in entry
    for figure_id in ("figs5_posterior", "figs6_spearman", "figs7_equifinality"):
        assert figure_id in entry
    assert "cannot be mixed with standard paper figures" in entry
    assert "t4_posterior_equifinality" in common
    assert "candidate_pair_predictions.csv" in common
    assert "run_dssat" not in common.lower()
    assert "matplotlib" not in Path("src/reporting/export_posterior_demo_data.py").read_text(encoding="utf-8")


def test_formal_calibration_figures_require_frozen_scenario_provenance():
    common = Path("paper/R/common.R").read_text(encoding="utf-8")
    entry = Path("paper/R/make_all.R").read_text(encoding="utf-8")
    assert "require_calibration_scenario" in common
    assert "actual_trial_calibration" in common
    assert "frozen_run_inputs" in common
    assert "require_calibration_scenario(bundle)" in entry


def test_make_all_selected_sa_figures_need_no_calibration_trajectory():
    """``--figure-ids`` selects a figure subset so SA figures can render from an
    SA data bundle without a calibration trajectory, and vice-versa (plan §7).

    Each scientific question is one module. The figure-selection guard must:
    - parse ``--figure-ids`` and default to ``all``;
    - gate the trajectory-requiring modules (fig4_dynamics, figs4_all_treatments)
      behind the selection so they only error on a missing trajectory when they
      were actually requested.
    """
    entry = Path("paper/R/make_all.R").read_text(encoding="utf-8")
    # The selection argument and helper exist.
    assert 'figure_ids <- if (is.null(args$figure_ids)) "all"' in entry
    assert "selected <- function(id)" in entry
    # Each figure module is guarded by selection().
    for figure_id in ("fig3_performance", "figs3_residuals", "fig4_dynamics", "figs4_all_treatments", "fig2_phi"):
        assert f'selected("{figure_id}")' in entry
    # The trajectory requirement is conditional on selecting a module that needs it.
    assert "needs_trajectory <-" in entry
    assert "needs_treatment_metadata <-" in entry


def test_daily_dssat_trajectory_uses_treatment_and_dap(tmp_path):
    (tmp_path / "PlantGro.OUT").write_text(
        "*RUN   1 : demo\n TREATMENT  2 : demo\n"
        "@YEAR DOY DAS DAP LAID LWAD SWAD CWAD\n"
        " 2025 075 8 0 0.1 1 2 3\n"
        " 2025 076 9 1 0.2 2 3 5\n",
        encoding="utf-8",
    )
    (tmp_path / "FreshWt.OUT").write_text(
        "*RUN   1 : demo\n TREATMENT  2 : demo\n"
        "@YEAR DOY DAS DAP CHPDT CHFPW\n"
        " 2025 075 8 0 0 0\n"
        " 2025 076 9 1 5 100\n",
        encoding="utf-8",
    )
    trajectory = read_dssat_trajectories(
        tmp_path,
        run_id="case",
        data_status="science_validated",
        role_by_treatment={"2": "calibration"},
    )
    assert {"LAID", "LWAD", "SWAD", "CWAD", "DRY_CUM", "FRESH_CUM"}.issubset(
        set(trajectory["variable"])
    )
    assert set(trajectory["treatment"]) == {"2"}
    assert set(trajectory["time"]) == {0.0, 1.0}
    assert set(trajectory["dataset_role"]) == {"calibration"}


def test_legacy_dates_align_to_daily_dap(tmp_path):
    _write_legacy_files(tmp_path)
    comparison = adapt_legacy_comparison_outputs(tmp_path, "case")
    trajectory = pd.DataFrame(
        {
            "treatment": ["2", "2", "13", "13"],
            "date_code": [25080, 25120, 25080, 25120],
            "time": [5, 45, 5, 45],
        }
    )
    aligned = align_comparison_to_trajectory(comparison, trajectory)
    process = aligned[aligned["variable"] == "LAID"]
    assert set(process["time"]) == {5.0, 45.0}
    assert set(process["time_label"]) == {"Days after planting"}


def test_treatment_metadata_requires_unique_explicit_water_and_nitrogen():
    data = pd.DataFrame(
        {
            "treatment": ["2", "13"],
            "treatment_label": ["TN2 (W3-N3)", "TN13 (W1-N0)"],
            "water_level": ["W3", "W1"],
            "nitrogen_level": ["N3", "N0"],
        }
    )
    result = validate_treatment_metadata(data)
    assert result.set_index("treatment").loc["2", "nitrogen_level"] == "N3"
    with pytest.raises(ValueError, match="duplicate"):
        validate_treatment_metadata(pd.concat([data, data.iloc[[0]]], ignore_index=True))


def test_r_dynamics_preserves_scientific_geometry_contract():
    code = Path("paper/R/fig_selected_dynamics.R").read_text(encoding="utf-8")
    entry = Path("paper/R/make_all.R").read_text(encoding="utf-8")
    assert "geom_smooth" not in code
    assert "daily DSSAT simulation" in code
    assert "monoH.FC" in code
    assert "Visual interpolation only" in code
    assert "nitrogen_level" in code
    assert "water_level" in code
    assert "harvest_dynamics" in entry
    assert "cumulative_smooth" in entry
    assert "FigS3_residuals_" in entry
    assert "FigS4_all_treatments_" in entry


def test_supplementary_r_modules_keep_residual_and_smoothing_definitions_explicit():
    residuals = Path("paper/R/fig_residual_diagnostics.R").read_text(encoding="utf-8")
    all_treatments = Path("paper/R/fig_all_treatment_dynamics.R").read_text(encoding="utf-8")
    assert "simulated - data$observed" in residuals
    assert "Q–Q panels are descriptive" in residuals
    assert "geom_smooth" not in residuals
    assert "monotone_cumulative_curve" in all_treatments
    assert "Visual interpolation only" in all_treatments
