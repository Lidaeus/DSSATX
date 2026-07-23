"""Integration test: posterior → extract → freeze → spec-loadable.

Proves the E01→E02/E03 approval bridge works end-to-end:

1. ``extract_bounds_from_posterior`` produces a proposal CSV from an IES
   posterior.
2. The proposal passes ``assert_valid_frozen_bounds`` (the same gate
   ``freeze_bounds.py`` applies before promotion).
3. ``freeze_bounds.py`` promotes the proposal to a frozen bounds CSV.
4. The frozen CSV is schema-compatible with ``ExperimentSpec`` (correct
   active count and parameter names).

The temperature-parameter group (TB2 < TO12 < TO22 < TM2) is the critical
edge case: independent per-parameter quantiles can produce overlapping
ranges that violate ``_validate_temperature_relationships``.  These tests
verify the extract tool emits proposals that already satisfy the
temperature ordering constraint so the freeze step never crashes on a
well-formed posterior.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.extract_bounds_from_posterior import extract_bounds_proposal
from src.common.param_registry import assert_valid_frozen_bounds


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "name", "init", "lower", "upper", "status",
    "pargp", "location", "file", "cultivar", "ecotype", "mode",
]


def _make_base_bounds(path: Path) -> Path:
    """Write a 4-row base bounds CSV with the complete TB2/TO12/TO22/TM2 group.

    All four are SPE temperature-stage parameters sharing the same pargp.
    Ranges and init values satisfy the strict ordering TB2 < TO12 < TO22 < TM2
    (non-overlapping ranges) so the base bounds themselves pass
    ``assert_valid_frozen_bounds``.
    """
    rows = [
        {"name": "TB2",  "init": "10.0", "lower": "6.0",  "upper": "14.0",
         "status": "active", "pargp": "SPE_TempStages", "location": "SPE",
         "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001",
         "mode": "both"},
        {"name": "TO12", "init": "22.0", "lower": "19.0", "upper": "25.0",
         "status": "active", "pargp": "SPE_TempStages", "location": "SPE",
         "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001",
         "mode": "both"},
        {"name": "TO22", "init": "30.0", "lower": "27.0", "upper": "34.0",
         "status": "active", "pargp": "SPE_TempStages", "location": "SPE",
         "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001",
         "mode": "both"},
        {"name": "TM2",  "init": "40.0", "lower": "36.0", "upper": "44.0",
         "status": "active", "pargp": "SPE_TempStages", "location": "SPE",
         "file": "TMGRO048.SPE", "cultivar": "TM0008", "ecotype": "TM0001",
         "mode": "both"},
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _make_param_set(path: Path) -> Path:
    """Write a 4-parameter set JSON declaring the temperature group."""
    path.write_text(json.dumps({
        "set_id": "test_tempgroup4",
        "parameters": ["TB2", "TO12", "TO22", "TM2"],
        "declared_count": 4,
        "source_file": "test",
        "source_sha256": "0" * 64,
        "applicable_observations": "CHPDT",
        "approval_note": "synthetic test set for pipeline integration",
    }), encoding="utf-8")
    return path


def _write_posterior(path: Path, columns: dict[str, np.ndarray]) -> Path:
    """Write a synthetic posterior CSV with a ``real_name`` column."""
    data = {"real_name": range(len(next(iter(columns.values()))))}
    data.update(columns)
    pd.DataFrame(data).to_csv(path, index=False)
    return path


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _row_by_name(rows: list[dict], name: str) -> dict:
    for r in rows:
        if r["name"].upper() == name.upper():
            return r
    raise KeyError(name)


# ---------------------------------------------------------------------------
# Happy path: well-ordered posterior
# ---------------------------------------------------------------------------

class TestWellOrderedPosterior:

    @pytest.fixture
    def well_ordered_posterior(self, tmp_path: Path) -> Path:
        rng = np.random.default_rng(42)
        return _write_posterior(tmp_path / "posterior_ok.csv", {
            "tb2":  rng.uniform(8.0, 12.0, size=200),
            "to12": rng.uniform(22.0, 26.0, size=200),
            "to22": rng.uniform(28.0, 32.0, size=200),
            "tm2":  rng.uniform(38.0, 42.0, size=200),
        })

    def test_proposal_passes_frozen_validation(
        self, well_ordered_posterior, tmp_path
    ):
        """A well-ordered posterior must produce a proposal that passes
        ``assert_valid_frozen_bounds`` without any error-level issues."""
        base = _make_base_bounds(tmp_path / "base_bounds.csv")
        pset = _make_param_set(tmp_path / "param_set.json")
        proposal = extract_bounds_proposal(
            well_ordered_posterior, pset, base,
            out_csv=tmp_path / "proposal.csv",
        )
        # This is the gate freeze_bounds.py applies; must not raise.
        issues = assert_valid_frozen_bounds(proposal)
        errors = [i for i in issues if i.severity == "error"]
        assert errors == [], (
            f"Proposal has {len(errors)} error-level validation issues: "
            + "; ".join(str(e) for e in errors[:5])
        )

    def test_freeze_bounds_promotes_proposal(
        self, well_ordered_posterior, tmp_path
    ):
        """The full extract→freeze pipeline must produce a frozen CSV."""
        base = _make_base_bounds(tmp_path / "base_bounds.csv")
        pset = _make_param_set(tmp_path / "param_set.json")
        proposal = extract_bounds_proposal(
            well_ordered_posterior, pset, base,
            out_csv=tmp_path / "proposal.csv",
        )

        frozen_dir = tmp_path / "frozen"
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "freeze_bounds.py"),
                "--proposal", str(proposal),
                "--crop", "eggplant",
                "--bounds-id", "test_tempgroup_v1",
                "--out-dir", str(frozen_dir),
                "--notes", "integration test",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"freeze_bounds.py failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        frozen_csv = frozen_dir / "test_tempgroup_v1.csv"
        assert frozen_csv.is_file()

        # Frozen CSV must also pass validation (freeze_bounds checks this,
        # but verify the written file is self-consistent).
        issues = assert_valid_frozen_bounds(frozen_csv)
        errors = [i for i in issues if i.severity == "error"]
        assert errors == []

    def test_frozen_csv_is_spec_compatible(
        self, well_ordered_posterior, tmp_path
    ):
        """The frozen CSV must have the right active count and parameter
        names for ExperimentSpec to load it (4 active, all temp-group names)."""
        base = _make_base_bounds(tmp_path / "base_bounds.csv")
        pset = _make_param_set(tmp_path / "param_set.json")
        proposal = extract_bounds_proposal(
            well_ordered_posterior, pset, base,
            out_csv=tmp_path / "proposal.csv",
        )

        frozen_dir = tmp_path / "frozen"
        subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "freeze_bounds.py"),
                "--proposal", str(proposal),
                "--crop", "eggplant",
                "--bounds-id", "test_tempgroup_v1",
                "--out-dir", str(frozen_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        rows = _read_csv(frozen_dir / "test_tempgroup_v1.csv")
        active = [r for r in rows if r["status"].lower() == "active"]
        assert len(active) == 4
        names = {r["name"].upper() for r in active}
        assert names == {"TB2", "TO12", "TO22", "TM2"}


# ---------------------------------------------------------------------------
# Violating path: overlapping temperature ranges
# ---------------------------------------------------------------------------

class TestOverlappingTemperaturePosterior:
    """Posteriors where independent quantiles produce overlapping ranges
    (e.g. TO12.upper > TO22.lower) must still yield a freezable proposal.

    The extract tool is responsible for enforcing the physical temperature
    ordering constraint (TB < TO1 < TO2 < TM) so the proposal is "ready for
    freeze_bounds approval" as documented.  If the tool cannot satisfy the
    constraint, it must raise a clear error rather than emitting an invalid
    proposal that freeze_bounds.py will reject with a cryptic traceback.
    """

    @pytest.fixture
    def overlapping_posterior(self, tmp_path: Path) -> Path:
        """TO12 posterior (24-30) overlaps TO22 posterior (26-32).

        Independent p5/p95 quantiles will produce:
          TO12.upper ≈ 29.8 > TO22.lower ≈ 26.2  → TEMP_RANGE_ORDER violation
        Init ordering is preserved (TO12.median 27 < TO22.median 29).
        """
        rng = np.random.default_rng(123)
        return _write_posterior(tmp_path / "posterior_overlap.csv", {
            "tb2":  rng.uniform(8.0, 12.0, size=200),
            "to12": rng.uniform(24.0, 30.0, size=200),
            "to22": rng.uniform(26.0, 32.0, size=200),
            "tm2":  rng.uniform(38.0, 42.0, size=200),
        })

    def test_overlapping_posterior_produces_freezable_proposal(
        self, overlapping_posterior, tmp_path
    ):
        """The extract tool must adjust overlapping ranges so the proposal
        passes ``assert_valid_frozen_bounds``."""
        base = _make_base_bounds(tmp_path / "base_bounds.csv")
        pset = _make_param_set(tmp_path / "param_set.json")
        proposal = extract_bounds_proposal(
            overlapping_posterior, pset, base,
            out_csv=tmp_path / "proposal.csv",
        )
        issues = assert_valid_frozen_bounds(proposal)
        errors = [i for i in issues if i.severity == "error"]
        assert errors == [], (
            f"Overlapping posterior produced {len(errors)} error-level issues: "
            + "; ".join(str(e) for e in errors[:5])
        )

    def test_overlapping_posterior_freeze_succeeds(
        self, overlapping_posterior, tmp_path
    ):
        """End-to-end: overlapping posterior → extract → freeze must succeed."""
        base = _make_base_bounds(tmp_path / "base_bounds.csv")
        pset = _make_param_set(tmp_path / "param_set.json")
        proposal = extract_bounds_proposal(
            overlapping_posterior, pset, base,
            out_csv=tmp_path / "proposal.csv",
        )

        frozen_dir = tmp_path / "frozen"
        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "freeze_bounds.py"),
                "--proposal", str(proposal),
                "--crop", "eggplant",
                "--bounds-id", "test_overlap_v1",
                "--out-dir", str(frozen_dir),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"freeze_bounds.py failed on overlapping posterior:\n"
            f"stderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Violating path: reversed init medians
# ---------------------------------------------------------------------------

class TestReversedInitPosterior:
    """Posteriors where the median ordering violates TB < TO1 < TO2 < TM.

    The extract tool must either correct the init values or raise a clear
    error — it must not emit a proposal that fails TEMP_INIT_ORDER.
    """

    @pytest.fixture
    def reversed_init_posterior(self, tmp_path: Path) -> Path:
        """TO12 median (28) > TO22 median (26) — init ordering violation."""
        rng = np.random.default_rng(456)
        return _write_posterior(tmp_path / "posterior_reversed.csv", {
            "tb2":  rng.uniform(8.0, 12.0, size=200),
            "to12": rng.uniform(26.0, 30.0, size=200),   # median ~28
            "to22": rng.uniform(24.0, 28.0, size=200),   # median ~26
            "tm2":  rng.uniform(38.0, 42.0, size=200),
        })

    def test_reversed_init_produces_freezable_proposal(
        self, reversed_init_posterior, tmp_path
    ):
        """The extract tool must not emit a proposal with TEMP_INIT_ORDER
        errors."""
        base = _make_base_bounds(tmp_path / "base_bounds.csv")
        pset = _make_param_set(tmp_path / "param_set.json")
        proposal = extract_bounds_proposal(
            reversed_init_posterior, pset, base,
            out_csv=tmp_path / "proposal.csv",
        )
        issues = assert_valid_frozen_bounds(proposal)
        errors = [i for i in issues if i.severity == "error"]
        assert errors == [], (
            f"Reversed-init posterior produced {len(errors)} error-level issues: "
            + "; ".join(str(e) for e in errors[:5])
        )
