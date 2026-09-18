"""Build, audit, and run the best71 local nitrogen A--E arms."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "workspace/reports/e02_v46_best71_nitrogen_multiarm_20260831"
MANIFEST = REPORT / "arm_configuration_manifest.csv"
SETUP = ROOT / "tools/calibration/setup_v46_best71_nitrogen_multiarm_20260831.py"
PORTS = {"a": 4211, "b": 4212, "c": 4213, "d": 4214, "e": 4215}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def status(state: str, current: str | None, completed: list[str], error: str | None = None) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "orchestrator_status.json").write_text(
        json.dumps({"schema_version": 1, "state": state, "current_arm": current,
                    "completed_arms": completed, "updated_at": now(), "error": error},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def setup() -> pd.DataFrame:
    subprocess.run([sys.executable, str(SETUP)], cwd=ROOT, check=True)
    frame = pd.read_csv(MANIFEST, encoding="utf-8-sig")
    if set(frame["arm"].astype(str)) != set(PORTS):
        raise RuntimeError("configuration manifest does not contain exactly A-E")
    return frame


def build(row: pd.Series) -> Path:
    arm = str(row["arm"])
    run_id = f"e02_v46_best71_n_{arm}_{row['label']}_60x3_20260831"
    case = f"e02_v46_best71_n_{arm}_20260831"
    run_dir = ROOT / "workspace/runs" / run_id
    pst = run_dir / f"{case}.pst"
    if not pst.is_file():
        if run_dir.exists() and any(run_dir.iterdir()):
            raise FileExistsError(f"refusing to mix partial build artifacts: {run_dir}")
        cmd = [sys.executable, str(ROOT / "src/calibration/build_pest.py"),
               "--mode", "eggplant_stage2", "--prefix", case,
               "--bounds-id", str(row["bounds_id"]), "--bounds-crop", "eggplant",
               "--multiseason-design", str(ROOT / row["design_path"]),
               "--noptmax", "3", "--ies-num-reals", "60", "--batch", "DSSBatch.v48",
               "--harvest-var", "CHFPW", "--param-review-mode", "off", "--out-dir", str(run_dir)]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        (REPORT / f"arm_{arm}_build.stdout.log").write_text(result.stdout, encoding="utf-8")
        (REPORT / f"arm_{arm}_build.stderr.log").write_text(result.stderr, encoding="utf-8")
        if result.returncode != 0:
            raise RuntimeError(f"arm {arm} build failed: {result.returncode}")
    return run_dir


def audit(row: pd.Series, run_dir: Path) -> None:
    arm = str(row["arm"])
    case = f"e02_v46_best71_n_{arm}_20260831"
    registry_path = run_dir / f"{case}_observation_registry.csv"
    if not registry_path.is_file():
        raise FileNotFoundError(f"arm {arm}: missing observation registry")
    registry = pd.read_csv(registry_path, encoding="utf-8-sig")
    positive = registry[pd.to_numeric(registry["weight"], errors="coerce") > 0]
    # N-response requires complete selected treatment cells in both seasons.
    expected_25 = {2, 3, 4, 5, 9, 10, 11, 12, 13, 14}
    expected_26 = set(range(1, 13))
    for season, expected in (("25SP", expected_25), ("26SP", expected_26)):
        actual = set(pd.to_numeric(positive.loc[positive["season_id"].eq(season), "treatment"], errors="coerce").dropna().astype(int))
        if actual != expected:
            raise RuntimeError(f"arm {arm} {season} active treatment scope {sorted(actual)} != {sorted(expected)}")
    nresp = positive[positive["obgnme"].astype(str).str.contains("NRESP", case=False, na=False)]
    if nresp.empty:
        raise RuntimeError(f"arm {arm}: no active N_RESPONSE observations")
    # The corrected contract removes LAIX and multi-date CANOPY targets.
    forbidden = positive[positive["obgnme"].astype(str).str.contains("LAIX|LAIDM|LAIDDM", case=False, regex=True, na=False)]
    if not forbidden.empty:
        raise RuntimeError(f"arm {arm}: forbidden CANOPY observations still have positive weight")
    if set(pd.to_numeric(positive["weight"], errors="coerce")) == {0.0}:
        raise RuntimeError(f"arm {arm}: no positive-weight observations")
    receipt = {"schema_version": 1, "arm": arm, "build_audit": "pass", "n_active": int(row["n_active"]),
               "n_response_obs": int(len(nresp)), "all22_treatments": True, "n2_n1_levels": True,
               "observation_policy": "configs/runs/e02_v46_best71_n12_objective_contract_20260831.csv",
               "audited_at": now()}
    (run_dir / "best71_nitrogen_build_audit.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(row: pd.Series, run_dir: Path) -> None:
    arm = str(row["arm"])
    case = f"e02_v46_best71_n_{arm}_20260831"
    run_id = f"e02_v46_best71_n_{arm}_{row['label']}_60x3_20260831"
    cmd = [sys.executable, str(ROOT / "tools/parallel/run_parallel.py"),
           "--run-dir", str(run_dir), "--case", case, "--mode", "ies",
           "--n-agents", "6", "--port", str(PORTS[arm]), "--wait"]
    with (REPORT / f"arm_{arm}_run.log").open("a", encoding="utf-8") as log:
        log.write(f"\n[{now()}] {' '.join(cmd)}\n")
        log.flush()
        result = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"arm {arm} run failed: {result.returncode}")
    state_path = run_dir / "run_status.json"
    if not state_path.is_file():
        raise RuntimeError(f"arm {arm}: missing run_status.json after manager exit")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--arm", choices=list(PORTS), help="run only one arm after build/audit")
    args = parser.parse_args()
    frame = setup()
    if args.arm:
        frame = frame[frame["arm"].astype(str).eq(args.arm)]
    items: list[tuple[pd.Series, Path]] = []
    for _, row in frame.iterrows():
        run_dir = build(row)
        audit(row, run_dir)
        items.append((row, run_dir))
        print(f"[build-audit] arm {row['arm']} passed", flush=True)
    if args.build_only:
        status("built_and_audited", None, [])
        return 0
    completed: list[str] = []
    try:
        for row, run_dir in items:
            arm = str(row["arm"])
            status("running", arm, completed)
            run(row, run_dir)
            completed.append(arm)
        status("calibration_completed_pending_all22_gate", None, completed)
    except Exception as exc:
        status("failed", None, completed, repr(exc))
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
