"""Build the approved multi-seed formal Morris case set."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.common.project import git_metadata, sha256_file
from src.sensitivity.sa_build_sen_case import build_case


DEFAULT_SEEDS = [20260729, 20260812]


def validate_seed_plan(seeds: list[int]) -> list[int]:
    normalized = [int(seed) for seed in seeds]
    if len(normalized) < 2 or len(normalized) != len(set(normalized)):
        raise ValueError("Formal Morris requires at least two unique seeds")
    if 20260715 in normalized:
        raise ValueError("Seed 20260715 is reserved for failure diagnosis and cannot be formal")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description="Build independent formal Morris cases for reviewed fixed seeds")
    parser.add_argument("--bounds", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-profile", required=True)
    parser.add_argument("--out-root", required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--morris-r", type=int, default=30)
    parser.add_argument("--morris-p", type=int, default=6)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    if args.morris_r < 20:
        parser.error("Formal Morris requires r >= 20")
    try:
        args.seeds = validate_seed_plan(args.seeds)
    except ValueError as exc:
        parser.error(str(exc))
    git_info = git_metadata()
    if git_info.get("git_dirty") and not args.allow_dirty:
        parser.error("Refusing formal case build from a dirty worktree; commit and re-run")

    output = Path(args.out_root).resolve()
    if output.exists() and any(output.iterdir()):
        parser.error(f"Refusing to mix with an existing case set: {output}")
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for seed in args.seeds:
        case_dir = output / f"seed_{seed}"
        pst = build_case(
            args.bounds,
            case_dir=case_dir,
            workspace_dir=PROJECT_ROOT,
            cultivar="TM0008",
            morris_r=args.morris_r,
            morris_p=args.morris_p,
            random_seed=seed,
            output_profile=args.output_profile,
            input_dir=args.input_dir,
        )
        cases.append({"seed": seed, "case_dir": str(case_dir), "pst": str(pst)})
    with Path(args.bounds).open("r", encoding="utf-8-sig", newline="") as handle:
        parameter_count = sum(
            1 for row in csv.DictReader(handle) if str(row.get("status", "")).strip().lower() == "active"
        )
    manifest = {
        "run_type": "formal_morris_multiseed",
        "git_commit": git_info.get("git_commit"),
        "git_branch": git_info.get("git_branch"),
        "git_dirty": bool(git_info.get("git_dirty")),
        "bounds": str(Path(args.bounds).resolve()),
        "bounds_sha256": sha256_file(args.bounds),
        "input_dir": str(Path(args.input_dir).resolve()),
        "input_manifest_sha256": sha256_file(Path(args.input_dir) / "input_manifest.json"),
        "output_profile": str(Path(args.output_profile).resolve()),
        "output_profile_sha256": sha256_file(args.output_profile),
        "morris_r": args.morris_r,
        "morris_p": args.morris_p,
        "seeds": args.seeds,
        "parameter_count": parameter_count,
        "runs_per_seed": args.morris_r * (parameter_count + 1),
        "planned_total_runs": len(args.seeds) * args.morris_r * (parameter_count + 1),
        "cases": cases,
    }
    (output / "formal_morris_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
