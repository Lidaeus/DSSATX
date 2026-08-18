"""Build, audit and optionally execute the corrected 25SP E02 objective."""
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
DESIGN = ROOT / "configs/runs/eggplant_e02_v2_formal25sp_state_terminal_n2response_20260802.json"
POLICY = ROOT / "configs/runs/e02_v2_state_terminal_n2response_policy_20260802.csv"
BOUNDS = "eggplant_e02_v2_formal25sp_nreleased_20260802"
BUNDLE = ROOT / "data/user/experiments/xxql2501_layermean_ic_valid_n012_v1_20260801"
BATCH = BUNDLE / "DSSBatch.v48"
EXPECTED_MAPPING = {
    2: ("W3", "N3", 399.0, 481.4),
    3: ("W3", "N2", 271.0, 481.4),
    4: ("W3", "N1", 130.0, 481.4),
    5: ("W3", "N0", 0.0, 481.4),
    10: ("W1", "N3", 399.0, 283.1),
    11: ("W1", "N2", 271.0, 283.1),
    12: ("W1", "N1", 130.0, 283.1),
    13: ("W1", "N0", 0.0, 283.1),
}


def run(command: list[str]) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _audit_mapping(path: Path) -> list[dict[str, object]]:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    actual = {}
    for row in frame.itertuples(index=False):
        actual[int(row.treatment)] = (
            str(row.water_level),
            str(row.nitrogen_level),
            round(float(row.nitrogen_kg_ha), 1),
            round(float(row.irrigation_mm), 1),
        )
    if actual != EXPECTED_MAPPING:
        raise RuntimeError(
            "FileX-derived TRNO water/N mapping failed: "
            f"expected={EXPECTED_MAPPING}, actual={actual}"
        )
    return frame[
        [
            "season_id", "treatment", "mi", "water_level", "irrigation_mm",
            "mf", "nitrogen_kg_ha", "nitrogen_level", "filex_path",
        ]
    ].to_dict("records")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--n-reals", type=int, default=200)
    parser.add_argument("--noptmax", type=int, default=5)
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    case = args.run_id or (
        f"e02_v2_formal25sp_state_terminal_n2response_"
        f"{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    )
    out = ROOT / "workspace/runs" / case
    if out.exists():
        raise FileExistsError(out)
    out.mkdir(parents=True)

    run(
        [
            sys.executable,
            str(ROOT / "src/calibration/build_pest.py"),
            "--mode", "eggplant_stage2",
            "--multiseason-design", str(DESIGN),
            "--input-dir", str(BUNDLE),
            "--bounds-id", BOUNDS,
            "--bounds-crop", "eggplant",
            "--prefix", case,
            "--noptmax", str(args.noptmax),
            "--ies-num-reals", str(args.n_reals),
            "--random-seed", "20260802",
            "--bad-phi-sigma", "1e300",
            "--batch", str(BATCH),
            "--harvest-var", "CHPDT",
            "--include-n-uptake",
            "--include-soil",
            "--out-dir", str(out),
            "--param-review-mode", "off",
            "--observation-policy-csv", str(POLICY),
            "--initial-ensemble-method", "sobol",
        ]
    )

    pst = pyemu.Pst(str(out / f"{case}.pst"))
    registry = pd.read_csv(
        out / f"{case}_observation_registry.csv", encoding="utf-8-sig"
    )
    registry["weight_num"] = pd.to_numeric(
        registry["weight"], errors="coerce"
    ).fillna(0.0)
    active = registry.loc[registry["weight_num"] > 0].copy()
    active_groups = active["obgnme"].astype(str).str.upper()
    all_groups = registry["obgnme"].astype(str).str.upper()

    expected_counts = {
        "LAIXM": 8,
        "LAIDM": 32,
        "LWADM": 32,
        "SWADM": 32,
        "SNAMM": 8,
        "LNAMM": 8,
        "HPODWM": 88,
        "CHPDTM": 8,
        "NRESPM": 2,
    }
    actual_counts = {
        token: int(active_groups.str.contains(token, regex=False).sum())
        for token in expected_counts
    }
    diagnostic_chpdt = int(
        (
            all_groups.str.contains("CHPDTM", regex=False)
            & registry["weight_num"].eq(0)
        ).sum()
    )
    forbidden_increment_tokens = int(
        active_groups.str.contains(
            "LAIDDM|LWADDM|SWADDM|LAIETM|LWETM|SWETM", regex=True
        ).sum()
    )
    if (
        pst.npar_adj != 99
        or actual_counts != expected_counts
        or diagnostic_chpdt != 80
        or forbidden_increment_tokens != 0
    ):
        raise RuntimeError(
            "corrected-objective preflight failed: "
            f"npar={pst.npar_adj}, counts={actual_counts}, "
            f"chpdt_diag={diagnostic_chpdt}, "
            f"forbidden_increment_tokens={forbidden_increment_tokens}"
        )

    group_audit = pd.read_csv(
        out / f"{case}_group_weight_audit.csv", encoding="utf-8-sig"
    )
    budgets = dict(zip(group_audit["variable_family"], group_audit["phi_budget"]))
    expected_budgets = {
        "CANOPY": 1.00,
        "BIOMASS": 1.00,
        "PLANT_N": 1.00,
        "HARVEST_DRY_INCREMENT": 1.25,
        "HARVEST_DRY_TOTAL": 0.50,
        "N_RESPONSE": 0.75,
        "SOIL_WATER": 1.00,
    }
    for family, expected in expected_budgets.items():
        if budgets.get(family) != expected:
            raise RuntimeError(
                f"budget preflight failed for {family}: expected {expected}, "
                f"found {budgets.get(family)}"
            )

    filex_mapping = _audit_mapping(
        out / f"{case}_filex_water_n_mapping_audit.csv"
    )
    receipt = {
        "run_id": case,
        "reference_run": "e02_v2_formal25sp_nreleased_200x5_20260802",
        "bounds_id": BOUNDS,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(len(active)),
        "active_observation_counts": actual_counts,
        "n_cumulative_intermediate_diagnostic": diagnostic_chpdt,
        "filex_mapping_authority": str(next(BUNDLE.glob("*.TMX")).resolve()),
        "filex_mapping": filex_mapping,
        "nitrogen_contrast": "terminal N2-N0 within W1 and within W3",
        "water_contrast": "disabled: W2 TRNO9 is outside the approved treatment set",
        "n_reals": args.n_reals,
        "noptmax": args.noptmax,
        "initial_ensemble_method": "sobol",
        "status": "built",
    }
    receipt_path = out / "formal_launch_receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Preflight passed:", json.dumps(receipt, ensure_ascii=False), flush=True)

    if args.execute:
        run(
            [
                sys.executable,
                str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir", str(out),
                "--case", case,
                "--mode", "ies",
                "--n-agents", str(args.n_agents),
                "--wait",
            ]
        )
        status = json.loads((out / "run_status.json").read_text(encoding="utf-8"))
        receipt["status"] = status.get("engineering_status", status.get("status"))
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
