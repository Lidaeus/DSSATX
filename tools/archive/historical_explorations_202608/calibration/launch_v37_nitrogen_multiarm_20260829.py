"""Build, audit, and sequentially run v37 local nitrogen arms A-E.

This launcher never calls a best-member selector.  Every frozen bound was
created from iteration-3 realization 137 by the companion setup script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "workspace/reports/e02_v37_n_response_multiarm_execution_20260829"
CONFIG_MANIFEST = REPORT / "arm_configuration_manifest.csv"
ANCHOR_PARAMS = (
    ROOT / "workspace/runs/e02_formal_v37_fresh_yield_source_sink_200x4_20260829"
    / "best_member_137_two_season_deterministic_20260829/best_member_137_params.csv"
)
EXPECTED_TREATMENTS = {"25SP": {2, 5, 10, 13}, "26SP": {1, 3, 9, 12}}
PORTS = {"a": 4121, "b": 4122, "c": 4123, "d": 4124, "e": 4125}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metadata() -> list[dict[str, object]]:
    frame = pd.read_csv(CONFIG_MANIFEST)
    rows: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        arm = str(row["arm"])
        run_id = f"e02_v37_nmulti_arm_{arm}_60x3_20260829"
        rows.append(
            {
                "arm": arm,
                "run_id": run_id,
                "case": f"e02_v37_nmulti_arm_{arm}_20260829",
                "bounds_id": str(row["bounds_id"]),
                "bounds_path": Path(str(row["bounds_path"])),
                "design_path": Path(str(row["design_path"])),
                "lambda": float(row["nresponse_lambda"]),
                "active": set(str(row["active_parameters"]).split(";")),
                "port": PORTS[arm],
            }
        )
    return rows


def audit_bounds(arm: dict[str, object]) -> None:
    bounds = pd.read_csv(Path(arm["bounds_path"]))
    bounds["key"] = bounds["name"].astype(str).str.lower()
    active = set(bounds.loc[bounds["status"].eq("active"), "key"])
    if active != arm["active"]:
        raise RuntimeError(f"arm {arm['arm']}: active set mismatch: {sorted(active ^ arm['active'])}")
    anchor = pd.read_csv(ANCHOR_PARAMS)
    anchor_values = dict(zip(anchor["name"].astype(str).str.lower(), pd.to_numeric(anchor["value"])))
    fixed = bounds.loc[bounds["status"].eq("fixed")]
    expected = fixed["key"].map(anchor_values).to_numpy(float)
    if not np.allclose(pd.to_numeric(fixed["init"]).to_numpy(float), expected, rtol=0, atol=1e-10):
        raise RuntimeError(f"arm {arm['arm']}: fixed parameter differs from iteration-3 member 137")
    if not np.allclose(fixed["lower"], fixed["upper"], rtol=0, atol=0):
        raise RuntimeError(f"arm {arm['arm']}: fixed parameter has a nonzero range")


def build_arm(arm: dict[str, object]) -> Path:
    run_dir = ROOT / "workspace/runs" / str(arm["run_id"])
    pst = run_dir / f"{arm['case']}.pst"
    if pst.is_file():
        return run_dir
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"refusing to mix partial artifacts: {run_dir}")
    command = [
        sys.executable, str(ROOT / "src/calibration/build_pest.py"),
        "--mode", "eggplant_stage2", "--prefix", str(arm["case"]),
        "--bounds-id", str(arm["bounds_id"]), "--bounds-crop", "eggplant",
        "--multiseason-design", str(arm["design_path"]), "--noptmax", "3",
        "--ies-num-reals", "60", "--batch", "DSSBatch.v48", "--harvest-var", "CHFPW",
        "--param-review-mode", "off", "--out-dir", str(run_dir),
    ]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / f"arm_{arm['arm']}_build.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (REPORT / f"arm_{arm['arm']}_build.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"arm {arm['arm']} build failed with {completed.returncode}")
    return run_dir


def audit_build(arm: dict[str, object], run_dir: Path) -> None:
    case = str(arm["case"])
    registry = pd.read_csv(run_dir / f"{case}_observation_registry.csv")
    positive = registry.loc[pd.to_numeric(registry["weight"]) > 0].copy()
    for season, expected in EXPECTED_TREATMENTS.items():
        actual = set(pd.to_numeric(positive.loc[positive["season_id"].eq(season), "treatment"]).astype(int))
        if actual != expected:
            raise RuntimeError(f"arm {arm['arm']} {season}: treatment scope {actual} != {expected}")
    if positive["sim_token"].isin(["CHPDTS", "CHPDTS_T", "HPODWS"]).any():
        raise RuntimeError(f"arm {arm['arm']}: active dry-harvest target found")
    for season, count in {"25SP": 20, "26SP": 10}.items():
        response = registry.loc[
            registry["season_id"].eq(season) & registry["obgnme"].str.contains("NRESP")
        ]
        if len(response) != count or not response["weight_mode"].eq("season_nse").all():
            raise RuntimeError(f"arm {arm['arm']} {season}: invalid N_RESPONSE rows")
        if not np.allclose(pd.to_numeric(response["nse_lambda"]), float(arm["lambda"])):
            raise RuntimeError(f"arm {arm['arm']} {season}: N_RESPONSE lambda mismatch")
        if response.groupby("treatment")["nse_sst"].nunique().gt(1).any():
            raise RuntimeError(f"arm {arm['arm']} {season}: unstable SST within response stratum")
        if response["treatment"].nunique() != 2:
            raise RuntimeError(f"arm {arm['arm']} {season}: expected two water-specific N strata")
    receipt = {
        "schema_version": 1,
        "arm": arm["arm"], "run_id": arm["run_id"], "case": arm["case"],
        "anchor_iteration": 3, "anchor_member": 137,
        "active_parameters": sorted(arm["active"]),
        "nresponse_lambda": arm["lambda"], "num_reals": 60, "noptmax": 3, "agents": 6,
        "official_exe_sha256": sha256(ROOT / "DSCSM048.EXE"),
        "workspace_exe_sha256": sha256(ROOT / "workspace/DSCSM048.EXE"),
        "build_audit": "pass", "audited_at": utc_now(),
    }
    if receipt["official_exe_sha256"] != receipt["workspace_exe_sha256"]:
        raise RuntimeError("workspace DSSAT executable is not the approved official executable")
    (run_dir / "nitrogen_arm_build_audit.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run_arm(arm: dict[str, object], run_dir: Path) -> None:
    case = str(arm["case"])
    status_path = run_dir / "run_status.json"
    if status_path.is_file():
        status = json.loads(status_path.read_text(encoding="utf-8"))
        if status.get("status") == "completed":
            return
    command = [
        sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
        "--run-dir", str(run_dir), "--case", case, "--mode", "ies",
        "--n-agents", "6", "--port", str(arm["port"]), "--wait",
    ]
    with (REPORT / f"arm_{arm['arm']}_run.log").open("a", encoding="utf-8") as log:
        log.write(f"\n[{utc_now()}] {' '.join(command)}\n")
        log.flush()
        completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise RuntimeError(f"arm {arm['arm']} run failed with {completed.returncode}")


def write_orchestrator(state: str, current_arm: str | None, completed: list[str], error: str | None = None) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1, "state": state, "current_arm": current_arm,
        "completed_arms": completed, "updated_at": utc_now(), "error": error,
        "anchor": {"iteration": 3, "member": 137},
        "conditional_f": "not_built_until_C_D_or_E_passes_postrun_science_gates",
    }
    (REPORT / "orchestrator_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    arms = metadata()
    built: list[tuple[dict[str, object], Path]] = []
    for arm in arms:
        audit_bounds(arm)
        run_dir = build_arm(arm)
        audit_build(arm, run_dir)
        built.append((arm, run_dir))
        print(f"[build-audit] arm {arm['arm']} passed", flush=True)
    if args.build_only:
        write_orchestrator("built_and_audited", None, [])
        return 0

    completed: list[str] = []
    try:
        for arm, run_dir in built:
            write_orchestrator("running", str(arm["arm"]), completed)
            run_arm(arm, run_dir)
            completed.append(str(arm["arm"]))
        write_orchestrator("arms_a_to_e_completed_pending_science_evaluation", None, completed)
    except Exception as exc:
        write_orchestrator("failed", None, completed, repr(exc))
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
