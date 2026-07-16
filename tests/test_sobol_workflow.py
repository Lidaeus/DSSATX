import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu
import pytest

from src.common.project import sha256_file
from src.sensitivity.sobol_audit import assess_sobol_case
from src.sensitivity.sobol_bootstrap import bootstrap_sobol
from src.sensitivity.sobol_case import build_sobol_case, load_approved_topk


ROOT = Path(__file__).resolve().parents[1]
APPROVAL = ROOT / "configs" / "sa" / "approved_topk" / "eggplant_p1_sobol_top16_20260716.json"
BOUNDS = ROOT / "data" / "parameter_registry" / "bounds_frozen" / "eggplant" / "eggplant_p1_xxql2501_v3_20260716.csv"
PROFILE = ROOT / "configs" / "sa" / "eggplant_p1_outputs.json"
INPUT = ROOT / "data" / "user" / "experiments" / "xxql2501_20260716"


def test_approved_sobol_topk_is_hash_locked_and_complete():
    metadata, frame, csv_path = load_approved_topk(APPROVAL)
    assert metadata["review_status"] == "approved"
    assert len(frame) == 16
    assert sha256_file(csv_path) == metadata["approved_topk_csv_sha256"]
    assert {"FL-SD", "RTNH4"}.issubset(set(frame["parameter"]))


def test_approved_sobol_topk_rejects_changed_csv(tmp_path):
    metadata = json.loads(APPROVAL.read_text(encoding="utf-8"))
    source_csv = APPROVAL.with_name(metadata["approved_topk_csv"])
    changed_csv = tmp_path / source_csv.name
    changed_csv.write_bytes(source_csv.read_bytes() + b"EXTRA,99,stable_core,approved\n")
    metadata_path = tmp_path / APPROVAL.name
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        load_approved_topk(metadata_path)


def test_build_sobol_preflight_preserves_exact_approved_parameter_set(tmp_path):
    case_dir = tmp_path / "sobol_case"
    pst_path = build_sobol_case(
        bounds_csv=BOUNDS,
        approval_json=APPROVAL,
        case_dir=case_dir,
        workspace_dir=ROOT,
        output_profile=PROFILE,
        input_dir=INPUT,
        samples=4,
        random_seed=20261114,
    )
    pst = pyemu.Pst(str(pst_path))
    adjustable = {
        str(name).upper()
        for name, row in pst.parameter_data.iterrows()
        if str(row["partrans"]).lower() != "fixed"
    }
    _, approved, _ = load_approved_topk(APPROVAL)
    assert adjustable == set(approved["parameter"])
    assert int(pst.pestpp_options["gsa_sobol_samples"]) == 4
    assert str(pst.pestpp_options["gsa_sobol_par_dist"]).lower() == "unif"
    manifest = (case_dir / "run_manifest.yaml").read_text(encoding="utf-8")
    assert "run_type: sensitivity_sobol_preflight_case" in manifest
    assert "sobol_parameter_count: 16" in manifest
    assert "sobol_expected_model_runs: 72" in manifest
    assert (case_dir / "sobol_approval.csv").read_bytes() == APPROVAL.with_name(
        "eggplant_p1_sobol_top16_20260716.csv"
    ).read_bytes()


def _write_synthetic_sobol_case(root: Path, *, failed_flag: int = 0) -> None:
    root.mkdir()
    (root / "run_manifest.yaml").write_text(
        "run_id: synthetic\n"
        "run_type: sensitivity_sobol_preflight_case\n"
        "sensitivity_method: sobol\n"
        "observation_count: 2\n"
        "sobol_parameter_count: 2\n"
        "sobol_samples: 1\n"
        "sobol_expected_model_runs: 4\n",
        encoding="utf-8",
    )
    (root / "run_status.json").write_text(
        json.dumps({"status": "completed", "scientific_status": "pending"}), encoding="utf-8"
    )
    (root / "sa_sen_sobol.rec").write_text("pestpp-sen analysis complete\n", encoding="utf-8")
    (root / "sa_obs_order.txt").write_text("YIELD\nLAI\n", encoding="utf-8")
    pd.DataFrame(
        {"run_id": range(4), "P1": [1, 2, 3, 4], "P2": [4, 3, 2, 1]}
    ).to_csv(root / "sa_sen_sobol.sobol.par.csv", index=False)
    pd.DataFrame(
        {
            "run_id": range(4),
            "failed_flag": [failed_flag, 0, 0, 0],
            "yield": [10, 11, 12, 13],
            "lai": [1, 2, 3, 4],
        }
    ).to_csv(root / "sa_sen_sobol.sobol.obs.csv", index=False)
    pd.DataFrame({"output": ["yield", "lai"], "P1": [0.2, 0.1], "P2": [0.1, 0.3]}).to_csv(
        root / "sa_sen_sobol.sobol.si.csv", index=False
    )
    pd.DataFrame({"output": ["yield", "lai"], "P1": [0.4, 0.2], "P2": [0.2, 0.5]}).to_csv(
        root / "sa_sen_sobol.sobol.sti.csv", index=False
    )


def test_sobol_audit_validates_complete_rectangular_case(tmp_path):
    case = tmp_path / "valid"
    _write_synthetic_sobol_case(case)
    report = assess_sobol_case(case)
    assert report.science_validated


def test_sobol_audit_rejects_any_model_failure(tmp_path):
    case = tmp_path / "failed"
    _write_synthetic_sobol_case(case, failed_flag=1)
    report = assess_sobol_case(case)
    assert not report.science_validated
    assert next(check for check in report.checks if check.check_id == "sobol_no_model_failures").status == "fail"


def test_sobol_audit_rejects_dssat_missing_sentinel(tmp_path):
    case = tmp_path / "missing"
    _write_synthetic_sobol_case(case)
    observations = pd.read_csv(case / "sa_sen_sobol.sobol.obs.csv")
    observations.loc[0, "yield"] = -99.0
    observations.to_csv(case / "sa_sen_sobol.sobol.obs.csv", index=False)
    report = assess_sobol_case(case)
    assert not report.science_validated
    assert next(check for check in report.checks if check.check_id == "sobol_outputs_finite").status == "fail"


def test_sobol_bootstrap_reproduces_pestpp_point_estimators(tmp_path):
    case = tmp_path / "bootstrap"
    case.mkdir()
    samples = 8
    a = pd.DataFrame({"p1": range(samples), "p2": range(10, 10 + samples)})
    b = pd.DataFrame({"p1": range(20, 20 + samples), "p2": range(30, 30 + samples)})
    hybrid_p1 = a.copy()
    hybrid_p1["p1"] = b["p1"]
    hybrid_p2 = a.copy()
    hybrid_p2["p2"] = b["p2"]
    parameters = pd.concat([a, b, hybrid_p1, hybrid_p2], ignore_index=True)
    parameters.insert(0, "run_id", range(len(parameters)))
    parameters.to_csv(case / "sa_sen_sobol.sobol.par.csv", index=False)
    values = parameters["p1"] + 2.0 * parameters["p2"] + 0.1 * parameters["p1"] * parameters["p2"]
    outputs = pd.DataFrame(
        {"run_id": parameters["run_id"], "failed_flag": 0, "yield": values}
    )
    outputs.to_csv(case / "sa_sen_sobol.sobol.obs.csv", index=False)
    raw = values.to_numpy(dtype=float)
    av = raw[:samples]
    bv = raw[samples : 2 * samples]
    variance = np.var(np.concatenate([av, bv]), ddof=0)
    s1_values = []
    st_values = []
    for index in range(2):
        hybrid = raw[(index + 2) * samples : (index + 3) * samples]
        s1_values.append(float(np.mean(bv * (hybrid - av)) / variance))
        st_values.append(float(0.5 * np.mean((av - hybrid) ** 2) / variance))
    pd.DataFrame({"output": ["yield"], "p1": [s1_values[0]], "p2": [s1_values[1]]}).to_csv(
        case / "sa_sen_sobol.sobol.si.csv", index=False
    )
    pd.DataFrame({"output": ["yield"], "p1": [st_values[0]], "p2": [st_values[1]]}).to_csv(
        case / "sa_sen_sobol.sobol.sti.csv", index=False
    )
    (case / "sa_sen_sobol.pst").write_text("++gsa_method(sobol)\n", encoding="utf-8")
    (case / "run_manifest.yaml").write_text(
        "run_type: sensitivity_sobol_preflight_case\n"
        "sobol_samples: 8\n"
        "sobol_parameter_count: 2\n"
        "sobol_expected_model_runs: 32\n",
        encoding="utf-8",
    )
    report = bootstrap_sobol(case, case / "bootstrap_audit", replicates=50, bootstrap_seed=123)
    assert report.science_validated
    result = pd.read_csv(case / "bootstrap_audit" / "sobol_bootstrap_indices.csv")
    assert len(result) == 2
    assert result["estimable"].all()
    assert result["ST_ci_high"].notna().all()
