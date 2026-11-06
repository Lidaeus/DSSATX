#!/usr/bin/env python3
"""Build, audit, and background-launch formal v38 nitrogen-guarded IES."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
DESIGN = ROOT / "configs/runs/e02_formal_v38_nitrogen_guarded_200x6_20260829.json"
BOUNDS_ID = "eggplant_e02_v38_nitrogen_guarded_formal_bounds"
BOUNDS = ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{BOUNDS_ID}.csv"
ANCHOR = (
    ROOT / "workspace/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829"
    / "best_member_137_two_season_deterministic_20260829/best_member_137_params.csv"
)
CASE = "e02_formal_v38_nitrogen_guarded_20260829"
RUN_DIR = ROOT / "workspace/runs/e02_formal_v38_nitrogen_guarded_200x6_20260829"
PORT = 4126
N_AGENTS = 6
N_REALS = 200
NOPTMAX = 6


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_sources() -> None:
    design = json.loads(DESIGN.read_text(encoding="utf-8"))
    if design["status"] != "formal_ready_user_approved":
        raise RuntimeError("formal design is not approved")
    if design["anchor"] != {
        "run_id": "e02_formal_v37_fresh_yield_source_sink_200x4_20260829",
        "iteration": 3,
        "member": 137,
        "selection_label_policy": "explicit_coordinates_only",
    }:
        raise RuntimeError("v38 anchor is not explicit v37 iteration-3 member137")
    bounds = pd.read_csv(BOUNDS)
    if int(bounds["status"].astype(str).str.lower().eq("active").sum()) != 42:
        raise RuntimeError("v38 frozen bounds do not contain exactly 42 active parameters")
    anchor = pd.read_csv(ANCHOR)
    anchor["name"] = anchor["name"].astype(str).str.lower()
    expected = dict(zip(anchor["name"], pd.to_numeric(anchor["value"])))
    actual = bounds.assign(name=bounds["name"].astype(str).str.lower())
    mismatches = actual.loc[
        ~np.isclose(pd.to_numeric(actual["init"]), actual["name"].map(expected), rtol=0, atol=1e-10)
    ]
    if not mismatches.empty:
        raise RuntimeError(f"frozen initial values drifted from the explicit anchor: {mismatches['name'].tolist()}")
    executable = Path(design["custom_dssat_executable"])
    if not executable.is_file():
        raise FileNotFoundError(executable)
    official = ROOT / "DSCSM048.EXE"
    if sha256(executable) != sha256(official):
        raise RuntimeError("configured DSSAT executable does not match the project official executable")


def build() -> None:
    if RUN_DIR.exists() and any(RUN_DIR.iterdir()):
        raise FileExistsError(f"refusing to mix a new formal run with existing artifacts: {RUN_DIR}")
    command = [
        PYTHON, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--prefix", CASE,
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--multiseason-design", str(DESIGN), "--noptmax", str(NOPTMAX),
        "--ies-num-reals", str(N_REALS), "--batch", "DSSBatch.v48",
        "--harvest-var", "CHFPW", "--param-review-mode", "off",
        "--out-dir", str(RUN_DIR),
    ]
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode:
        raise RuntimeError(f"build_pest failed with code {completed.returncode}")


def audit_build() -> None:
    registry = pd.read_csv(RUN_DIR / f"{CASE}_observation_registry.csv")
    positive = registry.loc[pd.to_numeric(registry["weight"]) > 0].copy()
    expected_treatments = {"25SP": {2, 5, 10, 13}, "26SP": {1, 3, 9, 12}}
    for season, expected in expected_treatments.items():
        actual = set(pd.to_numeric(positive.loc[positive["season_id"].eq(season), "treatment"]).astype(int))
        if actual != expected:
            raise RuntimeError(f"{season}: positive-weight scope is {sorted(actual)}, expected {sorted(expected)}")
    n_response = positive.loc[positive["obgnme"].str.contains("NRESP")]
    w_response = positive.loc[positive["obgnme"].str.contains("WRESP")]
    if len(n_response) != 30 or not np.allclose(pd.to_numeric(n_response["nse_lambda"]), 1.0):
        raise RuntimeError("N_RESPONSE was not built as 30 fresh-yield rows with lambda=1")
    if len(w_response) != 30 or not np.allclose(pd.to_numeric(w_response["nse_lambda"]), 0.5):
        raise RuntimeError("W_RESPONSE was not built as 30 fresh-yield rows with lambda=0.5")
    if positive["sim_token"].isin(["CHPDTS", "CHPDTS_T", "HPODWS"]).any():
        raise RuntimeError("dry-yield observations remain active")
    if "HFPOWS" not in set(positive["sim_token"]):
        raise RuntimeError("measured fresh increments are absent")
    increments = positive.loc[positive["sim_token"].eq("HFPOWS")]
    if not increments["sigma_source"].astype(str).str.contains("minimum_cv_5pct|sd/sqrt", regex=True).all():
        raise RuntimeError("fresh-increment uncertainty floor regressed")
    terminal = positive.loc[positive["sim_token"].eq("CHFPWS") & positive["rrmse_lambda"].notna()]
    if set(terminal["season_id"]) != {"25SP", "26SP"} or not np.allclose(
        pd.to_numeric(terminal["rrmse_lambda"]), 250.0
    ):
        raise RuntimeError("terminal fresh RRMSE objective was not built with lambda=250 per season")
    pst = pyemu.Pst(str(RUN_DIR / f"{CASE}.pst"))
    if pst.npar_adj != 42:
        raise RuntimeError(f"PEST control file contains {pst.npar_adj} adjustable parameters, expected 42")
    if int(pst.control_data.noptmax) != 6 or int(pst.pestpp_options.get("ies_num_reals", -1)) != 200:
        raise RuntimeError("PEST control file does not contain the approved 200x6 settings")
    audit = {
        "case": CASE, "run_dir": str(RUN_DIR), "bounds_id": BOUNDS_ID,
        "active_parameters": 42, "n_response_rows": len(n_response),
        "n_response_lambda": 1.0, "w_response_rows": len(w_response),
        "w_response_lambda": 0.5, "terminal_rrmse_lambda": 250.0,
        "official_dssat_sha256": sha256(ROOT / "DSCSM048.EXE"),
        "status": "prelaunch_audit_passed",
    }
    (RUN_DIR / "formal_v38_prelaunch_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def launch_background() -> None:
    command = [
        PYTHON, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR), "--case", CASE, "--mode", "ies",
        "--n-agents", str(N_AGENTS), "--port", str(PORT), "--no-wait",
    ]
    completed = subprocess.run(command, cwd=ROOT)
    if completed.returncode:
        raise RuntimeError(f"run_parallel failed with code {completed.returncode}")


def main() -> int:
    audit_sources()
    build()
    audit_build()
    launch_background()
    print(f"[launched] case={CASE} run_dir={RUN_DIR} port={PORT} agents={N_AGENTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
