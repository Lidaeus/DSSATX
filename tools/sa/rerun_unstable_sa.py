"""Run only the approved Morris/Sobol sensitivity expansions that remain unstable.

The campaign is intentionally narrow and non-destructive:
  * Morris: rerun only XXQL2502 at r=40 (three fixed seeds).
  * Sobol: retain N=128 as the baseline and run N=256 in all three seasons.

It creates new directories and never modifies the original N=64/N=128 or
Morris r=10/r=20 cases.  A non-zero exit code of 2 means execution completed
but at least one predeclared stability/convergence gate was still not met.

Examples
--------
python tools/sa/rerun_unstable_sa.py --status
python tools/sa/rerun_unstable_sa.py --dry-run
python tools/sa/rerun_unstable_sa.py --all
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.project import git_metadata, sha256_file
from src.sensitivity.sobol_case import build_sobol_case, load_approved_topk


DEFAULT_PLAN = ROOT / "configs" / "sa" / "stability_rerun_v1_20260722.json"
MORRIS_CASE = "sa_sen_morris"
SOBOL_CASE = "sa_sen_sobol"


def load_plan(path: str | Path) -> dict[str, Any]:
    plan_path = Path(path).resolve()
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    if data.get("approval_scope") != "sensitivity_stability_rerun":
        raise ValueError("Unexpected stability-rerun approval scope")
    if int(data.get("schema_version", 0)) != 1:
        raise ValueError("Unsupported stability-rerun plan schema")
    for section in ("morris", "sobol"):
        if not isinstance(data.get(section), dict):
            raise ValueError(f"Plan is missing {section} configuration")
    return data


def resolve(root_relative: str | Path) -> Path:
    path = Path(root_relative)
    return path if path.is_absolute() else ROOT / path


def run(command: list[str], *, dry_run: bool, allowed: set[int] | None = None) -> int:
    print("+", subprocess.list2cmdline(command), flush=True)
    if dry_run:
        return 0
    result = subprocess.run(command, cwd=ROOT, check=False)
    expected = {0} if allowed is None else allowed
    if result.returncode not in expected:
        raise RuntimeError(f"Command failed ({result.returncode}): {subprocess.list2cmdline(command)}")
    return int(result.returncode)


def require_clean_worktree(plan: dict[str, Any], *, dry_run: bool) -> None:
    if not plan.get("requires_clean_worktree", True) or dry_run:
        return
    metadata = git_metadata()
    if metadata.get("git_dirty"):
        raise RuntimeError(
            "Refusing to build formal stability reruns from a dirty worktree. "
            "Commit/stash the intended code first, then rerun this command."
        )


def complete(case_dir: Path, case: str) -> bool:
    record = case_dir / f"{case}.rec"
    return record.is_file() and "analysis complete" in record.read_text(encoding="utf-8", errors="ignore").lower()


def validated_sobol(case_dir: Path) -> bool:
    try:
        status = json.loads((case_dir / "run_status.json").read_text(encoding="utf-8"))
        audit = json.loads((case_dir / "sobol_audit" / "sobol_run_quality.json").read_text(encoding="utf-8"))
        bootstrap = json.loads((case_dir / "sobol_bootstrap" / "sobol_bootstrap_quality.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        status.get("status") == "completed"
        and status.get("scientific_status") == "validated"
        and audit.get("science_validated") is True
        and bootstrap.get("science_validated") is True
    )


def write_campaign_manifest(plan: dict[str, Any], new_cases: dict[str, Path]) -> Path:
    sobol = plan["sobol"]
    root = resolve(sobol["case_root"])
    manifest_path = root / "stability_rerun_campaign.json"
    levels = [int(value) for value in sobol["samples"]]
    if levels != [128, 256] or int(sobol["new_sample"]) != 256:
        raise ValueError("The approved rerun plan must compare N=128 with N=256")
    records = []
    parameter_count: int | None = None
    for season, config in sobol["seasons"].items():
        approval = resolve(sobol["approval_dir"]) / str(config["approval"])
        _, parameters, _ = load_approved_topk(approval)
        count = len(parameters)
        if parameter_count is None:
            parameter_count = count
        elif parameter_count != count:
            raise ValueError("Sobol approvals must contain the same parameter count")
        records.append(
            {
                "season": season,
                "baseline_n128": str(resolve(config["baseline_case"]).resolve()),
                "new_n256": str(new_cases[season].resolve()),
                "approval_sha256": sha256_file(approval),
            }
        )
    payload = {
        "schema_version": 1,
        "run_type": "formal_sobol_stability_rerun_campaign",
        "campaign_id": plan["campaign_id"],
        "planned_sample_schedule": levels,
        "budget_profile": "stability_rerun_v1",
        "schedule_source": str(DEFAULT_PLAN.relative_to(ROOT)),
        "user_adjustable": False,
        "parameter_count": parameter_count,
        "expected_maximum_model_runs": 256 * (int(parameter_count) + 2),
        "case_records": records,
        "plan_sha256": sha256_file(DEFAULT_PLAN),
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git_metadata(),
    }
    root.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("plan_sha256") != payload["plan_sha256"] or existing.get("case_records") != records:
            raise ValueError(f"Refusing conflicting Sobol rerun campaign manifest: {manifest_path}")
        return manifest_path
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def build_morris(plan: dict[str, Any], *, dry_run: bool) -> None:
    config = plan["morris"]
    case_root = resolve(config["case_root"])
    manifest = case_root / "formal_morris_manifest.json"
    if manifest.exists():
        print(f"[SKIP] Morris r={config['morris_r']} already built: {case_root}")
        return
    if case_root.exists() and any(case_root.iterdir()):
        raise FileExistsError(f"Refusing non-empty Morris rerun directory without manifest: {case_root}")
    command = [
        sys.executable, str(ROOT / "tools" / "build_formal_morris.py"),
        "--bounds", str(resolve(config["bounds"])),
        "--input-dir", str(resolve(config["input_dir"])),
        "--output-profile", str(resolve(config["output_profile"])),
        "--out-root", str(case_root),
        "--seeds", *[str(value) for value in config["seeds"]],
        "--morris-r", str(config["morris_r"]),
        "--morris-p", str(config["morris_p"]),
    ]
    run(command, dry_run=dry_run)


def run_morris(plan: dict[str, Any], *, dry_run: bool) -> None:
    config = plan["morris"]
    case_root = resolve(config["case_root"])
    for seed in config["seeds"]:
        case_dir = case_root / f"seed_{int(seed)}"
        if complete(case_dir, MORRIS_CASE):
            print(f"[SKIP] Morris seed {seed} already complete")
            continue
        if not (case_dir / f"{MORRIS_CASE}.pst").is_file() and not dry_run:
            raise FileNotFoundError(f"Build Morris cases before running: {case_dir}")
        run([
            sys.executable, str(ROOT / "tools" / "parallel" / "run_parallel.py"),
            "--run-dir", str(case_dir), "--case", MORRIS_CASE, "--mode", "sen",
            "--n-agents", str(config["agents"]), "--wait",
        ], dry_run=dry_run)


def postprocess_morris(plan: dict[str, Any], *, dry_run: bool) -> bool:
    config = plan["morris"]
    case_root = resolve(config["case_root"])
    if not dry_run and not all(complete(case_root / f"seed_{int(seed)}", MORRIS_CASE) for seed in config["seeds"]):
        raise RuntimeError("Cannot aggregate incomplete Morris cases")
    result_dir = resolve(config["result_dir"])
    command = [
        sys.executable, "-m", "src.sensitivity.morris_multiseed",
        "--output-profile", str(resolve(config["output_profile"])),
        "--out-dir", str(result_dir), "--top-k", "15",
    ]
    for seed in config["seeds"]:
        command.extend(["--case-dir", str(case_root / f"seed_{int(seed)}")])
    run(command, dry_run=dry_run)
    if dry_run:
        return False
    report = json.loads((result_dir / "morris_multiseed_stability.json").read_text(encoding="utf-8"))
    print(f"[MORRIS] stable={report['ranking_stable']} decision={report.get('decision')}")
    return bool(report["ranking_stable"])


def sobol_case_dir(plan: dict[str, Any], season: str) -> Path:
    sobol = plan["sobol"]
    return resolve(sobol["case_root"]) / season / f"n{int(sobol['new_sample']):04d}_seed_{int(sobol['seed'])}"


def build_sobol(plan: dict[str, Any], *, dry_run: bool) -> dict[str, Path]:
    sobol = plan["sobol"]
    cases: dict[str, Path] = {}
    for season, config in sobol["seasons"].items():
        case_dir = sobol_case_dir(plan, season)
        cases[season] = case_dir
        if (case_dir / f"{SOBOL_CASE}.pst").is_file():
            print(f"[SKIP] Sobol {season} N=256 already built")
            continue
        if case_dir.exists() and any(case_dir.iterdir()):
            raise FileExistsError(f"Refusing incomplete non-empty Sobol directory: {case_dir}")
        if dry_run:
            print(f"[BUILD] Sobol {season} N=256 -> {case_dir}")
            continue
        build_sobol_case(
            bounds_csv=resolve(sobol["bounds"]),
            approval_json=resolve(sobol["approval_dir"]) / str(config["approval"]),
            case_dir=case_dir,
            workspace_dir=ROOT,
            output_profile=resolve(config["output_profile"]),
            input_dir=resolve(config["input_dir"]),
            samples=int(sobol["new_sample"]),
            random_seed=int(sobol["seed"]),
            run_type="sensitivity_sobol_formal_case",
        )
        print(f"[BUILD] Sobol {season} N=256")
    if not dry_run:
        write_campaign_manifest(plan, cases)
    return cases


def run_sobol(plan: dict[str, Any], cases: dict[str, Path], *, dry_run: bool) -> None:
    for season, case_dir in cases.items():
        if complete(case_dir, SOBOL_CASE):
            print(f"[SKIP] Sobol {season} N=256 already complete")
            continue
        if not (case_dir / f"{SOBOL_CASE}.pst").is_file() and not dry_run:
            raise FileNotFoundError(f"Build Sobol case before running: {case_dir}")
        run([
            sys.executable, str(ROOT / "tools" / "parallel" / "run_parallel.py"),
            "--run-dir", str(case_dir), "--case", SOBOL_CASE, "--mode", "sen",
            "--n-agents", str(plan["sobol"]["agents"]), "--wait",
        ], dry_run=dry_run)


def finalize_sobol_case(case_dir: Path, *, replicates: int, dry_run: bool) -> None:
    if validated_sobol(case_dir):
        print(f"[SKIP] Sobol quality complete: {case_dir.name}")
        return
    if not dry_run and not complete(case_dir, SOBOL_CASE):
        raise RuntimeError(f"Cannot finalize incomplete Sobol case: {case_dir}")
    run([sys.executable, "-m", "src.sensitivity.sobol_audit", "--case-dir", str(case_dir)], dry_run=dry_run)
    run([
        sys.executable, "-m", "src.sensitivity.sobol_bootstrap", "--case-dir", str(case_dir),
        "--out-dir", str(case_dir / "sobol_bootstrap"), "--replicates", str(replicates),
        "--bootstrap-seed", "20260729",
    ], dry_run=dry_run)
    run([
        sys.executable, str(ROOT / "tools" / "parallel" / "run_parallel.py"),
        "--run-dir", str(case_dir), "--case", SOBOL_CASE, "--mode", "sen", "--finalize",
    ], dry_run=dry_run)
    if not dry_run and not validated_sobol(case_dir):
        raise RuntimeError(f"Sobol quality gate failed: {case_dir}")


def postprocess_sobol(plan: dict[str, Any], cases: dict[str, Path], *, dry_run: bool) -> bool:
    sobol = plan["sobol"]
    if dry_run:
        for season in sobol["seasons"]:
            print(f"[SOBOL] {season}: planned N=128 -> N=256 convergence assessment")
        return False
    campaign = write_campaign_manifest(plan, cases) if not dry_run else resolve(sobol["case_root"]) / "stability_rerun_campaign.json"
    all_converged = True
    for season, config in sobol["seasons"].items():
        baseline = resolve(config["baseline_case"])
        finalize_sobol_case(baseline, replicates=int(sobol["bootstrap_replicates"]), dry_run=dry_run)
        finalize_sobol_case(cases[season], replicates=int(sobol["bootstrap_replicates"]), dry_run=dry_run)
        destination = resolve(sobol["case_root"]) / season / "convergence_n0128_n0256"
        rc = run([
            sys.executable, "-m", "src.sensitivity.sobol_convergence",
            "--case-dir", str(baseline), "--case-dir", str(cases[season]),
            "--output-profile", str(resolve(config["output_profile"])),
            "--campaign-manifest", str(campaign), "--out-dir", str(destination),
        ], dry_run=dry_run, allowed={0, 2})
        if rc != 0:
            all_converged = False
        print(f"[SOBOL] {season}: {'converged' if rc == 0 else 'next scale required'}")
    return all_converged


def status(plan: dict[str, Any]) -> None:
    morris = plan["morris"]
    root = resolve(morris["case_root"])
    states = [complete(root / f"seed_{int(seed)}", MORRIS_CASE) for seed in morris["seeds"]]
    print(f"Morris {morris['season']} r={morris['morris_r']}: {sum(states)}/{len(states)} seed cases complete")
    for season, config in plan["sobol"]["seasons"].items():
        baseline = resolve(config["baseline_case"])
        new_case = sobol_case_dir(plan, season)
        print(
            f"Sobol {season}: baseline N128 validated={validated_sobol(baseline)}; "
            f"N256 built={(new_case / (SOBOL_CASE + '.pst')).is_file()} complete={complete(new_case, SOBOL_CASE)}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--all", action="store_true", help="build, run and assess the complete approved rerun")
    actions.add_argument("--build", action="store_true")
    actions.add_argument("--run", action="store_true")
    actions.add_argument("--postprocess", action="store_true")
    actions.add_argument("--status", action="store_true")
    parser.add_argument("--plan", default=str(DEFAULT_PLAN))
    parser.add_argument("--dry-run", action="store_true", help="print commands and planned case paths without writing or running")
    args = parser.parse_args(argv)
    plan = load_plan(args.plan)
    if args.status:
        status(plan)
        return 0
    if args.build or args.all:
        require_clean_worktree(plan, dry_run=args.dry_run)
        build_morris(plan, dry_run=args.dry_run)
        cases = build_sobol(plan, dry_run=args.dry_run)
    else:
        cases = {season: sobol_case_dir(plan, season) for season in plan["sobol"]["seasons"]}
    if args.run or args.all:
        run_morris(plan, dry_run=args.dry_run)
        run_sobol(plan, cases, dry_run=args.dry_run)
    if args.postprocess or args.all:
        morris_stable = postprocess_morris(plan, dry_run=args.dry_run)
        sobol_converged = postprocess_sobol(plan, cases, dry_run=args.dry_run)
        if not args.dry_run and not (morris_stable and sobol_converged):
            print("[RESULT] Rerun completed, but at least one predeclared stability/convergence gate remains unmet.")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
