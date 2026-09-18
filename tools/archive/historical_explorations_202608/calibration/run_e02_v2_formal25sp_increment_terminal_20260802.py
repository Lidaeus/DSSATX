"""Build, verify and optionally execute the 25SP mixed-harvest objective."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_formal25sp_increment_terminal_20260802.json"
POLICY = ROOT / "configs/runs/e02_v2_increment_terminal_policy_20260802.csv"
BOUNDS = "eggplant_e02_v2_formal25sp_nreleased_20260802"
BATCH = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801/DSSBatch.v48"


def run(cmd: list[str]) -> None:
    print("+", subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id")
    ap.add_argument("--n-reals", type=int, default=200)
    ap.add_argument("--noptmax", type=int, default=5)
    ap.add_argument("--n-agents", type=int, default=6)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    case = args.run_id or f"e02_v2_formal25sp_increment_terminal_{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    out = ROOT / "workspace/runs" / case
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)
    run([
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--multiseason-design", str(DESIGN),
        "--input-dir", str(BATCH.parent), "--bounds-id", BOUNDS,
        "--bounds-crop", "eggplant", "--prefix", case,
        "--noptmax", str(args.noptmax), "--ies-num-reals", str(args.n_reals),
        "--random-seed", "20260802", "--bad-phi-sigma", "1e300",
        "--batch", str(BATCH), "--harvest-var", "CHPDT",
        "--include-n-uptake", "--include-soil", "--out-dir", str(out),
        "--param-review-mode", "off", "--observation-policy-csv", str(POLICY),
        "--initial-ensemble-method", "sobol",
    ])

    pst = pyemu.Pst(str(out / f"{case}.pst"))
    reg = pd.read_csv(out / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    reg["weight_num"] = pd.to_numeric(reg["weight"], errors="coerce").fillna(0.0)
    active = reg[reg["weight_num"] > 0].copy()
    active_groups = active["obgnme"].astype(str).str.upper()
    all_groups = reg["obgnme"].astype(str).str.upper()
    chpdt_active = active[active_groups.str.contains("CHPDTM", regex=False)]
    chpdt_diag = reg[
        all_groups.str.contains("CHPDTM", regex=False) & reg["weight_num"].eq(0)
    ]
    hpodw_active = active[active_groups.str.contains("HPODWM", regex=False)]
    nresp_active = active[active_groups.str.contains("NRESP", regex=False)]
    process_expected = {
        "LAIDDM": 24, "LWADDM": 24, "SWADDM": 24,
        "LAIETM": 8, "LWETM": 8, "SWETM": 8,
    }
    process_counts = {
        key: int(active_groups.str.contains(key, regex=False).sum())
        for key in process_expected
    }
    raw_process_active = int(
        active_groups.str.contains(r"(?:^|_)LAIDM_|(?:^|_)LWADM_|(?:^|_)SWADM_", regex=True).sum()
    )
    if not (
        pst.npar_adj == 99
        and len(chpdt_active) == 8
        and len(chpdt_diag) == 80
        and len(hpodw_active) == 88
        and len(nresp_active) == 66
        and process_counts == process_expected
        and raw_process_active == 0
    ):
        raise RuntimeError(
            "mixed-objective preflight failed: "
            f"npar={pst.npar_adj}, chpdt_active={len(chpdt_active)}, "
            f"chpdt_diag={len(chpdt_diag)}, hpodw_active={len(hpodw_active)}, "
            f"nresp_active={len(nresp_active)}"
            f", process_counts={process_counts}, raw_process_active={raw_process_active}"
        )
    group_audit = pd.read_csv(out / f"{case}_group_weight_audit.csv", encoding="utf-8-sig")
    budgets = dict(zip(group_audit["variable_family"], group_audit["phi_budget"]))
    if budgets.get("HARVEST_DRY_INCREMENT") != 1.25 or budgets.get("HARVEST_DRY_TOTAL") != 0.50:
        raise RuntimeError(f"mixed-objective budget audit failed: {budgets}")
    expected_budgets = {
        "CANOPY": 0.20, "CANOPY_INCREMENT": 0.60,
        "CANOPY_TERMINAL": 0.20, "BIOMASS_INCREMENT": 0.75,
        "BIOMASS_TERMINAL": 0.25,
    }
    for family, value in expected_budgets.items():
        if budgets.get(family) != value:
            raise RuntimeError(
                f"process-objective budget audit failed for {family}: {budgets}"
            )
    receipt = {
        "run_id": case,
        "reference_run": "e02_v2_formal25sp_nreleased_200x5_20260802",
        "bounds_id": BOUNDS,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(len(active)),
        "n_harvest_increment_active": int(len(hpodw_active)),
        "n_harvest_terminal_total_active": int(len(chpdt_active)),
        "n_cumulative_intermediate_diagnostic": int(len(chpdt_diag)),
        "n_nresp_active": int(len(nresp_active)),
        "process_state_active_counts": process_counts,
        "raw_process_state_active": raw_process_active,
        "harvest_increment_budget": 1.25,
        "harvest_terminal_budget": 0.50,
        "n_reals": args.n_reals,
        "noptmax": args.noptmax,
        "initial_ensemble_method": "sobol",
        "status": "built",
    }
    (out / "formal_launch_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Preflight passed:", json.dumps(receipt, ensure_ascii=False))
    if args.execute:
        run([
            sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
            "--run-dir", str(out), "--case", case, "--mode", "ies",
            "--n-agents", str(args.n_agents), "--wait",
        ])
        status = json.loads((out / "run_status.json").read_text())
        receipt["status"] = status.get("engineering_status", status.get("status"))
        (out / "formal_launch_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
