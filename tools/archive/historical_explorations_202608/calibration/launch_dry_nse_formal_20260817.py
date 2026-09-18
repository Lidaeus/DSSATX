"""Launch, finalize, select, and replay the official formal confirmation run."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = "e02_fixedsoil_nse_official_25sp26sp_200x6_20260817"
RUN_DIR = ROOT / "workspace/runs" / CASE
OFFICIAL_EXE = ROOT / "DSCSM048.EXE"
OFFICIAL_SPE = Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE")
DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"
PORT = 4060


def _status(phase: str, **extra: object) -> None:
    payload = {"schema_version": 1, "case": CASE, "phase": phase, "updated_at": datetime.now(timezone.utc).isoformat(), **extra}
    (RUN_DIR / "formal_pipeline_status.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _active_processes() -> list[str]:
    result = subprocess.run(["tasklist"], capture_output=True, text=True, check=False)
    return [line.strip() for line in result.stdout.splitlines() if any(x in line.upper() for x in ("DSCSM", "PESTPP", "PANTHER"))]


def _swap() -> list[tuple[Path, Path]]:
    for path in (OFFICIAL_EXE, OFFICIAL_SPE, DEFAULT_EXE, GENOTYPE_DIR / "TMGRO048.SPE.base"):
        if not path.is_file():
            raise FileNotFoundError(path)
    replacements: list[tuple[Path, Path]] = []
    targets = [
        (DEFAULT_EXE, OFFICIAL_EXE),
        (GENOTYPE_DIR / "TMGRO048.SPE.base", OFFICIAL_SPE),
    ]
    plain = GENOTYPE_DIR / "TMGRO048.SPE"
    if plain.is_file():
        targets.append((plain, OFFICIAL_SPE))
    try:
        for live, source in targets:
            backup = live.with_name(live.name + ".default_backup_20260817_formal")
            if backup.exists():
                raise FileExistsError(f"stale swap backup: {backup}")
            live.replace(backup)
            shutil.copy2(source, live)
            replacements.append((live, backup))
    except Exception:
        _restore(replacements)
        raise
    return replacements


def _restore(replacements: list[tuple[Path, Path]]) -> None:
    for live, backup in reversed(replacements):
        if live.exists():
            live.unlink()
        if backup.exists():
            backup.replace(live)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-agents", type=int, default=6)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    if args.n_agents != 6:
        parser.error("formal confirmation contract requires exactly 6 agents")
    pst = RUN_DIR / f"{CASE}.pst"
    contract = RUN_DIR / "formal_confirmation_contract.json"
    if not pst.is_file() or not contract.is_file():
        print("ERROR: formal run is not prepared", file=sys.stderr)
        return 1
    if (RUN_DIR / f"{CASE}.rec").exists():
        print("ERROR: partial/completed PEST output exists; refusing to overwrite", file=sys.stderr)
        return 2
    active = _active_processes()
    if active:
        print("ERROR: DSSAT/PEST processes are already active:\n" + "\n".join(active), file=sys.stderr)
        return 3

    print(f"[launch] case={CASE}")
    print("[launch] official DSSAT v4.8 | 200 realizations | noptmax=6 | agents=6")
    print("[launch] bounds: PHTMAX=45..75, PODUR=12..58; other bounds unchanged")
    print("[launch] objective: raw cumulative dry, phi_season=75*(1-NSE_season)")
    _status("starting", agents=6, port=args.port)
    replacements: list[tuple[Path, Path]] = []
    rc = 1
    try:
        replacements = _swap()
        _status("calibrating", agents=6, port=args.port, official_dssat=True)
        command = [
            sys.executable, "tools/parallel/run_parallel.py", "--run-dir", str(RUN_DIR),
            "--case", CASE, "--mode", "ies", "--n-agents", "6", "--port", str(args.port), "--wait",
        ]
        rc = int(subprocess.run(command, cwd=ROOT, check=False).returncode)
    finally:
        if replacements:
            _restore(replacements)
            print("[restore] default executable and genotype templates restored")
    if rc:
        _status("calibration_failed", exit_code=rc)
        return rc

    _status("finalizing")
    finalize = subprocess.run([
        sys.executable, "-m", "src.calibration.finalize_calibration", "--run-dir", str(RUN_DIR), "--case", CASE,
    ], cwd=ROOT, check=False)
    if finalize.returncode:
        _status("finalize_failed", exit_code=int(finalize.returncode))
        return int(finalize.returncode)

    _status("deterministic_candidate_replays")
    replay = subprocess.run([sys.executable, "tools/calibration/postprocess_dry_nse_formal_20260817.py"], cwd=ROOT, check=False)
    if replay.returncode:
        _status("candidate_replay_failed", exit_code=int(replay.returncode))
        return int(replay.returncode)
    _status("completed", exit_code=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
