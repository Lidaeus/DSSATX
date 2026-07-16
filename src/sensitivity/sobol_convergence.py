"""Compare formal Sobol sample levels and expose run scale in final results."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from src.common.project import git_metadata, sha256_file
from src.sensitivity.morris_multiseed import _feature_metadata, _group_lookup
from src.sensitivity.output_contract import load_output_contract
from src.sensitivity.sobol_audit import read_flat_manifest


def _validated_case(case_dir: Path) -> tuple[dict[str, str], dict[str, Any]]:
    status = json.loads((case_dir / "run_status.json").read_text(encoding="utf-8"))
    if status.get("status") != "completed" or status.get("scientific_status") != "validated":
        raise ValueError(f"Formal Sobol case is not validated: {case_dir}")
    manifest = read_flat_manifest(case_dir / "run_manifest.yaml")
    if manifest.get("run_type") != "sensitivity_sobol_formal_case":
        raise ValueError(f"Refusing non-formal Sobol case: {case_dir}")
    for path in (
        case_dir / "sobol_audit" / "sobol_run_quality.json",
        case_dir / "sobol_bootstrap" / "sobol_bootstrap_quality.json",
    ):
        report = json.loads(path.read_text(encoding="utf-8"))
        if not report.get("science_validated"):
            raise ValueError(f"Formal Sobol quality report failed: {path}")
    return manifest, status


def _rank_case(
    case_dir: Path,
    lookup: dict[str, str],
    ranking_domains: dict[str, list[str]] | None = None,
    *,
    tolerance: float = 1e-12,
) -> tuple[int, pd.DataFrame, pd.DataFrame]:
    manifest, _ = _validated_case(case_dir)
    samples = int(manifest["sobol_samples"])
    frame = pd.read_csv(case_dir / "sobol_bootstrap" / "sobol_bootstrap_indices.csv")
    frame["observation"] = frame["observation"].astype(str).str.lower()
    frame["parameter"] = frame["parameter"].astype(str).str.upper()
    frame["ST"] = pd.to_numeric(frame["ST"], errors="coerce")
    estimable = frame["estimable"].astype(str).str.lower().isin({"true", "1"})
    if not bool(estimable.all()) or not np.isfinite(frame["ST"]).all() or bool((frame["ST"] < 0).any()):
        raise ValueError(f"Formal Sobol ST values must all be estimable, finite and non-negative: {case_dir}")
    metadata = frame["observation"].map(_feature_metadata)
    frame["treatment"] = [item[0] for item in metadata]
    frame["feature_family"] = [item[1] for item in metadata]
    unmapped = sorted(set(frame["feature_family"]) - set(lookup))
    if unmapped:
        raise ValueError(f"Unmapped Sobol response feature families: {unmapped}")
    frame["response_group"] = frame["feature_family"].map(lookup)
    totals = frame.groupby("observation")["ST"].transform("sum")
    if bool((totals <= tolerance).any()):
        failed = sorted(frame.loc[totals <= tolerance, "observation"].unique())
        raise ValueError(f"Responses with zero total Sobol effect cannot enter ranking: {failed}")
    frame["relative_ST"] = frame["ST"] / totals
    feature_scores = (
        frame.groupby(["response_group", "feature_family", "parameter"], as_index=False)["relative_ST"]
        .mean()
        .rename(columns={"relative_ST": "feature_score"})
    )
    group_scores = (
        feature_scores.groupby(["response_group", "parameter"], as_index=False)["feature_score"]
        .mean()
        .rename(columns={"feature_score": "group_score"})
    )
    # Rank within each ranking_domain separately, mirroring the Morris contract.
    # Sobol convergence must NEVER average effects across domains, because a
    # parameter important only to general growth would be diluted by (or dilute)
    # the water/nitrogen response domain. When no ranking_domains are declared
    # (synthetic unit-test profiles), all groups fall into a single "combined"
    # domain so the math reduces to the previous behaviour.
    if ranking_domains:
        group_to_domain = {
            str(group): str(domain)
            for domain, groups in ranking_domains.items()
            for group in groups
        }
        missing_groups = sorted(set(group_scores["response_group"]) - set(group_to_domain))
        if missing_groups:
            raise ValueError(f"Sobol response groups are absent from ranking_domains: {missing_groups}")
    else:
        group_to_domain = {str(group): "combined" for group in group_scores["response_group"].unique()}
    group_scores["ranking_domain"] = group_scores["response_group"].map(group_to_domain)
    ranking = (
        group_scores.groupby(["ranking_domain", "parameter"], as_index=False)["group_score"]
        .mean()
        .rename(columns={"group_score": "score"})
        .sort_values(["ranking_domain", "score", "parameter"], ascending=[True, False, True], kind="stable")
        .reset_index(drop=True)
    )
    ranking.insert(0, "base_samples", samples)
    ranking["rank"] = ranking.groupby("ranking_domain")["score"].rank(method="average", ascending=False)
    group_scores.insert(0, "base_samples", samples)
    return samples, ranking, group_scores


def _elapsed_seconds(status: dict[str, Any]) -> float | None:
    try:
        started = datetime.fromisoformat(str(status["started_at"]).replace("Z", "+00:00"))
        finished = datetime.fromisoformat(str(status["finished_at"]).replace("Z", "+00:00"))
        return float((finished - started).total_seconds())
    except Exception:
        return None


def analyze_convergence(
    case_dirs: list[str | Path],
    output_profile: str | Path,
    campaign_manifest: str | Path,
    out_dir: str | Path,
    *,
    min_spearman: float = 0.95,
    top_k: int = 8,
    min_jaccard: float = 0.75,
    max_rank_shift: float = 2.0,
) -> dict[str, Any]:
    if len(case_dirs) < 2:
        raise ValueError("Sobol convergence requires at least two formal sample levels")
    campaign = json.loads(Path(campaign_manifest).read_text(encoding="utf-8"))
    contract = load_output_contract(output_profile)
    lookup = _group_lookup(contract)
    ranking_domains = contract.get("ranking_domains")
    if ranking_domains is not None and not isinstance(ranking_domains, dict):
        raise ValueError("ranking_domains must be an object")
    rankings: list[pd.DataFrame] = []
    groups: list[pd.DataFrame] = []
    scales: list[dict[str, Any]] = []
    approval_ids: set[str] = set()
    parameter_sets: set[tuple[str, ...]] = set()

    for raw_case in case_dirs:
        case_dir = Path(raw_case).resolve()
        manifest, status = _validated_case(case_dir)
        samples, ranking, group_scores = _rank_case(case_dir, lookup, ranking_domains)
        rankings.append(ranking)
        groups.append(group_scores)
        approval_ids.add(manifest.get("sobol_approval_id", ""))
        parameter_sets.add(tuple(sorted(ranking["parameter"])))
        actual_runs = len(pd.read_csv(case_dir / "sa_sen_sobol.sobol.obs.csv"))
        scales.append(
            {
                "base_samples": samples,
                "parameter_count": int(manifest["sobol_parameter_count"]),
                "theoretical_model_runs": int(manifest["sobol_expected_model_runs"]),
                "actual_model_runs": actual_runs,
                "agents": int(status.get("n_agents", 0) or 0),
                "elapsed_seconds": _elapsed_seconds(status),
                "random_seed": int(manifest["random_seed"]),
                "case_dir": str(case_dir),
            }
        )
    if len(approval_ids) != 1 or len(parameter_sets) != 1:
        raise ValueError("Formal Sobol levels must use the same approval and parameter set")
    all_rankings = pd.concat(rankings, ignore_index=True)
    all_groups = pd.concat(groups, ignore_index=True)
    levels = sorted(int(value) for value in all_rankings["base_samples"].unique())
    if len(levels) != len(case_dirs):
        raise ValueError("Formal Sobol sample levels must be unique")
    comparisons: list[dict[str, Any]] = []
    domain_names = sorted(all_rankings["ranking_domain"].unique())
    for left, right in zip(levels[:-1], levels[1:]):
        # Compare each ranking domain independently. A parameter important in
        # only one domain must not be averaged with the other domain; the
        # convergence verdict is the AND over all domains (all must converge).
        domain_rows: list[dict[str, Any]] = []
        all_domains_pass = True
        for domain in domain_names:
            left_frame = (
                all_rankings[(all_rankings["base_samples"] == left) & (all_rankings["ranking_domain"] == domain)]
                .set_index("parameter")
            )
            right_frame = (
                all_rankings[(all_rankings["base_samples"] == right) & (all_rankings["ranking_domain"] == domain)]
                .set_index("parameter")
            )
            common = left_frame.index.intersection(right_frame.index)
            left_frame = left_frame.loc[common]
            right_frame = right_frame.loc[common]
            spearman = float(left_frame["rank"].corr(right_frame["rank"], method="spearman"))
            left_top = set(left_frame.nsmallest(top_k, "rank").index)
            right_top = set(right_frame.nsmallest(top_k, "rank").index)
            union = left_top | right_top
            jaccard = float(len(left_top & right_top) / len(union)) if union else 1.0
            rank_shift = float(
                max(abs(float(left_frame.loc[name, "rank"]) - float(right_frame.loc[name, "rank"])) for name in union)
            )
            passed = spearman >= min_spearman and jaccard >= min_jaccard and rank_shift <= max_rank_shift
            if not passed:
                all_domains_pass = False
            domain_rows.append(
                {
                    "ranking_domain": domain,
                    "spearman": spearman,
                    "top_k": int(top_k),
                    "top_k_jaccard": jaccard,
                    "max_top_k_rank_shift": rank_shift,
                    "passes": passed,
                }
            )
        comparisons.append(
            {
                "samples_a": int(left),
                "samples_b": int(right),
                "ranking_domains": domain_rows,
                "passes": all_domains_pass,
            }
        )
    latest_passes = bool(comparisons[-1]["passes"])
    planned = [int(value) for value in campaign["planned_sample_schedule"]]
    next_levels = [value for value in planned if value > max(levels)]
    decision = "stop_at_current_scale" if latest_passes else (
        "run_next_sample_level" if next_levels else "stop_without_convergence"
    )
    destination = Path(out_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    all_rankings.to_csv(destination / "sobol_scale_rankings.csv", index=False, encoding="utf-8-sig")
    all_groups.to_csv(destination / "sobol_scale_group_scores.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(scales).sort_values("base_samples").to_csv(
        destination / "sobol_run_scale.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(comparisons).to_csv(
        destination / "sobol_convergence_comparisons.csv", index=False, encoding="utf-8-sig"
    )
    git_info = git_metadata()
    result = {
        "schema_version": 1,
        "run_type": "formal_sobol_convergence",
        "science_validated": latest_passes,
        "budget_profile": campaign["budget_profile"],
        "schedule_source": campaign["schedule_source"],
        "user_adjustable": bool(campaign.get("user_adjustable")),
        "planned_sample_schedule": planned,
        "executed_sample_schedule": levels,
        "parameter_count": len(next(iter(parameter_sets))),
        "executed_model_runs": sum(item["actual_model_runs"] for item in scales),
        "maximum_planned_model_runs": int(campaign["expected_maximum_model_runs"]),
        "thresholds": {
            "spearman": min_spearman,
            "top_k": top_k,
            "top_k_jaccard": min_jaccard,
            "max_top_k_rank_shift": max_rank_shift,
        },
        "comparisons": comparisons,
        "run_scale": sorted(scales, key=lambda item: item["base_samples"]),
        "decision": decision,
        "next_sample_level": next_levels[0] if decision == "run_next_sample_level" else None,
        "output_profile_sha256": sha256_file(output_profile),
        "campaign_manifest_sha256": sha256_file(campaign_manifest),
        "analysis_git_commit": git_info.get("git_commit", ""),
        "analysis_git_dirty": git_info.get("git_dirty", False),
    }
    (destination / "sobol_convergence.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Formal Sobol convergence and run scale",
        "",
        f"- Budget profile: `{result['budget_profile']}` ({result['schedule_source']})",
        f"- Planned N: `{planned}`; executed N: `{levels}`",
        f"- Parameters: `{result['parameter_count']}`; executed model runs: `{result['executed_model_runs']}`",
        f"- User adjustable: `{str(result['user_adjustable']).lower()}` via `--profile` or `--samples`",
        f"- Decision: `{decision}`",
        "",
        "| N | Parameters | Theoretical runs | Actual runs | Agents | Elapsed seconds |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for item in result["run_scale"]:
        lines.append(
            f"| {item['base_samples']} | {item['parameter_count']} | {item['theoretical_model_runs']} | "
            f"{item['actual_model_runs']} | {item['agents']} | {item['elapsed_seconds']} |"
        )
    (destination / "sobol_convergence.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess formal Sobol sample-size convergence")
    parser.add_argument("--case-dir", action="append", required=True)
    parser.add_argument("--output-profile", required=True)
    parser.add_argument("--campaign-manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--min-spearman", type=float, default=0.95)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--min-jaccard", type=float, default=0.75)
    parser.add_argument("--max-rank-shift", type=float, default=2.0)
    args = parser.parse_args()
    result = analyze_convergence(
        args.case_dir,
        args.output_profile,
        args.campaign_manifest,
        args.out_dir,
        min_spearman=args.min_spearman,
        top_k=args.top_k,
        min_jaccard=args.min_jaccard,
        max_rank_shift=args.max_rank_shift,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["science_validated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
