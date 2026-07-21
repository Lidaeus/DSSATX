"""Freeze multi-season Morris evidence for the R paper-figure renderer.

The exporter consumes only the audited cross-seed summary products.  It never
reads DSSAT or PEST++ temporary files and it never renders a figure.  General
genetic effects and water-nitrogen response effects remain separate ranking
domains because their hierarchy-normalised scores answer different questions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DOMAIN_LABELS = {
    "general_genetic": "General genetic effects",
    "water_nitrogen_response": "Water-nitrogen response",
}
GROUP_LABELS = {
    "phenology": "Phenology",
    "canopy": "Canopy",
    "biomass": "Biomass",
    "yield_harvest": "Harvest",
    "water_response": "Water response",
    "nitrogen_response": "Nitrogen response",
    "water_nitrogen_interaction": "Water x nitrogen",
}
REQUIRED_FILES = {
    "consensus_ranking": "morris_consensus_ranking.csv",
    "seed_rankings": "morris_seed_rankings.csv",
    "seed_group_scores": "morris_seed_group_scores.csv",
    "pairwise_stability": "morris_seed_pairwise_stability.csv",
    "stability_report": "morris_multiseed_stability.json",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, role: str) -> dict[str, str]:
    return {"role": role, "path": path.name, "sha256": sha256_file(path)}


def _read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.ParserError) as exc:
        raise ValueError(f"cannot read Morris table: {path}") from exc
    missing = required - set(frame.columns)
    if missing or frame.empty:
        raise ValueError(f"{path.name} is empty or missing columns: {sorted(missing)}")
    return frame


def _finite_nonnegative(frame: pd.DataFrame, columns: list[str], source: Path) -> None:
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(values).all() or (values < 0).any():
            raise ValueError(f"{source.name} has invalid {column} values")
        frame[column] = values


def _load_season(season_dir: Path, season_order: int, season_label: str | None = None) -> dict[str, Any]:
    missing = [name for name in REQUIRED_FILES.values() if not (season_dir / name).is_file()]
    if missing:
        raise ValueError(f"Morris season {season_dir.name} is missing: {missing}")
    report_path = season_dir / REQUIRED_FILES["stability_report"]
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid stability report: {report_path}") from exc
    if report.get("run_type") != "formal_morris_multiseed_stability":
        raise ValueError(f"unexpected Morris run_type in {report_path}")
    if not report.get("case_quality_validated"):
        raise ValueError(f"Morris cases did not pass result quality gates: {season_dir.name}")

    consensus_path = season_dir / REQUIRED_FILES["consensus_ranking"]
    consensus = _read_csv(
        consensus_path,
        {"ranking_domain", "parameter", "mean_score", "mean_rank", "min_rank", "max_rank", "consensus_rank"},
    )
    seed_ranks_path = season_dir / REQUIRED_FILES["seed_rankings"]
    seed_ranks = _read_csv(seed_ranks_path, {"seed", "ranking_domain", "parameter", "score", "rank"})
    groups_path = season_dir / REQUIRED_FILES["seed_group_scores"]
    groups = _read_csv(groups_path, {"seed", "response_group", "parameter", "group_score", "ranking_domain"})
    pairs_path = season_dir / REQUIRED_FILES["pairwise_stability"]
    pairs = _read_csv(
        pairs_path,
        {"ranking_domain", "seed_a", "seed_b", "spearman", "top_k", "top_k_jaccard", "passes"},
    )

    expected_domains = set(DOMAIN_LABELS)
    for name, frame in (("consensus", consensus), ("seed rankings", seed_ranks), ("group scores", groups), ("stability", pairs)):
        domains = set(frame["ranking_domain"].astype(str))
        if domains != expected_domains:
            raise ValueError(f"{season_dir.name} {name} domains differ: {sorted(domains)}")
    _finite_nonnegative(consensus, ["mean_score", "mean_rank", "min_rank", "max_rank", "consensus_rank"], consensus_path)
    _finite_nonnegative(seed_ranks, ["score", "rank"], seed_ranks_path)
    _finite_nonnegative(groups, ["group_score"], groups_path)
    _finite_nonnegative(pairs, ["spearman", "top_k", "top_k_jaccard"], pairs_path)
    if consensus.duplicated(["ranking_domain", "parameter"]).any():
        raise ValueError(f"duplicate consensus parameter rows: {season_dir.name}")
    if seed_ranks.duplicated(["seed", "ranking_domain", "parameter"]).any():
        raise ValueError(f"duplicate seed ranking rows: {season_dir.name}")
    if groups.duplicated(["seed", "ranking_domain", "response_group", "parameter"]).any():
        raise ValueError(f"duplicate group-score rows: {season_dir.name}")

    parameter_sets = [set(part["parameter"].astype(str).str.upper()) for _, part in consensus.groupby("ranking_domain")]
    if not parameter_sets or any(values != parameter_sets[0] for values in parameter_sets[1:]):
        raise ValueError(f"ranking domains do not contain the same parameters: {season_dir.name}")
    parameter_count = len(parameter_sets[0])
    if int(report.get("parameter_count", -1)) != parameter_count:
        raise ValueError(f"parameter_count disagrees with consensus table: {season_dir.name}")
    seeds = sorted(int(value) for value in seed_ranks["seed"].unique())
    if seeds != sorted(int(value) for value in report.get("seeds", [])):
        raise ValueError(f"seed list disagrees with stability report: {season_dir.name}")

    thresholds = report.get("thresholds") or {}
    spearman_threshold = float(thresholds.get("spearman", np.nan))
    jaccard_threshold = float(thresholds.get("top_k_jaccard", np.nan))
    if not np.isfinite([spearman_threshold, jaccard_threshold]).all():
        raise ValueError(f"stability thresholds are missing: {season_dir.name}")
    derived_passes = (pairs["spearman"] >= spearman_threshold) & (pairs["top_k_jaccard"] >= jaccard_threshold)
    recorded_passes = pairs["passes"].astype(str).str.lower().map({"true": True, "false": False})
    if recorded_passes.isna().any() or not np.array_equal(derived_passes.to_numpy(), recorded_passes.to_numpy()):
        raise ValueError(f"pairwise pass flags disagree with thresholds: {season_dir.name}")

    domain_stable: dict[str, bool] = {}
    for domain in sorted(expected_domains):
        derived = bool(derived_passes[pairs["ranking_domain"].astype(str).eq(domain)].all())
        reported = bool((report.get("domain_stability") or {}).get(domain, {}).get("stable"))
        if derived != reported:
            raise ValueError(f"domain stability disagrees with pairwise evidence: {season_dir.name}/{domain}")
        domain_stable[domain] = derived
    derived_science = bool(all(domain_stable.values()))
    if bool(report.get("science_validated")) != derived_science:
        raise ValueError(f"season science_validated disagrees with domain evidence: {season_dir.name}")

    source_chain_issues: list[str] = []
    case_records = report.get("cases")
    if not isinstance(case_records, list) or len(case_records) != len(seeds):
        source_chain_issues.append("case_record_count")
    else:
        for case in case_records:
            case_dir = Path(str(case.get("case_dir", "")))
            mio = case_dir / "sa_sen_morris.mio"
            expected_hash = str(case.get("mio_sha256", ""))
            if not mio.is_file():
                source_chain_issues.append(f"missing_mio:{case.get('seed')}")
            elif not expected_hash or sha256_file(mio) != expected_hash:
                source_chain_issues.append(f"mio_hash:{case.get('seed')}")
    output_profile = Path(str(report.get("output_profile", "")))
    output_profile_hash = str(report.get("output_profile_sha256", ""))
    if not output_profile.is_file():
        source_chain_issues.append("missing_output_profile")
    elif not output_profile_hash or sha256_file(output_profile) != output_profile_hash:
        source_chain_issues.append("output_profile_hash")

    # A season label is deliberately independent of the final component of the
    # result directory.  Formal Morris runs are stored below e.g. XXQL2502/r20,
    # while the scientific season remains XXQL2502.
    season = season_label or season_dir.name
    for frame in (consensus, seed_ranks, groups, pairs):
        frame.insert(0, "season_order", season_order)
        frame.insert(0, "season", season)
        frame["season_label"] = season
        frame["domain_label"] = frame["ranking_domain"].map(DOMAIN_LABELS)
        frame["domain_stable"] = frame["ranking_domain"].map(domain_stable)
    pairs["spearman_threshold"] = spearman_threshold
    pairs["jaccard_threshold"] = jaccard_threshold
    pairs["seed_pair"] = pairs["seed_a"].astype(int).astype(str) + "-" + pairs["seed_b"].astype(int).astype(str)
    consensus["parameter"] = consensus["parameter"].astype(str).str.upper()
    seed_ranks["parameter"] = seed_ranks["parameter"].astype(str).str.upper()
    groups["parameter"] = groups["parameter"].astype(str).str.upper()
    groups["response_group_label"] = groups["response_group"].map(GROUP_LABELS)
    if groups["response_group_label"].isna().any():
        unknown = sorted(groups.loc[groups["response_group_label"].isna(), "response_group"].unique())
        raise ValueError(f"unknown response groups in {season_dir.name}: {unknown}")
    return {
        "season": season,
        "consensus": consensus,
        "seed_rankings": seed_ranks,
        "groups": groups,
        "pairs": pairs,
        "report": report,
        "domain_stable": domain_stable,
        "source_chain_complete": not source_chain_issues,
        "source_chain_issues": source_chain_issues,
        "inputs": [
            {"role": role, "season": season, "path": str((season_dir / name).resolve()), "sha256": sha256_file(season_dir / name)}
            for role, name in REQUIRED_FILES.items()
        ],
    }


def _load_focus(path: Path, parameters: set[str]) -> pd.DataFrame:
    frame = _read_csv(path, {"display_order", "parameter", "primary_domain", "process_label"})
    frame["parameter"] = frame["parameter"].astype(str).str.upper()
    frame["display_order"] = pd.to_numeric(frame["display_order"], errors="coerce")
    if frame[["display_order", "parameter", "primary_domain", "process_label"]].isna().any().any():
        raise ValueError("SA focus configuration has blank or invalid values")
    if frame.duplicated("parameter").any() or frame.duplicated("display_order").any():
        raise ValueError("SA focus parameters and display_order must be unique")
    if not set(frame["primary_domain"]).issubset(DOMAIN_LABELS):
        raise ValueError("SA focus configuration has an unknown ranking domain")
    missing = set(frame["parameter"]) - parameters
    if missing:
        raise ValueError(f"SA focus parameters are absent from Morris results: {sorted(missing)}")
    frame["domain_label"] = frame["primary_domain"].map(DOMAIN_LABELS)
    frame["parameter_label"] = frame["parameter"] + " - " + frame["process_label"]
    return frame.sort_values("display_order", kind="stable").reset_index(drop=True)


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    frame.to_csv(path, index=False, encoding="utf-8")
    return path


def export_sa_bundle(
    *,
    run_id: str,
    results_root: Path,
    out_dir: Path,
    focus_config: Path,
    seasons: list[str] | None = None,
    allow_unvalidated_demo: bool = False,
) -> Path:
    """Validate and freeze the current multi-season Morris evidence."""
    results_root = results_root.resolve()
    season_specs = seasons or sorted(
        path.name
        for path in results_root.iterdir()
        if path.is_dir() and (path / REQUIRED_FILES["stability_report"]).is_file()
    )
    if len(season_specs) < 2:
        raise ValueError("SA paper evidence requires at least two unique seasons")
    resolved_seasons: list[tuple[str, Path]] = []
    for spec in season_specs:
        # --season LABEL=RELATIVE_OR_ABSOLUTE_DIRECTORY supports the formal
        # nested result layout without introducing a copied/staged data tree.
        label, separator, location = spec.partition("=")
        if separator:
            if not label or not location:
                raise ValueError(f"invalid season mapping: {spec!r}")
            season_dir = Path(location)
            if not season_dir.is_absolute():
                season_dir = results_root / season_dir
        else:
            label, season_dir = spec, results_root / spec
        resolved_seasons.append((label, season_dir))
    labels = [label for label, _ in resolved_seasons]
    if len(set(labels)) != len(labels):
        raise ValueError("SA paper evidence requires unique season labels")
    loaded = [
        _load_season(directory, index + 1, label)
        for index, (label, directory) in enumerate(resolved_seasons)
    ]
    parameter_sets = [set(item["consensus"]["parameter"]) for item in loaded]
    if any(values != parameter_sets[0] for values in parameter_sets[1:]):
        raise ValueError("Morris seasons do not contain identical parameter sets")
    focus = _load_focus(focus_config.resolve(), parameter_sets[0])

    rankings = pd.concat([item["consensus"] for item in loaded], ignore_index=True)
    seed_rankings = pd.concat([item["seed_rankings"] for item in loaded], ignore_index=True)
    groups = pd.concat([item["groups"] for item in loaded], ignore_index=True)
    pairs = pd.concat([item["pairs"] for item in loaded], ignore_index=True)

    summary = (
        rankings.groupby(["ranking_domain", "domain_label", "parameter"], as_index=False)
        .agg(
            cross_season_mean_score=("mean_score", "mean"),
            cross_season_mean_rank=("consensus_rank", "mean"),
            cross_season_min_rank=("consensus_rank", "min"),
            cross_season_max_rank=("consensus_rank", "max"),
            seasons_top15=("consensus_rank", lambda values: int((values <= 15).sum())),
        )
        .sort_values(["ranking_domain", "cross_season_mean_rank", "parameter"], kind="stable")
    )
    summary["cross_season_rank"] = summary.groupby("ranking_domain").cumcount() + 1
    rankings = rankings.merge(
        summary[["ranking_domain", "parameter", "cross_season_mean_score", "cross_season_mean_rank",
                 "cross_season_min_rank", "cross_season_max_rank", "seasons_top15", "cross_season_rank"]],
        on=["ranking_domain", "parameter"], how="left", validate="many_to_one",
    )
    group_summary = (
        groups.groupby(["ranking_domain", "domain_label", "response_group", "response_group_label", "parameter"], as_index=False)
        .agg(group_score_mean=("group_score", "mean"), group_score_sd=("group_score", "std"),
             group_score_min=("group_score", "min"), group_score_max=("group_score", "max"))
    )
    group_summary["group_score_sd"] = group_summary["group_score_sd"].fillna(0.0)

    all_science_validated = all(
        bool(item["report"]["science_validated"]) and bool(item["source_chain_complete"])
        for item in loaded
    )
    data_status = "science_validated" if all_science_validated else "science_pending"
    if data_status != "science_validated" and not allow_unvalidated_demo:
        raise ValueError(
            "Not every season/domain passed the Morris stability gate; pass --allow-unvalidated-demo "
            "to create visibly marked layout/current-evidence figures"
        )
    for frame in (rankings, summary, seed_rankings, groups, group_summary, pairs, focus):
        frame.insert(0, "data_status", data_status)
        frame.insert(0, "run_id", run_id)

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "season_rankings": _write_csv(rankings, out_dir / "morris_season_rankings.csv"),
        "cross_season_summary": _write_csv(summary, out_dir / "morris_cross_season_summary.csv"),
        "seed_rankings": _write_csv(seed_rankings, out_dir / "morris_seed_rankings.csv"),
        "group_scores": _write_csv(groups, out_dir / "morris_group_scores.csv"),
        "group_summary": _write_csv(group_summary, out_dir / "morris_group_summary.csv"),
        "pairwise_stability": _write_csv(pairs, out_dir / "morris_pairwise_stability.csv"),
        "focus_parameters": _write_csv(focus, out_dir / "morris_focus_parameters.csv"),
    }
    domain_status = [
        {"season": item["season"], "ranking_domain": domain, "stable": stable}
        for item in loaded for domain, stable in item["domain_stable"].items()
    ]
    source_chain_status = [
        {"season": item["season"], "complete": item["source_chain_complete"],
         "issues": item["source_chain_issues"]}
        for item in loaded
    ]
    payload = {
        "schema_version": 1,
        "bundle_type": "morris_sa_evidence",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": data_status,
        "scenario_type": "multi_season_morris_sensitivity",
        "renderer_contract": "r_paper_figures_v2",
        "seasons": labels,
        "ranking_domains": list(DOMAIN_LABELS),
        "domain_status": domain_status,
        "source_chain_status": source_chain_status,
        "limitations": (
            "Current evidence bundle: every domain/season stability gate and the raw .mio/output-profile "
            "hash chain must pass before the DEMO mark can be removed. Output-level mu-star/sigma and "
            "Sobol convergence are outside this bundle."
            if data_status != "science_validated" else
            "Morris screening evidence only; sensitivity does not by itself authorize calibration."
        ),
        "focus_config": {"path": str(focus_config.resolve()), "sha256": sha256_file(focus_config.resolve())},
        "upstream_artifacts": [record for item in loaded for record in item["inputs"]],
        "artifacts": [_artifact(path, role) for role, path in outputs.items()],
    }
    manifest = out_dir / "paper_data_manifest.json"
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze multi-season Morris evidence for R paper figures")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--season", action="append", default=[])
    parser.add_argument("--focus-config", default="configs/figures/sa_focus_parameters.csv")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = export_sa_bundle(
            run_id=args.run_id,
            results_root=Path(args.results_root),
            out_dir=Path(args.out_dir),
            focus_config=Path(args.focus_config),
            seasons=args.season or None,
            allow_unvalidated_demo=args.allow_unvalidated_demo,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
