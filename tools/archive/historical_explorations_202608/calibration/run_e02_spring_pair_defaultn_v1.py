"""Run the two-spring default-N v1 calibration."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyemu


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "configs/runs/e02_n_response_snam_lnam_chpdtraw_nofresh_v1.csv"
GROUP_POLICY = ROOT / "configs/runs/t10_water_n_response_group_policy_harvestdry250_v1.csv"
DEFAULT_BOUNDS_ID = "eggplant_e02_spring_pair_defaultn_v1_20260730"
INPUT_DIR = ROOT / "data/user/experiments/xxql2501_special_defaultn_page25_v1_20260730"
BUNDLES = (
    {
        "season_id": "25SP",
        "experiment_code": "XXQL2501",
        "bundle_path": ROOT / "data/user/experiments/xxql2501_special_defaultn_page25_v1_20260730",
        "treatments": [2, 5, 10, 13],
        "filex": "XXQL2501.TMX",
    },
    {
        "season_id": "26SP",
        "experiment_code": "XXQL2601",
        "bundle_path": ROOT / "data/user/experiments/xxql2601_special_defaultn_page25_v1_20260730",
        "treatments": [1, 3, 9, 12],
        "filex": "XXQL2601.TMX",
    },
)


def run(command: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(bundle: dict) -> dict:
    bundle_path = Path(bundle["bundle_path"])
    manifest_path = bundle_path / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    audit = manifest.get("initial_mineral_n_audit") or {}
    if float(audit.get("SNO3", -1)) != 1.0 or float(audit.get("SNH4", -1)) != 0.5:
        raise RuntimeError(f"{bundle['season_id']}: bundle is not default SNO3=1.0/SNH4=0.5")
    filex = bundle_path / str(bundle["filex"])
    lines = filex.read_text(encoding="utf-8", errors="ignore").splitlines()
    planting_row = None
    for idx, line in enumerate(lines):
        if line.lstrip().startswith("@P PDATE"):
            for row in lines[idx + 1 :]:
                if row.strip() and not row.startswith(("@", "*", "!")):
                    planting_row = row
                    break
            break
    if planting_row is None:
        raise RuntimeError(f"{bundle['season_id']}: planting row not found in {filex}")
    fields = planting_row.split()
    if len(fields) < 16 or fields[11] != "25" or fields[14] != "-99":
        raise RuntimeError(
            f"{bundle['season_id']}: expected PAGE=25 and SPRL=-99, found row {planting_row!r}"
        )
    return {
        "season_id": bundle["season_id"],
        "bundle": str(bundle_path),
        "manifest_sha256": sha256(manifest_path),
        "filex_sha256": sha256(filex),
        "row_count": int(audit.get("row_count", 0)),
        "ic_count": int(audit.get("ic_count", 0)),
    }


def build_runtime_design() -> tuple[dict, dict[str, dict]]:
    bundle_audit: dict[str, dict] = {}
    seasons = []
    for bundle in BUNDLES:
        audit = verify_bundle(bundle)
        bundle_audit[str(bundle["season_id"])] = audit
        seasons.append(
            {
                "season_id": bundle["season_id"],
                "experiment_code": bundle["experiment_code"],
                "bundle_path": str(Path(bundle["bundle_path"]).relative_to(ROOT)).replace("/", "\\"),
                "bundle_manifest_sha256": audit["manifest_sha256"],
                "role": "calibration",
                "treatments": bundle["treatments"],
            }
        )
    payload = {
        "schema_version": 1,
        "design_id": "eggplant_e02_spring_pair_defaultn_v1_20260730",
        "cultivar_identity": "same_eggplant_cultivar",
        "shared_parameter_scope": (
            "55 shared crop/process parameters; default initial mineral N; "
            "PAGE=25; SPRL=-99; FL-VS fixed at 120; SOIL_SLPF active; "
            "fresh harvest excluded from Phi; dry-harvest indicators on original scale"
        ),
        "observation_policy": str(POLICY.relative_to(ROOT)).replace("/", "\\"),
        "group_policy": str(GROUP_POLICY.relative_to(ROOT)).replace("/", "\\"),
        "nitrogen_response_objective": {
            "enabled": True,
            "mapping_csv": "configs/runs/e02_spring_pair_water_n_mapping_20260730.csv",
            "source_variable": "CHPDT",
            "contrast": "ln1p_Nk_minus_ln1p_N0",
            "response_target": "observed_shape",
            "levels": ["N3"],
            "sigma_floor": 0.1,
            "budget_rule": "0.75 total per season; count-corrected across both water levels and the N3-N0 contrast",
        },
        "seasons": seasons,
        "t10_scheme": {
            "purpose": "Two-spring calibration with default initial mineral N and PAGE25 planting authority",
            "harvest_budget_total": 2.5,
            "absolute_harvest_budget": 1.75,
            "nitrogen_response_budget": 0.75,
            "active_parameters": 55,
            "ADAP": "diagnostic_only",
            "MDAP": "diagnostic_only",
            "seasonal_offsets": "none",
            "FileX_initial_SNO3": 1.0,
            "FileX_initial_SNH4": 0.5,
            "FileX_PAGE": 25,
            "FileX_SPRL": -99,
            "canonical_input_rule": "Only the two explicitly hashed special_defaultn_page25 bundles are valid for this design",
        },
    }
    return payload, bundle_audit


def verify_run(
    run_dir: Path,
    case: str,
    n_reals: int,
    noptmax: int,
    bundle_audit: dict[str, dict],
    *,
    bounds_id: str,
    n_agents: int,
) -> dict:
    pst = pyemu.Pst(str(run_dir / f"{case}.pst"))
    registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    bounds = pd.read_csv(
        ROOT / f"data/parameter_registry/bounds_frozen/eggplant/{bounds_id}.csv",
        encoding="utf-8-sig",
    )
    active = registry.loc[pd.to_numeric(registry["weight"], errors="coerce") > 0].copy()
    family = active["variable_family"] if "variable_family" in active.columns else active["obgnme"]
    response = active.loc[family.astype(str).str.contains("N_RESPONSE|NRESP", case=False, regex=True)]
    fresh_cum = active.loc[active["obgnme"].astype(str).str.contains("CHFPWM", case=False, regex=False)]
    problems: list[str] = []
    if pst.npar_adj != 55:
        problems.append(f"expected 55 adjustable parameters, got {pst.npar_adj}")
    if int(pst.control_data.noptmax) != noptmax:
        problems.append(f"expected noptmax={noptmax}")
    if int(pst.pestpp_options.get("ies_num_reals", -1)) != n_reals:
        problems.append(f"expected ies_num_reals={n_reals}")
    if len(response) == 0:
        problems.append("no active N_RESPONSE observations")
    if len(fresh_cum) != 0:
        problems.append(f"expected CHFPWM to stay diagnostic-only, found {len(fresh_cum)} active observations")
    flvs = bounds.loc[bounds["name"].eq("FL-VS")]
    if flvs.empty or tuple(flvs.iloc[0][["init", "lower", "upper"]].astype(float)) != (120.0, 120.0, 120.0):
        problems.append("FL-VS is not fixed at 120")
    slpf = bounds.loc[bounds["name"].eq("SOIL_SLPF")]
    if slpf.empty or tuple(slpf.iloc[0][["lower", "upper"]].astype(float)) != (0.9, 0.96):
        problems.append("SOIL_SLPF bounds are not 0.90-0.96")
    adap = active.loc[active["obgnme"].astype(str).str.contains("ADAP", case=False)]
    if not adap.empty:
        problems.append("ADAP entered Phi")
    if problems:
        raise RuntimeError("two-spring default-N preflight failed: " + "; ".join(problems))
    return {
        "run_id": case,
        "run_dir": str(run_dir),
        "bounds_id": bounds_id,
        "n_parameters_adjustable": int(pst.npar_adj),
        "n_observations_active": int(pst.nnz_obs),
        "n_response_observations": int(len(response)),
        "n_fresh_cum_observations": int(len(fresh_cum)),
        "selected_treatments": {item["season_id"]: item["treatments"] for item in BUNDLES},
        "n_reals": n_reals,
        "noptmax": noptmax,
        "n_agents_default": int(n_agents),
        "filex_initial_mineral_n": {"SNO3": 1.0, "SNH4": 0.5},
        "filex_planting_authority": {"PAGE": 25, "SPRL": -99},
        "input_bundles": bundle_audit,
        "status": "built",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id")
    parser.add_argument("--n-reals", type=int, default=150)
    parser.add_argument("--noptmax", type=int, default=5)
    parser.add_argument("--n-agents", type=int, default=7)
    parser.add_argument("--random-seed", type=int, default=20260730)
    parser.add_argument("--bounds-id", default=DEFAULT_BOUNDS_ID)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    case = args.run_id or f"e02_spring_pair_defaultn_v1_observedshape_{args.n_reals}x{args.noptmax}_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir = ROOT / "workspace/runs" / case
    if run_dir.exists():
        raise FileExistsError(run_dir)
    run_dir.mkdir(parents=True)

    design_payload, bundle_audit = build_runtime_design()
    runtime_design = run_dir / "runtime_multiseason_design.json"
    runtime_design.write_text(
        json.dumps(design_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    run([
        sys.executable,
        str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2",
        "--multiseason-design", str(runtime_design),
        "--input-dir", str(INPUT_DIR),
        "--bounds-id", str(args.bounds_id),
        "--bounds-crop", "eggplant",
        "--prefix", case,
        "--noptmax", str(args.noptmax),
        "--ies-num-reals", str(args.n_reals),
        "--random-seed", str(args.random_seed),
        "--bad-phi-sigma", "1e300",
        "--batch", str(INPUT_DIR / "DSSBatch.v48"),
        "--harvest-var", "CHPDT",
        "--include-n-uptake",
        "--out-dir", str(run_dir),
        "--param-review-mode", "off",
        "--observation-policy-csv", str(POLICY),
    ])

    pst_path = run_dir / f"{case}.pst"
    pst = pyemu.Pst(str(pst_path))
    pst.pestpp_options.update(
        {
            "ies_use_approx": False,
            "ies_lambda_mults": "0.5,1.0,10.0",
            "lambda_scale_fac": "0.9,1.0",
            "ies_enforce_bounds": True,
        }
    )
    pst.write(str(pst_path))

    receipt = verify_run(
        run_dir,
        case,
        args.n_reals,
        args.noptmax,
        bundle_audit,
        bounds_id=str(args.bounds_id),
        n_agents=int(args.n_agents),
    )
    receipt["design"] = str(runtime_design)
    receipt_path = run_dir / "formal_launch_receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Preflight passed: {receipt_path}")
    if not args.execute:
        return 0

    run([
        sys.executable,
        str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir),
        "--case", case,
        "--mode", "ies",
        "--n-agents", str(args.n_agents),
        "--wait",
    ])
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if status.get("engineering_status") != "engineering_validated":
        raise RuntimeError(status.get("engineering_status_error") or status.get("engineering_status"))
    receipt["status"] = "engineering_validated"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
