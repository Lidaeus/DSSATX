"""P0-A regression tests: single weight/transform entry, retired improved path.

Validates the article contract that ``observation_policy`` is the only source
of weights and transforms in formal (stage2/joint) calibration, and that the
retired ``weight_scheme=improved`` double-weighting path is explicitly rejected
rather than silently chained.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_build_pest_rejects_weight_scheme_improved_in_stage2():
    """``--weight-scheme improved`` must fail fast in eggplant_stage2 mode."""
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "src" / "calibration" / "build_pest.py"),
            "--mode", "eggplant_stage2",
            "--weight-scheme", "improved",
            "--bounds-id", "eggplant_t9_highdim_v1_20260722",
            "--bounds-crop", "eggplant",
            "--batch", str(PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_20260716" / "DSSBatch.v48"),
            "--prefix", "_p0a_reject_test",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "weight_scheme=improved must be rejected in stage2"
    combined = result.stdout + result.stderr
    assert "retired" in combined or "improved" in combined.lower()


def test_build_pest_rejects_weight_scheme_improved_in_joint():
    """``--weight-scheme improved`` must also fail in eggplant_joint mode."""
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "src" / "calibration" / "build_pest.py"),
            "--mode", "eggplant_joint",
            "--weight-scheme", "improved",
            "--bounds-id", "eggplant_t9_highdim_v1_20260722",
            "--bounds-crop", "eggplant",
            "--batch", str(PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_20260716" / "DSSBatch.v48"),
            "--prefix", "_p0a_reject_test2",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_build_pest_source_has_no_improved_blocks():
    """The retired double-weighting blocks must be gone from the source."""
    source = (PROJECT_ROOT / "src" / "calibration" / "build_pest.py").read_text(encoding="utf-8")
    assert 'weight_scheme == "improved"' not in source, (
        "the retired weight_scheme=improved double-weighting block must be removed"
    )


def test_build_pest_dead_imports_removed():
    """The five dead weight_scheme imports must no longer appear in build_pest."""
    source = (PROJECT_ROOT / "src" / "calibration" / "build_pest.py").read_text(encoding="utf-8")
    for dead in (
        "normalize_and_weight",
        "compute_cv_based_sigma",
        "VARIABLE_TREATMENT",
    ):
        assert dead not in source, f"dead import {dead!r} must be removed from build_pest.py"
    # build_observation_weights / compute_balanced_weights may appear in comments
    # documenting the retirement; verify they are not *called*.
    import re
    calls = re.findall(r"\b(build_observation_weights|compute_balanced_weights)\s*\(", source)
    assert calls == [], (
        "build_observation_weights/compute_balanced_weights must not be called from build_pest.py"
    )


def test_build_pest_retains_live_weight_symbols():
    """The live symbols (WEIGHT_POLICY_ID, weight_from_sigma) must remain."""
    source = (PROJECT_ROOT / "src" / "calibration" / "build_pest.py").read_text(encoding="utf-8")
    assert "WEIGHT_POLICY_ID" in source
    assert "weight_from_sigma" in source
    assert "apply_observation_policy" in source


def test_observation_policy_is_single_weight_source(tmp_path):
    """A build through the experiment runner must produce weights traceable to
    the observation_policy CSV, not a second improved-weight overwrite.

    This is the 'one observation, one transform, one weight' regression: after
    build, every active observation's weight_policy_id must be observation_policy_v2
    (the policy module's version), not the retired raw_sigma_v1.
    """
    from src.calibration.experiment_runner import prepare_experiment_run, run_build

    result = prepare_experiment_run(
        spec_path=PROJECT_ROOT / "configs" / "experiments" / "specs" / "E00_input_audit.json",
        run_dir=tmp_path / "single_weight_test",
    )
    run_build(result.spec, result.run_dir, prefix=result.experiment_id)

    audit_path = result.run_dir / f"{result.experiment_id}.weights.audit.csv"
    assert audit_path.is_file(), "weights audit CSV must exist"
    audit = pd.read_csv(audit_path, encoding="utf-8-sig")
    # Every active (weight>0) observation must carry the observation_policy version.
    active = audit[pd.to_numeric(audit["weight"], errors="coerce") > 0]
    assert len(active) > 0, "there must be active observations"
    versions = set(active["weight_policy_id"].astype(str))
    assert versions == {"observation_policy_v2"}, (
        f"active weights must all come from observation_policy_v2, got {versions}"
    )
