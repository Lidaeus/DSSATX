"""Tests for the unified input-manifest integrity and use-clause gates (W0.6).

Covers:
- ``test_input_manifest_file_hash_mismatch_is_rejected`` (plan §7)
- directory/bundle_id match
- untracked files are flagged
- the calibration use-gate rejects SA counterfactual bundles
- ``test_calibration_rejects_counterfactual_bundle`` (plan §7) — via the shared
  helper the calibration builder now calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.input_manifest import (
    InputManifestError,
    InputUseProhibitedError,
    USE_PARAMETER_CALIBRATION,
    assert_use_allowed,
    load_input_manifest,
    verify_calibrated_input_bundle,
    verify_manifest_files,
    verify_manifest_integrity,
)


def _write_bundle(
    directory: Path,
    *,
    bundle_id: str | None = None,
    files: dict[str, str] | None = None,
    prohibited_use: list[str] | None = None,
    intended_use: str | None = None,
    manifest_overrides: dict | None = None,
) -> Path:
    """Write a minimal valid bundle for testing."""
    directory.mkdir(parents=True, exist_ok=True)
    bundle_id = bundle_id or directory.name
    files = files or {}
    file_entries = []
    for name, content in files.items():
        path = directory / name
        path.write_text(content, encoding="utf-8")
        import hashlib

        file_entries.append(
            {
                "name": name,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "bytes": len(content.encode("utf-8")),
            }
        )
    manifest: dict = {
        "bundle_id": bundle_id,
        "created_at": "2026-07-16T00:00:00Z",
        "files": file_entries,
    }
    if intended_use is not None:
        manifest["intended_use"] = intended_use
    if prohibited_use is not None:
        manifest["prohibited_use"] = prohibited_use
    if manifest_overrides:
        manifest.update(manifest_overrides)
    manifest_path = directory / "input_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def test_load_input_manifest_parses_use_clauses(tmp_path):
    bundle = tmp_path / "sa_bundle"
    _write_bundle(
        bundle,
        files={"DSSBatch.v48": "x"},
        intended_use="genetic_parameter_sensitivity_analysis_only",
        prohibited_use=["parameter_calibration"],
    )
    manifest = load_input_manifest(bundle)
    assert manifest.bundle_id == "sa_bundle"
    assert manifest.intended_use == "genetic_parameter_sensitivity_analysis_only"
    assert manifest.prohibited_use == ("parameter_calibration",)
    assert manifest.prohibits(USE_PARAMETER_CALIBRATION)


def test_bundle_without_use_clauses_is_allowed_for_calibration(tmp_path):
    """An ordinary trial bundle carries no prohibited_use and must pass."""
    bundle = tmp_path / "trial_bundle"
    _write_bundle(bundle, files={"DSSBatch.v48": "x"})
    manifest = verify_calibrated_input_bundle(bundle)
    assert manifest.prohibited_use == ()


def test_calibration_rejects_counterfactual_bundle(tmp_path):
    """An SA counterfactual bundle prohibits parameter_calibration."""
    bundle = tmp_path / "sa_counterfactual"
    _write_bundle(
        bundle,
        files={"DSSBatch.v48": "x"},
        intended_use="genetic_parameter_sensitivity_analysis_only",
        prohibited_use=["parameter_calibration", "validation_against_observed_treatment_initial_conditions"],
    )
    with pytest.raises(InputUseProhibitedError, match="prohibits use 'parameter_calibration'"):
        verify_calibrated_input_bundle(bundle)


def test_input_manifest_file_hash_mismatch_is_rejected(tmp_path):
    """Tampering a payload file after manifest creation must fail verification."""
    bundle = tmp_path / "trial"
    _write_bundle(bundle, files={"DSSBatch.v48": "original content", "SOIL.SOL": "soil"})
    # Tamper: change bytes without updating the manifest hash.
    (bundle / "DSSBatch.v48").write_text("TAMPERED content", encoding="utf-8")
    with pytest.raises(InputManifestError, match="HASH_MISMATCH"):
        verify_manifest_integrity(bundle)
    issues = verify_manifest_files(load_input_manifest(bundle))
    codes = {issue.code for issue in issues}
    assert "HASH_MISMATCH" in codes


def test_bundle_id_directory_mismatch_is_rejected(tmp_path):
    bundle = tmp_path / "renamed_dir"
    _write_bundle(bundle, bundle_id="original_dir_name", files={"DSSBatch.v48": "x"})
    with pytest.raises(InputManifestError, match="does not match manifest bundle_id"):
        verify_manifest_integrity(bundle)


def test_untracked_file_in_bundle_is_flagged(tmp_path):
    bundle = tmp_path / "trial"
    _write_bundle(bundle, files={"DSSBatch.v48": "x"})
    (bundle / "mystery_extra_file.txt").write_text("not in manifest", encoding="utf-8")
    with pytest.raises(InputManifestError, match="UNTRACKED_FILE"):
        verify_manifest_integrity(bundle)


def test_missing_manifest_file_is_rejected(tmp_path):
    bundle = tmp_path / "empty"
    bundle.mkdir()
    with pytest.raises(InputManifestError, match="not found"):
        verify_manifest_integrity(bundle)


def test_missing_listed_file_is_rejected(tmp_path):
    bundle = tmp_path / "trial"
    manifest_path = bundle / "input_manifest.json"
    bundle.mkdir()
    manifest_path.write_text(
        json.dumps(
            {
                "bundle_id": "trial",
                "files": [{"name": "DSSBatch.v48", "sha256": "a" * 64, "bytes": 1}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(InputManifestError, match="FILE_MISSING"):
        verify_manifest_integrity(bundle)


def test_malformed_manifest_is_rejected(tmp_path):
    bundle = tmp_path / "trial"
    bundle.mkdir()
    (bundle / "input_manifest.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(InputManifestError, match="not valid JSON"):
        verify_manifest_integrity(bundle)


def test_assert_use_allowed_passes_when_not_prohibited(tmp_path):
    bundle = tmp_path / "trial"
    _write_bundle(bundle, files={"DSSBatch.v48": "x"}, prohibited_use=["some_other_use"])
    manifest = load_input_manifest(bundle)
    # Should not raise: parameter_calibration is not in the prohibited list.
    assert_use_allowed(manifest, use=USE_PARAMETER_CALIBRATION)


def test_real_calibration_bundle_passes_integrity():
    """The real frozen calibration bundle must pass the full integrity gate."""
    manifest = verify_manifest_integrity("data/user/experiments/xxql2501_20260716")
    assert manifest.bundle_id == "xxql2501_20260716"
    assert USE_PARAMETER_CALIBRATION not in manifest.prohibited_use


def test_real_sa_counterfactual_bundle_rejected_for_calibration():
    """The real SA counterfactual bundle must be rejected for calibration use."""
    with pytest.raises(InputUseProhibitedError):
        verify_calibrated_input_bundle(
            "data/user/experiments/xxql2501_sa_counterfactual_v1_20260716"
        )
