"""Build, audit, smoke-test and run the XFPHT/XFINT-fixed derivation of v48.

User-directed derivation (2026-09-03) of the two-season formal case
``e02_formal_v48_n_gradient_water2x_200x4_20260902`` (template batch r2, whose
lowest-Phi member is #55): XFPHT and XFINT are fixed at their v48 anchored
init values (43.726 d / 0.3799) and removed from calibration — 118 active
parameters instead of 120.  Everything else (two seasons, objectives, group
policy, seed) is inherited unchanged from the v48 design.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/runs/e02_formal_v48_fix_xfpht_xfint_20260903.json"
OBS = ROOT / "configs/runs/e02_formal_v47_free_nscale_observation_policy_20260901.csv"
BOUNDS_ID = "eggplant_e02_v48_fix_xfpht_xfint_formal_20260903"
BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / f"{BOUNDS_ID}.csv"
BASE_BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v48_n_gradient_water2x_formal_20260902.csv"
CASE = "e02_formal_v48_fix_xfpht_xfint_200x4_20260903"
RUN_ID = f"{CASE}_r1"
RUN_DIR = ROOT / "workspace/runs" / RUN_ID
REPORT_DIR = ROOT / "workspace/reports/e02_formal_v48_fix_xfpht_xfint_20260903_r1"
ANCHOR = ROOT / "workspace/reports/e02_formal_v47_free_nscale_20260902_candidates/lowest_phi_params.csv"
EXPECTED_ACTIVE = 118  # 120 (v48) minus XFPHT and XFINT (now fixed)
FIXED_PARAMS = {"xfpht": 43.7261, "xfint": 0.379887}


def run_logged(command: list[str], log_path: Path, *, cwd: Path = ROOT) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); see {log_path}")


def prepare_bounds() -> None:
    if BOUNDS.is_file():
        return
    frame = pd.read_csv(BASE_BOUNDS, encoding="utf-8-sig")
    names = frame["name"].astype(str).str.lower()
    mask = names.isin(FIXED_PARAMS)
    assert int(mask.sum()) == 2
    frame.loc[mask, "status"] = "fixed"
    for idx in frame[mask].index:
        frame.at[idx, "lower"] = frame.at[idx, "init"]
        frame.at[idx, "upper"] = frame.at[idx, "init"]
    frame.loc[mask, "review_note"] = (
        "fixed at v48 anchored init: XFPHT/XFINT removed from calibration (user-directed 2026-09-03)"
    )
    BOUNDS.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(BOUNDS, index=False, encoding="utf-8-sig")


def audit() -> None:
    pst = pyemu.Pst(str(RUN_DIR / f"{CASE}.pst"))
    active = pst.parameter_data.loc[pst.parameter_data.partrans.ne("fixed")]
    if len(active) != EXPECTED_ACTIVE:
        raise RuntimeError(f"expected {EXPECTED_ACTIVE} active parameters, got {len(active)}")
    fixed_rows = pst.parameter_data.loc[pst.parameter_data.index.astype(str).str.lower().isin(FIXED_PARAMS)]
    if len(fixed_rows) != 2 or not fixed_rows.partrans.eq("fixed").all():
        raise RuntimeError("XFPHT/XFINT must be present exactly once each and fixed")
    for name, expected in FIXED_PARAMS.items():
        matches = [n for n in fixed_rows.index if str(n).lower() == name]
        if len(matches) != 1:
            raise RuntimeError(f"expected exactly one fixed row for {name}, found {matches}")
        row = fixed_rows.loc[matches[0]]
        if abs(float(row.parval1) - expected) > 1e-4:
            raise RuntimeError(f"{name} fixed value drifted: {row.parval1} != {expected}")
    expected_bounds = {
        "xfrt": (0.6, 1.0),
        "frlff": (0.15, 0.5),
        "finref": (100.0, 300.0),
    }
    for name, (lower, upper) in expected_bounds.items():
        row = active.loc[active.parnme.astype(str).str.lower().eq(name)].iloc[0]
        if abs(float(row.parlbnd) - lower) > 1e-5 or abs(float(row.parubnd) - upper) > 1e-5:
            raise RuntimeError(f"{name} bounds audit failed")
    xmage = active.loc[active.parnme.astype(str).str.lower().eq("xmage")].iloc[0]
    if float(xmage.parubnd) >= FIXED_PARAMS["xfpht"]:
        raise RuntimeError("XMAGE < XFPHT ordering violated after fixing XFPHT")
    weights = pd.read_csv(RUN_DIR / f"{CASE}.weights.audit.csv", encoding="utf-8-sig")
    positive = weights[pd.to_numeric(weights["weight"], errors="coerce") > 0].copy()
    gradient = positive[positive["obgnme"].astype(str).str.contains("NG12M|NG23M|NGCVM", case=False, regex=True)]
    if len(gradient) != 45:
        raise RuntimeError(f"expected 45 active 26SP N-dose-gradient observations, got {len(gradient)}")
    if not gradient["obsnme"].astype(str).str.upper().str.startswith("26SP_").all():
        raise RuntimeError("N-dose-gradient leaked outside 26SP")
    wresp = positive[positive["obgnme"].astype(str).str.contains("WRESPM", case=False)]
    if set(pd.to_numeric(wresp["nse_lambda"], errors="coerce").dropna().round(8)) != {3.0}:
        raise RuntimeError("W_RESPONSE lambda audit failed")
    group = pd.read_csv(RUN_DIR / f"{CASE}_group_weight_audit.csv", encoding="utf-8-sig")
    grad_group = group[group["variable_family"].astype(str).eq("N_DOSE_GRADIENT")]
    if len(grad_group) != 1 or float(grad_group.iloc[0]["phi_budget"]) != 1.5:
        raise RuntimeError("N_DOSE_GRADIENT group-budget audit failed")
    payload = {
        "run_id": RUN_ID, "case": CASE, "npar_adj": len(active),
        "fixed_removed": {"xfpht": FIXED_PARAMS["xfpht"], "xfint": FIXED_PARAMS["xfint"]},
        "n_gradient_observations": len(gradient), "n_gradient_budget": 1.5,
        "w_response_lambda": 3.0, "expected_bounds": expected_bounds,
        "num_reals": 200, "noptmax": 4, "agents": 6,
        "template_run": "e02_formal_v48_n_gradient_water2x_200x4_20260902_r2 (member 55)",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "preflight_audit.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


def smoke() -> None:
    work = ROOT / "workspace/smoke/e02_formal_v48_fix_xfpht_xfint_20260903_r1_anchor"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    params = pd.read_csv(ANCHOR, encoding="utf-8-sig")
    param_path = work / "params.csv"
    params.to_csv(param_path, index=False)
    run_logged([
        sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
        "--design", str(DESIGN), "--param-csv", str(param_path),
        "--prefix", "v48xf_fix_smoke", "--harvest-var", "CHFPW",
    ], work / "smoke.log", cwd=work)
    gradient = work / "PestNDoseGradient.OUT"
    if not gradient.is_file() or len(gradient.read_text(encoding="utf-8").splitlines()) != 45:
        raise RuntimeError("N-dose-gradient smoke output must contain 45 one-observation rows")
    instruction = RUN_DIR / f"{CASE}_PestNDoseGradient.OUT.ins"
    parsed = pyemu.pst.pst_utils.InstructionFile(str(instruction)).read_output_file(str(gradient))
    if parsed is None or len(parsed) != 45:
        raise RuntimeError("generated N-dose-gradient instruction file did not parse all 45 values")
    parsed_values = pd.to_numeric(parsed["obsval"], errors="coerce")
    if parsed_values.isna().any():
        raise RuntimeError("generated N-dose-gradient instruction file returned non-numeric values")


def build() -> None:
    prepare_bounds()
    if RUN_DIR.exists() and any(RUN_DIR.iterdir()):
        raise FileExistsError(f"refusing to mix existing run directory: {RUN_DIR}")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    run_logged([
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--prefix", CASE,
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--multiseason-design", str(DESIGN),
        "--observation-policy-csv", str(OBS),
        "--noptmax", "4", "--ies-num-reals", "200",
        "--batch", "DSSBatch.v48", "--harvest-var", "CHFPW",
        "--param-review-mode", "off", "--out-dir", str(RUN_DIR),
    ], REPORT_DIR / "build.log")
    audit()
    smoke()


def run() -> None:
    run_logged([
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR), "--case", CASE, "--mode", "ies",
        "--n-agents", "6", "--port", "4255", "--wait",
    ], REPORT_DIR / "parallel_run.log")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--run-only", action="store_true")
    args = parser.parse_args()
    if args.run_only:
        run()
    elif args.build_only:
        build()
    else:
        build(); run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
