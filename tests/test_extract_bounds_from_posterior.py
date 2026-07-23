"""Tests for src.calibration.extract_bounds_from_posterior.

Validates the E01→E02 bridge tool: projecting an IES posterior onto an
approved parameter set and emitting a bounds proposal CSV.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.extract_bounds_from_posterior import extract_bounds_proposal
from src.common.param_registry import PHYSICAL_BOUNDS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def posterior_csv(tmp_path: Path) -> Path:
    """A synthetic posterior with 3 lower-case parameter columns."""
    rng = np.random.default_rng(42)
    df = pd.DataFrame({
        "real_name": range(100),
        # TB2: well within physical bounds (4.0, 15.0)
        "tb2": rng.uniform(8.0, 12.0, size=100),
        # LFMAX: posterior spills below physical lower (0.5) — needs clamping
        "lfmax": rng.uniform(0.1, 2.5, size=100),
        # Non-target column, should be ignored
        "csdl": [12.33] * 100,
    })
    path = tmp_path / "posterior.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def param_set_json(tmp_path: Path) -> Path:
    """A 2-parameter target set (TB2, LFMAX)."""
    path = tmp_path / "param_set.json"
    path.write_text(json.dumps({
        "set_id": "test_sobol2",
        "parameters": ["TB2", "lfmax"],  # mixed case on purpose
        "declared_count": 2,
        "source_file": "test",
        "source_sha256": "0" * 64,
        "applicable_observations": "CHPDT",
        "approval_note": "synthetic test set",
    }), encoding="utf-8")
    return path


@pytest.fixture
def base_bounds_csv(tmp_path: Path) -> Path:
    """A 3-row base bounds CSV (TB2, LFMAX active; CSDL fixed)."""
    path = tmp_path / "base_bounds.csv"
    rows = [
        {"name": "TB2", "init": "8.6", "lower": "6.0", "upper": "14.0",
         "status": "active", "pargp": "SPE_TempStages", "location": "SPE",
         "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001",
         "mode": "both"},
        {"name": "LFMAX", "init": "1.27", "lower": "0.9", "upper": "1.5",
         "status": "active", "pargp": "CUL_Growth", "location": "CUL",
         "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001",
         "mode": "both"},
        {"name": "CSDL", "init": "12.33", "lower": "12.33", "upper": "12.33",
         "status": "fixed", "pargp": "CUL_Photoperiod", "location": "CUL",
         "file": "TMGRO048.CUL.base", "cultivar": "TM0008", "ecotype": "TM0001",
         "mode": "both"},
    ]
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _row_by_name(rows: list[dict], name: str) -> dict:
    for r in rows:
        if r["name"].upper() == name.upper():
            return r
    raise KeyError(name)


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

class TestExtractBoundsProposal:

    def test_target_params_become_active(self, posterior_csv, param_set_json, base_bounds_csv, tmp_path):
        """Target parameters must be marked active with posterior-derived bounds."""
        out = extract_bounds_proposal(
            posterior_csv, param_set_json, base_bounds_csv,
            out_csv=tmp_path / "proposal.csv",
        )
        rows = _read_rows(out)
        tb2 = _row_by_name(rows, "TB2")
        lfmax = _row_by_name(rows, "LFMAX")
        assert tb2["status"] == "active"
        assert lfmax["status"] == "active"

    def test_non_target_param_fixed(self, posterior_csv, param_set_json, base_bounds_csv, tmp_path):
        """CSDL (not in target set) must be fixed at its init value."""
        out = extract_bounds_proposal(
            posterior_csv, param_set_json, base_bounds_csv,
            out_csv=tmp_path / "proposal.csv",
        )
        rows = _read_rows(out)
        csdl = _row_by_name(rows, "CSDL")
        assert csdl["status"] == "fixed"
        assert csdl["lower"] == csdl["init"]
        assert csdl["upper"] == csdl["init"]

    def test_posterior_bounds_within_base_envelope(self, posterior_csv, param_set_json, base_bounds_csv, tmp_path):
        """TB2 posterior (8-12) should produce a narrower range than the base (6-14)."""
        out = extract_bounds_proposal(
            posterior_csv, param_set_json, base_bounds_csv,
            out_csv=tmp_path / "proposal.csv",
        )
        rows = _read_rows(out)
        tb2 = _row_by_name(rows, "TB2")
        lo, hi = float(tb2["lower"]), float(tb2["upper"])
        # Posterior was uniform(8, 12); p5 ~ 8.2, p95 ~ 11.8
        assert 7.5 < lo < 8.5
        assert 11.5 < hi < 12.5
        assert lo < float(tb2["init"]) < hi

    def test_physical_clamp_applied(self, posterior_csv, param_set_json, base_bounds_csv, tmp_path):
        """LFMAX posterior spills below physical lower (0.5); lower must be clamped."""
        out = extract_bounds_proposal(
            posterior_csv, param_set_json, base_bounds_csv,
            out_csv=tmp_path / "proposal.csv",
        )
        rows = _read_rows(out)
        lfmax = _row_by_name(rows, "LFMAX")
        phys_lo, phys_hi = PHYSICAL_BOUNDS["LFMAX"]
        assert float(lfmax["lower"]) >= phys_lo
        assert float(lfmax["upper"]) <= phys_hi

    def test_metadata_columns_preserved(self, posterior_csv, param_set_json, base_bounds_csv, tmp_path):
        """pargp/location/file columns must be inherited from the base template."""
        out = extract_bounds_proposal(
            posterior_csv, param_set_json, base_bounds_csv,
            out_csv=tmp_path / "proposal.csv",
        )
        rows = _read_rows(out)
        tb2 = _row_by_name(rows, "TB2")
        assert tb2["pargp"] == "SPE_TempStages"
        assert tb2["location"] == "SPE"
        assert tb2["file"] == "TMGRO048.SPE"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_missing_parameter_raises(self, posterior_csv, base_bounds_csv, tmp_path):
        """A parameter set declaring a column absent from the posterior must fail."""
        pset = tmp_path / "bad_set.json"
        pset.write_text(json.dumps({
            "set_id": "bad", "parameters": ["TB2", "NONEXISTENT"],
            "declared_count": 2, "source_file": "t", "source_sha256": "0" * 64,
            "applicable_observations": "CHPDT", "approval_note": "t",
        }), encoding="utf-8")
        with pytest.raises(ValueError, match="absent from posterior"):
            extract_bounds_proposal(posterior_csv, pset, base_bounds_csv,
                                    out_csv=tmp_path / "out.csv")

    def test_invalid_quantile_raises(self, posterior_csv, param_set_json, base_bounds_csv, tmp_path):
        with pytest.raises(ValueError, match="lower_quantile < upper_quantile"):
            extract_bounds_proposal(posterior_csv, param_set_json, base_bounds_csv,
                                    lower_quantile=0.9, upper_quantile=0.1,
                                    out_csv=tmp_path / "out.csv")

    def test_degenerate_posterior_falls_back_to_physical(self, tmp_path):
        """Zero-variance posterior must fall back to the physical envelope."""
        # TB2 physical bounds are (4.0, 15.0)
        post = tmp_path / "degenerate.csv"
        pd.DataFrame({"real_name": [0, 1, 2], "tb2": [9.0, 9.0, 9.0]}).to_csv(post, index=False)

        pset = tmp_path / "set.json"
        pset.write_text(json.dumps({
            "set_id": "s", "parameters": ["TB2"], "declared_count": 1,
            "source_file": "t", "source_sha256": "0" * 64,
            "applicable_observations": "CHPDT", "approval_note": "t",
        }), encoding="utf-8")

        base = tmp_path / "base.csv"
        rows = [{"name": "TB2", "init": "9.0", "lower": "6.0", "upper": "14.0",
                 "status": "active", "pargp": "SPE_TempStages", "location": "SPE",
                 "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001",
                 "mode": "both"}]
        with base.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

        out = extract_bounds_proposal(post, pset, base, out_csv=tmp_path / "out.csv")
        tb2 = _row_by_name(_read_rows(out), "TB2")
        # p5 == p95 == 9.0 after clamping would be degenerate; fallback to physical
        assert float(tb2["lower"]) == 4.0
        assert float(tb2["upper"]) == 15.0
        assert tb2["status"] == "active"

    def test_default_output_path(self, posterior_csv, param_set_json, base_bounds_csv):
        """Without --out, the proposal is written next to the base bounds CSV."""
        out = extract_bounds_proposal(posterior_csv, param_set_json, base_bounds_csv)
        assert out.name == "base_bounds.proposal.csv"
        assert out.parent == base_bounds_csv.parent
