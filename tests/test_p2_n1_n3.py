import json
from pathlib import Path

import pandas as pd
import pytest
import pyemu

from src.calibration.design_config import (
    apply_observation_stage,
    apply_parameter_stage,
    load_design_config,
)
from src.calibration.finalize_calibration import finalize_calibration
from src.calibration.observation_policy import apply_observation_policy
from src.calibration.prior_coverage import summarize_prior_coverage
from tools.package_sa_evidence import package_sa_evidence
from src.calibration.build_pest import _finalize_ies_contract, _write_observation_noise_ensemble


DESIGN = Path("configs/runs/eggplant_p1_v4_design_20260717.json")


def test_design_stage_releases_only_declared_parameters_and_calibration_rows():
    spec = load_design_config(DESIGN, "S1")
    params = [{"name": "EM-FL"}, {"name": "TRIFL"}, {"name": "NSTFAC"}]
    assert [p["name"] for p in apply_parameter_stage(params, spec)] == ["EM-FL", "TRIFL"]
    outputs = [{
        "model_out_path": "PestEval.OUT",
        "obs_bases": {"ADAP"},
        "df": pd.DataFrame({"@RUN": [1, 2], "TN": [2, 5], "LAIDM": [1.0, 2.0]}),
    }]
    selected, report = apply_observation_stage(outputs, spec, [{"run": 1, "tn": 2}, {"run": 2, "tn": 5}])
    assert len(selected) == 1
    assert selected[0]["df"]["TN"].tolist() == [2]
    assert report["rows_dropped"] == 1


def test_s2_fixed_baseline_parameters_are_not_released_as_active():
    spec = load_design_config(DESIGN, "S2")
    params = [
        {"name": "EM-FL", "init": 20.0, "lower": 10.0, "upper": 30.0, "status": "active"},
        {"name": "TRIFL", "init": 0.5, "lower": 0.2, "upper": 0.8, "status": "active"},
        {"name": "NSTFAC", "init": 0.5, "lower": 0.3, "upper": 0.85, "status": "active"},
        {"name": "RTNO3", "init": 0.5, "lower": 0.2, "upper": 1.0, "status": "active"},
        {"name": "NMOBMX", "init": 0.1, "lower": 0.08, "upper": 0.3, "status": "active"},
        {"name": "NVSMOB", "init": 0.3, "lower": 0.2, "upper": 0.5, "status": "active"},
    ]
    staged = {p["name"]: p for p in apply_parameter_stage(params, spec)}
    assert set(staged) == {"EM-FL", "TRIFL", "NSTFAC", "RTNO3", "NMOBMX", "NVSMOB"}
    for name in ("EM-FL", "TRIFL"):
        assert staged[name]["status"] == "fixed"
        assert staged[name]["lower"] == staged[name]["upper"] == staged[name]["init"]
    assert staged["NSTFAC"]["status"] == "active"
    assert spec.observation["outputs"]["PestJoint.OUT"] == ["LAIX", "CNAM"]
    assert spec.observation["outputs"]["PestHarvest.OUT"] == ["PWAD", "PWAI"]
    assert "HWAM" not in spec.observation["outputs"]["PestJoint.OUT"]


def test_continuous_harvest_stages_do_not_use_season_end_hwam_or_duplicate_pwam():
    for stage in ("S2", "S3", "S4"):
        outputs = load_design_config(DESIGN, stage).observation["outputs"]
        assert "HWAM" not in outputs.get("PestJoint.OUT", [])
        assert "PWAM" not in outputs.get("PestJoint.OUT", [])
        assert outputs["PestHarvest.OUT"] == ["PWAD", "PWAI"]


def test_observation_noise_contract_is_explicit_and_reproducible(tmp_path):
    pst = pyemu.Pst.from_par_obs_names(["P"], ["OBS_A", "OBS_B"])
    obs_names = list(pst.observation_data.index)
    pst.observation_data.loc[obs_names[0], "obsval"] = 10.0
    pst.observation_data.loc[obs_names[1], "obsval"] = 20.0
    pst.observation_data.loc[obs_names[0], "weight"] = 0.5
    pst.observation_data.loc[obs_names[1], "weight"] = 0.25
    pst_path = tmp_path / "case.pst"
    pst.write(str(pst_path))
    audit = pd.DataFrame({
        "obsnme": ["OBS_A", "OBS_B"],
        "raw_sigma": [2.0, 4.0],
    })
    audit_path = tmp_path / "case.weights.csv"
    audit.to_csv(audit_path, index=False)
    first, _, _ = _write_observation_noise_ensemble(
        pst_path, audit_path, tmp_path, "case", 4, 123
    )
    values_first = pd.read_csv(first)
    second, _, _ = _write_observation_noise_ensemble(
        pst_path, audit_path, tmp_path, "case", 4, 123
    )
    values_second = pd.read_csv(second)
    pd.testing.assert_frame_equal(values_first, values_second)
    assert list(values_first.columns) == ["real_name", "obs_a", "obs_b"]
    assert len(values_first) == 4


def test_formal_staged_contract_disables_relative_phi_screening(tmp_path):
    pst = pyemu.Pst.from_par_obs_names(["P"], ["OBS_A"])
    obs_name = pst.observation_data.index[0]
    pst.observation_data.loc[obs_name, "obsval"] = 10.0
    pst.observation_data.loc[obs_name, "weight"] = 0.5
    pst_path = tmp_path / "case.pst"
    pst.write(str(pst_path))
    pd.DataFrame({"obsnme": ["OBS_A"], "raw_sigma": [2.0]}).to_csv(
        tmp_path / "case.weights.csv", index=False
    )
    payload = _finalize_ies_contract(
        pst_path, tmp_path, "case", 2, 99, 1.0e300, observation_noise=True
    )
    loaded = pyemu.Pst(str(pst_path))
    assert float(loaded.pestpp_options["ies_bad_phi_sigma"]) >= 1.0e299
    assert payload["relative_phi_screening"] is False
    assert payload["observation_noise"] is True


def test_prior_coverage_report_separates_observation_conflict_from_member_loss(tmp_path):
    pdc = pd.DataFrame({
        "name": ["OBS_A", "OBS_B"],
        "obs_mean": [10.0, 20.0], "obs_std": [1.0, 1.0],
        "obs_min": [9.0, 19.0], "obs_max": [11.0, 21.0],
        "sim_mean": [15.0, 20.0], "sim_std": [0.5, 0.5],
        "sim_min": [14.0, 19.5], "sim_max": [16.0, 20.5],
        "distance": [5.0, 0.0],
    })
    pdc_path = tmp_path / "case.1.pdc.csv"
    pdc.to_csv(pdc_path, index=False)
    audit_path = tmp_path / "case.weights.csv"
    pd.DataFrame({"obsnme": ["OBS_A", "OBS_B"], "obgnme": ["G1", "G1"]}).to_csv(
        audit_path, index=False
    )
    group, report = summarize_prior_coverage(pdc_path, audit_path)
    assert report["observation_count"] == 2
    assert report["conflict_count"] == 1
    assert group.loc[0, "conflict_fraction"] == pytest.approx(0.5)


def test_s4_validation_selection_is_rejected(tmp_path):
    payload = json.loads(DESIGN.read_text(encoding="utf-8"))
    payload["stages"]["S4"]["active_params"] = ["EM-FL"]
    payload["stages"]["S4"]["selection_evidence"] = "select the best validation result"
    path = tmp_path / "design.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="calibration-only"):
        load_design_config(path, "S4")


def test_explicit_sigma_combines_model_discrepancy_and_floor():
    obs = pd.DataFrame([{
        "obsnme": "x", "obsval": 10.0, "raw_obsval": 10.0, "weight": 1.0,
        "obgnme": "LAIXM", "sigma": 2.0, "sim_token": "LAIXS",
        "model_output_file": "PestJoint.OUT",
    }])
    out, _ = apply_observation_policy(obs, {"LAIXM": {"sigma": "2", "model_sigma": "3", "sigma_floor": "4"}})
    assert out.iloc[0]["raw_sigma"] == pytest.approx((2**2 + 3**2 + 4**2) ** 0.5)


def test_finalize_calibration_does_not_promote_without_science_manifest(tmp_path):
    (tmp_path / "case.0.par.csv").write_text(",a\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.1.par.csv").write_text(",a\n0,1.1\n1,2.1\n", encoding="utf-8")
    (tmp_path / "case.1.obs.csv").write_text(",y\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.phi.actual.csv").write_text("iteration,0,1\n1,1,2\n", encoding="utf-8")
    (tmp_path / "run_status.json").write_text(json.dumps({"status": "completed"}), encoding="utf-8")
    payload = finalize_calibration(tmp_path, "case")
    assert payload["engineering_status"] == "engineering_validated"
    assert payload["science_status"] == "science_pending"
    quality = json.loads((tmp_path / "ies_quality" / "ies_run_quality.json").read_text(encoding="utf-8"))
    assert quality["science_validated"] is False
    assert quality["science_validation_mode"] == "engineering_only"
    status = json.loads((tmp_path / "run_status.json").read_text(encoding="utf-8"))
    assert status["scientific_status"] == "not_assessed"


def test_sa_evidence_packager_hashes_existing_outputs(tmp_path):
    morris = tmp_path / "morris"
    sobol = tmp_path / "sobol"
    morris.mkdir(); sobol.mkdir()
    (morris / "run_manifest.yaml").write_text("run_id: m\n", encoding="utf-8")
    (morris / "morris_result.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (sobol / "run_manifest.yaml").write_text("run_id: s\n", encoding="utf-8")
    (sobol / "case.sobol.si.csv").write_text("output,p\ny,0.2\n", encoding="utf-8")
    manifest = package_sa_evidence(morris, sobol, tmp_path / "bundle")
    assert manifest["computation"] == "reused_existing_outputs_no_new_model_runs"
    assert manifest["artifact_count"] == 4
    assert len(manifest["artifacts"][0]["sha256"]) == 64
