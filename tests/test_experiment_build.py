"""End-to-end build tests for the experiment runner bridge (P0-B acceptance).

Verifies that the spec -> receipt -> PST path actually invokes the existing
``build_pest.py`` builder and produces a PST that honours the article contract
(CHPDT active, CHFPW/PWAD/PWAI/HWAM zero-weight).  These are heavier than the
pure contract tests in ``test_experiment_spec.py`` because they shell out to
the real builder; they need the project's frozen bounds and input bundles.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pyemu
import pytest
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.experiment_runner import prepare_experiment_run, run_build

SPECS_DIR = PROJECT_ROOT / "configs" / "experiments" / "specs"


@pytest.fixture
def e00_run(tmp_path):
    """Build the E00 spec end-to-end (spec -> receipt -> PST)."""
    result = prepare_experiment_run(
        spec_path=SPECS_DIR / "E00_input_audit.json",
        run_dir=tmp_path / "e00_build",
    )
    run_build(result.spec, result.run_dir, prefix=result.experiment_id)
    return result


def test_e00_build_generates_pst(e00_run):
    pst_path = e00_run.run_dir / f"{e00_run.experiment_id}.pst"
    assert pst_path.is_file(), f"PST not generated at {pst_path}"


def test_e00_receipt_has_all_hashes(e00_run):
    receipt = json.loads(e00_run.receipt_path.read_text(encoding="utf-8"))
    assert receipt["experiment_id"] == "E00_input_audit"
    assert receipt["spec_sha256"]
    assert receipt["parameter_set"]["sha256"]
    assert receipt["bounds"]["sha256"]
    assert receipt["observation_profile"]["sha256"]
    for s in receipt["season_inputs"]:
        assert s["input_manifest_sha256"]


def test_e00_pst_honours_dry_only_contract(e00_run):
    """The generated PST must have CHPDT active and forbidden vars zero-weight."""
    pst = pyemu.Pst(str(e00_run.run_dir / f"{e00_run.experiment_id}.pst"))
    obs = pst.observation_data
    names = obs["obsnme"].astype(str).str.upper()
    active = obs.loc[pd.to_numeric(obs["weight"], errors="coerce") > 0]
    an = active["obsnme"].astype(str).str.upper()
    assert an.str.contains("CHPDT").any(), "CHPDT must be active"
    assert not an.str.contains("CHFPW").any(), "CHFPW must be zero-weight"
    assert not an.str.contains("PWAD|PWAI|HWAM").any(), "PWAD/PWAI/HWAM forbidden"
    assert not an.str.contains("LAIX").any(), "LAIX must be diagnostic-only"


def test_e00_pst_parameter_count_matches_spec(e00_run):
    """PST adjustable-parameter count must equal the spec's declared count."""
    pst = pyemu.Pst(str(e00_run.run_dir / f"{e00_run.experiment_id}.pst"))
    receipt = json.loads(e00_run.receipt_path.read_text(encoding="utf-8"))
    assert pst.npar_adj == receipt["bounds"]["active_count"]
    assert pst.npar_adj == receipt["parameter_set"]["declared_count"]
