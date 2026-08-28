"""Acceptance-gate tests for the conditional-ensemble uncertainty pipeline.

Covers plan §10 of ``docs/PEST_IES条件集合不确定性图表开发方案_20260828.md``:
member selection/roles/coverage, quantile ordering, cumulative monotonicity,
sentinel handling, 25FA exclusion, renderer separation (no matplotlib, no
geom_smooth, R reads only the frozen bundle), DEMO gating, and manifest
hashing.  These tests are pure Python/text-level: they do not invoke R or
DSSAT (render QA runs separately with the pinned R install).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.export_conditional_predictions import (  # noqa: E402
    ALLOWED_SEASON_IDS,
    CUMULATIVE_VARIABLES,
    PREDICTION_SUMMARY_COLUMNS,
    RESIDUAL_MEMBER_COLUMNS,
    TRAJECTORY_SUMMARY_COLUMNS,
    aggregate_replay,
    build_replay_design,
    build_tpl_name_mapping,
    compute_interval_sensitivity,
    load_member_phi,
    load_parameter_ensemble,
    load_two_season_metadata,
    main as exporter_main,
)
from src.reporting.figure_data import VARIABLE_SPECS

RUN_FIXTURE = ROOT / "workspace" / "runs" / "e02_formal_armab_rrmse_official_200x6_20260828"
CASE = "e02_formal_armab_rrmse_200x6_20260828"
METADATA_CSV = ROOT / "configs" / "figures" / "treatment_metadata_two_season_20260828.csv"
PAPER_R = ROOT / "paper" / "R"
OFFICIAL_EXE_SHA = "92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a"
EMPTY_SE_TABLE = pd.DataFrame(
    columns=["season_id", "treatment", "date_code", "contract_variable", "observed_se"]
)


@contextlib.contextmanager
def tempdir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def write_member_status(path: Path, reals, flagged=()) -> None:
    rows = [
        {
            "real_name": real,
            "state": "retained" if real not in flagged else "dropped",
            "final_status": "retained" if real not in flagged else "dropped",
        }
        for real in reals
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def _aggregate_synthetic(**aggregate_kwargs):
    """Shared aggregate_replay call over the synthetic two-season replay."""
    with tempdir() as tmp:
        status = tmp / "status.csv"
        _write_status_for(status, aggregate_kwargs.pop("members", ["0", "1", "2"]))
        return aggregate_replay(member_status=pd.read_csv(status), **aggregate_kwargs)


def _write_status_for(path, members):
    write_member_status(path, members)


def _synthetic_events_and_trajectory(*, members=("0", "1", "2"), cum_decreasing=False):
    """Minimal 2-season x 1-treatment replay with monotone cumulative paths.

    Uses a purpose-built 2-row metadata frame (aggregate_replay is
    metadata-driven) so the complete-case gate expects exactly the synthetic
    treatments; the real 22-treatment freeze is covered by the demo-bundle
    tests below.
    """
    metadata = pd.DataFrame(
        {
            "season_id": ["25SP", "26SP"],
            "treatment": ["2", "1"],
            "treatment_label": ["TN2 (W3-N3)", "TN1 (W3-N3)"],
            "water_level": ["W3", "W3"],
            "nitrogen_level": ["N3", "N3"],
            "dataset_role": ["calibration", "calibration"],
        }
    )
    picked = [("25SP", "2"), ("26SP", "1")]
    event_rows, traj_rows = [], []
    roles = {("25SP", "2"): "calibration", ("26SP", "1"): "calibration"}
    for season, treatment in picked:
        base_cum = 1000.0
        for step in range(1, 5):
            cum = base_cum + 200.0 * step
            if cum_decreasing and step == 4:
                cum -= 400.0
            for index, real in enumerate(members):
                observed = base_cum + 200.0 * step
                record = {
                    "realization": real,
                    "season_id": season,
                    "dataset_role": roles[(season, treatment)],
                    "treatment": treatment,
                    "date_code": 25000 + step,
                    "dap": 200.0 + step,
                }
                event_rows.append(
                    {
                        **record,
                        "variable": "DRY_CUM",
                        "harvest_number": step,
                        "observed": observed,
                        "simulated": cum + 10.0 * index,
                        "source_file": "synthetic",
                    }
                )
                traj_rows.append(
                    {
                        **record,
                        "variable": "DRY_CUM",
                        "simulated": cum + 10.0 * index,
                    }
                )
    return pd.DataFrame(event_rows), pd.DataFrame(traj_rows), metadata


class TestInputLoading(unittest.TestCase):
    def test_two_season_metadata_freezes_roles_and_levels(self):
        metadata = load_two_season_metadata(METADATA_CSV)
        self.assertEqual(set(metadata["season_id"]), set(ALLOWED_SEASON_IDS))
        roles = metadata.groupby(["season_id", "dataset_role"])["treatment"].nunique().to_dict()
        self.assertEqual(roles[("25SP", "calibration")], 4)
        self.assertEqual(roles[("25SP", "validation")], 6)
        self.assertEqual(roles[("26SP", "calibration")], 4)
        self.assertEqual(roles[("26SP", "validation")], 8)
        self.assertEqual(set(metadata["water_level"]) - {"W1", "W2", "W3", "CK"}, set())

    def test_two_season_metadata_rejects_duplicate_season_treatment(self):
        bad = pd.read_csv(METADATA_CSV, dtype={"treatment": str})
        bad = pd.concat([bad, bad.iloc[[0]]], ignore_index=True)
        with tempdir() as tmp:
            path = tmp / "metadata.csv"
            bad.to_csv(path, index=False)
            with self.assertRaises(ValueError):
                load_two_season_metadata(path)

    def test_parameter_ensemble_excludes_base_and_requires_unique_realizations(self):
        with tempdir() as tmp:
            par = tmp / "fake.par.csv"
            frame = pd.DataFrame(
                {
                    "real_name": ["0", "1", "2", "base"],
                    "csdl": [12.1, 12.2, 12.3, 12.4],
                    "em-fl": [23.0, 23.5, 24.0, 24.5],
                }
            )
            frame.to_csv(par, index=False)
            ensemble = load_parameter_ensemble(par)
            self.assertEqual(ensemble["real_name"].tolist(), ["0", "1", "2"])
            duplicated = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
            dup_path = tmp / "dup.par.csv"
            duplicated.to_csv(dup_path, index=False)
            with self.assertRaises(ValueError):
                load_parameter_ensemble(dup_path)

    def test_tpl_name_mapping_restores_dssat_casing(self):
        with tempdir() as tmp:
            tpl = tmp / "tpl"
            tpl.write_text("ptf ~\nname,value\nCSDL,~ CSDL ~\nEM-FL,~ EM-FL ~\n", encoding="utf-8")
            mapping = build_tpl_name_mapping(tpl)
            self.assertEqual(mapping["em-fl"], "EM-FL")
            self.assertEqual(mapping["csdl"], "CSDL")

    def test_member_phi_uses_realization_columns_of_requested_iteration(self):
        with tempdir() as tmp:
            phi = tmp / "phi.csv"
            pd.DataFrame(
                {
                    "iteration": [0, 6],
                    "mean": [10.0, 5.0],
                    "0": [9.0, 4.0],
                    "1": [8.0, 3.0],
                    "2": [7.0, 2.0],
                }
            ).to_csv(phi, index=False)
            self.assertEqual(load_member_phi(phi, 6), {"0": 4.0, "1": 3.0, "2": 2.0})


class TestAggregation(unittest.TestCase):
    def _run(self, events, trajectory, metadata, member_phi=None):
        with tempdir() as tmp:
            status = tmp / "status.csv"
            write_member_status(status, sorted(set(events["realization"])))
            return aggregate_replay(
                events=events,
                trajectory=trajectory,
                metadata=metadata,
                candidate_members=sorted(set(events["realization"])),
                run_id="synthetic",
                ensemble_iteration=6,
                member_phi=member_phi or {},
                member_status=pd.read_csv(status),
                observed_se_table=EMPTY_SE_TABLE,
            )

    def test_quantile_order_uniform_members_and_contracts(self):
        events, trajectory, metadata = _synthetic_events_and_trajectory()
        aggregate = self._run(events, trajectory, metadata)
        ps = aggregate.prediction_summary
        self.assertEqual(list(ps.columns), PREDICTION_SUMMARY_COLUMNS)
        self.assertEqual(list(aggregate.trajectory_summary.columns), TRAJECTORY_SUMMARY_COLUMNS)
        self.assertTrue((ps["sim_q025"] <= ps["sim_q25"]).all())
        self.assertTrue((ps["sim_q25"] <= ps["sim_median"]).all())
        self.assertTrue((ps["sim_median"] <= ps["sim_q75"]).all())
        self.assertTrue((ps["sim_q75"] <= ps["sim_q975"]).all())
        self.assertTrue((ps["n_members_valid"] == 3).all())
        self.assertTrue((ps["n_members_valid"] == ps["n_members_expected"]).all())

    def test_decreasing_cumulative_quantiles_abort(self):
        events, trajectory, metadata = _synthetic_events_and_trajectory(cum_decreasing=True)
        with self.assertRaises(ValueError):
            self._run(events, trajectory, metadata)

    def test_residual_formulas_match_plan_definitions(self):
        events, trajectory, metadata = _synthetic_events_and_trajectory()
        aggregate = self._run(events, trajectory, metadata, member_phi={"0": 1.0, "1": 2.0, "2": 3.0})
        residual = aggregate.residual_members
        self.assertEqual(list(residual.columns), RESIDUAL_MEMBER_COLUMNS)
        member0 = residual[
            (residual["realization"] == "0")
            & (residual["season_id"] == "25SP")
            & (residual["treatment"] == "2")
            & (residual["variable"] == "DRY_CUM")
        ]
        self.assertEqual(len(member0), 1)
        observed = np.array([1200.0, 1400.0, 1600.0, 1800.0])
        simulated = observed.copy()  # member "0" carries zero jitter
        expected_bias = 100.0 * np.sum(simulated - observed) / np.sum(observed)
        self.assertAlmostEqual(member0["signed_relative_bias_pct"].iloc[0], expected_bias, places=6)
        expected_rrmse = 100.0 * np.sqrt(np.mean((simulated - observed) ** 2)) / np.mean(np.abs(observed))
        self.assertAlmostEqual(member0["rrmse_pct"].iloc[0], expected_rrmse, places=6)
        self.assertAlmostEqual(member0["terminal_relative_error_pct"].iloc[0], 0.0, places=6)
        self.assertEqual(member0["member_phi"].iloc[0], 1.0)

    def test_interval_sensitivity_reports_exclusions(self):
        events, _, _ = _synthetic_events_and_trajectory()
        flagged = compute_interval_sensitivity(
            events=events, valid_members=["0", "1", "2"], machine_flagged={"2"}
        )
        self.assertEqual(set(flagged["variable"]), {"DRY_CUM"})
        self.assertEqual(int(flagged["excluded_members"].iloc[0]), 1)
        self.assertGreater(float(flagged["max_abs_q975_diff"].iloc[0]), 0.0)
        unflagged = compute_interval_sensitivity(
            events=events, valid_members=["0", "1", "2"], machine_flagged=set()
        )
        self.assertTrue((unflagged["excluded_members"] == 0).all())
        self.assertTrue((unflagged["max_abs_q025_diff"] == 0).all())


class TestReplayDesignAndCli(unittest.TestCase):
    def test_design_covers_all_two_spring_treatments_and_rejects_25fa(self):
        metadata = load_two_season_metadata(METADATA_CSV)
        with tempdir() as tmp:
            design = {
                "cultivar_identity": "TM0008",
                "observation_policy": "policy.csv",
                "group_policy": "groups.csv",
                "seasons": [
                    {"season_id": "25SP", "experiment_code": "XXQL2501", "bundle_path": "x"},
                    {"season_id": "26SP", "experiment_code": "XXQL2601", "bundle_path": "y"},
                ],
            }
            source = tmp / "calibration_design.json"
            source.write_text(json.dumps(design), encoding="utf-8")
            out = tmp / "replay_design.json"
            build_replay_design(
                calibration_design=source,
                metadata=metadata,
                season_bundles={
                    "25SP": ROOT / "data/user/experiments/xxql2501_formal_armab_rrmse_20260828",
                    "26SP": ROOT / "data/user/experiments/xxql2601_formal_armab_rrmse_20260828",
                },
                case="synthetic",
                out_path=out,
            )
            payload = json.loads(out.read_text(encoding="utf-8"))
            counts = {entry["season_id"]: entry["treatments"] for entry in payload["seasons"]}
            self.assertEqual(len(counts["25SP"]), 10)
            self.assertEqual(len(counts["26SP"]), 12)
            self.assertNotIn("25FA", counts)

    def test_cli_rejects_25fa_season(self):
        with self.assertRaises(SystemExit):
            exporter_main(
                [
                    "--run-dir", "unused",
                    "--case", "c",
                    "--iteration", "6",
                    "--calibration-design", "unused.json",
                    "--season", "25FA=data/user/experiments/xxfa_formal_armab_rrmse_20260828",
                    "--treatment-metadata", str(METADATA_CSV),
                    "--official-dssat", "D:/Tomato_Cal/DSCSM048.EXE",
                    "--out-dir", "unused-out",
                ]
            )

    def test_cli_requires_both_seasons_and_all_explicit_inputs(self):
        base = [
            "--run-dir", "unused",
            "--case", "c",
            "--iteration", "6",
            "--calibration-design", "unused.json",
            "--treatment-metadata", str(METADATA_CSV),
            "--official-dssat", "D:/Tomato_Cal/DSCSM048.EXE",
            "--out-dir", "unused-out",
        ]
        with self.assertRaises(SystemExit):
            exporter_main(base)  # no --season at all
        with self.assertRaises(SystemExit):
            exporter_main(
                base + ["--season", "25SP=data/user/experiments/xxql2501_formal_armab_rrmse_20260828"]
            )  # only one season: 25SP and 26SP are both mandatory


class TestRendererSeparation(unittest.TestCase):
    def test_exporter_does_not_import_matplotlib(self):
        source = (ROOT / "src" / "reporting" / "export_conditional_predictions.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("matplotlib", source)

    def test_conditional_r_modules_exist_and_are_registered(self):
        for module in (
            "fig_model_performance_uncertainty.R",
            "fig_treatment_residual_uncertainty.R",
            "common.R",
            "make_all.R",
        ):
            self.assertTrue((PAPER_R / module).is_file(), module)
        make_all = (PAPER_R / "make_all.R").read_text(encoding="utf-8")
        for identifier in (
            "fig_model_performance_uncertainty",
            "diagnostic_conditional_residual_by_treatment",
            "fig4_dynamics_conditional",
            "figs4_all_treatments_conditional",
            "read_conditional_bundle",
        ):
            self.assertIn(identifier, make_all)

    def test_conditional_dynamics_never_smooth_and_use_ensemble_ribbons(self):
        for module in ("fig_selected_dynamics.R", "fig_all_treatment_dynamics.R"):
            text = (PAPER_R / module).read_text(encoding="utf-8")
            self.assertNotIn("geom_smooth", text, module)
            for ribbon_column in ("sim_q025", "sim_q975", "sim_median"):
                self.assertIn(ribbon_column, text, module)

    def test_r_conditional_readers_only_consume_frozen_bundle(self):
        common = (PAPER_R / "common.R").read_text(encoding="utf-8")
        self.assertIn("read_conditional_bundle", common)
        self.assertIn("parameter_conditional_ensemble_only", common)
        self.assertIn("Conditional input is not science_validated", common)
        for module in (
            "fig_model_performance_uncertainty.R",
            "fig_treatment_residual_uncertainty.R",
        ):
            text = (PAPER_R / module).read_text(encoding="utf-8")
            for forbidden in ("PestHarvest", "PestTmtGrow", ".par.csv", "read.csv"):
                self.assertNotIn(forbidden, text, f"{module} contains {forbidden}")

    def test_r_terminology_uses_conditional_interval_wording(self):
        text = (PAPER_R / "fig_model_performance_uncertainty.R").read_text(encoding="utf-8").lower()
        self.assertIn("conditional-ensemble prediction interval", text)
        self.assertNotIn("confidence interval", text)
        self.assertNotIn("credible interval", text)


class TestFrozenDemoBundle(unittest.TestCase):
    """Gate checks against the generated 20-member DEMO bundle when present."""

    BUNDLE = RUN_FIXTURE / "paper_data" / "conditional_predictions_demo20"

    def setUp(self):
        if not (self.BUNDLE / "paper_data_manifest.json").is_file():
            self.skipTest("demo20 bundle not generated on this machine")

    def test_manifest_hashes_and_required_artifacts(self):
        manifest = json.loads((self.BUNDLE / "paper_data_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["bundle_type"], "conditional_ensemble_predictions")
        self.assertEqual(manifest["interval_semantics"], "parameter_conditional_ensemble_only")
        self.assertEqual(manifest["data_status"], "legacy_layout_demo")
        names = {artifact["path"] for artifact in manifest["artifacts"]}
        for required in (
            "conditional_prediction_summary.csv",
            "conditional_trajectory_summary.csv",
            "conditional_residual_by_treatment_member.csv",
            "treatment_metadata_two_season.csv",
            "conditional_replay_quality.json",
        ):
            self.assertIn(required, names)
        for artifact in manifest["artifacts"]:
            digest = hashlib.sha256((self.BUNDLE / artifact["path"]).read_bytes()).hexdigest()
            self.assertEqual(digest, artifact["sha256"], artifact["path"])

    def test_full_two_spring_coverage_roles_and_uniform_members(self):
        prediction = pd.read_csv(
            self.BUNDLE / "conditional_prediction_summary.csv", dtype={"treatment": str}
        )
        counts = prediction.groupby(["season_id", "dataset_role"])["treatment"].nunique().to_dict()
        self.assertEqual(counts[("25SP", "calibration")], 4)
        self.assertEqual(counts[("25SP", "validation")], 6)
        self.assertEqual(counts[("26SP", "calibration")], 4)
        self.assertEqual(counts[("26SP", "validation")], 8)
        self.assertNotIn("25FA", set(prediction["season_id"]))
        self.assertTrue((prediction["n_members_valid"] == prediction["n_members_expected"]).all())
        self.assertTrue((prediction["observed"] > -90).all())
        self.assertTrue(
            ((prediction["sim_q025"] <= prediction["sim_q25"])
             & (prediction["sim_q25"] <= prediction["sim_median"])
             & (prediction["sim_median"] <= prediction["sim_q75"])
             & (prediction["sim_q75"] <= prediction["sim_q975"])).all()
        )

    def test_cumulative_quantiles_non_decreasing(self):
        prediction = pd.read_csv(
            self.BUNDLE / "conditional_prediction_summary.csv", dtype={"treatment": str}
        )
        for variable in CUMULATIVE_VARIABLES:
            part = prediction[prediction["variable"] == variable]
            self.assertFalse(part.empty, variable)
            for column in ("sim_q025", "sim_q25", "sim_median", "sim_q75", "sim_q975"):
                for _, group in part.groupby(["season_id", "treatment"]):
                    values = group.sort_values("dap")[column].to_numpy(float)
                    self.assertTrue(np.all(np.diff(values) >= -1e-9), f"{variable}/{column}")

    def test_residual_table_carries_member_phi_and_status(self):
        residual = pd.read_csv(self.BUNDLE / "conditional_residual_by_treatment_member.csv")
        self.assertTrue(residual["member_phi"].notna().any())
        self.assertTrue((residual["member_status"] != "unknown").all())

    def test_quality_json_records_environment_and_demo_gate(self):
        quality = json.loads((self.BUNDLE / "conditional_replay_quality.json").read_text(encoding="utf-8"))
        self.assertFalse(quality["science"]["science_validated"])
        self.assertTrue(quality["science"]["demo_mode"])
        self.assertEqual(quality["interval_semantics"], "parameter_conditional_ensemble_only")
        self.assertEqual(quality["replay_environment"]["dssat_exe_sha256"], OFFICIAL_EXE_SHA)
        self.assertGreaterEqual(quality["members"]["valid_rate"], 0.98)
        self.assertEqual(
            quality["observed_consistency"], "verified_identical_across_members"
        )


class TestVariableSpecsCoverContract(unittest.TestCase):
    def test_contract_variables_have_specs(self):
        for variable in ("DRY_INC", "DRY_CUM", "FRESH_INC", "FRESH_CUM", "LAID", "LWAD", "SWAD"):
            self.assertIn(variable, VARIABLE_SPECS)


if __name__ == "__main__":
    unittest.main()
