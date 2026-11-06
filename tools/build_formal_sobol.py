"""Build approval-gated formal Sobol cases from an adjustable budget profile."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[1]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from src.common.project import PROJECT_ROOT, git_metadata, sha256_file
from src.sensitivity.sobol_case import build_sobol_case, load_approved_topk


DEFAULT_BUDGETS = PROJECT_ROOT / "configs" / "sa" / "sobol_budget_profiles.json"


def resolve_budget(
    budget_config: str | Path,
    profile: str | None = None,
    samples: str | None = None,
) -> tuple[dict[str, object], list[int], str]:
    path = Path(budget_config).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    selected_profile = profile or str(config["default_profile"])
    profiles = config.get("profiles") or {}
    if selected_profile not in profiles:
        raise ValueError(f"Unknown Sobol budget profile: {selected_profile}")
    if samples:
        schedule = [int(value.strip()) for value in str(samples).split(",") if value.strip()]
        source = "custom_cli_override"
    else:
        schedule = [int(value) for value in profiles[selected_profile]["sample_schedule"]]
        source = f"profile:{selected_profile}"
    if len(schedule) < 2 or any(value < 32 for value in schedule):
        raise ValueError("Formal Sobol schedule requires at least two sample sizes, all >=32")
    if schedule != sorted(set(schedule)):
        raise ValueError("Formal Sobol sample sizes must be unique and strictly increasing")
    return config, schedule, source


def build_campaign(
    *,
    output_root: str | Path,
    bounds: str | Path,
    approval: str | Path,
    output_profile: str | Path,
    input_dir: str | Path,
    budget_config: str | Path = DEFAULT_BUDGETS,
    profile: str | None = None,
    samples: str | None = None,
    build_levels: int = 2,
    random_seed: int = 20261215,
) -> dict[str, object]:
    config, schedule, source = resolve_budget(budget_config, profile, samples)
    build_levels = int(build_levels)
    if build_levels < 1 or build_levels > len(schedule):
        raise ValueError("build_levels must select one or more planned sample sizes")
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Formal Sobol campaign directory must be new or empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    selected = schedule[:build_levels]
    cases = []
    _, approved_parameters, _ = load_approved_topk(approval)
    parameter_count = len(approved_parameters)
    for sample_size in selected:
        case_dir = root / f"n{sample_size:04d}_seed_{int(random_seed)}"
        pst = build_sobol_case(
            bounds_csv=bounds,
            approval_json=approval,
            case_dir=case_dir,
            workspace_dir=PROJECT_ROOT,
            output_profile=output_profile,
            input_dir=input_dir,
            samples=sample_size,
            random_seed=random_seed,
            run_type="sensitivity_sobol_formal_case",
        )
        cases.append(
            {
                "base_samples": sample_size,
                "parameter_count": parameter_count,
                "expected_model_runs": sample_size * (parameter_count + 2),
                "case_dir": str(case_dir),
                "pst_sha256": sha256_file(pst),
            }
        )
    git_info = git_metadata()
    selected_profile = profile or str(config["default_profile"])
    profile_values = config["profiles"][selected_profile]
    campaign = {
        "schema_version": 1,
        "run_type": "formal_sobol_adaptive_campaign",
        "budget_profile": selected_profile,
        "schedule_source": source,
        "planned_sample_schedule": schedule,
        "built_sample_schedule": selected,
        "user_adjustable": True,
        "adjustment_arguments": {"profile": "--profile", "custom_samples": "--samples"},
        "parameter_count": parameter_count,
        "expected_initial_model_runs": sum(item["expected_model_runs"] for item in cases),
        "expected_maximum_model_runs": sum(value * (parameter_count + 2) for value in schedule),
        "recommended_agents": int(profile_values["recommended_agents"]),
        "bootstrap_replicates": int(profile_values["bootstrap_replicates"]),
        "random_seed": int(random_seed),
        "budget_config": str(Path(budget_config).resolve()),
        "budget_config_sha256": sha256_file(budget_config),
        "git_commit": git_info.get("git_commit", ""),
        "git_dirty": git_info.get("git_dirty", False),
        "cases": cases,
    }
    (root / "formal_sobol_campaign.json").write_text(
        json.dumps(campaign, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return campaign


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an adjustable formal Sobol campaign")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--bounds", required=True)
    parser.add_argument("--approval", required=True)
    parser.add_argument("--output-profile", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--budget-config", default=str(DEFAULT_BUDGETS))
    parser.add_argument("--profile", default=None)
    parser.add_argument("--samples", default=None, help="Custom comma-separated schedule, e.g. 64,96,192")
    parser.add_argument("--build-levels", type=int, default=2)
    parser.add_argument("--random-seed", type=int, default=20261215)
    args = parser.parse_args()
    campaign = build_campaign(
        output_root=args.output_root,
        bounds=args.bounds,
        approval=args.approval,
        output_profile=args.output_profile,
        input_dir=args.input_dir,
        budget_config=args.budget_config,
        profile=args.profile,
        samples=args.samples,
        build_levels=args.build_levels,
        random_seed=args.random_seed,
    )
    print(json.dumps(campaign, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
