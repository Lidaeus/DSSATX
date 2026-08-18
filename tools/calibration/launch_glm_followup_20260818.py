"""WP4: launch a PEST-GLM follow-up run (pilot or formal) end to end.

Pipeline per invocation:

1. Preflight — refuse to start when DSSAT/PEST processes are already active
   or a stale exe/SPE backup exists.
2. Build (only when the target run dir is absent) via
   ``prepare_ies_to_glm_20260818.py`` (pool, arm, stage, noptmax).
3. Run ``tools/parallel/run_parallel.py --mode glm`` against the official
   DSSAT v4.8 exe/SPE (root ``DSCSM048.EXE`` is already the official build;
   the workspace copy is swapped in and restored in ``finally``).
4. On success (``--wait``), optionally run the Jacobian auditor (WP3) and the
   screening evaluator (WP5).

The official IES source directory is never modified.

Usage:
    python tools/calibration/launch_glm_followup_20260818.py \
        --stage pilot --pool top15 --objective-arm A --agents 2 --port 4045 --wait
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATE_TAG = "20260818"
OFFICIAL_EXE = ROOT / "DSCSM048.EXE"
WORKSPACE_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"


def case_name(arm: str, pool: str, stage: str) -> str:
    return f"e02_glm_{arm}_{pool}_{stage}_official_{DATE_TAG}"


def _active_processes() -> list[str]:
    result = subprocess.run(["tasklist"], capture_output=True, text=True, check=False)
    return [line.strip() for line in result.stdout.splitlines()
            if any(tok in line.upper() for tok in ("DSCSM", "PEST", "PANTHER"))]


def _preflight() -> None:
    active = _active_processes()
    if active:
        raise SystemExit("refusing to start: active DSSAT/PEST processes:\n" + "\n".join(active[:5]))
    if not OFFICIAL_EXE.is_file():
        raise SystemExit(f"official DSSAT exe missing: {OFFICIAL_EXE}")
    for stale in (ROOT / "workspace/DSCSM048.EXE.glm_followup_bk",
                  GENOTYPE_DIR / "TMGRO048.SPE.glm_followup_bk"):
        if stale.exists():
            raise SystemExit(f"stale backup present (previous run failed to restore): {stale}")


def _run(command: list[str]) -> int:
    printable = subprocess.list2cmdline([str(c) for c in command])
    print(f"+ {printable}", flush=True)
    return subprocess.run(command, cwd=str(ROOT), check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["pilot", "formal"], default="pilot")
    parser.add_argument("--pool", choices=["top15", "top23", "selected"], default="top15")
    parser.add_argument("--objective-arm", choices=["A", "B", "C"], default="A")
    parser.add_argument("--noptmax", type=int, default=None,
                        help="default: pilot=1, formal=5 (max 7; >5 requires --allow-noptmax-override)")
    parser.add_argument("--allow-noptmax-override", action="store_true")
    parser.add_argument("--agents", type=int, default=6)
    parser.add_argument("--variant", choices=["official"], default="official")
    parser.add_argument("--port", type=int, default=4045)
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--audit", action="store_true",
                        help="after a successful --wait run, execute WP3 Jacobian audit + WP5 screening")
    args = parser.parse_args()

    if args.wait and args.background:
        raise SystemExit("--wait and --background are mutually exclusive")

    noptmax = args.noptmax
    if noptmax is None:
        noptmax = 1 if args.stage == "pilot" else 5
    if args.stage == "formal" and noptmax > 5 and not args.allow_noptmax_override:
        raise SystemExit("formal noptmax > 5 requires --allow-noptmax-override (plan section 7 stage 3)")
    if noptmax > 7:
        raise SystemExit("noptmax must not exceed 7 (plan section 7 stage 3)")

    _preflight()
    case = case_name(args.objective_arm, args.pool, args.stage)
    run_dir = ROOT / "workspace/runs" / case
    if not run_dir.is_dir():
        rc = _run([sys.executable, "tools/calibration/prepare_ies_to_glm_20260818.py",
                   "--pool", args.pool, "--objective-arm", args.objective_arm,
                   "--stage", args.stage, "--noptmax", str(noptmax)])
        if rc != 0:
            return rc
    else:
        print(f"[launch] existing run dir reused: {run_dir}")

    parallel = [sys.executable, "tools/parallel/run_parallel.py",
                "--run-dir", str(run_dir), "--case", case,
                "--mode", "glm", "--n-agents", str(args.agents),
                "--port", str(args.port)]
    parallel += ["--wait"] if args.wait else ["--background"]

    # The GLM follow-up uses the official DSSAT v4.8 only; swap the workspace
    # exe (which run_parallel agents execute) to the official build and restore
    # it in finally so a preflight failure never strands a swapped exe.
    backup = ROOT / "workspace/DSCSM048.EXE.glm_followup_bk"
    import shutil
    shutil.copy2(WORKSPACE_EXE, backup)
    shutil.copy2(OFFICIAL_EXE, WORKSPACE_EXE)
    try:
        rc = _run(parallel)
    finally:
        if backup.exists():
            backup.replace(WORKSPACE_EXE)
            print("[restore] workspace DSCSM048.EXE restored")

    if rc != 0:
        return rc
    if args.wait and args.audit:
        rc = _run([sys.executable, "tools/calibration/analyze_glm_jacobian_20260818.py",
                   "--run-dir", str(run_dir)])
        if rc != 0:
            return rc
        rc = _run([sys.executable, "tools/calibration/evaluate_glm_followup_20260818.py",
                   "--run-dir", str(run_dir)])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
