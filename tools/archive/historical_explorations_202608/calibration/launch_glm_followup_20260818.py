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
import json
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


def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_reusable_design(run_dir: Path, args, noptmax: int) -> None:
    """Refuse to reuse a same-named run dir whose design does not match.

    Code-review 20260818 P1: an existing directory was silently reused even
    after the selected-pool definition changed, so a stale 23-parameter task
    ran under a 'selected' label.  Reuse now requires pool, arm, stage,
    noptmax, derinc scale and (for selected pools) the parameter-set hash to
    match the on-disk ``glm_design.json`` / ``selected_parameters.csv``.
    """
    design_path = run_dir / "glm_design.json"
    if not design_path.is_file():
        raise SystemExit(
            f"existing run dir lacks glm_design.json; refusing blind reuse: {run_dir}")
    design = json.loads(design_path.read_text(encoding="utf-8"))
    mismatches = []
    if design.get("pool") != args.pool:
        mismatches.append(f"pool {design.get('pool')} != {args.pool}")
    if design.get("objective_arm") != args.objective_arm:
        mismatches.append(f"arm {design.get('objective_arm')} != {args.objective_arm}")
    if design.get("stage") != args.stage:
        mismatches.append(f"stage {design.get('stage')} != {args.stage}")
    if int(design.get("noptmax", -1)) != int(noptmax):
        mismatches.append(f"noptmax {design.get('noptmax')} != {noptmax}")
    if abs(float(design.get("derinc_scale", 1.0)) - float(args.derinc_scale)) > 1e-12:
        mismatches.append(f"derinc_scale {design.get('derinc_scale')} != {args.derinc_scale}")
    if args.pool == "selected":
        selected_csv = run_dir / "selected_parameters.csv"
        if not selected_csv.is_file():
            mismatches.append("selected_parameters.csv missing")
        else:
            source = Path(args.selected_set_csv) if args.selected_set_csv else _default_selected_csv()
            if _sha256_file(selected_csv) != _sha256_file(source):
                mismatches.append(
                    f"selected_parameters.csv differs from {source}; the pool "
                    "definition changed since this run dir was built")
    if mismatches:
        raise SystemExit(
            "existing run dir does not match the requested design — refusing to "
            "reuse (stale task from before a code/pool fix would silently run "
            "otherwise):\n  " + "\n  ".join(mismatches) +
            f"\nMove or archive {run_dir} and launch again to rebuild.")


def _default_selected_csv() -> Path:
    from tools.calibration.prepare_ies_to_glm_20260818 import DEFAULT_SELECTED_SET_CSV
    return DEFAULT_SELECTED_SET_CSV


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
    parser.add_argument("--derinc-scale", type=float, default=1.0,
                        help="passed through to the builder (0.5/2.0 spot checks)")
    parser.add_argument("--selected-set-csv", type=Path, default=None,
                        help="passed through to the builder for --pool selected")
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
        build_cmd = [sys.executable, "tools/calibration/prepare_ies_to_glm_20260818.py",
                     "--pool", args.pool, "--objective-arm", args.objective_arm,
                     "--stage", args.stage, "--noptmax", str(noptmax),
                     "--derinc-scale", str(args.derinc_scale)]
        if args.selected_set_csv is not None:
            build_cmd += ["--selected-set-csv", str(args.selected_set_csv)]
        rc = _run(build_cmd)
        if rc != 0:
            return rc
    else:
        _verify_reusable_design(run_dir, args, noptmax)
        print(f"[launch] existing run dir reused (design verified): {run_dir}")

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
