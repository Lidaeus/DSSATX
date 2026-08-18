import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import pyemu

from src.calibration.design_config import (
    apply_observation_stage,
    apply_parameter_stage,
    load_design_config,
    load_frozen_bounds_lookup,
)
from src.calibration.finalize_calibration import (
    _science_evidence,
    finalize_calibration,
    verify_calibration_artifact_manifest,
)
from src.calibration.observation_policy import apply_observation_policy
from src.calibration.prior_coverage import summarize_prior_coverage
from src.calibration.stage_representative import resolve_final_iteration, write_stage_representative
from src.calibration.engineering_gate import engineering_status, profile_for_run
from src.common.quality import (
    read_flat_run_manifest_field,
    serialize_manifest_scalar,
)
from src.reporting.quality_gate import assess_ies_run
from tools.package_sa_evidence import package_sa_evidence
from src.calibration.build_pest import (
    _build_ins_and_obs,
    _finalize_ies_contract,
    _fixed_from_provenance,
    _resolve_upstream_run_dir,
    _write_observation_noise_ensemble,
    _write_run_manifest,
)


DESIGN = Path("configs/runs/eggplant_p1_v4_design_20260717.json")


def test_design_stage_releases_only_declared_parameters_and_calibration_rows():
    spec = load_design_config(DESIGN, "S1")
    # Non-collapsed bounds so apply_parameter_stage does not require a
    # frozen_bounds lookup; this test is about parameter/observation filtering.
    params = [
        {"name": "EM-FL", "init": 23.3, "lower": 23.0, "upper": 31.0},
        {"name": "TRIFL", "init": 0.64, "lower": 0.2, "upper": 0.85},
        {"name": "NSTFAC", "init": 0.5, "lower": 0.3, "upper": 0.85},
    ]
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
    # Active parameters are marked with PEST's free-adjustable transform "none"
    # (the build copies `status` into `partrans`), not the "active" label used
    # in the frozen bounds CSV.
    assert staged["NSTFAC"]["status"] == "none"
    assert spec.observation["outputs"]["PestJoint.OUT"] == ["LAIX", "CNAM"]
    assert "PestHarvest.OUT" not in spec.observation["outputs"]
    assert spec.observation["representative_outputs"]["PestHarvest.OUT"] == ["PWAI", "PWAD"]
    assert "HWAM" not in spec.observation["outputs"]["PestJoint.OUT"]


def test_continuous_harvest_stages_do_not_use_season_end_hwam_or_duplicate_pwam():
    for stage in ("S2", "S3", "S4"):
        outputs = load_design_config(DESIGN, stage).observation["outputs"]
        assert "HWAM" not in outputs.get("PestJoint.OUT", [])
        assert "PWAM" not in outputs.get("PestJoint.OUT", [])
        if stage == "S2":
            assert "PestHarvest.OUT" not in outputs
        elif stage == "S3":
            assert outputs["PestHarvest.OUT"] == ["PWAI"]
    assert set(load_design_config(DESIGN, "S3").stage_config["fixed_params"]) == {
        "EM-FL", "TRIFL", "NSTFAC", "RTNO3", "NMOBMX", "NVSMOB"
    }
    assert set(load_design_config(DESIGN, "S4").stage_config["fixed_params"]) == {"XFRT", "XFINT"}
    s4 = load_design_config(DESIGN, "S4")
    # Non-collapsed bounds so no frozen_bounds lookup is needed here; this
    # assertion is about which params are released/fixed, not range restoration.
    s4_params = [
        {"name": name, "init": 1.0, "lower": 0.5, "upper": 1.5}
        for name in ("EM-FL", "TRIFL", "NSTFAC", "RTNO3", "NMOBMX", "NVSMOB", "XFRT", "XFINT")
    ]
    released = {item["name"]: item for item in apply_parameter_stage(s4_params, s4)}
    assert set(released) == {item["name"] for item in s4_params}
    assert all(released[name]["status"] == "fixed" for name in ("XFRT", "XFINT"))


def test_hwam_cannot_be_reintroduced_as_a_calibration_target():
    frame = pd.DataFrame({
        "@RUN": [1],
        "TN": [2],
        "HWAMM": [4000.0],
        "HWAMS": [3500.0],
    })
    with pytest.raises(ValueError, match="HWAM is diagnostic-only"):
        _build_ins_and_obs(
            frame,
            obs_bases={"HWAM"},
            critical_obs=set(),
            model_out_path="PestJoint.OUT",
            group_sigmas={"HWAMM": 50.0},
        )


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
        "raw_sigma": [200.0, 400.0],
        "sigma": [2.0, 4.0],
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
    # The ensemble must use uncertainty on the same scale as PST obsval, not
    # the raw-scale uncertainty retained only for provenance.
    expected = np.random.default_rng(123).normal(
        loc=np.array([[10.0, 20.0]]),
        scale=np.array([[2.0, 4.0]]),
        size=(4, 2),
    )
    np.testing.assert_allclose(
        values_first[["obs_a", "obs_b"]].to_numpy(), expected, rtol=0, atol=1e-10
    )


def test_formal_staged_contract_disables_relative_phi_screening(tmp_path):
    pst = pyemu.Pst.from_par_obs_names(["P"], ["OBS_A"])
    obs_name = pst.observation_data.index[0]
    pst.observation_data.loc[obs_name, "obsval"] = 10.0
    pst.observation_data.loc[obs_name, "weight"] = 0.5
    pst_path = tmp_path / "case.pst"
    pst.write(str(pst_path))
    pd.DataFrame({"obsnme": ["OBS_A"], "raw_sigma": [200.0], "sigma": [2.0]}).to_csv(
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


def test_treatment_roles_reject_cross_role_overlap(tmp_path):
    payload = json.loads(DESIGN.read_text(encoding="utf-8"))
    split_path = Path("configs/runs/xxql2501_v4_validation_split_20260717.json")
    split = json.loads(split_path.read_text(encoding="utf-8"))
    split["treatment_roles"]["validation"].append(split["treatment_roles"]["calibration"][0])
    split_out = tmp_path / "split.json"
    split_out.write_text(json.dumps(split), encoding="utf-8")
    payload["validation_split_id"] = "split"
    path = tmp_path / "design.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate treatment IDs"):
        load_design_config(path, "S1")


def test_unknown_treatment_role_is_rejected_before_phi():
    spec = load_design_config(DESIGN, "S1")
    outputs = [{
        "model_out_path": "PestEval.OUT",
        "df": pd.DataFrame({"TN": [2, 999], "ADAP": [1.0, 2.0]}),
    }]
    with pytest.raises(ValueError, match="unrecognized treatment IDs"):
        apply_observation_stage(outputs, spec, [{"run": 1, "tn": 2}])


def test_fixed_from_requires_upstream_run_and_finalize_provenance(tmp_path):
    source = tmp_path / "s1_representative_params.csv"
    source.write_text("name,value\nEM-FL,20\n", encoding="utf-8")
    with pytest.raises(ValueError, match="run_manifest.yaml"):
        _fixed_from_provenance([str(source)])
    (tmp_path / "run_manifest.yaml").write_text(
        'run_id: "s1_case"\n', encoding="utf-8"
    )
    finalize_dir = tmp_path / "calibration_finalize"
    finalize_dir.mkdir()
    (finalize_dir / "calibration_finalize.json").write_text(json.dumps({
        "engineering_status": "engineering_validated",
        "science_status": "science_pending",
    }), encoding="utf-8")
    records = _fixed_from_provenance([str(source)])
    assert records[0]["run_id"] == "s1_case"
    assert records[0]["science_status"] == "science_pending"
    assert len(records[0]["sha256"]) == 64


def test_fixed_from_rejects_manifest_finalize_case_mismatch(tmp_path):
    source = tmp_path / "stage_representative_params.csv"
    source.write_text("name,value\nEM-FL,20\n", encoding="utf-8")
    (tmp_path / "run_manifest.yaml").write_text(
        'run_id: "run_A"\ndesign_stage: "S1"\napproval_scope: "tooling_development"\n',
        encoding="utf-8",
    )
    finalize_dir = tmp_path / "calibration_finalize"
    finalize_dir.mkdir()
    (finalize_dir / "calibration_finalize.json").write_text(json.dumps({
        "case": "run_B",
        "engineering_status": "engineering_validated",
        "science_status": "science_pending",
        "stage_representative": {"sha256": "x"},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="run_id.*finalize case"):
        _fixed_from_provenance(
            [str(source)], current_stage="S2", approval_scope="tooling_development"
        )


def test_fixed_from_rejects_non_adjacent_stage(tmp_path):
    source = tmp_path / "stage_representative_params.csv"
    source.write_text("name,value\nEM-FL,20\n", encoding="utf-8")
    (tmp_path / "run_manifest.yaml").write_text(
        'run_id: "run_A"\ndesign_stage: "S1"\ndesign_table_id: "design"\napproval_scope: "tooling_development"\n',
        encoding="utf-8",
    )
    finalize_dir = tmp_path / "calibration_finalize"
    finalize_dir.mkdir()
    import hashlib
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    (finalize_dir / "calibration_finalize.json").write_text(json.dumps({
        "case": "run_A", "design_stage": "S1", "design_table_id": "design",
        "approval_scope": "tooling_development", "engineering_status": "engineering_validated",
        "stage_representative": {"sha256": digest},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="S3 must inherit S2"):
        _fixed_from_provenance(
            [str(source)], current_stage="S3", design_table_id="design",
            approval_scope="tooling_development"
        )


def test_fixed_from_rejects_tampered_representative_hash(tmp_path):
    source = tmp_path / "stage_representative_params.csv"
    source.write_text("name,value\nEM-FL,20\n", encoding="utf-8")
    (tmp_path / "run_manifest.yaml").write_text(
        'run_id: "run_A"\ndesign_stage: "S1"\ndesign_table_id: "design"\napproval_scope: "tooling_development"\n',
        encoding="utf-8",
    )
    finalize_dir = tmp_path / "calibration_finalize"
    finalize_dir.mkdir()
    (finalize_dir / "calibration_finalize.json").write_text(json.dumps({
        "case": "run_A", "design_stage": "S1", "design_table_id": "design",
        "approval_scope": "tooling_development", "engineering_status": "engineering_validated",
        "stage_representative": {"sha256": "0" * 64},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="representative file hash .* does not match finalize"):
        _fixed_from_provenance(
            [str(source)], current_stage="S2", design_table_id="design",
            approval_scope="tooling_development"
        )


def test_member_drop_without_evidence_is_not_inferred_as_failure_or_screening(tmp_path):
    prefix = "case"
    pd.DataFrame({"real_name": ["r0", "r1"], "p": [1.0, 2.0]}).to_csv(
        tmp_path / f"{prefix}.0.par.csv", index=False
    )
    pd.DataFrame({"real_name": ["r0"], "p": [1.1]}).to_csv(
        tmp_path / f"{prefix}.1.par.csv", index=False
    )
    pd.DataFrame({"real_name": ["r0"], "o": [3.0]}).to_csv(
        tmp_path / f"{prefix}.1.obs.csv", index=False
    )
    pd.DataFrame({"iteration": [0, 1], "r0": [2.0, 1.0], "r1": [4.0, None]}).to_csv(
        tmp_path / f"{prefix}.phi.actual.csv", index=False
    )
    assess_ies_run(tmp_path, prefix)
    status = pd.read_csv(tmp_path / "ies_quality" / f"{prefix}.member_status.csv")
    assert {
        "real_name", "first_seen_iteration", "last_seen_iteration",
        "final_status", "reason", "evidence_source",
    }.issubset(status.columns)
    assert status.loc[status.real_name == "r1", "final_status"].iloc[0] == "other_dropped"
    (tmp_path / f"{prefix}.rec").write_text(
        "...dropping par:obs realizations: 1 : r1 , 2 : r2\n", encoding="utf-8"
    )
    assess_ies_run(tmp_path, prefix)
    status = pd.read_csv(tmp_path / "ies_quality" / f"{prefix}.member_status.csv")
    assert status.loc[status.real_name == "r1", "final_status"].iloc[0] == "high_phi_screened"


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


def test_tooling_development_finalize_can_never_promote(tmp_path):
    (tmp_path / "case.0.par.csv").write_text(",a\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.1.par.csv").write_text(",a\n0,1.1\n1,2.1\n", encoding="utf-8")
    (tmp_path / "case.1.obs.csv").write_text(",y\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.phi.actual.csv").write_text("iteration,0,1\n1,1,2\n", encoding="utf-8")
    (tmp_path / "run_manifest.yaml").write_text(
        'approval_scope: "tooling_development"\n', encoding="utf-8"
    )
    (tmp_path / "science_validation_manifest.json").write_text(json.dumps({
        "group_phi_checked": True,
        "deterministic_rerun_checked": True,
        "validation_split_frozen": True,
        "source_hashes_bound": True,
    }), encoding="utf-8")
    payload = finalize_calibration(tmp_path, "case")
    assert payload["science_status"] == "science_pending"
    assert payload["science_failures"] == ["science_promotion_disabled_until_machine_evidence"]


def test_science_evidence_booleans_cannot_promote_automatically(tmp_path):
    (tmp_path / "science_validation_manifest.json").write_text(json.dumps({
        "group_phi_checked": True,
        "deterministic_rerun_checked": True,
        "validation_split_frozen": True,
        "source_hashes_bound": True,
    }), encoding="utf-8")
    ok, failures = _science_evidence(tmp_path)
    assert ok is False
    assert failures == ["science_promotion_disabled_until_machine_evidence"]


def test_degenerate_formal_ies_cannot_pass_engineering_gate(tmp_path):
    (tmp_path / "case.0.par.csv").write_text(",a\n0,1\n1,1\n", encoding="utf-8")
    (tmp_path / "case.1.par.csv").write_text(",a\n0,1\n1,1\n", encoding="utf-8")
    (tmp_path / "case.1.obs.csv").write_text(",y\n0,1\n1,1\n", encoding="utf-8")
    (tmp_path / "case.phi.actual.csv").write_text(
        "iteration,0,1\n0,5,5\n1,5,5\n", encoding="utf-8"
    )
    (tmp_path / "case.pst").write_text("* control data\n", encoding="utf-8")
    payload = finalize_calibration(tmp_path, "case")
    assert payload["engineering_status"] == "engineering_failed"
    assert any(
        item in payload["engineering_failures"]
        for item in ("ies_prior_variation", "ies_simulation_variation", "ies_phi_variation", "ies_parameter_update")
    )


def test_stage_representative_is_median_and_reproducibly_recorded(tmp_path):
    pd.DataFrame({"real_name": ["r0", "r1", "r2"], "P": [1.0, 3.0, 5.0]}).to_csv(
        tmp_path / "case.2.par.csv", index=False
    )
    result = write_stage_representative(tmp_path, "case")
    assert result is not None
    table = pd.read_csv(tmp_path / "calibration_finalize" / "stage_representative_params.csv")
    assert table.loc[table.name == "P", "value"].iloc[0] == pytest.approx(3.0)
    meta = json.loads((tmp_path / "calibration_finalize" / "stage_representative_params.json").read_text())
    assert meta["rule"] == "median_of_final_parameter_ensemble"
    assert result["sha256"] == meta["output_sha256"]


def test_final_iteration_ignores_stale_higher_ensemble_beyond_phi(tmp_path):
    pd.DataFrame({"real_name": ["0"], "p": [3.0]}).to_csv(
        tmp_path / "case.3.par.csv", index=False
    )
    pd.DataFrame({"real_name": ["0"], "p": [999.0]}).to_csv(
        tmp_path / "case.5.par.csv", index=False
    )
    pd.DataFrame({"iteration": [0, 1, 2, 3], "mean": [4.0, 3.0, 2.0, 1.0]}).to_csv(
        tmp_path / "case.phi.actual.csv", index=False
    )
    iteration, source = resolve_final_iteration(tmp_path, "case")
    assert iteration == 3
    assert source.name == "case.3.par.csv"


def test_finalize_manifest_representative_fields_are_upserted(tmp_path):
    (tmp_path / "case.0.par.csv").write_text(",a\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.1.par.csv").write_text(",a\n0,1.1\n1,2.1\n", encoding="utf-8")
    (tmp_path / "case.1.obs.csv").write_text(",y\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.phi.actual.csv").write_text("iteration,0,1\n0,1,2\n1,0.5,1.5\n", encoding="utf-8")
    (tmp_path / "run_manifest.yaml").write_text(
        'run_id: "case"\ndesign_stage: "S1"\ndesign_table_id: "design"\napproval_scope: "tooling_development"\n',
        encoding="utf-8",
    )
    finalize_calibration(tmp_path, "case")
    finalize_calibration(tmp_path, "case")
    manifest = (tmp_path / "run_manifest.yaml").read_text(encoding="utf-8")
    assert manifest.count("stage_representative_params_sha256:") == 1


def test_finalize_writes_minimal_artifact_hash_manifest(tmp_path):
    """finalize must emit a SHA-256 manifest for the core per-stage artifacts
    (PST, final ensemble, Phi, quality report, member status, finalize payload,
    representative params, and any representative deterministic-rerun outputs),
    closing the gap the T3.1 review flagged: run_manifest did not bind these.
    The _agents/ temp tree is intentionally excluded."""
    (tmp_path / "case.0.par.csv").write_text(",a\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.1.par.csv").write_text(",a\n0,1.1\n1,2.1\n", encoding="utf-8")
    (tmp_path / "case.1.obs.csv").write_text(",y\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.phi.actual.csv").write_text("iteration,0,1\n0,1,2\n1,0.5,1.5\n", encoding="utf-8")
    (tmp_path / "case.pst").write_text("* pst stub\n", encoding="utf-8")
    (tmp_path / "run_manifest.yaml").write_text(
        'run_id: "case"\ndesign_stage: "S1"\ndesign_table_id: "design"\napproval_scope: "tooling_development"\n',
        encoding="utf-8",
    )
    # Representative deterministic-rerun outputs (only .OUT files are hashed).
    rerun = tmp_path / "representative_deterministic_rerun"
    rerun.mkdir()
    (rerun / "PestTmtGrow.OUT").write_text("@LAIDS 1.0\n", encoding="utf-8")
    (rerun / "PestHarvest.OUT").write_text("@PWAIS 2.0\n", encoding="utf-8")
    payload = finalize_calibration(tmp_path, "case")
    manifest_path = Path(payload["calibration_artifacts_manifest"])
    assert manifest_path.is_file()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = {a["role"] for a in data["artifacts"]}
    # Core scientific artifacts that run_manifest did not previously bind.
    assert {"pst", "final_parameter_ensemble", "final_observation_ensemble", "phi_actual",
            "quality_report", "member_status", "finalize_payload",
            "stage_representative_params"} <= roles
    # Deterministic-rerun outputs are included...
    rerun_artifacts = [a for a in data["artifacts"]
                       if a["role"] == "representative_deterministic_rerun_output"]
    assert {Path(a["path"]).name for a in rerun_artifacts} == {"PestTmtGrow.OUT", "PestHarvest.OUT"}
    # ...and every entry has a 64-char sha256 plus a run_dir-relative path.
    for artifact in data["artifacts"]:
        assert len(artifact["sha256"]) == 64
        assert not Path(artifact["path"]).is_absolute()
        assert "\\" not in artifact["path"]  # portable JSON paths on Windows too
        assert (tmp_path / artifact["path"]).is_file()
    # No _agents/ path leaks in (the manifest is minimal by design).
    assert not any("_agents" in a["path"] for a in data["artifacts"])
    verified = verify_calibration_artifact_manifest(tmp_path, "case")
    assert verified["artifact_count"] == len(verified["artifacts"])
    with pytest.raises(ValueError, match="missing required deterministic rerun outputs"):
        verify_calibration_artifact_manifest(
            tmp_path, "case", required_rerun_outputs={"Evaluate.OUT"}
        )


def test_artifact_manifest_verifier_rejects_tampered_output(tmp_path):
    """A generated hash list is useful only when downstream tools reject
    mutated artifacts before reading them."""
    (tmp_path / "case.0.par.csv").write_text(",a\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.1.par.csv").write_text(",a\n0,1.1\n1,2.1\n", encoding="utf-8")
    (tmp_path / "case.1.obs.csv").write_text(",y\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.phi.actual.csv").write_text(
        "iteration,0,1\n0,1,2\n1,0.5,1.5\n", encoding="utf-8"
    )
    (tmp_path / "case.pst").write_text("* pst stub\n", encoding="utf-8")
    (tmp_path / "run_manifest.yaml").write_text(
        'run_id: "case"\ndesign_stage: "S1"\ndesign_table_id: "design"\n'
        'approval_scope: "tooling_development"\n',
        encoding="utf-8",
    )
    finalize_calibration(tmp_path, "case")
    verify_calibration_artifact_manifest(tmp_path, "case")
    with (tmp_path / "case.1.par.csv").open("a", encoding="utf-8") as handle:
        handle.write("2,999\n")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        verify_calibration_artifact_manifest(tmp_path, "case")


def test_prior_only_profile_allows_no_update_but_requires_variation(tmp_path):
    prefix = "prior"
    pd.DataFrame({"real_name": ["r0", "r1"], "p": [1.0, 2.0]}).to_csv(
        tmp_path / f"{prefix}.0.par.csv", index=False
    )
    pd.DataFrame({"real_name": ["r0", "r1"], "o": [1.0, 2.0]}).to_csv(
        tmp_path / f"{prefix}.0.obs.csv", index=False
    )
    pd.DataFrame({"iteration": [0], "0": [1.0], "1": [2.0]}).to_csv(
        tmp_path / f"{prefix}.phi.actual.csv", index=False
    )
    pst = pyemu.Pst.from_par_obs_names(["p"], ["o"])
    pst.control_data.noptmax = 0
    pst.write(str(tmp_path / f"{prefix}.pst"))
    report = assess_ies_run(tmp_path, prefix)
    assert profile_for_run(tmp_path, prefix) == "prior_only"
    status, failures = engineering_status(report, "prior_only")
    assert status == "engineering_validated", failures


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


# ---------------------------------------------------------------------------
# T2.2 regression tests: stage-inheritance path, manifest YAML scalars, and
# the design↔CLI contract cross-check. These reproduce the five findings from
# the staged-calibration tooling review and guard against silent regressions.
# ---------------------------------------------------------------------------


def _write_finalise_subdir_layout(
    run_dir: Path,
    *,
    run_id: str = "run_A",
    design_stage: str = "S1",
    design_table_id: str = "design",
    approval_scope: str = "tooling_development",
    representative_rows: str = "name,value\nEM-FL,20\nTRIFL,0.6\n",
) -> Path:
    """Build the real finalize subdir layout produced by write_stage_representative.

    The representative CSV lives at ``<run_dir>/calibration_finalize/
    stage_representative_params.csv`` while the manifest and finalize json sit
    one level up — exactly the layout that previously broke
    ``_fixed_from_provenance`` when it treated ``source.parent`` as the run dir.
    """
    finalize_dir = run_dir / "calibration_finalize"
    finalize_dir.mkdir(parents=True, exist_ok=True)
    source = finalize_dir / "stage_representative_params.csv"
    source.write_text(representative_rows, encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    (run_dir / "run_manifest.yaml").write_text(
        f'run_id: "{run_id}"\n'
        f'design_stage: "{design_stage}"\n'
        f'design_table_id: "{design_table_id}"\n'
        f'approval_scope: "{approval_scope}"\n',
        encoding="utf-8",
    )
    (finalize_dir / "calibration_finalize.json").write_text(json.dumps({
        "case": run_id,
        "design_stage": design_stage,
        "design_table_id": design_table_id,
        "approval_scope": approval_scope,
        "engineering_status": "engineering_validated",
        "science_status": "science_pending",
        "stage_representative": {"sha256": digest},
    }), encoding="utf-8")
    (finalize_dir / "stage_representative_params.json").write_text(json.dumps({
        "schema_version": 1,
        "rule": "median_of_final_parameter_ensemble",
        "case": run_id,
        "source": "run_A.2.par.csv",
        "source_sha256": "0" * 64,
        "iteration": 2,
        "output": "stage_representative_params.csv",
        "output_sha256": digest,
    }), encoding="utf-8")
    return source


def test_fixed_from_locates_run_dir_from_finalize_subdir(tmp_path):
    """Finding 1 [P0]: the auto-generated representative CSV sits under
    ``<run_dir>/calibration_finalize/`` and must resolve back to ``<run_dir>``."""
    run_dir = tmp_path / "s1_run"
    run_dir.mkdir()
    source = _write_finalise_subdir_layout(run_dir)

    run_dir_resolved, manifest, finalize, metadata = _resolve_upstream_run_dir(source)
    assert run_dir_resolved == run_dir.resolve()
    assert manifest.name == "run_manifest.yaml"
    assert finalize.name == "calibration_finalize.json"
    assert metadata.name == "stage_representative_params.json"

    records = _fixed_from_provenance(
        [str(source)], current_stage="S2", design_table_id="design",
        approval_scope="tooling_development",
    )
    assert records[0]["run_id"] == "run_A"
    assert records[0]["design_stage"] == "S1"
    assert records[0]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_fixed_from_rejects_unknown_layout(tmp_path):
    """A representative CSV floating in a directory with no manifest/finalize
    must fail with a message naming the two supported placements."""
    floating = tmp_path / "stage_representative_params.csv"
    floating.write_text("name,value\nEM-FL,20\n", encoding="utf-8")
    with pytest.raises(ValueError, match="run_manifest.yaml"):
        _resolve_upstream_run_dir(floating)


def test_fixed_from_rejects_three_way_hash_mismatch(tmp_path):
    """Finding 5 [T2.2 task 4]: if the representative metadata json's
    ``output_sha256`` disagrees with the finalize hash and the file bytes,
    the inheritance must fail before any downstream build consumes it."""
    run_dir = tmp_path / "s1_run"
    run_dir.mkdir()
    source = _write_finalise_subdir_layout(run_dir)
    # Tamper with the metadata json's hash only; finalize and file still agree.
    metadata_path = run_dir / "calibration_finalize" / "stage_representative_params.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["output_sha256"] = "f" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="representative hash disagreement"):
        _fixed_from_provenance(
            [str(source)], current_stage="S2", design_table_id="design",
            approval_scope="tooling_development",
        )


def test_manifest_scalar_round_trips_windows_path():
    """Finding 2 [P1]: a Windows path with backslashes must serialize as a
    valid YAML scalar and round-trip through the project reader unchanged."""
    raw = r"D:\Tomato_Cal\workspace\runs\s1_run"
    line = f"stage_representative_params: {serialize_manifest_scalar(raw)}"
    assert "'D:\\Tomato_Cal\\workspace\\runs\\s1_run'" in line  # single-quoted, backslashes literal
    manifest = tmp_path_manifest = Path(__file__).parent / "_scalar_roundtrip_manifest.yaml"
    try:
        tmp_path_manifest.write_text(line + "\n", encoding="utf-8")
        assert read_flat_run_manifest_field(tmp_path_manifest, "stage_representative_params") == raw
    finally:
        tmp_path_manifest.unlink(missing_ok=True)
    # Standard YAML must also accept it (pyyaml is a project dependency via flopy).
    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load(line)
    assert parsed["stage_representative_params"] == raw


def test_write_run_manifest_emits_valid_yaml_for_windows_paths(tmp_path):
    """Finding 2 (related): ``_write_run_manifest`` had the same backslash bug
    as ``_upsert_manifest_fields``. A path-typed value must render as a
    standard-YAML-parseable scalar."""
    manifest_path = _write_run_manifest(
        str(tmp_path),
        run_id="s1_case",
        stage_representative_params=r"D:\Tomato_Cal\workspace\s1_run\rep.csv",
        n_params=2,
    )
    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load(Path(manifest_path).read_text(encoding="utf-8"))
    assert parsed["run_id"] == "s1_case"
    assert parsed["stage_representative_params"] == r"D:\Tomato_Cal\workspace\s1_run\rep.csv"
    assert parsed["n_params"] == 2
    # Project reader must round-trip the path too.
    assert read_flat_run_manifest_field(manifest_path, "stage_representative_params") == \
        r"D:\Tomato_Cal\workspace\s1_run\rep.csv"


def test_finalize_upsert_manifest_with_windows_path_is_valid_yaml(tmp_path):
    """Finding 2 end-to-end: finalize upserts the representative path (a
    Windows absolute path) into the manifest; the result must be readable by
    both the project reader and a standard YAML parser."""
    (tmp_path / "case.0.par.csv").write_text(",a\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.1.par.csv").write_text(",a\n0,1.1\n1,2.1\n", encoding="utf-8")
    (tmp_path / "case.1.obs.csv").write_text(",y\n0,1\n1,2\n", encoding="utf-8")
    (tmp_path / "case.phi.actual.csv").write_text("iteration,0,1\n0,1,2\n1,0.5,1.5\n", encoding="utf-8")
    manifest = tmp_path / "run_manifest.yaml"
    manifest.write_text(
        'run_id: "case"\ndesign_stage: "S1"\ndesign_table_id: "design"\n'
        'approval_scope: "tooling_development"\n',
        encoding="utf-8",
    )
    finalize_calibration(tmp_path, "case")
    yaml = pytest.importorskip("yaml")
    parsed = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    representative_path = parsed["stage_representative_params"]
    # On Windows this is a backslash path; on POSIX the temp dir has no
    # backslashes. Either way the value must equal what the project reader
    # returns and contain "stage_representative_params.csv".
    assert representative_path.endswith("stage_representative_params.csv")
    assert read_flat_run_manifest_field(manifest, "stage_representative_params") == representative_path
    assert parsed["stage_representative_params_sha256"] == \
        read_flat_run_manifest_field(manifest, "stage_representative_params_sha256")


def test_design_spec_exposes_bounds_input_policy_ids():
    """Finding 4 [P2]: DesignSpec must surface the declared contract ids so
    the staged entry can cross-check them against the CLI selection."""
    spec = load_design_config(DESIGN, "S2")
    assert spec.bounds_id == "eggplant_p1_xxql2501_v4_sobol20_20260717"
    assert spec.input_bundle == "xxql2501_20260716"
    assert spec.observation_policy_id == "assumption_based_sigma_v2"


def test_s4_re_releases_parameters_pinned_by_fixed_from(tmp_path):
    """S4 inherits the full S3 representative parameter set via --fixed-from,
    which collapses every inherited parameter to lower==upper==init. The S4
    design re-releases EM-FL/TRIFL/NSTFAC/RTNO3/NMOBMX/NVSMOB as active while
    keeping XFRT/XFINT fixed. apply_parameter_stage must restore the declared
    search range of the active parameters from the frozen bounds; without the
    frozen_bounds lookup the PST would end up with npar_adj=0 (all fixed) and
    S4 could not run."""
    spec = load_design_config(DESIGN, "S4")
    # Simulate the post-fixed-from state: every parameter collapsed to a point.
    representative_values = {
        "EM-FL": 23.2541, "TRIFL": 0.623152,
        "NSTFAC": 0.85, "RTNO3": 0.031359,
        "NMOBMX": 0.08, "NVSMOB": 0.37186,
        "XFRT": 0.9430525, "XFINT": 0.2822495,
    }
    params = []
    for name, val in representative_values.items():
        params.append({"name": name, "init": val, "lower": val, "upper": val, "status": "fixed"})

    # Without frozen_bounds the stage must now fail loudly rather than silently
    # leave active parameters with collapsed (lower==upper) bounds — that was
    # the historical silent-degradation path the review flagged.
    with pytest.raises(ValueError, match="collapsed bounds .* but no frozen bounds lookup"):
        apply_parameter_stage(params, spec)

    # With frozen_bounds: active parameters recover their full search range.
    bounds_lookup = load_frozen_bounds_lookup(
        "data/parameter_registry/bounds_frozen/eggplant/eggplant_p1_xxql2501_v4_sobol20_20260717.csv"
    )
    staged = {p["name"]: p for p in apply_parameter_stage(params, spec, frozen_bounds=bounds_lookup)}
    assert set(staged) == {"EM-FL", "TRIFL", "NSTFAC", "RTNO3", "NMOBMX", "NVSMOB", "XFRT", "XFINT"}
    for name in spec.active_params:
        assert staged[name]["status"] == "none"
        assert staged[name]["lower"] < staged[name]["upper"], f"{name} bounds still collapsed"
        # The inherited representative value stays as the starting point.
        assert staged[name]["init"] == representative_values[name]
    # XFRT/XFINT remain pinned at the S3 representative median.
    for name in ("XFRT", "XFINT"):
        assert staged[name]["status"] == "fixed"
        assert staged[name]["lower"] == staged[name]["upper"] == staged[name]["init"]


def test_apply_parameter_stage_rejects_missing_frozen_bound():
    """An active parameter with collapsed bounds but absent from the frozen
    bounds lookup must fail loudly instead of staying numerically fixed
    (Finding 3 [P2])."""
    spec = load_design_config(DESIGN, "S4")
    # All S4 active+fixed params present, but collapsed (post-fixed-from state).
    params = [
        {"name": n, "init": v, "lower": v, "upper": v, "status": "fixed"}
        for n, v in {"EM-FL": 23.3, "TRIFL": 0.64, "NSTFAC": 0.5, "RTNO3": 0.012,
                     "NMOBMX": 0.09, "NVSMOB": 0.38, "XFRT": 0.99, "XFINT": 0.3}.items()
    ]
    # Lookup that omits EM-FL entirely.
    incomplete = {n: (0.1, 1.0) for n in spec.active_params if n != "EM-FL"}
    with pytest.raises(ValueError, match="no active entry in the frozen bounds"):
        apply_parameter_stage(params, spec, frozen_bounds=incomplete)


def test_apply_parameter_stage_rejects_out_of_range_inherited_init():
    """An inherited init outside the restored bounds signals a real
    config/inheritance conflict; it must fail rather than be silently replaced
    by the midpoint (Finding 3 [P2])."""
    spec = load_design_config(DESIGN, "S4")
    params = [
        {"name": n, "init": v, "lower": v, "upper": v, "status": "fixed"}
        for n, v in {"EM-FL": 99.0, "TRIFL": 0.64, "NSTFAC": 0.5, "RTNO3": 0.012,
                     "NMOBMX": 0.09, "NVSMOB": 0.38, "XFRT": 0.99, "XFINT": 0.3}.items()
    ]
    # EM-FL frozen range is [23.0, 31.0]; 99.0 is well outside.
    bounds_lookup = {"EM-FL": (23.0, 31.0)}
    bounds_lookup.update({n: (0.1, 1.0) for n in spec.active_params if n != "EM-FL"})
    with pytest.raises(ValueError, match="inherited init 99.0 is outside the frozen bounds"):
        apply_parameter_stage(params, spec, frozen_bounds=bounds_lookup)


def test_apply_parameter_stage_rejects_non_finite_inherited_init():
    """A non-finite inherited init (e.g. from a corrupt representative CSV)
    must fail rather than be silently replaced (Finding 3 [P2])."""
    spec = load_design_config(DESIGN, "S4")
    params = [
        {"name": n, "init": v, "lower": v, "upper": v, "status": "fixed"}
        for n, v in {"EM-FL": float("nan"), "TRIFL": 0.64, "NSTFAC": 0.5, "RTNO3": 0.012,
                     "NMOBMX": 0.09, "NVSMOB": 0.38, "XFRT": 0.99, "XFINT": 0.3}.items()
    ]
    bounds_lookup = {"EM-FL": (23.0, 31.0)}
    bounds_lookup.update({n: (0.1, 1.0) for n in spec.active_params if n != "EM-FL"})
    with pytest.raises(ValueError, match="non-finite inherited init"):
        apply_parameter_stage(params, spec, frozen_bounds=bounds_lookup)
