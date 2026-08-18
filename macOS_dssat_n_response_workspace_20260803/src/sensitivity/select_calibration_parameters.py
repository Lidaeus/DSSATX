"""Select a calibration candidate set from frozen multi-domain SA evidence.

The water-nitrogen-response score and the general-genetic score answer
different scientific questions.  They are therefore accumulated separately;
the calibration candidate set is the union of the smallest per-domain sets
that reach the requested contribution threshold.

This module only writes a reviewable proposal.  It never changes a frozen
parameter-bounds file or starts a calibration run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = {
    "ranking_domain",
    "parameter",
    "cross_season_mean_score",
    "data_status",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def select_by_domain(
    summary: pd.DataFrame,
    *,
    threshold: float = 0.90,
    excluded_parameters: tuple[str, ...] = (),
    required_domains: tuple[str, ...] = (
        "general_genetic",
        "water_nitrogen_response",
    ),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the union candidate table and per-domain coverage table."""
    missing = REQUIRED_COLUMNS - set(summary.columns)
    if missing:
        raise ValueError(f"sensitivity summary is missing columns: {sorted(missing)}")
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0, 1]")

    work = summary.copy()
    work["ranking_domain"] = work["ranking_domain"].astype(str).str.strip()
    work["parameter"] = work["parameter"].astype(str).str.strip().str.upper()
    work["cross_season_mean_score"] = pd.to_numeric(
        work["cross_season_mean_score"], errors="coerce"
    )
    if work["cross_season_mean_score"].isna().any():
        raise ValueError("cross_season_mean_score contains non-numeric values")
    if (work["cross_season_mean_score"] < 0).any():
        raise ValueError("cross_season_mean_score contains negative values")
    excluded = {str(value).strip().upper() for value in excluded_parameters}
    work = work.loc[~work["parameter"].isin(excluded)].copy()
    duplicates = work.duplicated(["ranking_domain", "parameter"], keep=False)
    if duplicates.any():
        keys = work.loc[duplicates, ["ranking_domain", "parameter"]].to_dict("records")
        raise ValueError(f"duplicate domain/parameter rows: {keys}")

    absent = [domain for domain in required_domains if domain not in set(work["ranking_domain"])]
    if absent:
        raise ValueError(f"required ranking domains are absent: {absent}")

    selected_parts: list[pd.DataFrame] = []
    coverage_rows: list[dict[str, object]] = []
    for domain in required_domains:
        ranked = work.loc[work["ranking_domain"].eq(domain)].copy()
        total = float(ranked["cross_season_mean_score"].sum())
        if total <= 0.0:
            raise ValueError(f"ranking domain {domain!r} has zero total contribution")
        ranked = ranked.sort_values(
            ["cross_season_mean_score", "parameter"],
            ascending=[False, True],
            kind="stable",
        ).reset_index(drop=True)
        ranked["normalized_contribution"] = ranked["cross_season_mean_score"] / total
        ranked["cumulative_contribution"] = ranked["normalized_contribution"].cumsum()
        crossing = ranked.index[ranked["cumulative_contribution"].ge(threshold)]
        stop = int(crossing[0]) if len(crossing) else len(ranked) - 1
        chosen = ranked.iloc[: stop + 1].copy()
        chosen["domain_rank"] = range(1, len(chosen) + 1)
        selected_parts.append(chosen)
        coverage_rows.append(
            {
                "ranking_domain": domain,
                "threshold": threshold,
                "selected_count": len(chosen),
                "selected_contribution": float(chosen["normalized_contribution"].sum()),
                "domain_total_score": total,
            }
        )

    selected_long = pd.concat(selected_parts, ignore_index=True)
    union_rows: list[dict[str, object]] = []
    for parameter in sorted(selected_long["parameter"].unique()):
        member = selected_long.loc[selected_long["parameter"].eq(parameter)]
        row: dict[str, object] = {
            "parameter": parameter,
            "selected_domain_count": int(member["ranking_domain"].nunique()),
            "selected_domains": ";".join(sorted(member["ranking_domain"].unique())),
        }
        for domain in required_domains:
            domain_row = member.loc[member["ranking_domain"].eq(domain)]
            prefix = domain.replace("water_nitrogen_response", "water_n_response")
            row[f"{prefix}_selected"] = not domain_row.empty
            row[f"{prefix}_rank"] = (
                int(domain_row.iloc[0]["domain_rank"]) if not domain_row.empty else pd.NA
            )
            row[f"{prefix}_contribution"] = (
                float(domain_row.iloc[0]["normalized_contribution"])
                if not domain_row.empty
                else 0.0
            )
        union_rows.append(row)

    union = pd.DataFrame(union_rows)
    union = union.sort_values(
        ["selected_domain_count", "general_genetic_rank", "water_n_response_rank", "parameter"],
        ascending=[False, True, True, True],
        na_position="last",
        kind="stable",
    ).reset_index(drop=True)
    union.insert(0, "selection_order", range(1, len(union) + 1))
    return union, pd.DataFrame(coverage_rows)


def build_selection_proposal(
    summary_csv: str | Path,
    out_dir: str | Path,
    *,
    threshold: float = 0.90,
    allow_provisional: bool = False,
    excluded_parameters: tuple[str, ...] = (),
) -> Path:
    source = Path(summary_csv).resolve()
    output = Path(out_dir).resolve()
    summary = pd.read_csv(source, encoding="utf-8-sig")
    statuses = sorted(set(summary["data_status"].astype(str).str.strip()))
    if statuses != ["science_validated"] and not allow_provisional:
        raise ValueError(
            f"sensitivity evidence is not science_validated ({statuses}); "
            "pass --allow-provisional to create a review-only proposal"
        )

    selected, coverage = select_by_domain(
        summary,
        threshold=threshold,
        excluded_parameters=excluded_parameters,
    )
    selected.insert(1, "evidence_status", ";".join(statuses))
    output.mkdir(parents=True, exist_ok=True)
    selected_path = output / "calibration_parameter_candidates.csv"
    coverage_path = output / "domain_coverage.csv"
    selected.to_csv(selected_path, index=False, encoding="utf-8")
    coverage.to_csv(coverage_path, index=False, encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proposal_only": True,
        "automatic_bounds_change": False,
        "threshold": threshold,
        "selection_rule": "per_domain_minimum_cumulative_then_union",
        "required_domains": ["general_genetic", "water_nitrogen_response"],
        "excluded_parameters": sorted(
            {str(value).strip().upper() for value in excluded_parameters}
        ),
        "source": {"path": str(source), "sha256": _sha256(source)},
        "source_data_status": statuses,
        "union_parameter_count": len(selected),
        "artifacts": [
            {"path": selected_path.name, "sha256": _sha256(selected_path)},
            {"path": coverage_path.name, "sha256": _sha256(coverage_path)},
        ],
        "limitations": (
            "A 90% sensitivity contribution rule controls screening coverage, not "
            "parameter identifiability. Literature, observation support, bounds, and "
            "equifinality diagnostics remain mandatory before bounds are frozen."
        ),
    }
    manifest_path = output / "selection_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a review-only calibration parameter proposal from multi-domain SA"
    )
    parser.add_argument("--summary", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--threshold", type=float, default=0.90)
    parser.add_argument("--allow-provisional", action="store_true")
    parser.add_argument(
        "--exclude-parameter",
        action="append",
        default=[],
        help="Exclude a scientifically inapplicable parameter before domain normalization; repeatable",
    )
    args = parser.parse_args(argv)
    print(
        build_selection_proposal(
            args.summary,
            args.out_dir,
            threshold=args.threshold,
            allow_provisional=args.allow_provisional,
            excluded_parameters=tuple(args.exclude_parameter),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
