"""Build, run, audit and compare the three-season formal Sobol N=128 level.

The script appends N=128 to the existing ``sobol_formal_v1`` campaigns.  It
never rebuilds N=64 and never builds N=256.  Runs are sequential by season to
avoid manager-port races and resource contention.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterator


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.project import git_metadata, sha256_file
from src.sensitivity.sobol_case import build_sobol_case


BOUNDS = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_formal_multiseason_candidate_v4_20260721.csv"
RUN_ROOT = ROOT / "workspace/runs/sobol_formal_v1"
SEED = 20260729
SAMPLES = 128
CASE = "sa_sen_sobol"
SEASONS = {
    "XXQL2501": {
        "approval": ROOT / "configs/sa/approved_topk/eggplant_formal_sobol_top23_v1_20260721_xxql2501.json",
        "profile": ROOT / "configs/sa/eggplant_formal_xxql2501_outputs_20260720.json",
        "input": ROOT / "data/user/experiments/xxql2501_sa_controlled_candidate_20260720",
    },
    "XXQL2502": {
        "approval": ROOT / "configs/sa/approved_topk/eggplant_formal_sobol_top23_v1_20260721_xxql2502.json",
        "profile": ROOT / "configs/sa/eggplant_formal_xxql2502_outputs_20260720.json",
        "input": ROOT / "data/user/experiments/xxql2502_sa_controlled_candidate_20260720",
    },
    "XXQL2601": {
        "approval": ROOT / "configs/sa/approved_topk/eggplant_formal_sobol_top23_v1_20260721_xxql2601.json",
        "profile": ROOT / "configs/sa/eggplant_formal_xxql2601_outputs_20260720.json",
        "input": ROOT / "data/user/experiments/xxql2601_sa_controlled_tn12_w1_candidate_20260721",
    },
}


def _case_dir(season: str, samples: int = SAMPLES) -> Path:
    return RUN_ROOT / season / f"n{samples:04d}_seed_{SEED}"


def _run(command: list[str]) -> None:
    print("+", subprocess.list2cmdline(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {subprocess.list2cmdline(command)}")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _validated_level(season: str, samples: int) -> None:
    case_dir = _case_dir(season, samples)
    status = _load_json(case_dir / "run_status.json")
    if status.get("status") != "completed" or status.get("scientific_status") != "validated":
        raise ValueError(f"{season} N={samples} is not completed/validated: {case_dir}")
    for relative in (
        "sobol_audit/sobol_run_quality.json",
        "sobol_bootstrap/sobol_bootstrap_quality.json",
    ):
        report = _load_json(case_dir / relative)
        if report.get("science_validated") is not True:
            raise ValueError(f"{season} N={samples} quality report failed: {relative}")


def _require_clean_worktree() -> None:
    info = git_metadata()
    if info.get("git_dirty"):
        raise ValueError("Formal N=128 build requires a clean worktree; commit or stash changes first")


def _append_campaign_case(manifest_path: Path, case_dir: Path, pst_path: Path) -> None:
    campaign = _load_json(manifest_path)
    planned = [int(value) for value in campaign.get("planned_sample_schedule", [])]
    if SAMPLES not in planned:
        raise ValueError(f"Campaign does not preregister N={SAMPLES}: {manifest_path}")
    cases = list(campaign.get("cases") or [])
    existing = [item for item in cases if int(item.get("base_samples", -1)) == SAMPLES]
    if existing:
        expected = str(case_dir.resolve())
        if len(existing) != 1 or str(Path(existing[0]["case_dir"]).resolve()) != expected:
            raise ValueError(f"Campaign contains a conflicting N={SAMPLES} case")
        return
    parameter_count = int(campaign["parameter_count"])
    cases.append(
        {
            "base_samples": SAMPLES,
            "parameter_count": parameter_count,
            "expected_model_runs": SAMPLES * (parameter_count + 2),
            "case_dir": str(case_dir.resolve()),
            "pst_sha256": sha256_file(pst_path),
        }
    )
    campaign["cases"] = sorted(cases, key=lambda item: int(item["base_samples"]))
    campaign["built_sample_schedule"] = sorted({int(item["base_samples"]) for item in cases})
    campaign["expected_initial_model_runs"] = sum(int(item["expected_model_runs"]) for item in cases)
    manifest_path.write_text(json.dumps(campaign, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build() -> None:
    _require_clean_worktree()
    for season, config in SEASONS.items():
        _validated_level(season, 64)
        case_dir = _case_dir(season)
        manifest = RUN_ROOT / season / "formal_sobol_campaign.json"
        if case_dir.exists() and any(case_dir.iterdir()):
            pst = case_dir / f"{CASE}.pst"
            if not pst.is_file():
                raise FileExistsError(f"Refusing incomplete non-empty N=128 directory: {case_dir}")
            _append_campaign_case(manifest, case_dir, pst)
            print(f"[SKIP] {season} N=128 already built")
            continue
        print(f"[BUILD] {season} N=128")
        pst = build_sobol_case(
            bounds_csv=BOUNDS,
            approval_json=config["approval"],
            case_dir=case_dir,
            workspace_dir=ROOT,
            output_profile=config["profile"],
            input_dir=config["input"],
            samples=SAMPLES,
            random_seed=SEED,
            run_type="sensitivity_sobol_formal_case",
        )
        _append_campaign_case(manifest, case_dir, pst)
    print("Three-season Sobol N=128 build complete")


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextmanager
def _single_runner() -> Iterator[None]:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    lock = RUN_ROOT / ".n128_runner.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text(encoding="ascii").strip())
        except ValueError:
            pid = -1
        if _process_exists(pid):
            raise RuntimeError(f"Another N=128 runner is active (PID {pid}); refusing duplicate launch")
        lock.unlink()
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _complete(case_dir: Path) -> bool:
    rec = case_dir / f"{CASE}.rec"
    return rec.is_file() and "analysis complete" in rec.read_text(encoding="utf-8", errors="ignore")


def run(n_agents: int) -> None:
    with _single_runner():
        for season in SEASONS:
            case_dir = _case_dir(season)
            if not (case_dir / f"{CASE}.pst").is_file():
                raise FileNotFoundError(f"Build N=128 before running: {case_dir}")
            if _complete(case_dir):
                print(f"[SKIP] {season} N=128 already complete")
                continue
            print(f"[RUN] {season} N=128 with {n_agents} agents")
            _run(
                [
                    sys.executable,
                    str(ROOT / "tools/parallel/run_parallel.py"),
                    "--run-dir",
                    str(case_dir),
                    "--case",
                    CASE,
                    "--mode",
                    "sen",
                    "--n-agents",
                    str(n_agents),
                    "--wait",
                ]
            )


def postprocess(replicates: int) -> None:
    for season, config in SEASONS.items():
        case_dir = _case_dir(season)
        if not _complete(case_dir):
            raise ValueError(f"Cannot postprocess incomplete case: {case_dir}")
        _run([sys.executable, "-m", "src.sensitivity.sobol_audit", "--case-dir", str(case_dir)])
        _run(
            [
                sys.executable,
                "-m",
                "src.sensitivity.sobol_bootstrap",
                "--case-dir",
                str(case_dir),
                "--out-dir",
                str(case_dir / "sobol_bootstrap"),
                "--replicates",
                str(replicates),
                "--bootstrap-seed",
                str(SEED),
            ]
        )
        _run(
            [
                sys.executable,
                str(ROOT / "tools/parallel/run_parallel.py"),
                "--run-dir",
                str(case_dir),
                "--case",
                CASE,
                "--mode",
                "sen",
                "--finalize",
            ]
        )
        _run(
            [
                sys.executable,
                "-m",
                "src.sensitivity.sobol_convergence",
                "--case-dir",
                str(_case_dir(season, 64)),
                "--case-dir",
                str(case_dir),
                "--output-profile",
                str(config["profile"]),
                "--campaign-manifest",
                str(RUN_ROOT / season / "formal_sobol_campaign.json"),
                "--out-dir",
                str(RUN_ROOT / season / "convergence_n0064_n0128"),
            ]
        )


def status() -> None:
    expected = SAMPLES * 25
    for season in SEASONS:
        case_dir = _case_dir(season)
        if not case_dir.exists():
            print(f"{season}: NOT_BUILT")
            continue
        state_path = case_dir / "run_status.json"
        state = _load_json(state_path) if state_path.is_file() else {}
        log = case_dir / "manager/panther_manager.stdout.log"
        completed = failed = 0
        if log.is_file():
            text = log.read_text(encoding="utf-8", errors="ignore")
            completed_matches = re.findall(r"C(\d+)", text)
            failed_matches = re.findall(r"F(\d+)", text)
            completed = int(completed_matches[-1]) if completed_matches else 0
            failed = int(failed_matches[-1]) if failed_matches else 0
        print(
            f"{season}: status={state.get('status', 'built')} science={state.get('scientific_status', 'pending')} "
            f"completed={completed}/{expected} failed={failed}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--build", action="store_true")
    actions.add_argument("--run", action="store_true")
    actions.add_argument("--postprocess", action="store_true")
    actions.add_argument("--all", action="store_true", help="build, run, audit/bootstrap/finalize and compare N=64->128")
    actions.add_argument("--status", action="store_true")
    parser.add_argument("--n-agents", type=int, default=12)
    parser.add_argument("--replicates", type=int, default=1000)
    args = parser.parse_args()
    if args.n_agents < 1 or args.replicates < 100:
        parser.error("--n-agents must be >=1 and --replicates must be >=100")
    if args.build:
        build()
    elif args.run:
        run(args.n_agents)
    elif args.postprocess:
        postprocess(args.replicates)
    elif args.all:
        build()
        run(args.n_agents)
        postprocess(args.replicates)
    else:
        status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
