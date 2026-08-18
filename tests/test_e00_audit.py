"""Tests for the E00 input/observation/parameter-set freeze audit."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from src.calibration.e00_audit import (
    audit_bounds_profile,
    audit_chpdt_harvest_alignment,
    audit_input_manifests,
    audit_parameter_profiles,
    run_e00_audit,
)
from src.calibration.experiment_spec import ExperimentSpec

PROJECT_ROOT = Path(__file__).resolve().parents[1]
E00_SPEC = PROJECT_ROOT / "configs" / "experiments" / "specs" / "E00_input_audit.json"


# ---------------------------------------------------------------------------
# Operation 2/3: parameter profiles
# ---------------------------------------------------------------------------

class TestParameterProfiles:

    def test_profiles_consistent_and_distinct(self):
        profiles, findings = audit_parameter_profiles()
        fails = [f for f in findings if f.status == "fail"]
        assert fails == [], f"unexpected profile failures: {[f.detail for f in fails]}"
        assert profiles["sobol23"]["declared_count"] == 23
        assert profiles["full55"]["declared_count"] == 55

    def test_sobol23_includes_pm06(self):
        profiles, _ = audit_parameter_profiles()
        assert "PM06" in profiles["sobol23"]["parameters"]

    def test_full55_is_not_auto_superset_of_sobol23(self):
        profiles, _ = audit_parameter_profiles()
        assert len(profiles["full55"]["params_beyond_sobol23"]) > 0


def test_bounds_audit_uses_parameter_set_selected_by_spec(tmp_path):
    bounds = tmp_path / "joint54.csv"
    bounds.write_text(
        "name,status\nRHGHT,active\nXFPHT,active\nFL-VS,fixed\n",
        encoding="utf-8",
    )

    class _ParameterSet:
        set_id = "joint54"
        declared_count = 2
        parameters = ("RHGHT", "XFPHT")

    class _Spec:
        bounds_path = bounds
        bounds_id = "joint54"
        parameter_set = _ParameterSet()

    findings = audit_bounds_profile(_Spec(), {})
    assert [(f.status, f.detail) for f in findings] == [
        ("pass", "joint54: frozen active=2 == declared=2; active names match")
    ]


# ---------------------------------------------------------------------------
# Operation 4: harvest alignment (synthetic FileT fixture)
# ---------------------------------------------------------------------------

FILET_WITH_CHPDT = """*EXP.DATA (T): XXTEST
@TRNO   DATE  CHFPW CHPDT
     2 25140  4710   235
     2 25146  9807   490
     3 25140  4000   200
"""

FILET_NO_CHPDT = """*EXP.DATA (T): XXTEST
@TRNO   DATE  CHFPW CHPDT
     2 25140  -99   -99
"""


def _make_spec_with_filet(tmp_path: Path, filet_content: str, treatments=(2, 3)):
    """Build a minimal ExperimentSpec-like object with a synthetic FileT."""
    # We can't easily build a full ExperimentSpec from scratch; instead test the
    # alignment function directly via a lightweight stand-in that mirrors the
    # real ExperimentSpec's public attributes used by the audit.
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    filet = bundle / "XXTEST.TMT"
    filet.write_text(filet_content, encoding="utf-8")

    class _Season:
        def __init__(self):
            self.season_id = "25SP"
            self.role = "calibration"
            self.input_manifest_path = bundle / "input_manifest.json"

    class _Spec:
        def __init__(self):
            self.season_inputs = (_Season(),)
            self.multiseason_design_path = tmp_path / "design.json"

    (tmp_path / "design.json").write_text(json.dumps({
        "seasons": [{"season_id": "25SP", "treatments": list(treatments)}]
    }), encoding="utf-8")
    return _Spec()


def test_harvest_alignment_reads_real_and_virtual_events(tmp_path):
    spec = _make_spec_with_filet(tmp_path, FILET_WITH_CHPDT)
    rows, findings = audit_chpdt_harvest_alignment(spec)
    # TN2 has 2 events, TN3 has 1
    real = [r for r in rows if r["event_role"] == "real"]
    virtual = [r for r in rows if r["event_role"] == "virtual_terminal"]
    assert len(real) == 3
    assert len(virtual) == 2  # one virtual per treatment
    # model date = observed - 1
    tn2_first = next(r for r in real if r["treatment"] == 2 and r["event_number"] == 1)
    assert tn2_first["model_harvest_date"] == 25140 - 1


def test_harvest_alignment_fails_on_missing_chpdt(tmp_path):
    spec = _make_spec_with_filet(tmp_path, FILET_NO_CHPDT, treatments=(2,))
    rows, findings = audit_chpdt_harvest_alignment(spec)
    fails = [f for f in findings if f.status == "fail"]
    assert any("no direct CHFPW/CHPDT" in f.detail for f in fails)
    assert rows == []


# ---------------------------------------------------------------------------
# End-to-end: real E00 spec
# ---------------------------------------------------------------------------

class TestE00EndToEnd:

    def test_e00_audit_passes_on_real_inputs(self, tmp_path):
        receipt = run_e00_audit(E00_SPEC, tmp_path / "e00_audit")
        assert receipt["status"] == "pass"
        assert receipt["n_findings_failed"] == 0
        assert receipt["bounds_id"] == "eggplant_t9_highdim_v1_20260722"
        assert set(receipt["seasons"]) == {"25SP", "25FA", "26SP"}

    def test_e00_writes_receipt_and_alignment_csv(self, tmp_path):
        out = tmp_path / "e00_audit"
        run_e00_audit(E00_SPEC, out)
        assert (out / "E00_audit_receipt.json").is_file()
        assert (out / "E00_harvest_alignment_audit.csv").is_file()
        receipt = json.loads((out / "E00_audit_receipt.json").read_text(encoding="utf-8"))
        assert receipt["harvest_alignment_rows"] > 0

    def test_e00_alignment_has_real_and_virtual_events(self, tmp_path):
        out = tmp_path / "e00_audit"
        run_e00_audit(E00_SPEC, out)
        import pandas as pd
        df = pd.read_csv(out / "E00_harvest_alignment_audit.csv")
        assert set(df["event_role"]) == {"real", "virtual_terminal"}
        # 25SP and 25FA calibrated; 26SP is frozen_validation (skipped)
        assert set(df["season_id"]) == {"25SP", "25FA"}

    def test_e00_model_date_is_observed_minus_one(self, tmp_path):
        out = tmp_path / "e00_audit"
        run_e00_audit(E00_SPEC, out)
        import pandas as pd
        df = pd.read_csv(out / "E00_harvest_alignment_audit.csv")
        real = df[df["event_role"] == "real"]
        # all real events: model_harvest_date = observed_date - 1 (same YYDDD year)
        assert (real["model_harvest_date"] == real["observed_date"] - 1).all()

    def test_e00_manifest_audit_verifies_files(self, tmp_path):
        spec = ExperimentSpec.load(E00_SPEC)
        rows, findings = audit_input_manifests(spec)
        assert len(rows) == 3
        # all three seasons should pass (real inputs)
        fails = [f for f in findings if f.status == "fail"]
        assert fails == []
        for row in rows:
            assert row["files_missing"] == 0
            assert row["files_sha_mismatch"] == 0
