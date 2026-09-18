"""Build, audit, and sequentially run corrected v46 yield arms A-E."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "workspace/reports/e02_v46_corrected_yield_multiarm_20260830"
MANIFEST = REPORT / "arm_configuration_manifest.csv"
SETUP = ROOT / "tools/calibration/setup_v46_corrected_yield_multiarm_20260830.py"
EXPECTED = {"25SP": {3, 5, 11, 13}, "26SP": {5, 6, 11, 12}}
PORTS = {"a": 4141, "b": 4142, "c": 4143, "d": 4144, "e": 4145}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_status(state: str, current: str | None, completed: list[str], error: str | None = None) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "orchestrator_status.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state": state,
                "current_arm": current,
                "completed_arms": completed,
                "updated_at": utc_now(),
                "error": error,
                "postrun_gate": "deterministic all-22 shortlist; per-season mean of N2-N0 and N1-N0 over complete water strata",
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def load_arms() -> list[dict[str, object]]:
    subprocess.run([sys.executable, str(SETUP)], cwd=ROOT, check=True)
    rows = []
    for _, row in pd.read_csv(MANIFEST).iterrows():
        arm = str(row["arm"])
        label = str(row["label"])
        rows.append(
            {
                "arm": arm,
                "label": label,
                "bounds_id": str(row["bounds_id"]),
                "bounds_path": ROOT / Path(str(row["bounds_path"])),
                "design_path": ROOT / Path(str(row["design_path"])),
                "active": set(str(row["active_parameters"]).split(";")),
                "soil_sha256": str(row["soil_sha256"]),
                "run_id": f"e02_v46_arm_{arm}_{label}_60x3_20260830",
                "case": f"e02_v46_arm_{arm}_20260830",
                "port": PORTS[arm],
            }
        )
    return rows


def audit_source_and_bounds(item: dict[str, object]) -> None:
    official = ROOT / "DSCSM048.EXE"
    workspace = ROOT / "workspace/DSCSM048.EXE"
    if not official.is_file() or not workspace.is_file() or sha256(official) != sha256(workspace):
        raise RuntimeError("workspace DSSAT executable is not the approved official executable")
    for bundle in (
        ROOT / "data/user/experiments/xxql2501_user_ic_scheme4_20260830",
        ROOT / "data/user/experiments/xxql2601_formal_scheme4_soil_20260830",
    ):
        if sha256(bundle / "SOIL.SOL") != item["soil_sha256"]:
            raise RuntimeError(f"non-unified soil file: {bundle}")
    bounds = pd.read_csv(Path(item["bounds_path"]))
    bounds["key"] = bounds["name"].astype(str).str.lower()
    active = set(bounds.loc[bounds["status"].eq("active"), "key"])
    if active != item["active"]:
        raise RuntimeError(f"arm {item['arm']} active-set mismatch: {sorted(active ^ item['active'])}")
    soil = bounds.loc[bounds["key"].str.startswith("soil_")]
    if not soil["status"].eq("fixed").all():
        raise RuntimeError(f"arm {item['arm']} contains an active soil parameter")


def build(item: dict[str, object]) -> Path:
    run_dir = ROOT / "workspace/runs" / str(item["run_id"])
    pst = run_dir / f"{item['case']}.pst"
    if not pst.is_file():
        if run_dir.exists() and any(run_dir.iterdir()):
            raise FileExistsError(f"refusing to mix partial build artifacts: {run_dir}")
        command = [
            sys.executable, str(ROOT / "src/calibration/build_pest.py"),
            "--mode", "eggplant_stage2", "--prefix", str(item["case"]),
            "--bounds-id", str(item["bounds_id"]), "--bounds-crop", "eggplant",
            "--multiseason-design", str(item["design_path"]),
            "--noptmax", "3", "--ies-num-reals", "60", "--batch", "DSSBatch.v48",
            "--harvest-var", "CHFPW", "--param-review-mode", "off", "--out-dir", str(run_dir),
        ]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        REPORT.mkdir(parents=True, exist_ok=True)
        (REPORT / f"arm_{item['arm']}_build.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (REPORT / f"arm_{item['arm']}_build.stderr.log").write_text(completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(f"arm {item['arm']} build failed: {completed.returncode}")
    return run_dir


def audit_build(item: dict[str, object], run_dir: Path) -> None:
    registry = pd.read_csv(run_dir / f"{item['case']}_observation_registry.csv")
    positive = registry.loc[pd.to_numeric(registry["weight"]) > 0].copy()
    for season, expected in EXPECTED.items():
        actual = set(pd.to_numeric(positive.loc[positive["season_id"].eq(season), "treatment"]).astype(int))
        if actual != expected:
            raise RuntimeError(f"arm {item['arm']} {season} treatment scope {actual} != {expected}")
    if positive["sim_token"].isin({"CHPDTS", "CHPDTS_T", "HPODWS"}).any():
        raise RuntimeError(f"arm {item['arm']} has an active dry-yield target")
    late = positive.loc[
        positive["season_id"].eq("25SP")
        & positive["obsnme"].astype(str).str.contains("25194")
    ]
    if late.empty or not late["sim_token"].isin({"LAIDS", "LAIDDS", "LAIETS", "LWADDS", "LWETS", "SWADDS", "SWETS"}).all():
        raise RuntimeError(f"arm {item['arm']} 25194 is missing state targets or contains a yield target")
    receipt = {
        "schema_version": 1,
        "arm": item["arm"], "run_id": item["run_id"], "build_audit": "pass",
        "num_reals": 60, "noptmax": 3, "agents": 6,
        "soil_sha256": item["soil_sha256"], "simulation_last_event": 25194,
        "observed_yield_cutoff": 25192,
        "hard_gate": "per-season mean of N2-N0 and N1-N0; N3 excluded",
        "audited_at": utc_now(),
    }
    (run_dir / "v46_build_audit.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(item: dict[str, object], run_dir: Path) -> None:
    status = run_dir / "run_status.json"
    if status.is_file() and json.loads(status.read_text(encoding="utf-8")).get("status") == "completed":
        return
    command = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir), "--case", str(item["case"]), "--mode", "ies",
        "--n-agents", "6", "--port", str(item["port"]), "--wait",
    ]
    with (REPORT / f"arm_{item['arm']}_run.log").open("a", encoding="utf-8") as log:
        log.write(f"\n[{utc_now()}] {' '.join(command)}\n")
        log.flush()
        completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise RuntimeError(f"arm {item['arm']} run failed: {completed.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    items = load_arms()
    built = []
    for item in items:
        audit_source_and_bounds(item)
        run_dir = build(item)
        audit_build(item, run_dir)
        built.append((item, run_dir))
        print(f"[build-audit] arm {item['arm']} passed", flush=True)
    if args.build_only:
        write_status("built_and_audited", None, [])
        return 0
    completed_arms: list[str] = []
    try:
        for item, run_dir in built:
            write_status("running", str(item["arm"]), completed_arms)
            run(item, run_dir)
            completed_arms.append(str(item["arm"]))
        write_status("calibration_completed_pending_all22_mean_n_gate", None, completed_arms)
    except Exception as exc:
        write_status("failed", None, completed_arms, repr(exc))
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
