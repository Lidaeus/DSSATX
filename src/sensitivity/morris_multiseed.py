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
    return {"seed": int(manifest["random_seed"]), "manifest": manifest}


def _feature_metadata(observation: str) -> tuple[int, str]:
    match = _TN_RE.match(str(observation).strip())
    if not match:
        raise ValueError(f"Expected treatment-specific observation, got: {observation}")
    feature = match.group("feature").upper()
    family = _DAP_RE.sub("_DAP", feature)
    return int(match.group("treatment")), family


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


def _rank_case(case_dir: Path, lookup: dict[str, str], tolerance: float = 1e-12) -> tuple[int, pd.DataFrame, pd.DataFrame]:
    identity = _require_validated_case(case_dir)
    seed = int(identity["seed"])
    frame = load_morris_summary(case_dir / "sa_sen_morris.mio")
    frame["obs"] = frame["obs"].astype(str).str.lower()
    frame["par"] = frame["par"].astype(str).str.upper()
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    if not np.isfinite(frame["score"]).all() or (frame["score"] < 0).any():
        raise ValueError(f"Morris scores must be finite and non-negative: {case_dir}")
    metadata = frame["obs"].map(_feature_metadata)
    frame["treatment"] = [item[0] for item in metadata]
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
    ranking = (
        group_scores.groupby("par", as_index=False)["group_score"]
        .mean()
        .rename(columns={"par": "parameter", "group_score": "score"})
        .sort_values(["score", "parameter"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )
    ranking.insert(0, "seed", seed)
    ranking["rank"] = ranking["score"].rank(method="average", ascending=False)
    group_scores.insert(0, "seed", seed)
    group_scores = group_scores.rename(columns={"par": "parameter"})
    return seed, ranking, group_scores


def analyze_multiseed(
    case_dirs: list[str | Path],
    output_profile: str | Path,
    out_dir: str | Path,
    *,
    top_k: int = 15,
    min_spearman: float = 0.90,
    min_jaccard: float = 0.80,
) -> dict[str, Any]:
    if len(case_dirs) < 2:
        raise ValueError("Cross-seed stability requires at least two cases")
    contract = load_output_contract(output_profile)
    lookup = _group_lookup(contract)
    rankings: list[pd.DataFrame] = []
    group_scores: list[pd.DataFrame] = []
    case_records: list[dict[str, Any]] = []
    seen_seeds: set[int] = set()
    expected_parameters: set[str] | None = None
    for raw_case in case_dirs:
        case_dir = Path(raw_case).resolve()
        seed, ranking, groups = _rank_case(case_dir, lookup)
        if seed in seen_seeds:
            raise ValueError(f"Duplicate formal seed: {seed}")
        seen_seeds.add(seed)
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
            }
        )

    all_rankings = pd.concat(rankings, ignore_index=True)
    all_groups = pd.concat(group_scores, ignore_index=True)
    pair_rows: list[dict[str, Any]] = []
    for left, right in combinations(sorted(seen_seeds), 2):
        left_frame = all_rankings[all_rankings["seed"] == left].set_index("parameter")
        right_frame = all_rankings[all_rankings["seed"] == right].set_index("parameter")
        spearman = float(left_frame["rank"].corr(right_frame["rank"], method="spearman"))
        left_top = set(left_frame.nsmallest(top_k, "rank").index)
        right_top = set(right_frame.nsmallest(top_k, "rank").index)
        union = left_top | right_top
        jaccard = float(len(left_top & right_top) / len(union)) if union else 1.0
        pair_rows.append(
            {
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
        all_rankings.groupby("parameter", as_index=False)
        .agg(mean_score=("score", "mean"), mean_rank=("rank", "mean"), min_rank=("rank", "min"), max_rank=("rank", "max"))
        .sort_values(["mean_rank", "parameter"], kind="stable")
    )
    consensus.insert(0, "consensus_rank", np.arange(1, len(consensus) + 1))

    destination = Path(out_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    all_rankings.to_csv(destination / "morris_seed_rankings.csv", index=False, encoding="utf-8-sig")
    all_groups.to_csv(destination / "morris_seed_group_scores.csv", index=False, encoding="utf-8-sig")
    pairs.to_csv(destination / "morris_seed_pairwise_stability.csv", index=False, encoding="utf-8-sig")
    consensus.to_csv(destination / "morris_consensus_ranking.csv", index=False, encoding="utf-8-sig")
    result = {
        "schema_version": 1,
        "run_type": "formal_morris_multiseed_stability",
        "science_validated": True,
        "seed_count": len(seen_seeds),
        "seeds": sorted(seen_seeds),
        "parameter_count": len(expected_parameters or set()),
        "top_k": top_k,
        "thresholds": {"spearman": min_spearman, "top_k_jaccard": min_jaccard},
        "minimum_pairwise_spearman": float(pairs["spearman"].min()),
        "minimum_pairwise_top_k_jaccard": float(pairs["top_k_jaccard"].min()),
        "stable": stable,
        "decision": decision,
        "output_profile": str(Path(output_profile).resolve()),
        "output_profile_sha256": sha256_file(output_profile),
        "cases": case_records,
    }
    (destination / "morris_multiseed_stability.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
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
        top_k=args.top_k,
        min_spearman=args.min_spearman,
        min_jaccard=args.min_jaccard,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
