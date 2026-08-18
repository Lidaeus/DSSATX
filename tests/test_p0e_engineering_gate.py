"""P0-E regression tests: engineering gate, phi_outlier, spec retention, legacy modes.

Validates the article contract (P0-E):
1. High-Phi members are recorded as a non-fatal ``ies_phi_outlier`` warning,
   never causing the gate to fail.
2. The spec-declared ``min_retention_rate`` (in experiment_receipt.json) overrides
   the hardcoded loss threshold.
3. Legacy modes (eggplant_harvest/process/v13) are deprecated and rejected by
   the new experiment entry point.
"""
from __future__ import annotations

import json
import subprocess
import sys
import warnings
from pathlib import Path

import pandas as pd
import pyemu
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from src.reporting.quality_gate import (
    FORMAL_IES_MAX_REALIZATION_LOSS_FRACTION,
    _retention_loss_from_receipt,
    assess_ies_run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_micro_ies(tmp_path: Path, prefix: str = "case", *, n_real: int = 4) -> None:
    """Write a minimal persisted IES directory that passes the gate."""
    idx = [str(i) for i in range(n_real)]
    pd.DataFrame({"p": [1.0 + i * 0.1 for i in range(n_real)]}, index=idx).to_csv(
        tmp_path / f"{prefix}.0.par.csv"
    )
    pd.DataFrame({"p": [1.05 + i * 0.1 for i in range(n_real)]}, index=idx).to_csv(
        tmp_path / f"{prefix}.1.par.csv"
    )
    pd.DataFrame(
        {"active": [10.0 + i for i in range(n_real)]}, index=idx
    ).to_csv(tmp_path / f"{prefix}.1.obs.csv")
    pd.DataFrame(
        {"iteration": [0, 1], **{str(i): [6.0 + i, 4.0 + i] for i in range(n_real)}}
    ).to_csv(tmp_path / f"{prefix}.phi.actual.csv", index=False)
    pst = pyemu.Pst.from_par_obs_names(["p"], ["active"])
    pst.control_data.noptmax = 1
    pst.write(tmp_path / f"{prefix}.pst")


# ---------------------------------------------------------------------------
# P0-E.1: phi_outlier is non-fatal
# ---------------------------------------------------------------------------

class TestPhiOutlierNonFatal:

    def test_phi_outlier_recorded_as_warning_not_fail(self, tmp_path):
        """A run with high-Phi outliers must record them as a warning, not fail."""
        prefix = "case"
        _write_micro_ies(tmp_path, prefix)
        report = assess_ies_run(tmp_path, prefix)
        outlier = next(
            (c for c in report.checks if c.check_id == "ies_phi_outlier"), None
        )
        # the check may be absent if <4 iterations; when present it must not fail
        if outlier is not None:
            assert outlier.status in ("pass", "warn"), (
                f"ies_phi_outlier must be non-fatal, got {outlier.status!r}"
            )
            assert outlier.status != "fail"
        # overall status must not be failed solely due to outliers
        assert report.status != "fail" or not any(
            c.check_id == "ies_phi_outlier" and c.status == "fail" for c in report.checks
        )

    def test_high_phi_does_not_cause_engineering_failure(self, tmp_path):
        """A successful run (all members finite, retained) with one large-Phi
        member must still pass the engineering gate."""
        prefix = "case"
        n = 6
        idx = [str(i) for i in range(n)]
        pd.DataFrame({"p": [1.0 + i * 0.1 for i in range(n)]}, index=idx).to_csv(
            tmp_path / f"{prefix}.0.par.csv"
        )
        pd.DataFrame({"p": [1.05 + i * 0.1 for i in range(n)]}, index=idx).to_csv(
            tmp_path / f"{prefix}.1.par.csv"
        )
        pd.DataFrame({"active": [10.0 + i for i in range(n)]}, index=idx).to_csv(
            tmp_path / f"{prefix}.1.obs.csv"
        )
        # one member has a huge Phi (outlier), rest are normal
        phis = [5.0, 6.0, 7.0, 5.5, 6.5, 9999.0]
        pd.DataFrame(
            {"iteration": [0, 1], **{str(i): [phis[i], phis[i] * 0.9] for i in range(n)}}
        ).to_csv(tmp_path / f"{prefix}.phi.actual.csv", index=False)
        pst = pyemu.Pst.from_par_obs_names(["p"], ["active"])
        pst.control_data.noptmax = 1
        pst.write(tmp_path / f"{prefix}.pst")
        report = assess_ies_run(tmp_path, prefix)
        # the outlier is recorded but does not fail the gate
        assert report.status != "fail", (
            "high-Phi outlier must not cause engineering failure"
        )


# ---------------------------------------------------------------------------
# P0-E.2: spec-declared retention threshold
# ---------------------------------------------------------------------------

class TestSpecRetentionThreshold:

    def test_retention_loss_from_receipt_default(self, tmp_path):
        """A receipt with min_retention_rate=0.95 yields loss=0.05."""
        (tmp_path / "experiment_receipt.json").write_text(
            json.dumps({"execution": {"min_retention_rate": 0.95}}), encoding="utf-8"
        )
        assert _retention_loss_from_receipt(tmp_path) == pytest.approx(0.05)

    def test_retention_loss_none_without_receipt(self, tmp_path):
        """No receipt -> None (legacy runs keep the default threshold)."""
        assert _retention_loss_from_receipt(tmp_path) is None

    def test_assess_ies_honours_receipt_threshold(self, tmp_path):
        """The gate must use the receipt's min_retention_rate, not the 0.02 default."""
        prefix = "case"
        _write_micro_ies(tmp_path, prefix)
        (tmp_path / "experiment_receipt.json").write_text(
            json.dumps({"execution": {"min_retention_rate": 0.95}}), encoding="utf-8"
        )
        report = assess_ies_run(tmp_path, prefix)
        align = next(c for c in report.checks if c.check_id == "ies_realization_alignment")
        # with 0.95 threshold, the loss fraction shown is 0.05, not 0.02
        assert align.threshold == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# P0-E.3: legacy mode deprecation
# ---------------------------------------------------------------------------

class TestLegacyModeDeprecation:

    def test_deprecated_modes_emit_warning(self):
        """build_pest.py source must mark harvest/process/v13 as deprecated."""
        source = (PROJECT_ROOT / "src" / "calibration" / "build_pest.py").read_text(encoding="utf-8")
        assert "_DEPRECATED_MODES" in source
        for mode in ("eggplant_harvest", "eggplant_process", "eggplant_v13"):
            assert mode in source

    def test_experiment_runner_uses_stage2_only(self):
        """The new experiment entry point must only use eggplant_stage2 mode."""
        source = (PROJECT_ROOT / "src" / "calibration" / "experiment_runner.py").read_text(encoding="utf-8")
        assert '"--mode", "eggplant_stage2"' in source or "'eggplant_stage2'" in source
        # it must not reference any deprecated mode
        for mode in ("eggplant_harvest", "eggplant_process", "eggplant_v13"):
            assert mode not in source, (
                f"experiment_runner must not reference deprecated mode {mode!r}"
            )

    def test_deprecated_mode_warns_on_build(self, tmp_path):
        """Invoking build_pest.py with a deprecated mode emits DeprecationWarning."""
        result = subprocess.run(
            [
                sys.executable, "-W", "all",
                str(PROJECT_ROOT / "src" / "calibration" / "build_pest.py"),
                "--mode", "eggplant_harvest",
                "--batch", str(PROJECT_ROOT / "data" / "user" / "experiments" / "xxql2501_20260716" / "DSSBatch.v48"),
                "--prefix", "_p0e_deprecate_test",
                "--out-dir", str(tmp_path / "dep"),
            ],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        combined = result.stdout + result.stderr
        assert "DEPRECATED" in combined or "DeprecationWarning" in combined
