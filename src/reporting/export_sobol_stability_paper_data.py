"""Freeze a three-season Sobol budget/stability record for the R renderer."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np

from src.sensitivity.sobol_audit import read_flat_manifest
from src.sensitivity.sa_contract import (
    ALL_RESPONSES,
    AMBIGUOUS_FRUIT_DRY_MASS_PHRASES,
    CUMULATIVE_HARVEST_DRY_MASS_ID,
    RANKING_DOMAIN_GENERAL,
    RANKING_DOMAIN_WATER_NITROGEN,
)


# Fixed scalar responses that enter the Sobol effect decomposition.
# Each row is (response_id, paper_label, ranking_domain, output_pattern, unit,
# display_in_figure).  The response_id and paper_label are sourced from the
# single source of truth (sa_contract.ALL_RESPONSES) so the published names
# never drift back to the ambiguous "fruit dry mass" phrasing forbidden by
# plan §4.1.  output_pattern matches the per-treatment / WN columns in
# sa_sen_sobol.sobol.obs.csv.
def _contract_label(response_id: str, fallback: str) -> str:
    """Resolve a paper_label from the contract, falling back if undeclared."""
    spec = ALL_RESPONSES.get(response_id)
    return spec.paper_label if spec else fallback


_EFFECT_RESPONSES = (
    ("MEAN_ADAPS", _contract_label("MEAN_ADAPS", "Anthesis"),
     RANKING_DOMAIN_GENERAL, r"^tn\d+_adaps$", "d", True),
    ("MEAN_LAI_AUC", _contract_label("MEAN_LAI_AUC", "Seasonal LAI integral"),
     RANKING_DOMAIN_GENERAL, r"^tn\d+_lai_auc$", "d·m²/m²", True),
    ("MEAN_AGB_END_CWAD", _contract_label("MEAN_AGB_END_CWAD", "End-of-season aboveground biomass"),
     RANKING_DOMAIN_GENERAL, r"^tn\d+_agb_end_cwad$", "kg/ha", True),
    # Plan §4.1 note: this MUST be "season-end cumulative harvested dry mass",
    # never the ambiguous "fruit dry mass" (sa_contract pins the label).
    (CUMULATIVE_HARVEST_DRY_MASS_ID, ALL_RESPONSES[CUMULATIVE_HARVEST_DRY_MASS_ID].paper_label,
     RANKING_DOMAIN_GENERAL, r"^tn\d+_fruitd_end$", "kg/ha", True),
    # Diagnostic only (plan §4.2): wide first-order CIs, never used for
    # interaction-strength claims — display_in_figure=False.
    ("MEAN_CUMHARVEST_DAP50", _contract_label("MEAN_CUMHARVEST_DAP50", "DAP at 50% cumulative harvest"),
     RANKING_DOMAIN_GENERAL, r"^tn\d+_cumharvest_dap50$", "d", False),
    ("WN_WATER_FRUITD_END", _contract_label("WN_WATER_FRUITD_END", "Water contrast in cumulative harvested dry mass"),
     RANKING_DOMAIN_WATER_NITROGEN, r"^wn_water_n\d+_fruitd_end$", "kg/ha", True),
    ("WN_NSLOPE_FRUITD_END", _contract_label("WN_NSLOPE_FRUITD_END", "Nitrogen-response slope of cumulative harvested dry mass"),
     RANKING_DOMAIN_WATER_NITROGEN, r"^wn_nslope_w\d+_fruitd_end$", "(kg/ha)/(kg N/ha)", True),
    ("WN_INTERACTION_FRUITD_END", _contract_label("WN_INTERACTION_FRUITD_END", "Difference in nitrogen-response slopes between water levels"),
     RANKING_DOMAIN_WATER_NITROGEN, r"^wn_interaction_fruitd_end$", "(kg/ha)/(kg N/ha)", True),
)


def _assert_no_ambiguous_labels() -> None:
    """Reject any response label containing an ambiguous phrase (plan §4.1).

    Guard against future regressions where a label drifts back to "fruit dry
    mass" or similar.  Called once at import time so the failure is immediate.
    """
    for _rid, label, _dom, _pat, _unit, _disp in _EFFECT_RESPONSES:
        low = str(label).lower()
        for phrase in AMBIGUOUS_FRUIT_DRY_MASS_PHRASES:
            if phrase in low:
                raise ValueError(
                    f"Sobol effect response {_rid!r} label {label!r} contains the "
                    f"ambiguous phrase {phrase!r}; use the contract label from "
                    f"sa_contract.ALL_RESPONSES (plan §4.1)."
                )


_assert_no_ambiguous_labels()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _label_path(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError("season paths must use SEASON=PATH")
    label, path = value.split("=", 1)
    if not label or not path:
        raise ValueError("season paths must use non-empty SEASON=PATH")
    return label, Path(path).resolve()


def _read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    table = pd.read_csv(path)
    missing = required - set(table.columns)
    if missing or table.empty:
        raise ValueError(f"{path} is missing columns or is empty: {sorted(missing)}")
    return table


def _effect_decomposition(case_dir: Path, season: str, *, replicates: int = 1000,
                          seed: int = 20260729) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Estimate S1, ST and their paired difference for fixed scalar responses.

    Treatment-level outputs are averaged *within each Sobol realization* before
    applying the estimator.  Consequently every row remains a Sobol index for
    one explicitly defined scalar model response; indices are never averaged
    after estimation.
    """
    manifest = read_flat_manifest(case_dir / "run_manifest.yaml")
    samples = int(manifest["sobol_samples"])
    parameters = pd.read_csv(case_dir / "sa_sen_sobol.sobol.par.csv")
    outputs = pd.read_csv(case_dir / "sa_sen_sobol.sobol.obs.csv")
    if not len(parameters.columns) or parameters.columns[0] != "run_id":
        raise ValueError("Sobol parameter table must start with run_id")
    if list(outputs.columns[:2]) != ["run_id", "failed_flag"]:
        raise ValueError("Sobol response table must start with run_id,failed_flag")
    parameter_count = len(parameters.columns) - 1
    if int(manifest.get("sobol_parameter_count", parameter_count)) != parameter_count:
        raise ValueError("Sobol manifest parameter count does not match the parameter table")
    expected = samples * (parameter_count + 2)
    if len(parameters) != expected or len(outputs) != expected:
        raise ValueError(f"Effect decomposition requires a complete Sobol design: {case_dir}")
    parameter_ids = pd.to_numeric(parameters["run_id"], errors="raise").astype(int)
    output_ids = pd.to_numeric(outputs["run_id"], errors="raise").astype(int)
    expected_ids = np.arange(expected)
    if (
        parameter_ids.duplicated().any()
        or output_ids.duplicated().any()
        or not np.array_equal(np.sort(parameter_ids.to_numpy()), expected_ids)
        or not np.array_equal(np.sort(output_ids.to_numpy()), expected_ids)
    ):
        raise ValueError(f"Sobol run_id coverage is incomplete or duplicated: {case_dir}")
    # Saltelli block membership is encoded by run_id, not physical CSV row
    # position.  Sort both tables explicitly before slicing A/B/hybrid blocks.
    parameters = parameters.assign(run_id=parameter_ids).sort_values("run_id", kind="stable").reset_index(drop=True)
    outputs = outputs.assign(run_id=output_ids).sort_values("run_id", kind="stable").reset_index(drop=True)
    if bool((pd.to_numeric(outputs["failed_flag"], errors="raise") != 0).any()):
        raise ValueError(f"Effect decomposition requires a complete Sobol design: {case_dir}")
    rng = np.random.default_rng(seed)
    resamples = rng.integers(0, samples, size=(replicates, samples))
    rows: list[dict[str, object]] = []
    scales: list[dict[str, object]] = []
    response_columns = list(outputs.columns[2:])
    for response_id, label, domain, pattern, unit, display in _EFFECT_RESPONSES:
        columns = [name for name in response_columns if re.match(pattern, name, flags=re.IGNORECASE)]
        if not columns:
            raise ValueError(f"No Sobol outputs match fixed response {response_id}: {pattern}")
        values = outputs[columns].apply(pd.to_numeric, errors="raise").mean(axis=1).to_numpy(dtype=float)
        a = values[:samples]
        b = values[samples : 2 * samples]
        variance = float(np.var(np.concatenate([a, b]), ddof=0))
        if not np.isfinite(variance) or variance <= 1e-12:
            raise ValueError(f"Composite Sobol response is not estimable: {response_id}")
        a_boot = a[resamples]
        b_boot = b[resamples]
        variance_boot = np.var(np.concatenate([a_boot, b_boot], axis=1), axis=1, ddof=0)
        if float((variance_boot > 1e-12).mean()) < 0.95:
            raise ValueError(f"Composite response fails bootstrap variance gate: {response_id}")
        scales.append({
            "season": season,
            "response_id": response_id,
            "response_label": label,
            "ranking_domain": domain,
            "unit": unit,
            "component_count": len(columns),
            "response_sd": float(np.sqrt(variance)),
            "response_min": float(min(np.min(a), np.min(b))),
            "response_max": float(max(np.max(a), np.max(b))),
            "display_in_figure": display,
        })
        response_rows: list[dict[str, object]] = []
        for parameter_index, parameter in enumerate(parameters.columns[1:]):
            hybrid = values[(parameter_index + 2) * samples : (parameter_index + 3) * samples]
            s1 = float(np.mean(b * (hybrid - a)) / variance)
            st = float(0.5 * np.mean((a - hybrid) ** 2) / variance)
            hybrid_boot = hybrid[resamples]
            valid = variance_boot > 1e-12
            s1_boot = np.mean(b_boot[valid] * (hybrid_boot[valid] - a_boot[valid]), axis=1) / variance_boot[valid]
            st_boot = 0.5 * np.mean((a_boot[valid] - hybrid_boot[valid]) ** 2, axis=1) / variance_boot[valid]
            gap_boot = st_boot - s1_boot
            s1_low, s1_high = np.quantile(s1_boot, [0.025, 0.975])
            st_low, st_high = np.quantile(st_boot, [0.025, 0.975])
            gap_low, gap_high = np.quantile(gap_boot, [0.025, 0.975])
            response_rows.append({
                "season": season,
                "response_id": response_id,
                "response_label": label,
                "ranking_domain": domain,
                "display_in_figure": display,
                "parameter": str(parameter).upper(),
                "S1": s1,
                "S1_ci_low": float(s1_low),
                "S1_ci_high": float(s1_high),
                "ST": st,
                "ST_ci_low": float(st_low),
                "ST_ci_high": float(st_high),
                "interaction_remainder": st - s1,
                "interaction_ci_low": float(gap_low),
                "interaction_ci_high": float(gap_high),
                "interaction_supported": bool(gap_low > 0),
                "first_order_interval_outside_unit_range": bool(s1_low < 0 or s1_high > 1),
                "bootstrap_replicates": replicates,
            })
        response_frame = pd.DataFrame(response_rows).sort_values(
            ["ST", "parameter"], ascending=[False, True], kind="stable"
        )
        response_frame["total_effect_rank"] = range(1, len(response_frame) + 1)
        rows.extend(response_frame.to_dict("records"))
    return pd.DataFrame(rows), pd.DataFrame(scales)


def export_sobol_stability_bundle(*, run_id: str, convergence_dirs: dict[str, Path],
                                  bootstrap_reports: dict[str, Path], out_dir: Path,
                                  effect_season: str | None = None,
                                  effect_case: Path | None = None) -> Path:
    """Build a single DEMO-only bundle from converged and nonconverged seasons."""
    if not convergence_dirs or not bootstrap_reports:
        raise ValueError("at least one convergence result and one bootstrap-gated season are required")
    rankings, metrics, scales, summary, upstream = [], [], [], [], []
    for season, directory in convergence_dirs.items():
        report_path = directory / "sobol_convergence.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("run_type") != "formal_sobol_convergence":
            raise ValueError(f"unexpected Sobol convergence report: {report_path}")
        comparison = (report.get("comparisons") or [None])[0]
        if not isinstance(comparison, dict):
            raise ValueError(f"missing comparison record: {report_path}")
        metric = pd.DataFrame(comparison.get("ranking_domains") or [])
        required_metric = {"ranking_domain", "spearman", "top_k_jaccard", "max_top_k_rank_shift", "passes"}
        if required_metric - set(metric.columns):
            raise ValueError(f"incomplete domain diagnostics: {report_path}")
        metric.insert(0, "season", season)
        metric.insert(1, "samples_a", comparison.get("samples_a"))
        metric.insert(2, "samples_b", comparison.get("samples_b"))
        for key, value in (report.get("thresholds") or {}).items():
            metric[f"threshold_{key}"] = value
        metrics.append(metric)
        ranking_path = directory / "sobol_scale_rankings.csv"
        rank = _read_csv(ranking_path, {"base_samples", "ranking_domain", "parameter", "score", "rank"})
        rank.insert(0, "season", season)
        rankings.append(rank)
        scale_path = directory / "sobol_run_scale.csv"
        scale = _read_csv(scale_path, {"base_samples", "parameter_count", "theoretical_model_runs", "actual_model_runs"})
        scale.insert(0, "season", season)
        scales.append(scale)
        passed = bool(report.get("science_validated"))
        summary.append({
            "season": season,
            "evidence_status": "converged" if passed else "rank_convergence_not_met",
            "science_validated": passed,
            "detail": "All prespecified rank-convergence checks passed" if passed else "At least one prespecified rank-convergence check was not met",
            "bootstrap_valid_fraction": pd.NA,
            "bootstrap_threshold": pd.NA,
        })
        for role, path in (("convergence", report_path), ("scale_rankings", ranking_path), ("run_scale", scale_path)):
            upstream.append({"season": season, "role": role, "path": str(path), "sha256": _sha256(path)})

    for season, report_path in bootstrap_reports.items():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        checks = {item.get("check_id"): item for item in report.get("checks", []) if isinstance(item, dict)}
        gate = checks.get("sobol_bootstrap_resamples")
        if not gate or gate.get("status") != "fail":
            raise ValueError(f"bootstrap report does not document a failed resample gate: {report_path}")
        summary.append({
            "season": season,
            "evidence_status": "bootstrap_resample_gate_not_met",
            "science_validated": False,
            "detail": str(gate.get("message")),
            "bootstrap_valid_fraction": gate.get("actual"),
            "bootstrap_threshold": gate.get("threshold"),
        })
        upstream.append({"season": season, "role": "bootstrap_quality", "path": str(report_path), "sha256": _sha256(report_path)})

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    output = {
        "sobol_scale_rankings.csv": pd.concat(rankings, ignore_index=True),
        "sobol_convergence_metrics.csv": pd.concat(metrics, ignore_index=True),
        "sobol_run_scale.csv": pd.concat(scales, ignore_index=True),
        "sobol_stability_summary.csv": pd.DataFrame(summary).sort_values("season", kind="stable"),
    }
    if effect_season or effect_case:
        if not effect_season or effect_case is None:
            raise ValueError("effect_season and effect_case must be supplied together")
        matching = [item for item in summary if item["season"] == effect_season]
        if len(matching) != 1 or not matching[0]["science_validated"]:
            raise ValueError("Effect decomposition is allowed only for a convergence-validated season")
        effects, response_scales = _effect_decomposition(effect_case.resolve(), effect_season)
        output["sobol_effect_decomposition.csv"] = effects
        output["sobol_response_scales.csv"] = response_scales
        for role, path in (
            ("effect_source_parameters", effect_case / "sa_sen_sobol.sobol.par.csv"),
            ("effect_source_outputs", effect_case / "sa_sen_sobol.sobol.obs.csv"),
        ):
            upstream.append({"season": effect_season, "role": role, "path": str(path), "sha256": _sha256(path)})
    artifacts = []
    for name, table in output.items():
        table.insert(0, "data_status", "science_pending")
        table.insert(0, "run_id", run_id)
        path = out_dir / name
        table.to_csv(path, index=False, encoding="utf-8")
        artifacts.append({"role": name.removesuffix(".csv"), "path": name, "sha256": _sha256(path), "rows": len(table)})
    manifest = {
        "schema_version": 1,
        "bundle_type": "sobol_multiseason_stability_evidence",
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_status": "science_pending",
        "scenario_type": "formal_sobol_budget_stability_assessment",
        "renderer_contract": "r_paper_figures_v2",
        "limitations": "This combined bundle is a transparent numerical-stability record. Quantitative S1/ST decomposition is limited to the convergence-validated effect season. ST-S1 is an aggregate interaction-involving remainder, not a pairwise interaction, and is interpreted only with its paired bootstrap interval. Cross-season pooled quantitative Sobol claims remain prohibited.",
        "upstream_artifacts": upstream,
        "artifacts": artifacts,
    }
    manifest_path = out_dir / "paper_data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze multi-season Sobol stability evidence for R")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--convergence-season", action="append", default=[], metavar="SEASON=DIR")
    parser.add_argument("--bootstrap-gate-season", action="append", default=[], metavar="SEASON=QUALITY_JSON")
    parser.add_argument("--effect-season")
    parser.add_argument("--effect-case")
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)
    try:
        print(export_sobol_stability_bundle(
            run_id=args.run_id,
            convergence_dirs=dict(_label_path(value) for value in args.convergence_season),
            bootstrap_reports=dict(_label_path(value) for value in args.bootstrap_gate_season),
            out_dir=Path(args.out_dir),
            effect_season=args.effect_season,
            effect_case=Path(args.effect_case) if args.effect_case else None,
        ))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
