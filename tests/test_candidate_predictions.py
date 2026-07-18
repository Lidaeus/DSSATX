"""T4.2-A synthetic/negative tests for candidate_predictions.

No real DSSAT is run here: the deterministic rerun is replaced by an injected
synthetic runner that writes fixed Evaluate.OUT/PlantGro.OUT/FreshWt.OUT bytes.
These tests cover the 11 cases required by the T4.2 handoff §9 and verify the
frozen prediction-distance definition by hand-computable regressions.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from src.reporting import candidate_predictions as cp


# ---------------------------------------------------------------------------
# Helpers to build a minimal but contract-complete S4 run dir + posterior demo.
# ---------------------------------------------------------------------------

def _write_policy(path: Path) -> None:
    path.write_text(
        "group,transform,offset,reference,sigma,sigma_source,model_sigma,sigma_floor,group_multiplier,n_eff,phi_role,note\n"
        "ADAPM,raw,0,1,25.0,assumption,2.0,1.0,1.0,,calibration,d\n"
        "LAIXM,raw,0,1,0.8,assumption,0.2,0.1,1.0,,calibration,d\n"
        "CNAMM,raw,0,1,25.0,assumption,5.0,2.0,1.0,,calibration,d\n"
        "LAIDM,raw,0,1,2.0,assumption,0.5,0.2,1.0,,calibration,d\n"
        "LWADM,raw,0,1,150.0,assumption,20.0,10.0,1.0,,calibration,d\n"
        "SWADM,raw,0,1,200.0,assumption,25.0,10.0,1.0,,calibration,d\n"
        "PWADM,raw,0,1,250.0,assumption,30.0,20.0,1.0,,calibration,d\n"
        "PWAIM,raw,0,1,250.0,assumption,30.0,20.0,1.25,,calibration,d\n",
        encoding="utf-8",
    )


def _make_minimal_run_dir(tmp_path: Path, *, case: str = "s4", reals: int = 4) -> Path:
    """Build a minimal S4-shaped run dir with the hashes candidate_predictions checks."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    # Ensemble: real_name + 2 params.
    rows = [{"real_name": str(i), "em-fl": 23.0 + i * 0.1, "trifl": 0.2 + i * 0.05} for i in range(reals)]
    ensemble = run_dir / f"{case}.2.par.csv"
    pd.DataFrame(rows).to_csv(ensemble, index=False)
    # Artifact manifest pointing at the ensemble + a stub rerun dir.
    rerun = run_dir / "representative_deterministic_rerun"
    rerun.mkdir()
    for name in ("Evaluate.OUT", "PlantGro.OUT", "FreshWt.OUT"):
        (rerun / name).write_text("stub\n", encoding="utf-8")
    (run_dir / f"{case}.pst").write_text("pst\n", encoding="utf-8")
    (run_dir / f"{case}.2.obs.csv").write_text("real_name,o\n0,1\n", encoding="utf-8")
    (run_dir / f"{case}.phi.actual.csv").write_text("iteration,mean\n0,1\n", encoding="utf-8")
    finalize_dir = run_dir / "calibration_finalize"
    finalize_dir.mkdir()
    finalize_payload = {
        "schema_version": 1, "case": case,
        "engineering_status": "engineering_validated",
        "science_status": "science_pending",
        "scientific_status": "not_assessed",
        "stage_representative": {"sha256": "x" * 64},
    }
    finalize_path = finalize_dir / "calibration_finalize.json"
    finalize_path.write_text(json.dumps(finalize_payload), encoding="utf-8")
    (finalize_dir / "stage_representative_params.csv").write_text("name,value\nem-fl,23.0\n", encoding="utf-8")
    # Minimal artifact manifest with all required roles.
    artifacts = [
        {"role": "pst", "path": f"{case}.pst", "sha256": cp.sha256_file(run_dir / f"{case}.pst")},
        {"role": "final_parameter_ensemble", "path": f"{case}.2.par.csv", "sha256": cp.sha256_file(ensemble)},
        {"role": "final_observation_ensemble", "path": f"{case}.2.obs.csv", "sha256": cp.sha256_file(run_dir / f"{case}.2.obs.csv")},
        {"role": "phi_actual", "path": f"{case}.phi.actual.csv", "sha256": cp.sha256_file(run_dir / f"{case}.phi.actual.csv")},
        {"role": "quality_report", "path": "ies_quality/q.json", "sha256": "0" * 64},
        {"role": "member_status", "path": f"ies_quality/{case}.member_status.csv", "sha256": "0" * 64},
        {"role": "finalize_payload", "path": "calibration_finalize/calibration_finalize.json", "sha256": cp.sha256_file(finalize_path)},
        {"role": "stage_representative_params", "path": "calibration_finalize/stage_representative_params.csv", "sha256": cp.sha256_file(finalize_dir / "stage_representative_params.csv")},
    ]
    # create placeholder files referenced by placeholder hashes
    (run_dir / "ies_quality").mkdir()
    (run_dir / "ies_quality" / "q.json").write_text("{}", encoding="utf-8")
    artifacts[4] = {"role": "quality_report", "path": "ies_quality/q.json", "sha256": cp.sha256_file(run_dir / "ies_quality" / "q.json")}
    (run_dir / "ies_quality" / f"{case}.member_status.csv").write_text("real\n0\n", encoding="utf-8")
    artifacts[5] = {"role": "member_status", "path": f"ies_quality/{case}.member_status.csv", "sha256": cp.sha256_file(run_dir / "ies_quality" / f"{case}.member_status.csv")}
    # But verify_calibration_artifact_manifest will reject the placeholder rerun hash if required;
    # candidate_predictions passes required_rerun_outputs so rerun outputs must be real files (they are stubs).
    # Add rerun outputs to manifest so hashes line up if verifier checks them.
    for name in ("Evaluate.OUT", "PlantGro.OUT", "FreshWt.OUT"):
        artifacts.append({"role": "representative_deterministic_rerun_output", "path": f"representative_deterministic_rerun/{name}", "sha256": cp.sha256_file(rerun / name)})
    (finalize_dir / "calibration_artifacts_manifest.json").write_text(
        json.dumps({"schema_version": 1, "case": case, "run_dir": str(run_dir), "artifact_count": len(artifacts), "artifacts": artifacts}),
        encoding="utf-8",
    )
    return run_dir


def _write_run_manifest(run_dir: Path, *, case: str, input_dir: Path, design_path: Path, split_path: Path, batch_path: Path, policy_path: Path, harvest_var: str = "CHPDT") -> None:
    from src.common.quality import serialize_manifest_scalar
    lines = [
        f"run_id: {serialize_manifest_scalar(case)}",
        f"design_stage: {serialize_manifest_scalar('S4')}",
        f"design_table_id: {serialize_manifest_scalar('design')}",
        f"approval_scope: {serialize_manifest_scalar('tooling_development')}",
        f"bounds_id: {serialize_manifest_scalar('b')}",
        f"input_dir: {serialize_manifest_scalar(str(input_dir))}",
        f"input_manifest_sha256: {serialize_manifest_scalar(cp.sha256_file(input_dir / 'input_manifest.json'))}",
        f"design_config: {serialize_manifest_scalar(str(design_path))}",
        f"design_config_sha256: {serialize_manifest_scalar(cp.sha256_file(design_path))}",
        f"validation_split_sha256: {serialize_manifest_scalar(cp.sha256_file(split_path))}",
        f"batch_sha256: {serialize_manifest_scalar(cp.sha256_file(batch_path))}",
        f"observation_policy_csv: {serialize_manifest_scalar(str(policy_path))}",
        f"observation_policy_sha256: {serialize_manifest_scalar(cp.sha256_file(policy_path))}",
        f"harvest_var: {serialize_manifest_scalar(harvest_var)}",
    ]
    (run_dir / "run_manifest.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_input_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "input"
    bundle.mkdir()
    # verify_manifest_integrity requires at least one listed file with matching hash.
    placeholder = bundle / "XXQL.TMT"
    placeholder.write_text("*TMT\n", encoding="utf-8")
    sha = cp.sha256_file(placeholder)
    (bundle / "input_manifest.json").write_text(
        json.dumps({
            "bundle_id": bundle.name,
            "intended_use": None,
            "prohibited_use": [],
            "files": [{"name": "XXQL.TMT", "sha256": sha, "bytes": placeholder.stat().st_size}],
        }),
        encoding="utf-8",
    )
    return bundle


def _write_posterior_manifest(posterior_dir: Path, *, case: str, pairs_df: pd.DataFrame,
                              finalize_sha: str, artifact_manifest_sha: str) -> Path:
    posterior_dir.mkdir(parents=True, exist_ok=True)
    pairs_path = posterior_dir / "candidate_pairs.csv"
    pairs_df.to_csv(pairs_path, index=False, encoding="utf-8")
    (posterior_dir / "posterior_diagnostics.csv").write_text("name,value\nem-fl,23\n", encoding="utf-8")
    (posterior_dir / "spearman_correlation.csv").write_text("a,b\nem-fl,trifl\n", encoding="utf-8")
    artifacts = [
        {"role": "posterior_diagnostics", "path": "posterior_diagnostics.csv", "sha256": cp.sha256_file(posterior_dir / "posterior_diagnostics.csv")},
        {"role": "spearman_correlation", "path": "spearman_correlation.csv", "sha256": cp.sha256_file(posterior_dir / "spearman_correlation.csv")},
        {"role": "candidate_pairs", "path": "candidate_pairs.csv", "sha256": cp.sha256_file(pairs_path)},
    ]
    manifest = {
        "schema_version": 1, "run_id": case, "data_status": "tooling_demo",
        "candidate_pair_count": len(pairs_df), "candidate_pair_status": "prediction_distance_pending",
        "upstream": {
            "calibration_finalize_sha256": finalize_sha,
            "calibration_artifacts_manifest_sha256": artifact_manifest_sha,
        },
        "artifacts": artifacts,
    }
    path = posterior_dir / "posterior_results_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _synthetic_runner_factory(comparisons: dict[int, pd.DataFrame]):
    """Return a runner that writes minimal OUT files so build_comparison_from_rerun
    produces the precomputed comparison frame for each realization.

    The runner writes the comparison rows directly as canonical CSV into
    Evaluate.OUT-style content is not feasible; instead we monkeypatch
    build_comparison_from_rerun in the test. This factory is only used where
    we want the runner to be invoked and produce real output files."""

    def _runner(*, param_csv, work_dir, input_dir, batch_name, harvest_var):
        for name in cp.REQUIRED_RERUN_OUTPUTS:
            (work_dir / name).write_text(f"stub for {param_csv.name}\n", encoding="utf-8")
        return 0

    return _runner


def _build_full_context(tmp_path: Path, *, case: str = "s4", pairs: list[tuple[int, int]] | None = None):
    """Assemble run_dir + input + design + split + policy + posterior for build_candidate_prediction_bundle.

    Returns a dict with all paths. build_comparison_from_rerun is monkeypatched
    per-test to return synthetic comparison frames, so we do not need real DSSAT
    outputs here."""
    run_dir = _make_minimal_run_dir(tmp_path, case=case)
    input_dir = _write_input_bundle(tmp_path)

    # Minimal design config + validation split that load_design_config accepts.
    design_path = tmp_path / "design.json"
    split_path = tmp_path / "split.json"
    design_path.write_text(json.dumps({
        "design_table_id": "design", "approval_scope": "tooling_development",
        "validation_split_id": "split", "bounds_id": "b", "input_bundle": input_dir.name,
        "observation_policy_id": "policy", "stages": {
            "S4": {"active_params": ["EM-FL", "TRIFL"], "fixed_params": [],
                   "observation_outputs": {"PestEval.OUT": ["ADAP"]}, "representative_outputs": {}}
        },
    }), encoding="utf-8")
    split_path.write_text(json.dumps({
        "treatment_roles": {"calibration": [2, 3], "validation": [5], "diagnostic": [9]},
    }), encoding="utf-8")

    # Batch file referenced by run_manifest (hash-bound). Format mirrors the
    # real DSSBatch.v48: each treatment line is "<filex> <tn> ...". The filex
    # base name becomes the excode, so XXQL.TMX -> excode XXQL -> input XXQL.TMT.
    batch_path = run_dir / "DSSBatch.v48"
    batch_path.write_text(
        "$BATCH(T)\n@FILEX\nXXQL.TMX 2 1 0 0 0\nXXQL.TMX 3 1 0 0 0\n"
        "XXQL.TMX 5 1 0 0 0\nXXQL.TMX 9 1 0 0 0\n",
        encoding="utf-8",
    )
    # The input bundle already contains XXQL.TMT (with manifest entry); no need
    # to write it again. build_comparison_from_rerun is monkeypatched per-test
    # so the TMT parsing path is not exercised.

    policy_path = tmp_path / "policy.csv"
    _write_policy(policy_path)

    _write_run_manifest(run_dir, case=case, input_dir=input_dir, design_path=design_path,
                        split_path=split_path, batch_path=batch_path, policy_path=policy_path)

    if pairs is None:
        pairs = [(0, 1), (2, 3)]
    pairs_df = pd.DataFrame([
        {"run_id": case, "data_status": "tooling_demo", "pair_id": i + 1,
         "real_a": a, "real_b": b, "phi_a": 10.0 + i, "phi_b": 11.0 + i,
         "phi_total": 10.5 + i, "parameter_distance": 1.0 + i * 0.1,
         "prediction_distance": "", "classification": "candidate_pair_prediction_pending"}
        for i, (a, b) in enumerate(pairs)
    ])
    finalize_sha = cp.sha256_file(run_dir / "calibration_finalize" / "calibration_finalize.json")
    artifact_manifest_sha = cp.sha256_file(run_dir / "calibration_finalize" / "calibration_artifacts_manifest.json")
    posterior_manifest = _write_posterior_manifest(
        run_dir / "t4_posterior_demo", case=case, pairs_df=pairs_df,
        finalize_sha=finalize_sha, artifact_manifest_sha=artifact_manifest_sha,
    )

    return {
        "run_dir": run_dir, "case": case, "input_dir": input_dir,
        "policy_path": policy_path, "posterior_manifest": posterior_manifest,
        "pairs": pairs,
    }


def _comparison_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a canonical comparison-like frame for distance tests.

    Required columns for _align_pair/_distance_components: dataset_role,
    variable, treatment, simulated (plus optional date_code/harvest_number)."""
    df = pd.DataFrame(rows)
    if "date_code" not in df.columns:
        df["date_code"] = -1.0
    if "harvest_number" not in df.columns:
        df["harvest_number"] = -1.0
    return df


# ---------------------------------------------------------------------------
# Tests 1-11 (T4.2 handoff §9)
# ---------------------------------------------------------------------------

def test_t42a_sigma_eff_uses_raw_components_and_no_group_multiplier():
    """#7 (partial): sigma_eff = sqrt(sigma^2+model^2+floor^2); PWAIM's 1.25
    group_multiplier must NOT inflate it."""
    tmp = Path(__file__).parent / "_policy_tmp.csv"
    _write_policy(tmp)
    try:
        m = cp._sigma_eff_map(tmp)
    finally:
        tmp.unlink()
    # ADAPM: sqrt(25^2 + 2^2 + 1^2) = sqrt(630)
    assert m["ADAP"] == pytest.approx(math.sqrt(25 ** 2 + 2 ** 2 + 1 ** 2))
    # PWAIM: sqrt(250^2 + 30^2 + 20^2); multiplier 1.25 ignored
    assert m["DRY_INC"] == pytest.approx(math.sqrt(250 ** 2 + 30 ** 2 + 20 ** 2))


def test_t42a_distance_hand_computed_regression():
    """#7: hand-computed RMS, equal variable weight, equal role weight.

    Both validation and diagnostic roles are populated so _classify does not
    fall back to prediction_incomplete (a None role is treated as incomplete
    by the frozen §7.3/§7.4 contract)."""
    sigma_eff = {"LAIX": 1.0, "CNAM": 2.0, "ADAP": 1.0}
    # validation: LAIX |1-2|/1=1, CNAM |3-1|/2=1 -> d_validation=mean(1,1)=1
    # diagnostic: ADAP |1-1|/1=0 -> d_diagnostic=0
    # prediction_distance = mean(1, 0) = 0.5
    comp_a = _comparison_frame([
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0},
        {"dataset_role": "validation", "variable": "CNAM", "treatment": 5, "simulated": 3.0},
        {"dataset_role": "diagnostic", "variable": "ADAP", "treatment": 9, "simulated": 1.0},
    ])
    comp_b = _comparison_frame([
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 2.0},
        {"dataset_role": "validation", "variable": "CNAM", "treatment": 5, "simulated": 1.0},
        {"dataset_role": "diagnostic", "variable": "ADAP", "treatment": 9, "simulated": 1.0},
    ])
    aligned = cp._align_pair(comp_a, comp_b)
    components = cp._distance_components(aligned, sigma_eff)
    d_val, d_diag, pred = cp._aggregate_distance(components)
    assert d_val == pytest.approx(1.0)
    assert d_diag == pytest.approx(0.0)
    assert pred == pytest.approx(0.5)
    assert cp._classify(d_val, d_diag, demo=True) == "demo_prediction_similar"
    # If validation diverges (>1 sigma): classification flips to divergent.
    comp_b2 = comp_b.copy()
    comp_b2.loc[comp_b2["variable"] == "LAIX", "simulated"] = 5.0  # |1-5|/1=4
    aligned2 = cp._align_pair(comp_a, comp_b2)
    comps2 = cp._distance_components(aligned2, sigma_eff)
    d_val2, d_diag2, _ = cp._aggregate_distance(comps2)
    assert d_val2 > 1.0
    assert cp._classify(d_val2, d_diag2, demo=True) == "demo_prediction_divergent"


def test_t42a_calibration_rows_excluded_from_distance():
    """#6: calibration role rows never enter prediction distance."""
    sigma_eff = {"LAIX": 1.0}
    comp_a = _comparison_frame([
        {"dataset_role": "calibration", "variable": "LAIX", "treatment": 2, "simulated": 100.0},
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0},
    ])
    comp_b = _comparison_frame([
        {"dataset_role": "calibration", "variable": "LAIX", "treatment": 2, "simulated": 1.0},
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0},
    ])
    components = cp._distance_components(cp._align_pair(comp_a, comp_b), sigma_eff)
    assert set(components["dataset_role"]) == {"validation"}
    assert "calibration" not in set(components["dataset_role"])
    d_val, d_diag, pred = cp._aggregate_distance(components)
    assert pred == pytest.approx(0.0)


def test_t42a_align_pair_rejects_mismatched_rows():
    """#5: A/B must align one-to-one on scientific keys; mismatch fails."""
    sigma_eff = {"LAIX": 1.0}
    comp_a = _comparison_frame([{"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0}])
    comp_b = _comparison_frame([
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 2.0},
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 9, "simulated": 3.0},
    ])
    with pytest.raises(ValueError, match="do not align one-to-one"):
        cp._align_pair(comp_a, comp_b)
    # Duplicate keys also fail.
    dup = _comparison_frame([
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0},
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 2.0},
    ])
    with pytest.raises(ValueError, match="duplicate alignment keys"):
        cp._align_pair(dup, dup)


def test_t42a_sigma_rejects_missing_nonpositive_or_nonraw():
    """#8: missing group, non-positive sigma, non-raw transform all fail.

    _sigma_eff_map iterates variables in _VARIABLE_TO_POLICY_GROUP order
    (ADAP first), so the failing group must be ADAPM to surface the right
    error message rather than a 'lacks group' for a later variable."""
    # Non-raw transform on ADAPM (first variable).
    bad_policy = Path(__file__).parent / "_policy_bad.csv"
    bad_policy.write_text(
        "group,transform,offset,reference,sigma,sigma_source,model_sigma,sigma_floor,group_multiplier\n"
        "ADAPM,log,0,1,25.0,assumption,2.0,1.0,1.0\n",
        encoding="utf-8",
    )
    try:
        with pytest.raises(ValueError, match="raw transform"):
            cp._sigma_eff_map(bad_policy)
    finally:
        bad_policy.unlink()
    # Non-positive sigma on ADAPM.
    bad_policy.write_text(
        "group,transform,offset,reference,sigma,sigma_source,model_sigma,sigma_floor,group_multiplier\n"
        "ADAPM,raw,0,1,0,assumption,2.0,1.0,1.0\n",
        encoding="utf-8",
    )
    try:
        with pytest.raises(ValueError, match="invalid sigma=0.0"):
            cp._sigma_eff_map(bad_policy)
    finally:
        bad_policy.unlink()


def test_t42a_unique_realizations_dedup():
    """#4: candidates collapse to unique realizations (column-first order, dedup)."""
    pairs = pd.DataFrame([
        {"real_a": 4, "real_b": 16}, {"real_a": 9, "real_b": 20}, {"real_a": 2, "real_b": 32},
    ])
    uniq = cp._unique_realizations(pairs)
    # real_a column first (4,9,2) then real_b column (16,20,32), dedup preserves order.
    assert uniq == [4, 9, 2, 16, 20, 32]
    assert len(uniq) == 6  # all unique
    # Repeat realization only kept once.
    pairs2 = pd.DataFrame([{"real_a": 1, "real_b": 1}])
    assert cp._unique_realizations(pairs2) == [1]
    pairs3 = pd.DataFrame([{"real_a": 4, "real_b": 4}, {"real_a": 4, "real_b": 16}])
    assert cp._unique_realizations(pairs3) == [4, 16]  # 4 deduped


def test_t42a_export_params_rejects_missing_duplicate_nonfinite(tmp_path):
    """#3: candidate realization missing / duplicate params / non-finite values fail."""
    ens = pd.DataFrame({"real_name": ["0", "1"], "em-fl": [23.0, 23.1], "trifl": [0.2, 0.3]})
    out = tmp_path / "real_0.csv"
    cp._export_candidate_params(ens, 0, out)
    df = pd.read_csv(out)
    assert set(df["name"]) == {"em-fl", "trifl"}
    with pytest.raises(ValueError, match="absent from the final ensemble"):
        cp._export_candidate_params(ens, 99, tmp_path / "real_99.csv")
    # Non-finite value.
    ens_nf = pd.DataFrame({"real_name": ["0"], "em-fl": [float("nan")]})
    with pytest.raises(ValueError, match="non-finite"):
        cp._export_candidate_params(ens_nf, 0, tmp_path / "r.csv")
    # Case-insensitive duplicate.
    ens_dup = pd.DataFrame({"real_name": ["0"], "EM-FL": [23.0], "em-fl": [23.1]})
    with pytest.raises(ValueError, match="duplicate parameter"):
        cp._export_candidate_params(ens_dup, 0, tmp_path / "r.csv")


def test_t42a_demo_flag_required_when_not_science_validated(tmp_path, monkeypatch):
    """#2: science_pending without --allow-unvalidated-demo fails before any DSSAT run."""
    ctx = _build_full_context(tmp_path)
    calls = {"n": 0}

    def _runner(**kw):
        calls["n"] += 1
        return 0

    with pytest.raises(ValueError, match="not science_validated"):
        cp.build_candidate_prediction_bundle(
            run_dir=ctx["run_dir"], case=ctx["case"],
            posterior_manifest=ctx["posterior_manifest"],
            out_dir=tmp_path / "out",
            observation_policy_csv=ctx["policy_path"],
            allow_unvalidated_demo=False,
            dssat_runner=_runner,
        )
    assert calls["n"] == 0  # zero model calls


def test_t42a_posterior_hash_tamper_fails_before_runs(tmp_path):
    """#1: tampering with a posterior manifest artifact hash fails before DSSAT runs."""
    ctx = _build_full_context(tmp_path)
    # Tamper with the candidate_pairs.csv content (hash no longer matches manifest).
    pairs_path = ctx["run_dir"] / "t4_posterior_demo" / "candidate_pairs.csv"
    pairs_path.write_text(pairs_path.read_text() + "\n", encoding="utf-8")
    calls = {"n": 0}

    def _runner(**kw):
        calls["n"] += 1
        return 0

    with pytest.raises(ValueError, match="hash mismatch"):
        cp.build_candidate_prediction_bundle(
            run_dir=ctx["run_dir"], case=ctx["case"],
            posterior_manifest=ctx["posterior_manifest"],
            out_dir=tmp_path / "out",
            observation_policy_csv=ctx["policy_path"],
            allow_unvalidated_demo=True,
            dssat_runner=_runner,
        )
    assert calls["n"] == 0


def test_t42a_failed_candidate_run_classified_incomplete(tmp_path, monkeypatch):
    """#9: a failing candidate run (missing outputs) classifies the pair as
    prediction_incomplete, never as similar."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])

    def _runner(**kw):
        # Write nothing -> all outputs missing -> incomplete.
        return 0

    # Monkeypatch build_comparison_from_rerun so it isn't called for the failed run.
    def _fake_build(rerun_dir, **kw):
        return _comparison_frame([])

    monkeypatch.setattr(cp, "build_comparison_from_rerun", _fake_build)
    manifest_path = cp.build_candidate_prediction_bundle(
        run_dir=ctx["run_dir"], case=ctx["case"],
        posterior_manifest=ctx["posterior_manifest"],
        out_dir=tmp_path / "out",
        observation_policy_csv=ctx["policy_path"],
        allow_unvalidated_demo=True,
        dssat_runner=_runner,
    )
    pair_df = pd.read_csv(tmp_path / "out" / "candidate_pair_predictions.csv")
    assert pair_df["classification"].iloc[0] == "prediction_incomplete"
    assert pair_df["prediction_distance"].iloc[0] != pair_df["prediction_distance"].iloc[0]  # NaN


def test_t42a_demo_never_emits_science_or_equifinality_labels(tmp_path, monkeypatch):
    """#10: under tooling_demo upstream the classification can only be one of
    the demo_* or incomplete labels, never science_validated / functional_equifinality."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])

    # Synthetic comparisons with both validation and diagnostic roles so the
    # distance is well-defined (neither role None).
    comp = _comparison_frame([
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0},
        {"dataset_role": "diagnostic", "variable": "ADAP", "treatment": 9, "simulated": 1.0},
    ])
    monkeypatch.setattr(cp, "build_comparison_from_rerun", lambda rerun_dir, **kw: comp)

    def _runner(**kw):
        for name in cp.REQUIRED_RERUN_OUTPUTS:
            (kw["work_dir"] / name).write_text("x\n", encoding="utf-8")
        return 0

    cp.build_candidate_prediction_bundle(
        run_dir=ctx["run_dir"], case=ctx["case"],
        posterior_manifest=ctx["posterior_manifest"],
        out_dir=tmp_path / "out",
        observation_policy_csv=ctx["policy_path"],
        allow_unvalidated_demo=True,
        dssat_runner=_runner,
    )
    pair_df = pd.read_csv(tmp_path / "out" / "candidate_pair_predictions.csv")
    allowed = {"demo_prediction_similar", "demo_prediction_divergent", "prediction_incomplete"}
    assert set(pair_df["classification"]) <= allowed
    forbidden = {"science_validated", "functional_equifinality", "prediction_similar", "prediction_divergent"}
    assert not (set(pair_df["classification"]) & forbidden)


def test_t42a_manifest_paths_posix_relative_and_hashes_verifiable(tmp_path, monkeypatch):
    """#11: manifest paths are POSIX-relative and every sha256 recomputes correctly."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])
    comp = _comparison_frame([
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0},
        {"dataset_role": "diagnostic", "variable": "ADAP", "treatment": 9, "simulated": 1.0},
    ])
    monkeypatch.setattr(cp, "build_comparison_from_rerun", lambda rerun_dir, **kw: comp)

    def _runner(**kw):
        for name in cp.REQUIRED_RERUN_OUTPUTS:
            (kw["work_dir"] / name).write_text("x\n", encoding="utf-8")
        return 0

    out_dir = tmp_path / "out"
    manifest_path = cp.build_candidate_prediction_bundle(
        run_dir=ctx["run_dir"], case=ctx["case"],
        posterior_manifest=ctx["posterior_manifest"],
        out_dir=out_dir,
        observation_policy_csv=ctx["policy_path"],
        allow_unvalidated_demo=True,
        dssat_runner=_runner,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for art in manifest["artifacts"]:
        rel = art["path"]
        assert "\\" not in rel, f"non-POSIX path in manifest: {rel}"
        assert not Path(rel).is_absolute()
        actual = cp.sha256_file(out_dir / rel)
        assert actual == art["sha256"], f"hash mismatch for {rel}"


# ---------------------------------------------------------------------------
# T4.2.1-A contract close-out tests (review P1/P2 findings, 7 items)
# ---------------------------------------------------------------------------

def test_t421_policy_cli_must_hash_match_frozen(tmp_path, monkeypatch):
    """[P1] A CLI policy whose hash differs from the S4-frozen one fails; the
    default (no CLI policy) uses the frozen bytes."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])
    comp = _comparison_frame([
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0},
        {"dataset_role": "diagnostic", "variable": "ADAP", "treatment": 9, "simulated": 1.0},
    ])
    monkeypatch.setattr(cp, "build_comparison_from_rerun", lambda rerun_dir, **kw: comp)

    def _runner(**kw):
        for name in cp.REQUIRED_RERUN_OUTPUTS:
            (kw["work_dir"] / name).write_text("x\n", encoding="utf-8")
        return 0

    # Default: no observation_policy_csv -> uses frozen policy, succeeds.
    out1 = tmp_path / "out_default"
    cp.build_candidate_prediction_bundle(
        run_dir=ctx["run_dir"], case=ctx["case"],
        posterior_manifest=ctx["posterior_manifest"], out_dir=out1,
        allow_unvalidated_demo=True, dssat_runner=_runner,
    )
    assert (out1 / "candidate_prediction_manifest.json").is_file()

    # A different policy file (hash mismatch) must fail before any run.
    bad_policy = tmp_path / "bad_policy.csv"
    bad_policy.write_text(
        "group,transform,offset,reference,sigma,sigma_source,model_sigma,sigma_floor,group_multiplier\n"
        "ADAPM,raw,0,1,999.0,assumption,2.0,1.0,1.0\n",  # different sigma -> different hash
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match the S4-frozen observation policy hash"):
        cp.build_candidate_prediction_bundle(
            run_dir=ctx["run_dir"], case=ctx["case"],
            posterior_manifest=ctx["posterior_manifest"], out_dir=tmp_path / "out_bad",
            observation_policy_csv=bad_policy,
            allow_unvalidated_demo=True, dssat_runner=_runner,
        )


def test_t421_harvest_var_mismatch_rejected(tmp_path, monkeypatch):
    """[P2] --harvest-var must equal the S4-frozen value."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])
    monkeypatch.setattr(cp, "build_comparison_from_rerun", lambda rerun_dir, **kw: _comparison_frame([]))

    def _runner(**kw):
        return 0

    with pytest.raises(ValueError, match="does not match the S4-frozen"):
        cp.build_candidate_prediction_bundle(
            run_dir=ctx["run_dir"], case=ctx["case"],
            posterior_manifest=ctx["posterior_manifest"], out_dir=tmp_path / "out",
            harvest_var="FWAG",  # frozen is CHPDT
            allow_unvalidated_demo=True, dssat_runner=_runner,
        )


def test_t421_posterior_upstream_hash_stale_rejected(tmp_path, monkeypatch):
    """[P1] A posterior whose recorded finalize/artifact hash disagrees with
    the current S4 must fail (it belongs to a different calibration)."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])
    monkeypatch.setattr(cp, "build_comparison_from_rerun", lambda rerun_dir, **kw: _comparison_frame([]))

    def _runner(**kw):
        return 0

    # Tamper the posterior manifest's upstream finalize hash.
    pm = json.loads(ctx["posterior_manifest"].read_text(encoding="utf-8"))
    pm["upstream"]["calibration_finalize_sha256"] = "f" * 64
    ctx["posterior_manifest"].write_text(json.dumps(pm), encoding="utf-8")

    with pytest.raises(ValueError, match="posterior upstream calibration_finalize_sha256"):
        cp.build_candidate_prediction_bundle(
            run_dir=ctx["run_dir"], case=ctx["case"],
            posterior_manifest=ctx["posterior_manifest"], out_dir=tmp_path / "out",
            allow_unvalidated_demo=True, dssat_runner=_runner,
        )


def test_t421_candidate_pairs_schema_strict():
    """[P2] >3 pairs, >6 unique realizations, non-integer, self-pair, and
    duplicate pair_id all fail the consumer-side schema gate."""
    base = {"run_id": "s4", "data_status": "tooling_demo", "phi_a": 1.0, "phi_b": 1.0,
            "phi_total": 1.0, "parameter_distance": 1.0, "prediction_distance": "",
            "classification": "candidate_pair_prediction_pending"}
    # 4 pairs -> too many
    too_many = pd.DataFrame([dict(base, pair_id=i, real_a=i, real_b=i + 10) for i in range(1, 5)])
    with pytest.raises(ValueError, match="1-3 pairs"):
        cp._validate_candidate_pairs_schema(too_many)
    # A valid 3-pair / 6-unique frame is accepted.
    ok_six = pd.DataFrame([dict(base, pair_id=1, real_a=0, real_b=1),
                           dict(base, pair_id=2, real_a=2, real_b=3),
                           dict(base, pair_id=3, real_a=4, real_b=5)])
    validated = cp._validate_candidate_pairs_schema(ok_six)
    assert len(validated) == 3
    # >6 unique is unreachable with <=3 pairs (max 6), so the pair-count gate
    # is the effective ceiling; documented here for clarity.
    # Non-integer realization 4.5 rejected
    frac = pd.DataFrame([dict(base, pair_id=1, real_a=4.5, real_b=9)])
    with pytest.raises(ValueError, match="non-negative integer"):
        cp._validate_candidate_pairs_schema(frac)
    # Self-pair
    selfp = pd.DataFrame([dict(base, pair_id=1, real_a=4, real_b=4)])
    with pytest.raises(ValueError, match="real_a == real_b"):
        cp._validate_candidate_pairs_schema(selfp)
    # Duplicate pair_id
    dup = pd.DataFrame([dict(base, pair_id=1, real_a=0, real_b=1),
                        dict(base, pair_id=1, real_a=2, real_b=3)])
    with pytest.raises(ValueError, match="duplicate pair_id"):
        cp._validate_candidate_pairs_schema(dup)


def test_t421_nonempty_out_dir_rejected(tmp_path, monkeypatch):
    """[P1] A non-empty output directory is refused (no --force), to avoid
    inheriting stale outputs."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(cp, "build_comparison_from_rerun", lambda rerun_dir, **kw: _comparison_frame([]))

    def _runner(**kw):
        return 0

    with pytest.raises(ValueError, match="not empty"):
        cp.build_candidate_prediction_bundle(
            run_dir=ctx["run_dir"], case=ctx["case"],
            posterior_manifest=ctx["posterior_manifest"], out_dir=out,
            allow_unvalidated_demo=True, dssat_runner=_runner,
        )


def test_t421_nonzero_returncode_with_prestaged_outs_marks_incomplete(tmp_path, monkeypatch):
    """[P1] A runner that returns non-zero while pre-existing OUT files are
    present must NOT be mistaken for a successful run. Previously such a case
    was accepted (missing_outputs=[]). Now the pair is prediction_incomplete."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])

    def _runner(**kw):
        # Simulate the review's reproduction: pre-stage stale OUTs, return 1,
        # write nothing new. The candidate must still be rejected because the
        # returncode is non-zero, regardless of the stale files.
        for name in cp.REQUIRED_RERUN_OUTPUTS:
            (kw["work_dir"] / name).write_text("STALE\n", encoding="utf-8")
        return 1

    monkeypatch.setattr(cp, "build_comparison_from_rerun", lambda rerun_dir, **kw: _comparison_frame([]))
    cp.build_candidate_prediction_bundle(
        run_dir=ctx["run_dir"], case=ctx["case"],
        posterior_manifest=ctx["posterior_manifest"], out_dir=tmp_path / "out",
        allow_unvalidated_demo=True, dssat_runner=_runner,
    )
    pair_df = pd.read_csv(tmp_path / "out" / "candidate_pair_predictions.csv")
    assert pair_df["classification"].iloc[0] == "prediction_incomplete"
    runs = pd.read_csv(tmp_path / "out" / "candidate_runs.csv")
    assert (runs["returncode"] == 1).all()


def test_t421_comparison_includes_both_sides(tmp_path, monkeypatch):
    """[P1] candidate_comparison.csv must include BOTH A and B realizations
    with a candidate_side column, not just the A side."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])
    comp = _comparison_frame([
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0},
        {"dataset_role": "diagnostic", "variable": "ADAP", "treatment": 9, "simulated": 1.0},
    ])
    monkeypatch.setattr(cp, "build_comparison_from_rerun", lambda rerun_dir, **kw: comp)

    def _runner(**kw):
        for name in cp.REQUIRED_RERUN_OUTPUTS:
            (kw["work_dir"] / name).write_text("x\n", encoding="utf-8")
        return 0

    cp.build_candidate_prediction_bundle(
        run_dir=ctx["run_dir"], case=ctx["case"],
        posterior_manifest=ctx["posterior_manifest"], out_dir=tmp_path / "out",
        allow_unvalidated_demo=True, dssat_runner=_runner,
    )
    comp_df = pd.read_csv(tmp_path / "out" / "candidate_comparison.csv")
    sides = set(comp_df["candidate_side"])
    assert sides == {"A", "B"}, f"expected both sides, got {sides}"
    reals = set(comp_df["realization"])
    assert reals == {0, 1}, f"expected both realizations, got {reals}"


def test_t421_candidate_run_manifest_records_argv(tmp_path, monkeypatch):
    """[P2] Each candidate_run_manifest.json records a reproducible argv with
    no --cultivar (matches the S4 model command) and the frozen harvest_var."""
    ctx = _build_full_context(tmp_path, pairs=[(0, 1)])
    comp = _comparison_frame([
        {"dataset_role": "validation", "variable": "LAIX", "treatment": 5, "simulated": 1.0},
        {"dataset_role": "diagnostic", "variable": "ADAP", "treatment": 9, "simulated": 1.0},
    ])
    monkeypatch.setattr(cp, "build_comparison_from_rerun", lambda rerun_dir, **kw: comp)

    def _runner(**kw):
        for name in cp.REQUIRED_RERUN_OUTPUTS:
            (kw["work_dir"] / name).write_text("x\n", encoding="utf-8")
        return 0

    cp.build_candidate_prediction_bundle(
        run_dir=ctx["run_dir"], case=ctx["case"],
        posterior_manifest=ctx["posterior_manifest"], out_dir=tmp_path / "out",
        allow_unvalidated_demo=True, dssat_runner=_runner,
    )
    run_manifest = json.loads((tmp_path / "out" / "runs" / "real_0" / "candidate_run_manifest.json").read_text())
    argv = run_manifest["argv"]
    assert "--harvest-var" in argv and "CHPDT" in argv
    assert "--cultivar" not in argv  # cultivar inferred from frozen FileX, not hardcoded
    assert run_manifest["harvest_var"] == "CHPDT"
