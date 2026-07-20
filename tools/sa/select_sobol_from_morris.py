"""Create season-bound Sobol approvals from stable multi-season Morris results."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.project import sha256_file


def _assign(values: list[str], label: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{label} must use SEASON=PATH: {value}")
        season, path = value.split("=", 1)
        result[season.strip().upper()] = Path(path).resolve()
    return result


def select_parameters(
    result_dirs: dict[str, Path],
    *,
    top_k: int = 15,
    minimum_domain_count: int = 2,
    season_specific_score: float = 0.02,
) -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    counts: Counter[str] = Counter()
    scores: defaultdict[str, list[float]] = defaultdict(list)
    ranks: defaultdict[str, list[int]] = defaultdict(list)
    sources: dict[str, dict[str, str]] = {}

    for season, directory in sorted(result_dirs.items()):
        stability_path = directory / "morris_multiseed_stability.json"
        ranking_path = directory / "morris_consensus_ranking.csv"
        stability = json.loads(stability_path.read_text(encoding="utf-8"))
        if stability.get("ranking_stable") is not True:
            raise ValueError(f"{season} Morris ranking is not stable: {stability_path}")
        frame = pd.read_csv(ranking_path)
        if set(frame["ranking_domain"].astype(str)) != {"general_genetic", "water_nitrogen_response"}:
            raise ValueError(f"{season} must contain exactly the two registered ranking domains")
        for _, domain in frame.groupby("ranking_domain"):
            top = domain.nsmallest(top_k, "consensus_rank")
            counts.update(top["parameter"].astype(str).str.upper())
            for row in domain.itertuples(index=False):
                parameter = str(row.parameter).upper()
                scores[parameter].append(float(row.mean_score))
                ranks[parameter].append(int(row.consensus_rank))
        sources[season] = {
            "result_dir": str(directory),
            "stability_sha256": sha256_file(stability_path),
            "ranking_sha256": sha256_file(ranking_path),
        }

    rows = []
    for parameter, domain_count in counts.items():
        max_score = max(scores[parameter])
        robust = domain_count >= minimum_domain_count
        safeguard = domain_count == 1 and max_score >= season_specific_score
        if not (robust or safeguard):
            continue
        rows.append(
            {
                "parameter": parameter,
                "top15_domain_count": domain_count,
                "minimum_domain_rank": min(ranks[parameter]),
                "maximum_mean_score": max_score,
                "mean_score_across_domains": sum(scores[parameter]) / len(scores[parameter]),
                "selection_class": "cross_domain_recurrent" if robust else "season_specific_safeguard",
                "approval_status": "approved",
            }
        )
    frame = pd.DataFrame(rows).sort_values(
        ["top15_domain_count", "mean_score_across_domains", "parameter"],
        ascending=[False, False, True],
        kind="stable",
    )
    frame.insert(1, "selection_order", range(1, len(frame) + 1))
    return frame, sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", action="append", required=True, help="SEASON=result directory")
    parser.add_argument("--output-profile", action="append", required=True, help="SEASON=profile JSON")
    parser.add_argument("--input-dir", action="append", required=True, help="SEASON=input bundle")
    parser.add_argument("--bounds", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--top-k", type=int, default=15)
    parser.add_argument("--minimum-domain-count", type=int, default=2)
    parser.add_argument("--season-specific-score", type=float, default=0.02)
    args = parser.parse_args()

    results = _assign(args.result, "--result")
    profiles = _assign(args.output_profile, "--output-profile")
    inputs = _assign(args.input_dir, "--input-dir")
    if not results or set(results) != set(profiles) or set(results) != set(inputs):
        parser.error("result, output-profile and input-dir season keys must match")

    bounds = Path(args.bounds).resolve()
    output = Path(args.out_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    selected, sources = select_parameters(
        results,
        top_k=args.top_k,
        minimum_domain_count=args.minimum_domain_count,
        season_specific_score=args.season_specific_score,
    )
    csv_path = output / f"{args.approval_id}.csv"
    if csv_path.exists():
        parser.error(f"Refusing to overwrite approval: {csv_path}")
    selected.to_csv(csv_path, index=False, encoding="utf-8-sig")
    csv_hash = sha256_file(csv_path)
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for season in sorted(results):
        profile = profiles[season]
        input_dir = inputs[season]
        metadata = {
            "schema_version": 1,
            "approval_id": f"{args.approval_id}_{season.lower()}",
            "review_status": "approved",
            "approved_at": created_at,
            "approved_by": "user_request_20260721",
            "approved_parameter_count": len(selected),
            "approved_topk_csv": csv_path.name,
            "approved_topk_csv_sha256": csv_hash,
            "selection_rule": (
                f"top-{args.top_k} in at least {args.minimum_domain_count} of six season-domain rankings; "
                f"or single-domain safeguard with maximum normalized Morris score >= {args.season_specific_score:g}"
            ),
            "source_morris": sources,
            "bounds_id": bounds.stem,
            "bounds_sha256": sha256_file(bounds),
            "output_profile_id": json.loads(profile.read_text(encoding="utf-8"))["profile_id"],
            "output_profile_sha256": sha256_file(profile),
            "input_bundle_id": input_dir.name,
            "input_manifest_sha256": sha256_file(input_dir / "input_manifest.json"),
            "sobol_parameter_distribution": "uniform",
            "formal_sample_schedule": [64, 128, 256],
        }
        path = output / f"{args.approval_id}_{season.lower()}.json"
        path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Selected {len(selected)} parameters: {', '.join(selected['parameter'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
