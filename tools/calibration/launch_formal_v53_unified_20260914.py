"""Build, audit, smoke-test and run the v53 formal unified case (user-approved 2026-09-14).

XFPHT/XFINT re-activated, FRLFF lower 0.22, LNREF [3.9, 5.3], unified bundles
(REMOVALS + LAI imputed + unscaled 26SP harvest system), 200x4 x 8 agents, seed 43.
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
DESIGN = ROOT / "configs/runs/e02_formal_v53_unified_200x4_20260914.json"
OBS = ROOT / "configs/runs/e02_formal_v47_free_nscale_observation_policy_20260901.csv"
BOUNDS_ID = "eggplant_e02_v53_unified_formal_20260914"
CASE = "e02_formal_v53_unified_200x4_20260914"
RUN_ID = f"{CASE}_r1"
RUN_DIR = ROOT / "workspace/runs" / RUN_ID
REPORT_DIR = ROOT / "workspace/reports/e02_formal_v53_unified_20260914_r1"
ANCHOR = ROOT / "workspace/reports/e02_formal_v47_free_nscale_20260902_candidates/lowest_phi_params.csv"
EXPECTED_ACTIVE = 114
DROP_FROM_ANCHOR = {"page_25sp", "penv_25sp", "page_26sp", "penv_26sp", "icns_25sp", "icns_26sp"}


def run_logged(command, log_path, *, cwd=None):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, cwd=cwd or ROOT, stdout=handle, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); see {log_path}")


def audit():
    pst = pyemu.Pst(str(RUN_DIR / f"{CASE}.pst"))
    active = pst.parameter_data.loc[pst.parameter_data.partrans.ne("fixed")]
    if len(active) != EXPECTED_ACTIVE:
        raise RuntimeError(f"expected {EXPECTED_ACTIVE} active, got {len(active)}")
    low = active.parnme.astype(str).str.lower()
    checks = {
        "xfpht": (35.0, 70.0), "xfint": (0.12, 0.40),
        "frlff": (0.22, None), "lnref": (3.9, 5.3),
    }
    for name, (lb, ub) in checks.items():
        row = active.loc[low.eq(name)].iloc[0]
        if abs(float(row.parlbnd) - lb) > 1e-6:
            raise RuntimeError(f"{name} lower {row.parlbnd} != {lb}")
        if ub is not None and abs(float(row.parubnd) - ub) > 1e-6:
            raise RuntimeError(f"{name} upper {row.parubnd} != {ub}")
    for name in ("page_25sp", "penv_25sp", "page_26sp", "penv_26sp", "icns_25sp", "icns_26sp"):
        if name in set(low):
            raise RuntimeError(f"season-scoped {name} must not be adjustable in v53")
    weights = pd.read_csv(RUN_DIR / f"{CASE}.weights.audit.csv", encoding="utf-8-sig")
    positive = weights[pd.to_numeric(weights["weight"], errors="coerce") > 0].copy()
    gradient = positive[positive["obgnme"].astype(str).str.contains("NG12M|NG23M|NGCVM", case=False, regex=True)]
    if len(gradient) != 45 or not gradient["obsnme"].astype(str).str.upper().str.startswith("26SP_").all():
        raise RuntimeError(f"N-dose-gradient audit failed: {len(gradient)} rows")
    imputed = positive["obsnme"].astype(str).str.lower().str.contains("26sp_laid.*r.*_d180") if False else None
    wresp = positive[positive["obgnme"].astype(str).str.contains("WRESPM", case=False)]
    if set(pd.to_numeric(wresp["nse_lambda"], errors="coerce").dropna().round(8)) != {3.0}:
        raise RuntimeError("W_RESPONSE lambda audit failed")
    payload = {"run_id": RUN_ID, "npar_adj": len(active), "bounds_spot": {k: str(v) for k, v in checks.items()},
               "n_gradient": len(gradient), "w_lambda": 3.0, "num_reals": 200, "noptmax": 4, "agents": 8, "seed": 43}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "preflight_audit.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload))


def smoke():
    work = ROOT / "workspace/smoke/e02_formal_v53_unified_r1_anchor"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    params = pd.read_csv(ANCHOR, encoding="utf-8-sig")
    params = params[~params["name"].astype(str).str.lower().isin(DROP_FROM_ANCHOR)]
    param_path = work / "params.csv"
    params.to_csv(param_path, index=False)
    run_logged([sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                "--design", str(DESIGN.resolve()), "--param-csv", str(param_path.resolve()),
                "--prefix", "v53_smoke", "--harvest-var", "CHFPW"], work / "smoke.log", cwd=work)
    gradient = work / "PestNDoseGradient.OUT"
    if not gradient.is_file() or len(gradient.read_text(encoding="utf-8").splitlines()) != 45:
        raise RuntimeError("N-dose-gradient smoke must contain 45 rows")


def build():
    if RUN_DIR.exists() and any(RUN_DIR.iterdir()):
        raise FileExistsError(RUN_DIR)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    run_logged([sys.executable, str(ROOT / "src/calibration/build_pest.py"),
                "--mode", "eggplant_stage2", "--prefix", CASE,
                "--bounds-id", BOUNDS_ID, "--bounds-crop", "eggplant",
                "--multiseason-design", str(DESIGN.resolve()),
                "--observation-policy-csv", str(OBS.resolve()),
                "--noptmax", "4", "--ies-num-reals", "200",
                "--batch", "DSSBatch.v48", "--harvest-var", "CHFPW",
                "--param-review-mode", "off", "--out-dir", str(RUN_DIR)],
               REPORT_DIR / "build.log")
    audit()
    smoke()


def run():
    run_logged([sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(RUN_DIR), "--case", CASE, "--mode", "ies",
                "--n-agents", "8", "--port", "4259", "--wait"],
               REPORT_DIR / "parallel_run.log")


def main():
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
