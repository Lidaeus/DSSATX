"""Contract tests for the small T4 posterior/equifinality R input bundle."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.reporting.export_posterior_demo_data import export_t4_demo_bundle


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(directory: Path, name: str, run_id: str, roles: dict[str, Path], upstream=None):
    payload = {
        "run_id": run_id,
        "data_status": "tooling_demo",
        "artifacts": [
            {"role": role, "path": path.name, "sha256": _sha(path)} for role, path in roles.items()
        ],
    }
    if upstream:
        payload["upstream"] = upstream
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _build_inputs(tmp_path: Path):
    run_id = "demo_run"
    posterior, candidate = tmp_path / "posterior", tmp_path / "candidate"
    posterior.mkdir(); candidate.mkdir()
    def frame(path, data):
        pd.DataFrame(data).to_csv(path, index=False)
        return path
    posterior_roles = {
        "posterior_diagnostics": frame(posterior / "posterior_diagnostics.csv", {
            "run_id": [run_id], "data_status": ["tooling_demo"], "parameter": ["A"]}),
        "spearman_correlation": frame(posterior / "spearman_correlation.csv", {
            "run_id": [run_id], "data_status": ["tooling_demo"], "parameter_a": ["A"], "parameter_b": ["B"], "spearman": [0.1]}),
        "candidate_pairs": frame(posterior / "candidate_pairs.csv", {
            "run_id": [run_id], "data_status": ["tooling_demo"], "pair_id": [1]}),
    }
    posterior_manifest = _write_manifest(posterior, "posterior_results_manifest.json", run_id, posterior_roles)
    candidate_roles = {
        "candidate_pair_predictions": frame(candidate / "candidate_pair_predictions.csv", {
            "run_id": [run_id], "data_status": ["tooling_demo"], "pair_id": [1]}),
    }
    _write_manifest(candidate, "candidate_prediction_manifest.json", run_id, candidate_roles,
                    {"posterior_results_manifest_sha256": _sha(posterior_manifest)})
    return run_id, posterior, candidate


def test_t4_demo_export_requires_explicit_demo_opt_in(tmp_path):
    run_id, posterior, candidate = _build_inputs(tmp_path)
    with pytest.raises(ValueError, match="allow-unvalidated-demo"):
        export_t4_demo_bundle(run_id=run_id, posterior_dir=posterior, candidate_dir=candidate,
                              out_dir=tmp_path / "out")
    manifest = export_t4_demo_bundle(run_id=run_id, posterior_dir=posterior, candidate_dir=candidate,
                                     out_dir=tmp_path / "out", allow_unvalidated_demo=True)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["bundle_type"] == "t4_posterior_equifinality"
    assert payload["data_status"] == "legacy_layout_demo"


def test_t4_demo_export_rejects_unbound_candidate_manifest(tmp_path):
    run_id, posterior, candidate = _build_inputs(tmp_path)
    path = candidate / "candidate_prediction_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["upstream"]["posterior_results_manifest_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="does not bind"):
        export_t4_demo_bundle(run_id=run_id, posterior_dir=posterior, candidate_dir=candidate,
                              out_dir=tmp_path / "out", allow_unvalidated_demo=True)
