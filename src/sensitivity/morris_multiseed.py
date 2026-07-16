"""Auditable cross-seed stability analysis for formal Morris cases."""

from __future__ import annotations

import argparse
import json
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from src.common.quality import load_morris_summary
from src.common.project import sha256_file
from src.sensitivity.output_contract import load_output_contract


_TN_RE = re.compile(r"^tn(?P<treatment>\d+)_(?P<feature>.+)$", re.IGNORECASE)
_DAP_RE = re.compile(r"_dap\d{2,3}$", re.IGNORECASE)
_WN_WATER_RE = re.compile(r"^wn_water_(?P<level>n\d+)_(?P<feature>.+)$", re.IGNORECASE)
_WN_NSLOPE_RE = re.compile(r"^wn_nslope_(?P<water>w\d+)_(?P<feature>.+)$", re.IGNORECASE)
_WN_INTERACTION_RE = re.compile(r"^wn_interaction_(?P<feature>.+)$", re.IGNORECASE)


def _read_flat_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _require_validated_case(case_dir: Path) -> dict[str, Any]:
    status = json.loads((case_dir / "run_status.json").read_text(encoding="utf-8"))
    if status.get("status") != "completed" or status.get("scientific_status") != "validated":
        raise ValueError(f"Case is not scientifically validated: {case_dir}")
    for name in ("morris_run_quality.json", "morris_result_quality.json"):
        report = json.loads((case_dir / "morris_audit" / name).read_text(encoding="utf-8"))
        if not report.get("science_validated"):
            raise ValueError(f"Quality report failed for {case_dir}: {name}")
    manifest = _read_flat_manifest(case_dir / "run_manifest.yaml")
    if manifest.get("run_type") != "sensitivity_formal_case":
        raise ValueError(f"Refusing non-formal Morris case: {case_dir}")
    return {
        "seed": int(manifest["random_seed"]),
        "manifest": manifest,
        "bounds_sha256": manifest.get("bounds_sha256", ""),
        "input_manifest_sha256": manifest.get("input_manifest_sha256", ""),
        "output_profile_sha256": manifest.get("output_profile_sha256", ""),
    }


def _feature_metadata(observation: str) -> tuple[str, str]:
    match = _TN_RE.match(str(observation).strip())
    if match:
        feature = match.group("feature").upper()
        family = _DAP_RE.sub("_DAP", feature)
        return f"TN{int(match.group('treatment'))}", family
    match = _WN_WATER_RE.match(str(observation).strip())
    if match:
        return match.group("level").upper(), f"WATER_{match.group('feature').upper()}"
    match = _WN_NSLOPE_RE.match(str(observation).strip())
    if match:
        return match.group("water").upper(), f"NITROGEN_{match.group('feature').upper()}"
    match = _WN_INTERACTION_RE.match(str(observation).strip())
    if match:
        return "W3xN", f"INTERACTION_{match.group('feature').upper()}"
    raise ValueError(f"Expected treatment-specific or WN-derived observation, got: {observation}")


def _group_lookup(contract: dict[str, object]) -> dict[str, str]:
    groups = contract.get("response_groups")
    if not isinstance(groups, dict) or not groups:
        raise ValueError("Output contract must declare response_groups")
    lookup: dict[str, str] = {}
    for group, features in groups.items():
        if not isinstance(features, list) or not features:
            raise ValueError(f"Response group must contain features: {group}")
        for feature in features:
            key = str(feature).strip().upper()
            if key in lookup:
                raise ValueError(f"Response feature appears in multiple groups: {key}")
            lookup[key] = str(group)
    return lookup


def _rank_case(
    case_dir: Path,
    lookup: dict[str, str],
    ranking_domains: dict[str, list[str]] | None = None,
    *,
    expected_observation_count: int | None = None,
    tolerance: float = 1e-12,
) -> tuple[int, pd.DataFrame, pd.DataFrame, dict[str, str]]:
    identity = _require_validated_case(case_dir)
    seed = int(identity["seed"])
    frame = load_morris_summary(case_dir / "sa_sen_morris.mio")
    frame["obs"] = frame["obs"].astype(str).str.lower()
    frame["par"] = frame["par"].astype(str).str.upper()
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    if not np.isfinite(frame["score"]).all() or (frame["score"] < 0).any():
        raise ValueError(f"Morris scores must be finite and non-negative: {case_dir}")
    # The formal ranking is defined over the exact contracted response set. A
    # case whose .mio does not carry the expected number of observations (e.g.
    # a stale 136-output profile mixed with a 164-output one) must not enter a
    # multi-seed consensus, because the missing responses silently change the
    # ranking basis.
    unique_observations = frame["obs"].nunique()
    if expected_observation_count is not None and unique_observations != int(expected_observation_count):
        raise ValueError(
            f"Case {case_dir} has {unique_observations} observations but the contract "
            f"declares {expected_observation_count}; a mixed observation set cannot rank"
        )
    metadata = frame["obs"].map(_feature_metadata)
    frame["response_context"] = [item[0] for item in metadata]
    frame["feature_family"] = [item[1] for item in metadata]
    unmapped = sorted(set(frame["feature_family"]) - set(lookup))
    if unmapped:
        raise ValueError(f"Unmapped response feature families: {unmapped}")
    frame["response_group"] = frame["feature_family"].map(lookup)
    totals = frame.groupby("obs")["score"].transform("sum")
    if bool((totals <= tolerance).any()):
        failed = sorted(frame.loc[totals <= tolerance, "obs"].unique())
        raise ValueError(f"Degenerate responses cannot enter formal ranking: {failed}")
    frame["relative_effect"] = frame["score"] / totals

    feature_scores = (
        frame.groupby(["response_group", "feature_family", "par"], as_index=False)["relative_effect"]
        .mean()
        .rename(columns={"relative_effect": "feature_score"})
    )
    group_scores = (
        feature_scores.groupby(["response_group", "par"], as_index=False)["feature_score"]
        .mean()
        .rename(columns={"feature_score": "group_score"})
    )
    if ranking_domains:
        group_to_domain = {
            str(group): str(domain)
            for domain, groups in ranking_domains.items()
            for group in groups
        }
        missing_groups = sorted(set(group_scores["response_group"]) - set(group_to_domain))
        if missing_groups:
            raise ValueError(f"Response groups are absent from ranking_domains: {missing_groups}")
    else:
        group_to_domain = {str(group): "combined" for group in group_scores["response_group"].unique()}
    group_scores["ranking_domain"] = group_scores["response_group"].map(group_to_domain)
    ranking = (
        group_scores.groupby(["ranking_domain", "par"], as_index=False)["group_score"]
        .mean()
        .rename(columns={"par": "parameter", "group_score": "score"})
        .sort_values(["ranking_domain", "score", "parameter"], ascending=[True, False, True], kind="stable")
        .reset_index(drop=True)
    )
    ranking.insert(0, "seed", seed)
    ranking["rank"] = ranking.groupby("ranking_domain")["score"].rank(method="average", ascending=False)
    group_scores.insert(0, "seed", seed)
    group_scores = group_scores.rename(columns={"par": "parameter"})
    return seed, ranking, group_scores, identity


def analyze_multiseed(
    case_dirs: list[str | Path],
    output_profile: str | Path,
    out_dir: str | Path,
    *,
    excluded_case_dirs: list[str | Path] | None = None,
    top_k: int = 15,
    min_spearman: float = 0.90,
    min_jaccard: float = 0.80,
) -> dict[str, Any]:
    if len(case_dirs) < 2:
        raise ValueError("Cross-seed stability requires at least two cases")
    contract = load_output_contract(output_profile)
    lookup = _group_lookup(contract)
    ranking_domains = contract.get("ranking_domains")
    if ranking_domains is not None and not isinstance(ranking_domains, dict):
        raise ValueError("ranking_domains must be an object")
    # The formal P1 contract declares the full observation set (164) and both
    # ranking domains. When a contract carries an observation_count we are in a
    # formal run and enforce that both domains are present and exactly named:
    # a consensus over a different domain set silently changes the scientific
    # meaning. Synthetic unit-test profiles (no observation_count) are left to
    # declare whatever domains they exercise.
    expected_observation_count = contract.get("observation_count")
    if expected_observation_count is not None:
        required_domains = {"general_genetic", "water_nitrogen_response"}
        if ranking_domains is None or set(ranking_domains) != required_domains:
            raise ValueError(
                "Formal P1 ranking requires exactly the two ranking domains "
                f"{sorted(required_domains)}; got {sorted((ranking_domains or {}).keys())}"
            )
    rankings: list[pd.DataFrame] = []
    group_scores: list[pd.DataFrame] = []
    case_records: list[dict[str, Any]] = []
    seen_seeds: set[int] = set()
    expected_parameters: set[str] | None = None
    # Provenance hashes that must be identical across every formal seed: a
    # multi-seed consensus mixing different bounds, input bundles, or output
    # profiles is meaningless because the ranking basis differs per seed.
    reference_hashes: dict[str, str] | None = None
    for raw_case in case_dirs:
        case_dir = Path(raw_case).resolve()
        seed, ranking, groups, identity = _rank_case(
            case_dir,
            lookup,
            ranking_domains,
            expected_observation_count=expected_observation_count,
        )
        if seed in seen_seeds:
            raise ValueError(f"Duplicate formal seed: {seed}")
        seen_seeds.add(seed)
        # Cross-seed provenance consistency: bounds/input/profile hashes must
        # match. Empty hashes (synthetic fixtures) are treated as matching.
        seed_hashes = {
            "bounds_sha256": identity.get("bounds_sha256", ""),
            "input_manifest_sha256": identity.get("input_manifest_sha256", ""),
            "output_profile_sha256": identity.get("output_profile_sha256", ""),
        }
        if reference_hashes is None:
            reference_hashes = seed_hashes
        elif seed_hashes != reference_hashes:
            raise ValueError(
                f"Case {case_dir} provenance hashes differ from the first seed; "
                f"a multi-seed consensus cannot mix bounds/input/profile versions: "
                f"{seed_hashes} vs {reference_hashes}"
            )
        parameters = set(ranking["parameter"])
        if expected_parameters is not None and parameters != expected_parameters:
            raise ValueError("Formal seeds do not contain identical parameter sets")
        expected_parameters = parameters
        rankings.append(ranking)
        group_scores.append(groups)
        case_records.append(
            {
                "seed": seed,
                "case_dir": str(case_dir),
                "mio_sha256": sha256_file(case_dir / "sa_sen_morris.mio"),
                **seed_hashes,
            }
        )

    excluded_records: list[dict[str, Any]] = []
    for raw_case in excluded_case_dirs or []:
        case_dir = Path(raw_case).resolve()
        status = json.loads((case_dir / "run_status.json").read_text(encoding="utf-8"))
        if status.get("scientific_status") != "failed":
            raise ValueError(f"Excluded case must have scientific_status=failed: {case_dir}")
        manifest = _read_flat_manifest(case_dir / "run_manifest.yaml")
        if manifest.get("run_type") != "sensitivity_formal_case":
            raise ValueError(f"Excluded case is not formal: {case_dir}")
        audit = json.loads(
            (case_dir / "morris_audit" / "morris_run_audit.json").read_text(encoding="utf-8")
        )
        summary = audit.get("summary") or {}
        excluded_records.append(
            {
                "seed": int(manifest["random_seed"]),
                "case_dir": str(case_dir),
                "scientific_status": "failed",
                "model_failed_runs": int(summary.get("model_failed_runs", 0)),
                "runtime_failed_runs": int(summary.get("runtime_failed_runs", 0)),
                "fully_valid_trajectories": int(summary.get("fully_valid_trajectories", 0)),
                "expected_trajectories": int(summary.get("expected_trajectories", 0)),
                "exclusion_reason": "formal_quality_gate_failed",
            }
        )

    all_rankings = pd.concat(rankings, ignore_index=True)
    all_groups = pd.concat(group_scores, ignore_index=True)
    pair_rows: list[dict[str, Any]] = []
    domain_names = sorted(all_rankings["ranking_domain"].unique())
    for domain in domain_names:
        domain_frame = all_rankings[all_rankings["ranking_domain"] == domain]
        for left, right in combinations(sorted(seen_seeds), 2):
            left_frame = domain_frame[domain_frame["seed"] == left].set_index("parameter")
            right_frame = domain_frame[domain_frame["seed"] == right].set_index("parameter")
            spearman = float(left_frame["rank"].corr(right_frame["rank"], method="spearman"))
            left_top = set(left_frame.nsmallest(top_k, "rank").index)
            right_top = set(right_frame.nsmallest(top_k, "rank").index)
            union = left_top | right_top
            jaccard = float(len(left_top & right_top) / len(union)) if union else 1.0
            pair_rows.append(
                {
                    "ranking_domain": domain,
                    "seed_a": left,
                    "seed_b": right,
                    "spearman": spearman,
                    "top_k": top_k,
                    "top_k_jaccard": jaccard,
                    "passes": spearman >= min_spearman and jaccard >= min_jaccard,
                }
            )
    pairs = pd.DataFrame(pair_rows)
    stable = bool(pairs["passes"].all())
    decision = "stop_at_current_seed_count" if stable else "add_next_prespecified_seed"
    consensus = (
        all_rankings.groupby(["ranking_domain", "parameter"], as_index=False)
        .agg(mean_score=("score", "mean"), mean_rank=("rank", "mean"), min_rank=("rank", "min"), max_rank=("rank", "max"))
        .sort_values(["mean_rank", "parameter"], kind="stable")
    )
    consensus["consensus_rank"] = consensus.groupby("ranking_domain").cumcount() + 1

    top_sets = {
        (str(domain), int(seed)): set(group.nsmallest(top_k, "rank")["parameter"])
        for (domain, seed), group in all_rankings.groupby(["ranking_domain", "seed"])
    }
    stable_core_by_domain = {
        domain: set.intersection(*(top_sets[(domain, seed)] for seed in sorted(seen_seeds)))
        for domain in domain_names
    }
    top_union_by_domain = {
        domain: set.union(*(top_sets[(domain, seed)] for seed in sorted(seen_seeds)))
        for domain in domain_names
    }
    rank_columns = (
        all_rankings.pivot(index=["ranking_domain", "parameter"], columns="seed", values="rank")
        .rename(columns=lambda seed: f"rank_seed_{int(seed)}")
        .reset_index()
    )
    group_columns = (
        all_groups.groupby(["parameter", "response_group"], as_index=False)["group_score"]
        .mean()
        .pivot(index="parameter", columns="response_group", values="group_score")
        .rename(columns=lambda group: f"score_group_{group}")
        .reset_index()
    )
    proposal_parts = []
    for domain in domain_names:
        part = consensus[
            consensus["ranking_domain"].eq(domain)
            & consensus["parameter"].isin(top_union_by_domain[domain])
        ].merge(rank_columns, on=["ranking_domain", "parameter"], how="left")
        part = part.merge(group_columns, on="parameter", how="left")
        part["selection_class"] = part["parameter"].map(
            lambda parameter: "stable_core"
            if parameter in stable_core_by_domain[domain]
            else "top_k_boundary_union"
        )
        proposal_parts.append(part)
    proposal = pd.concat(proposal_parts, ignore_index=True).sort_values(
        ["ranking_domain", "consensus_rank", "parameter"], kind="stable"
    )
    proposal["review_status"] = "pending"

    destination = Path(out_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    all_rankings.to_csv(destination / "morris_seed_rankings.csv", index=False, encoding="utf-8-sig")
    all_groups.to_csv(destination / "morris_seed_group_scores.csv", index=False, encoding="utf-8-sig")
    pairs.to_csv(destination / "morris_seed_pairwise_stability.csv", index=False, encoding="utf-8-sig")
    consensus.to_csv(destination / "morris_consensus_ranking.csv", index=False, encoding="utf-8-sig")
    proposal.to_csv(destination / "morris_topk_proposal.csv", index=False, encoding="utf-8-sig")
    result = {
        "schema_version": 1,
        "run_type": "formal_morris_multiseed_stability",
        # Per the P1 v4 plan, science_validated requires (a) every case to have
        # passed its per-case quality gate (enforced by _require_validated_case
        # above — any failing case raises before we reach here) AND (b) both
        # ranking domains to be stable. A stable run with a failed upstream
        # case never reaches this point; an unstable run is recorded for
        # diagnosis but is not citable as a validated science result.
        "science_validated": bool(stable),
        "case_quality_validated": True,
        "ranking_stable": bool(stable),
        "seed_count": len(seen_seeds),
        "seeds": sorted(seen_seeds),
        "parameter_count": len(expected_parameters or set()),
        "top_k": top_k,
        "thresholds": {"spearman": min_spearman, "top_k_jaccard": min_jaccard},
        "minimum_pairwise_spearman": float(pairs["spearman"].min()),
        "minimum_pairwise_top_k_jaccard": float(pairs["top_k_jaccard"].min()),
        "stable": stable,
        "decision": decision,
        "ranking_domains": domain_names,
        "domain_stability": {
            domain: {
                "stable": bool(pairs.loc[pairs["ranking_domain"].eq(domain), "passes"].all()),
                "minimum_pairwise_spearman": float(pairs.loc[pairs["ranking_domain"].eq(domain), "spearman"].min()),
                "minimum_pairwise_top_k_jaccard": float(pairs.loc[pairs["ranking_domain"].eq(domain), "top_k_jaccard"].min()),
                "top_k_stable_core_count": len(stable_core_by_domain[domain]),
                "top_k_union_count": len(top_union_by_domain[domain]),
            }
            for domain in domain_names
        },
        "top_k_proposal_review_status": "pending",
        "output_profile": str(Path(output_profile).resolve()),
        "output_profile_sha256": sha256_file(output_profile),
        "cases": case_records,
        "excluded_cases": excluded_records,
    }
    (destination / "morris_multiseed_stability.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    proposal_domains = {
        domain: {
            "stable_core_parameters": sorted(stable_core_by_domain[domain]),
            "boundary_union_parameters": sorted(top_union_by_domain[domain] - stable_core_by_domain[domain]),
            "proposed_parameter_count": len(top_union_by_domain[domain]),
        }
        for domain in domain_names
    }
    (destination / "morris_topk_proposal.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "proposal_type": "morris_topk_by_domain_for_sobol_review",
                "review_status": "pending",
                "top_k": top_k,
                "domains": proposal_domains,
                "selection_rule": (
                    "Rank and stabilize each declared scientific domain independently; "
                    "do not average general genetic influence with water-nitrogen response"
                ),
                "source_stability_report": "morris_multiseed_stability.json",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Formal Morris cross-seed stability",
        "",
        f"- Seeds: `{', '.join(map(str, result['seeds']))}`",
        f"- Minimum pairwise Spearman: `{result['minimum_pairwise_spearman']:.4f}` (threshold `{min_spearman:.2f}`)",
        f"- Minimum Top-{top_k} Jaccard: `{result['minimum_pairwise_top_k_jaccard']:.4f}` (threshold `{min_jaccard:.2f}`)",
        f"- Decision: `{decision}`",
        "",
        "Preflight cases are rejected and each formal seed must pass both trajectory and result quality reports.",
    ]
    (destination / "morris_multiseed_stability.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Assess formal Morris ranking stability across independent seeds")
    parser.add_argument("--case-dir", action="append", required=True)
    parser.add_argument("--excluded-case", action="append", default=[])
    parser.add_argument("--output-profile", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--top-k", type=int, default=15)
    parser.add_argument("--min-spearman", type=float, default=0.90)
    parser.add_argument("--min-jaccard", type=float, default=0.80)
    args = parser.parse_args()
    result = analyze_multiseed(
        args.case_dir,
        args.output_profile,
        args.out_dir,
        excluded_case_dirs=args.excluded_case,
        top_k=args.top_k,
        min_spearman=args.min_spearman,
        min_jaccard=args.min_jaccard,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
