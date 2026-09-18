"""Build, audit, and run the formal v47 freer-condition PEST-IES case."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
PREPARE = ROOT / "tools/calibration/prepare_formal_v47_free_nscale_20260901.py"
DESIGN = ROOT / "configs/runs/e02_formal_v47_free_nscale_20260901.json"
OBS = ROOT / "configs/runs/e02_formal_v47_free_nscale_observation_policy_20260901.csv"
BOUNDS_ID = "eggplant_e02_v47_free_nscale_formal_20260901"
CASE = "e02_formal_v47_free_nscale_200x6_20260901"
RUN_ID = f"{CASE}_r2"
RUN_DIR = ROOT / "workspace/runs" / RUN_ID
REPORT_DIR = ROOT / "workspace/reports/e02_formal_v47_free_nscale_20260901"
BUILD_LOG = REPORT_DIR / "r2_build.log"
RUN_LOG = REPORT_DIR / "r2_parallel_run.log"
SMOKE_ROOT = ROOT / "workspace/smoke/e02_formal_v47_free_nscale_20260901_r2_fix6"


def _run_logged(command: list[str], log_path: Path, *, cwd: Path = ROOT) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=cwd, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); see {log_path}")


def build() -> None:
    subprocess.run([sys.executable, str(PREPARE)], cwd=ROOT, check=True)
    if RUN_DIR.exists() and any(RUN_DIR.iterdir()):
        raise FileExistsError(f"refusing to mix existing run directory: {RUN_DIR}")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--prefix", CASE,
        "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
        "--multiseason-design", str(DESIGN),
        "--observation-policy-csv", str(OBS),
        "--noptmax", "6", "--ies-num-reals", "200",
        "--batch", "DSSBatch.v48", "--harvest-var", "CHFPW",
        "--param-review-mode", "off", "--out-dir", str(RUN_DIR),
    ]
    _run_logged(command, BUILD_LOG)
    audit()
    smoke_extreme_initial_n_scales()


def smoke_extreme_initial_n_scales() -> None:
    """Run both scale bounds through official DSSAT before PEST++ starts."""
    anchor = pd.read_csv(
        ROOT / "workspace/runs/e02_formal_v46_page_penv_n034_20260901_r3/calibration_finalize/stage_representative_params.csv"
    )
    for label, value in (("anchor", 1.0), ("lower", 0.15), ("upper", 1.2)):
        work = SMOKE_ROOT / label
        if work.exists() and any(work.iterdir()):
            raise FileExistsError(f"refusing to mix existing smoke directory: {work}")
        work.mkdir(parents=True, exist_ok=True)
        params = pd.concat(
            [anchor, pd.DataFrame({"name": ["ICNS_25SP", "ICNS_26SP"], "value": [value, value]})],
            ignore_index=True,
        )
        param_path = work / "params.csv"
        params.to_csv(param_path, index=False)
        command = [
            sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
            "--design", str(DESIGN), "--param-csv", str(param_path),
            "--prefix", f"v47_smoke_{label}", "--harvest-var", "CHFPW",
        ]
        _run_logged(command, work / "smoke.log", cwd=work)
        required = [
            work / "PestEval.OUT", work / "PestHarvest.OUT",
            work / "_seasons/25SP/Evaluate.OUT", work / "_seasons/26SP/Evaluate.OUT",
        ]
        missing = [str(path) for path in required if not path.is_file() or path.stat().st_size == 0]
        if missing:
            raise RuntimeError(f"initial-N scale {value:g} smoke outputs missing: {missing}")


def audit() -> None:
    pst = pyemu.Pst(str(RUN_DIR / f"{CASE}.pst"))
    active_par = pst.parameter_data.loc[pst.parameter_data.partrans.ne("fixed")]
    names = set(active_par.parnme.astype(str).str.lower())
    if len(active_par) != 120 or not {"icns_25sp", "icns_26sp"}.issubset(names):
        raise RuntimeError(f"parameter audit failed: npar_adj={len(active_par)}")
    for name, lower, upper in (("sfdur", 20.0, 65.0), ("vssink", 2.8213503, 7.0), ("icns_25sp", 0.15, 1.2), ("icns_26sp", 0.15, 1.2)):
        row = active_par.loc[active_par.parnme.astype(str).str.lower().eq(name)].iloc[0]
        # PEST control files use compact numeric formatting, so compare at
        # the precision actually preserved in the PST.
        if abs(float(row.parlbnd) - lower) > 1e-5 or abs(float(row.parubnd) - upper) > 1e-5:
            raise RuntimeError(f"{name}: unexpected bounds [{row.parlbnd}, {row.parubnd}]")

    weights = pd.read_csv(RUN_DIR / f"{CASE}.weights.audit.csv", encoding="utf-8-sig")
    active = weights[pd.to_numeric(weights["weight"], errors="coerce") > 0].copy()
    chtd = active[active["obgnme"].astype(str).str.contains("CHTDM", case=False)]
    if chtd.empty or not chtd["phi_role"].astype(str).str.lower().eq("calibration").all():
        raise RuntimeError("CHTD is not active in the audited objective")
    nresp = active[active["obgnme"].astype(str).str.contains("NRESPM", case=False)]
    wresp = active[active["obgnme"].astype(str).str.contains("WRESPM", case=False)]
    if nresp.empty or set(pd.to_numeric(nresp["nse_lambda"], errors="coerce").dropna().round(8)) != {3.0}:
        raise RuntimeError("N_RESPONSE lambda audit failed")
    if wresp.empty or set(pd.to_numeric(wresp["nse_lambda"], errors="coerce").dropna().round(8)) != {1.5}:
        raise RuntimeError("W_RESPONSE lambda audit failed")

    group = pd.read_csv(RUN_DIR / f"{CASE}_group_weight_audit.csv", encoding="utf-8-sig")
    height = group[group["variable_family"].astype(str).eq("CANOPY_HEIGHT")]
    if height.empty or not (pd.to_numeric(height["phi_budget"], errors="coerce") == 0.45).all():
        raise RuntimeError("CANOPY_HEIGHT budget audit failed")

    mapping = pd.read_csv(RUN_DIR / f"{CASE}_run_mapping.csv")
    counts = mapping.groupby("season_id")["treatment"].nunique().to_dict()
    if counts != {"25SP": 10, "26SP": 12}:
        raise RuntimeError(f"treatment audit failed: {counts}")

    summary = {
        "run_id": RUN_ID,
        "case": CASE,
        "npar_adj": int(len(active_par)),
        "parameters_added": ["ICNS_25SP", "ICNS_26SP"],
        "sfdur_bounds": [20.0, 65.0],
        "vssink_bounds": [2.8213503, 7.0],
        "height_phi_budget_per_season": 0.45,
        "n_response_lambda": 3.0,
        "w_response_lambda": 1.5,
        "treatments": counts,
        "official_dssat": str((ROOT / "DSCSM048.EXE").resolve()),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "preflight_audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def run() -> None:
    command = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(RUN_DIR), "--case", CASE, "--mode", "ies",
        "--n-agents", "6", "--port", "4248", "--wait",
    ]
    _run_logged(command, RUN_LOG)


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
        build()
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
