"""E01 sub-trial domain-specific observation policy tests.

Verifies that the E01-P / E01-O / E01-Y-strict pre-calibration sub-trials
resolve to the correct domain-specific observation policy CSV and that the
generated PSTs activate only the intended observation domain.

Backed by the article matrix §3 E01 sub-trial table:
  * E01-P: phenology only (ADAP)
  * E01-O: organ development only (LAID, LWAD, SWAD)
  * E01-Y-strict: yield only (CHPDT, ln(y+1))

25FA E01-P is intentionally absent: the matrix notes 25FA lacks valid ADAP.
"""
from __future__ import annotations

import sys
import subprocess
from pathlib import Path

import pyemu
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.calibration.experiment_runner import (
    _resolve_observation_policy_csv,
    prepare_experiment_run,
    run_build,
)
from src.calibration.experiment_spec import ExperimentSpec

SPECS_DIR = PROJECT_ROOT / "configs" / "experiments" / "specs"


# ---------------------------------------------------------------------------
# Policy resolution (lightweight, no build)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spec_name,expected_policy_stem", [
    ("E01_pre_calibration_25sp_pheno", "e01_pheno_only_v1"),
    ("E01_pre_calibration_25sp_organ", "e01_organ_only_v1"),
    ("E01_pre_calibration_25fa_organ", "e01_organ_only_v1"),
    ("E01_pre_calibration_25sp_yield_strict", "e01_yield_only_v1"),
    ("E01_pre_calibration_25fa_yield_strict", "e01_yield_only_v1"),
    # Regression: existing all-domain specs must still resolve to dry-only
    ("E01_pre_calibration_25sp_yield", "assumption_based_sigma_v5_dryonly"),
    ("E01_pre_calibration_25fa_yield", "assumption_based_sigma_v5_dryonly"),
])
def test_e01_subtrial_resolves_correct_policy(spec_name, expected_policy_stem):
    """Each E01 sub-trial spec must resolve to its domain-specific policy CSV."""
    spec = ExperimentSpec.load(SPECS_DIR / f"{spec_name}.json")
    policy_path = _resolve_observation_policy_csv(spec)
    assert policy_path.stem == expected_policy_stem, (
        f"{spec_name}: expected policy stem {expected_policy_stem!r}, "
        f"got {policy_path.stem!r}"
    )


# ---------------------------------------------------------------------------
# Observation contract (heavier, runs the real builder)
# ---------------------------------------------------------------------------

def _build_spec(spec_name, tmp_path):
    """Build an E01 sub-trial spec end-to-end and return the result + PST."""
    result = prepare_experiment_run(
        spec_path=SPECS_DIR / f"{spec_name}.json",
        run_dir=tmp_path / spec_name,
        smoke=True,
    )
    run_build(result.spec, result.run_dir, prefix=result.experiment_id)
    pst_path = result.run_dir / f"{result.experiment_id}.pst"
    assert pst_path.is_file(), f"PST not generated at {pst_path}"
    return result, pyemu.Pst(str(pst_path))


def _active_obs_domains(pst):
    """Return a dict of {domain: is_active} for a PST."""
    obs = pst.observation_data
    obs["weight"] = pd.to_numeric(obs["weight"], errors="coerce")
    active = obs[obs["weight"] > 0]
    an = active["obsnme"].astype(str).str.upper()
    return {
        "PDAT": bool(an.str.contains("PDAP").any()),
        "ADAP": bool(an.str.contains("ADAP").any()),
        "MDAT": bool(an.str.contains("MDAP").any()),
        "LAID": bool(an.str.contains("LAID").any()),
        "LWAD": bool(an.str.contains("LWAD").any()),
        "SWAD": bool(an.str.contains("SWAD").any()),
        "CHPDT": bool(an.str.contains("CHPDT").any()),
        "CHFPW": bool(an.str.contains("CHFPW").any()),
        "CNAM": bool(an.str.contains("CNAM").any()),
        "LAIX": bool(an.str.contains("LAIX").any()),
        "PWAD": bool(an.str.contains("PWAD").any()),
        "PWAI": bool(an.str.contains("PWAI").any()),
        "HWAM": bool(an.str.contains("HWAM").any()),
    }


def test_e01_pheno_25sp_uses_filea_event_dates(tmp_path):
    """PDAT/ADAT and the documented MDAT(PODD) proxy are active; HDAT is not."""
    _, pst = _build_spec("E01_pre_calibration_25sp_pheno", tmp_path)
    domains = _active_obs_domains(pst)
    assert domains["PDAT"] and domains["ADAP"] and domains["MDAT"]
    assert not domains["HWAM"]


def test_e01_organ_25sp_activates_only_laid_lwad_swad(tmp_path):
    """E01-O 25SP: only LAID/LWAD/SWAD active; all others zero-weight."""
    _, pst = _build_spec("E01_pre_calibration_25sp_organ", tmp_path)
    assert pst.npar_adj == 55
    domains = _active_obs_domains(pst)
    for expected in ("LAID", "LWAD", "SWAD"):
        assert domains[expected] is True, f"{expected} must be active in E01-O"
    for forbidden in ("ADAP", "CHPDT", "CHFPW", "CNAM", "LAIX",
                      "PWAD", "PWAI", "HWAM"):
        assert domains[forbidden] is False, (
            f"{forbidden} must be zero-weight in E01-O (got active)"
        )


def test_e01_organ_25fa_activates_only_laid_lwad_swad(tmp_path):
    """E01-O 25FA: only LAID/LWAD/SWAD active; all others zero-weight."""
    _, pst = _build_spec("E01_pre_calibration_25fa_organ", tmp_path)
    assert pst.npar_adj == 55
    domains = _active_obs_domains(pst)
    for expected in ("LAID", "LWAD", "SWAD"):
        assert domains[expected] is True, f"{expected} must be active in E01-O 25FA"
    for forbidden in ("ADAP", "CHPDT", "CHFPW", "CNAM", "LAIX",
                      "PWAD", "PWAI", "HWAM"):
        assert domains[forbidden] is False, (
            f"{forbidden} must be zero-weight in E01-O 25FA (got active)"
        )


def test_e01_yield_strict_25sp_activates_only_chpdt(tmp_path):
    """E01-Y-strict 25SP: only CHPDT active; all others zero-weight."""
    _, pst = _build_spec("E01_pre_calibration_25sp_yield_strict", tmp_path)
    assert pst.npar_adj == 55
    domains = _active_obs_domains(pst)
    assert domains["CHPDT"] is True, "CHPDT must be active in E01-Y-strict"
    for forbidden in ("ADAP", "LAID", "LWAD", "SWAD", "CHFPW", "CNAM",
                      "LAIX", "PWAD", "PWAI", "HWAM"):
        assert domains[forbidden] is False, (
            f"{forbidden} must be zero-weight in E01-Y-strict (got active)"
        )


def test_e01_yield_strict_25fa_activates_only_chpdt(tmp_path):
    """E01-Y-strict 25FA: only CHPDT active; all others zero-weight."""
    _, pst = _build_spec("E01_pre_calibration_25fa_yield_strict", tmp_path)
    assert pst.npar_adj == 55
    domains = _active_obs_domains(pst)
    assert domains["CHPDT"] is True, "CHPDT must be active in E01-Y-strict 25FA"
    for forbidden in ("ADAP", "LAID", "LWAD", "SWAD", "CHFPW", "CNAM",
                      "LAIX", "PWAD", "PWAI", "HWAM"):
        assert domains[forbidden] is False, (
            f"{forbidden} must be zero-weight in E01-Y-strict 25FA (got active)"
        )
