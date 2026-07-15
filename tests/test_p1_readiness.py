"""Regression tests for the formal-P1 bounds preflight."""

from pathlib import Path

import pandas as pd
import pyemu

from src.common.param_registry import validate_frozen_bounds
from src.sensitivity.p1_readiness import assess_p1_bounds
from src.sensitivity.sa_build_sen_case import build_case
from tools.prepare_p1_bounds_proposal import prepare_proposal


ROOT = Path(__file__).resolve().parents[1]
V14_FROZEN = ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_v14_20260405.csv"
V14_DESIGN = ROOT / "data" / "parameter_registry" / "bounds_proposals" / "eggplant" / "proposal_from_sa_v14.csv"


def test_historical_v14_frozen_cannot_start_p1():
    report = assess_p1_bounds(V14_FROZEN)
    assert not report.science_validated
    failed = {check.check_id for check in report.checks if check.status == "fail"}
    assert {"p1_bounds_valid", "p1_active_parameter_count", "p1_nuisance_parameters_fixed"}.issubset(failed)


def test_v14_derived_candidate_is_technically_ready_but_requires_approval(tmp_path):
    proposal = tmp_path / "eggplant_p1_candidate.csv"
    proposal, audit, metadata = prepare_proposal(V14_DESIGN, proposal)
    assert proposal.is_file() and audit.is_file() and metadata.is_file()
    assert not validate_frozen_bounds(str(proposal))

    frame = pd.read_csv(proposal)
    active = frame[frame["status"].str.lower() == "active"]
    assert len(active) == 57
    assert not active["location"].str.upper().isin({"SOIL", "IC", "INIT"}).any()

    technical = assess_p1_bounds(proposal, require_approval=False)
    assert technical.science_validated
    formal = assess_p1_bounds(proposal, require_approval=True)
    assert not formal.science_validated
    approval = next(check for check in formal.checks if check.check_id == "p1_bounds_approved")
    assert approval.actual == "pending"


def test_p1_active_parameter_budget_is_enforced(tmp_path):
    proposal = tmp_path / "eggplant_p1_candidate.csv"
    prepare_proposal(V14_DESIGN, proposal)
    report = assess_p1_bounds(proposal, max_active_parameters=20, require_approval=False)
    check = next(item for item in report.checks if item.check_id == "p1_active_parameter_count")
    assert check.status == "fail"


def test_p1_detects_bounds_changed_after_review_metadata(tmp_path):
    proposal = tmp_path / "eggplant_p1_candidate.csv"
    prepare_proposal(V14_DESIGN, proposal)
    text = proposal.read_text(encoding="utf-8-sig")
    proposal.write_text(text.replace("LFMAX,1.27", "LFMAX,1.28", 1), encoding="utf-8-sig")
    report = assess_p1_bounds(proposal, require_approval=False)
    check = next(item for item in report.checks if item.check_id == "p1_bounds_hash_matches")
    assert check.status == "fail"


def test_p1_candidate_builds_reproducible_morris_control_files(tmp_path):
    proposal = tmp_path / "eggplant_p1_candidate.csv"
    prepare_proposal(V14_DESIGN, proposal)
    case_dir = tmp_path / "case"
    pst_path = build_case(
        proposal,
        case_dir=case_dir,
        workspace_dir=ROOT,
        cultivar="TM0008",
        morris_r=4,
        morris_p=6,
        random_seed=20260715,
    )
    pst = pyemu.Pst(pst_path)
    assert pst.npar_adj == 57
    assert pst.nnz_obs == 90
    assert int(pst.pestpp_options["gsa_morris_r"]) == 4
    assert int(pst.pestpp_options["gsa_morris_p"]) == 6
    assert int(pst.pestpp_options["rand_seed"]) == 20260715
    manifest = (case_dir / "run_manifest.yaml").read_text(encoding="utf-8")
    assert "bounds_sha256:" in manifest
    assert "random_seed: 20260715" in manifest

    expected_names = [line.strip().lower() for line in (case_dir / "sa_obs_order.txt").read_text(encoding="utf-8").splitlines()]
    (case_dir / "SA_Indicators.OUT").write_text(
        "".join(f" {value:.6f}\n" for value in range(1, len(expected_names) + 1)),
        encoding="utf-8",
    )
    parsed = pyemu.pst_utils.try_process_output_file(
        case_dir / "SA_Indicators.OUT.ins", case_dir / "SA_Indicators.OUT"
    )
    assert parsed is not None and len(parsed) == len(expected_names)
    assert parsed.loc[expected_names[0], "obsval"] == 1.0
    assert parsed.loc[expected_names[-1], "obsval"] == float(len(expected_names))
    assert not any("MDAPS" in name.upper() for name in expected_names)
