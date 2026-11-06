"""Aggregate observation-level Morris effects into one row per parameter.

Produces ``morris_interaction_summary.csv`` — the data source for the
``fig_sa_interaction`` mu*–sigma scatter (plan task 3a).  The W2 exporter
``morris_response_effects.csv`` carries observation-level statistics (exact,
from .mio); this tool collapses them to a single (mu*, sigma) point per
parameter within a ranking domain by taking the median across observations,
seasons and seeds.

The median (rather than mean) is used because observation-level mu*/sigma are
right-skewed and the median is robust to a few high-magnitude observations.
The collapse is **descriptive only**: it supports a visual overview of which
parameters combine high importance (mu*) with high spread (sigma).  It is not
a treatment-mean statistic (see the P0 review finding) and the figure caption
states this.

Columns emitted::

    parameter, mu_star_median, sigma_median, sigma_ratio,
    response_group, response_group_label, ranking_domain,
    n_observations, season_set, seed_set
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.project import PROJECT_ROOT, git_metadata, sha256_file

OUTPUT_COLUMNS = [
    "parameter", "mu_star_median", "sigma_median", "sigma_ratio",
    "response_group", "response_group_label", "ranking_domain",
    "n_observations", "season_set", "seed_set",
]

# Human-readable labels for the response groups (mirrors the output contract).
_GROUP_LABELS = {
    "phenology": "Phenology",
    "canopy": "Canopy",
    "biomass": "Biomass",
    "yield_harvest": "Harvest",
    "water_response": "Water response",
    "nitrogen_response": "Nitrogen response",
    "water_nitrogen_interaction": "Water x nitrogen",
    "other": "Other",
}


def _median(values: list[float]) -> float:
    finite = [v for v in values if v == v]
    return statistics.median(finite) if finite else float("nan")


def aggregate_interaction_summary(
    effects_csv: str | Path,
    *,
    ranking_domain: str = "general_genetic",
) -> list[dict[str, str]]:
    """Aggregate observation-level effects to one row per parameter.

    For each parameter in *ranking_domain*, collapse all observation-level
    rows to a single mu* / sigma via median.  The dominant response_group
    (the one with the highest median mu*) is reported as the parameter's
    process-group colour assignment.
    """
    path = Path(effects_csv)
    # Accumulate per parameter: list of (mu_star, sigma, response_group, season, seed, mu_share)
    by_param: dict[str, list[tuple[float, float, str, str, str, float]]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if str(row.get("ranking_domain", "")).strip() != ranking_domain:
                continue
            parameter = str(row.get("parameter", "")).strip().upper()
            if not parameter:
                continue
            try:
                mu_star = float(row["mu_star"])
                sigma = float(row["sigma"])
            except (KeyError, ValueError):
                continue
            group = str(row.get("response_group", "other")).strip().lower()
            season = str(row.get("season", "")).strip()
            seed = str(row.get("seed", "")).strip()
            # dimensionless share for unit-free dominant-group determination
            share_str = str(row.get("mu_star_share_within_observation", "")).strip()
            try:
                mu_share = float(share_str)
            except ValueError:
                mu_share = float("nan")
            by_param[parameter].append((mu_star, sigma, group, season, seed, mu_share))

    out: list[dict[str, str]] = []
    for parameter, records in by_param.items():
        mu_stars = [r[0] for r in records]
        sigmas = [r[1] for r in records]
        groups = [r[2] for r in records]
        seasons = sorted({r[3] for r in records if r[3]})
        seeds = sorted({r[4] for r in records if r[4]})
        mu_med = _median(mu_stars)
        sig_med = _median(sigmas)
        # Dominant group: the process group in which this parameter has the
        # highest *dimensionless* share (mu_star_share_within_observation),
        # NOT the highest raw mu*.  Raw mu* is dimensionful (biomass in kg/ha
        # dwarfs canopy LAI), so comparing raw values across groups would make
        # every parameter look "biomass-dominated".  The share normalises away
        # the unit, giving a unit-free "where is this parameter most influential".
        group_shares: dict[str, list[float]] = defaultdict(list)
        for rec in records:
            mu_share = rec[5]  # (mu_star, sigma, group, season, seed, mu_share)
            group_shares[rec[2]].append(mu_share)
        dominant_group = max(group_shares, key=lambda g: _median(group_shares[g])) if group_shares else "other"
        sigma_ratio = (sig_med / mu_med) if mu_med and mu_med > 0 else float("nan")
        out.append({
            "parameter": parameter,
            "mu_star_median": f"{mu_med:.10g}",
            "sigma_median": f"{sig_med:.10g}",
            "sigma_ratio": f"{sigma_ratio:.10g}" if sigma_ratio == sigma_ratio else "",
            "response_group": dominant_group,
            "response_group_label": _GROUP_LABELS.get(dominant_group, dominant_group),
            "ranking_domain": ranking_domain,
            "n_observations": str(len(records)),
            "season_set": ";".join(seasons),
            "seed_set": ";".join(seeds),
        })

    out.sort(key=lambda r: -float(r["mu_star_median"]))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate observation-level Morris effects to one row per parameter (task 3a)."
    )
    parser.add_argument("--effects-csv", required=True,
                        help="morris_response_effects.csv (observation-level, W2 export).")
    parser.add_argument("--ranking-domain", default="general_genetic",
                        help="Ranking domain to aggregate (default: general_genetic).")
    parser.add_argument("--out", default=None, help="Output CSV path.")
    args = parser.parse_args(argv)

    rows = aggregate_interaction_summary(args.effects_csv, ranking_domain=args.ranking_domain)

    out_path = Path(args.out) if args.out else (
        PROJECT_ROOT / "workspace" / "sa" / "morris_interaction_summary.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Plain UTF-8 (no BOM) — R read.csv keeps a BOM in the column name (P1#2).
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    meta = git_metadata()
    print(f"morris_interaction_summary.csv written: {out_path}")
    print(f"  parameters: {len(rows)}")
    print(f"  ranking_domain: {args.ranking_domain}")
    from collections import Counter
    grp_counts = Counter(r["response_group_label"] for r in rows)
    for g, n in grp_counts.most_common():
        print(f"    {g}: {n}")
    print(f"  source: {Path(args.effects_csv).name} (sha256 {sha256_file(args.effects_csv)[:12]}…)")
    print(f"  git: {meta.get('git_commit', '?')[:12]} dirty={meta.get('git_dirty', '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
