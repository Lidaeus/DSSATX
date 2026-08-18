"""Three-season deterministic diagnostics for one PEST++ ensemble member.

This is a run-diagnostics entry point.  All figures are named
``diagnostic_*`` and are not paper Fig/FigS products.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import (  # noqa: E402
    _parse_batch_entries,
    _read_plantgro_vars_by_run,
    _read_tmt_process_obs,
)
from src.reporting.figure_data import (  # noqa: E402
    align_comparison_to_trajectory,
    read_dssat_trajectories,
)
from src.reporting.validation_metrics import build_comparison_from_rerun  # noqa: E402


SEASONS = [
    {
        "season_id": "25SP",
        "experiment_code": "XXQL2501",
        "bundle_path": "data/user/experiments/"
        "xxql2501_actual_trial_calibration_v6_adap34_moisturefix_page25_20260729",
        "bundle_manifest_sha256": "57c76e84e24d6e0a8ce3479de8fee05368d03a9807ef74e2d27971033ab3ad34",
        "role": "calibration",
        "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
    },
    {
        "season_id": "25FA",
        "experiment_code": "XXQL2502",
        "bundle_path": "data/user/experiments/"
        "xxql2502_actual_trial_calibration_v2_20260726",
        "bundle_manifest_sha256": "7d9f92021ce4e6fed3c588d1a4ee8c34bce62893178e68153b8f141449336512",
        "role": "calibration",
        "treatments": [3, 4, 7, 9, 1, 6, 10, 12],
    },
    {
        "season_id": "26SP",
        "experiment_code": "XXQL2601",
        "bundle_path": "data/user/experiments/"
        "xxql2601_actual_trial_calibration_v3_page25_20260728",
        "bundle_manifest_sha256": "db01851ab52c57e2a8b85e9fce3c789aedd86f0a123f6576890b3994c1a3c5ca",
        "role": "calibration",
        "treatments": [1, 3, 4, 6, 7, 9, 10, 12],
    },
]

LABELS = {
    "ADAP": "Anthesis timing",
    "LAIX": "Maximum LAI",
    "CNAM": "Canopy N",
    "LAID": "LAI",
    "LWAD": "Leaf dry mass",
    "SWAD": "Stem dry mass",
    "CHTD": "Plant height",
    "DRY_INC": "Incremental dry yield",
    "DRY_CUM": "Cumulative dry yield",
}
UNITS = {
    "CHTD": "m",
}
SEASON_COLORS = {"25SP": "#2878B5", "25FA": "#D95F02", "26SP": "#2A9D55"}
LINE_COLOR = "#345995"
OBS_COLOR = "#D1495B"


def _export_member(ensemble_path: Path, member: str, out_path: Path) -> None:
    frame = pd.read_csv(ensemble_path)
    real_col = next(
        (column for column in frame if str(column).lower() in {"real_name", "realization"}),
        None,
    )
    if real_col is None:
        raise ValueError(f"{ensemble_path} has no realization column")
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True) == str(member)
    if int(mask.sum()) != 1:
        raise ValueError(f"member {member} occurs {int(mask.sum())} times in {ensemble_path}")
    row = frame.loc[mask].iloc[0]
    records = []
    for column in frame.columns:
        if column == real_col:
            continue
        value = float(row[column])
        if not math.isfinite(value):
            raise ValueError(f"member {member}: non-finite {column}={value}")
        records.append({"name": str(column).upper(), "value": value})
    pd.DataFrame(records).to_csv(out_path, index=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_autumn_bundle(out_dir: Path) -> Path:
    """Combine the completed v2 observations with the authoritative PAGE=25 FileX."""
    source = ROOT / "data/user/experiments/xxql2502_actual_trial_calibration_v2_20260726"
    page25 = ROOT / "data/user/experiments/xxql2502_actual_trial_calibration_v3_page25_20260728"
    target = out_dir / "_input_bundles" / "xxql2502_v2obs_page25_diagnostic"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for item in source.iterdir():
        if item.is_file() and not item.name.startswith((".", "_")):
            shutil.copy2(item, target / item.name)
    shutil.copy2(page25 / "XXQL2502.TMX", target / "XXQL2502.TMX")
    manifest_path = target / "input_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bundle_id"] = target.name
    manifest["diagnostic_revision"] = {
        "observation_source": str(source.resolve()),
        "filex_source": str((page25 / "XXQL2502.TMX").resolve()),
        "reason": (
            "Use completed v2 FileA/FileT observations with user-authoritative "
            "PAGE=25 and SPRL=-99 FileX; soil initial conditions remain those in FileX."
        ),
    }
    filex = target / "XXQL2502.TMX"
    for record in manifest["files"]:
        if record.get("name") == filex.name:
            record["sha256"] = _sha256(filex)
            record["bytes"] = filex.stat().st_size
            record["copied_from"] = str((page25 / filex.name).resolve())
            break
    else:
        raise ValueError("25FA manifest does not list XXQL2502.TMX")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def _write_design(out_path: Path, seasons: list[dict]) -> None:
    payload = {
        "schema_version": 1,
        "design_id": "diagnostic_best_member_three_season_20260729",
        "cultivar_identity": "same_eggplant_cultivar",
        "shared_parameter_scope": (
            "Best 54-parameter member from 25SP+26SP; no autumn offsets applied"
        ),
        "observation_policy": "configs/runs/e02_55_fit_first_observation_policy_chpdt_log_v1.csv",
        "group_policy": "configs/runs/t10_dryonly_group_policy_v1.csv",
        "seasons": seasons,
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _add_chtd(
    comparison: pd.DataFrame,
    *,
    season: dict,
    season_dir: Path,
    selected_batch: Path,
    case: str,
) -> pd.DataFrame:
    bundle = ROOT / season["bundle_path"]
    tmt = bundle / f"{season['experiment_code']}.TMT"
    entries = _parse_batch_entries(str(selected_batch))
    observed = _read_tmt_process_obs(str(tmt), ["CHTD"])
    simulated = _read_plantgro_vars_by_run(str(season_dir / "PlantGro.OUT"), ["CHTD"])
    rows = []
    for entry in entries:
        run = int(entry["run"])
        treatment = int(entry["tn"])
        by_date = simulated.get(run, {})
        dates = sorted(by_date)
        for point in observed.get(treatment, []):
            date = int(point["DATE"])
            candidates = [value for value in dates if value <= date]
            sim_day = by_date.get(date)
            if sim_day is None and candidates:
                sim_day = by_date[candidates[-1]]
            obs = float(point.get("OBS_CHTD", -99))
            sim = float(sim_day.get("CHTD", np.nan)) if sim_day else np.nan
            if obs == -99 or not np.isfinite(obs) or not np.isfinite(sim):
                continue
            rows.append(
                {
                    "run_id": case,
                    "data_status": "engineering_validated_diagnostic",
                    "dataset_role": "diagnostic",
                    "variable": "CHTD",
                    "variable_label": LABELS["CHTD"],
                    "unit": UNITS["CHTD"],
                    "treatment": str(treatment),
                    "time": float(date % 1000),
                    "time_label": "Day of year",
                    "observed": obs,
                    "simulated": sim,
                    "source_file": str((season_dir / "PlantGro.OUT").resolve()),
                    "date_code": float(date),
                    "year": float(2000 + date // 1000),
                    "doy": float(date % 1000),
                    "dap": np.nan,
                    "harvest_number": np.nan,
                    "observed_sd": np.nan,
                    "observed_se": np.nan,
                    "n_rep": np.nan,
                }
            )
    return pd.concat([comparison, pd.DataFrame(rows)], ignore_index=True)


def _collect(
    out_dir: Path, case: str, seasons: list[dict]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    comparisons = []
    trajectories = []
    for season in seasons:
        sid = season["season_id"]
        season_dir = out_dir / "_seasons" / sid
        bundle = ROOT / season["bundle_path"]
        selected_batch = season_dir / "DSSBatch.selected.v48"
        entries = _parse_batch_entries(str(selected_batch))
        roles = {int(tn): "diagnostic" for tn in season["treatments"]}
        comparison = build_comparison_from_rerun(
            season_dir,
            case=case,
            data_status="engineering_validated_diagnostic",
            roles=roles,
            tmt_path=bundle / f"{season['experiment_code']}.TMT",
            entries=entries,
        )
        comparison = _add_chtd(
            comparison,
            season=season,
            season_dir=season_dir,
            selected_batch=selected_batch,
            case=case,
        )
        trajectory = read_dssat_trajectories(
            season_dir,
            run_id=case,
            data_status="engineering_validated_diagnostic",
            role_by_treatment={str(tn): "diagnostic" for tn in season["treatments"]},
        )
        comparison = align_comparison_to_trajectory(comparison, trajectory)
        comparison["season"] = sid
        trajectory["season"] = sid
        comparisons.append(comparison)
        trajectories.append(trajectory)
    return pd.concat(comparisons, ignore_index=True), pd.concat(trajectories, ignore_index=True)


def _metrics(group: pd.DataFrame) -> dict[str, float]:
    obs = group["observed"].to_numpy(float)
    sim = group["simulated"].to_numpy(float)
    residual = sim - obs
    rmse = float(np.sqrt(np.mean(residual**2)))
    mean_obs = float(np.mean(obs))
    denom = float(np.sum((obs - mean_obs) ** 2))
    nse = float(1 - np.sum(residual**2) / denom) if denom > 0 else np.nan
    r2 = float(np.corrcoef(obs, sim)[0, 1] ** 2) if len(group) > 1 else np.nan
    return {
        "n": len(group),
        "rmse": rmse,
        "rrmse_pct": 100 * rmse / mean_obs if mean_obs != 0 else np.nan,
        "nse": nse,
        "r2": r2,
        "bias": float(np.mean(residual)),
    }


def _write_metrics(comparison: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    rows = []
    for keys, group in comparison.groupby(["season", "variable"], sort=False):
        rows.append({"season": keys[0], "variable": keys[1], **_metrics(group)})
    for variable, group in comparison.groupby("variable", sort=False):
        rows.append({"season": "ALL", "variable": variable, **_metrics(group)})
    result = pd.DataFrame(rows)
    result.to_csv(out_dir / "diagnostic_metrics_by_season_variable.csv", index=False)
    treatment_rows = []
    for keys, group in comparison.groupby(
        ["season", "variable", "treatment"], sort=False
    ):
        treatment_rows.append(
            {
                "season": keys[0],
                "variable": keys[1],
                "treatment": keys[2],
                **_metrics(group),
            }
        )
    pd.DataFrame(treatment_rows).to_csv(
        out_dir / "diagnostic_metrics_by_season_variable_treatment.csv", index=False
    )
    return result


def _style_axis(ax: plt.Axes) -> None:
    ax.grid(True, color="#E7E7E7", linewidth=0.6)
    ax.spines[["top", "right"]].set_visible(False)


def _plot_scatter(comparison: pd.DataFrame, metrics: pd.DataFrame, out_dir: Path) -> Path:
    variables = [
        variable
        for variable in ("DRY_CUM", "DRY_INC", "LAID", "LWAD", "SWAD", "CHTD", "LAIX", "ADAP")
        if variable in set(comparison["variable"])
    ]
    fig, axes = plt.subplots(2, 4, figsize=(14, 7.2), dpi=180)
    for ax, variable in zip(axes.flat, variables):
        frame = comparison[comparison["variable"] == variable]
        for season, color in SEASON_COLORS.items():
            part = frame[frame["season"] == season]
            ax.scatter(
                part["observed"], part["simulated"], s=18, alpha=0.72,
                color=color, label=season, edgecolor="white", linewidth=0.25,
            )
        lo = float(min(frame["observed"].min(), frame["simulated"].min()))
        hi = float(max(frame["observed"].max(), frame["simulated"].max()))
        pad = max((hi - lo) * 0.05, 1e-6)
        ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#333333", lw=0.8)
        ax.set_xlim(lo - pad, hi + pad)
        ax.set_ylim(lo - pad, hi + pad)
        all_metric = metrics[
            (metrics["season"] == "ALL") & (metrics["variable"] == variable)
        ].iloc[0]
        ax.text(
            0.03, 0.97,
            f"n={int(all_metric['n'])}\nRRMSE={all_metric['rrmse_pct']:.1f}%\n"
            f"NSE={all_metric['nse']:.2f}\nR²={all_metric['r2']:.2f}",
            transform=ax.transAxes, ha="left", va="top", fontsize=8,
            bbox={"facecolor": "white", "alpha": 0.78, "edgecolor": "none"},
        )
        ax.set_title(LABELS.get(variable, variable))
        ax.set_xlabel("Observed")
        ax.set_ylabel("Simulated")
        _style_axis(ax)
    for ax in axes.flat[len(variables):]:
        ax.set_visible(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.955),
        ncol=3, frameon=False,
    )
    fig.suptitle("Best member: observed vs simulated (original scale)", y=0.995, fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    path = out_dir / "diagnostic_observed_vs_simulated_major_variables.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_residuals(comparison: pd.DataFrame, out_dir: Path) -> Path:
    variables = [
        variable
        for variable in ("DRY_CUM", "DRY_INC", "LAID", "LWAD", "SWAD", "CHTD", "LAIX", "ADAP")
        if variable in set(comparison["variable"])
    ]
    fig, axes = plt.subplots(2, 4, figsize=(14, 7.2), dpi=180)
    for ax, variable in zip(axes.flat, variables):
        frame = comparison[comparison["variable"] == variable].copy()
        frame["residual"] = frame["simulated"] - frame["observed"]
        for season, color in SEASON_COLORS.items():
            part = frame[frame["season"] == season]
            ax.scatter(
                part["observed"], part["residual"], s=18, alpha=0.72,
                color=color, label=season, edgecolor="white", linewidth=0.25,
            )
        ax.axhline(0, linestyle="--", color="#333333", lw=0.8)
        ax.set_title(LABELS.get(variable, variable))
        ax.set_xlabel("Observed")
        ax.set_ylabel("Residual (simulated − observed)")
        _style_axis(ax)
    for ax in axes.flat[len(variables):]:
        ax.set_visible(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.955),
        ncol=3, frameon=False,
    )
    fig.suptitle("Best member residual diagnostics (original scale)", y=0.995, fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.91))
    path = out_dir / "diagnostic_residuals_major_variables.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def _facet_dynamics(
    comparison: pd.DataFrame,
    trajectory: pd.DataFrame,
    *,
    season: dict,
    variable: str,
    title: str,
    ylabel: str,
    out_path: Path,
) -> None:
    sid = season["season_id"]
    treatments = season["treatments"]
    ncols = 5 if len(treatments) > 8 else 4
    nrows = int(math.ceil(len(treatments) / ncols))
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(3.0 * ncols, 2.6 * nrows),
        dpi=180,
        squeeze=False,
        sharey=variable == "DRY_CUM",
    )
    sim_var = "DRY_CUM" if variable == "DRY_CUM" else variable
    plotted_values: list[float] = []
    for ax, tn in zip(axes.flat, treatments):
        sim = trajectory[
            (trajectory["season"] == sid)
            & (trajectory["variable"] == sim_var)
            & (trajectory["treatment"].astype(str) == str(tn))
        ].sort_values("time")
        obs = comparison[
            (comparison["season"] == sid)
            & (comparison["variable"] == variable)
            & (comparison["treatment"].astype(str) == str(tn))
        ].sort_values("time")
        obs_time = obs["time"].copy()
        missing_dap = obs["dap"].isna() & obs["date_code"].notna()
        if missing_dap.any() and not sim.empty:
            planting_rows = sim.loc[sim["time"] == sim["time"].min(), ["date_code", "time"]]
            if not planting_rows.empty:
                planting_code = int(planting_rows.iloc[0]["date_code"])
                planting_dap = float(planting_rows.iloc[0]["time"])

                def calendar_dap(date_code: float) -> float:
                    def decode(code: int) -> dt.date:
                        yy, doy = divmod(code, 1000)
                        year = 2000 + yy if yy < 70 else 1900 + yy
                        return dt.date(year, 1, 1) + dt.timedelta(days=doy - 1)

                    return planting_dap + (
                        decode(int(date_code)) - decode(planting_code)
                    ).days

                obs_time.loc[missing_dap] = obs.loc[missing_dap, "date_code"].map(
                    calendar_dap
                )
        ax.plot(sim["time"], sim["simulated"], color=LINE_COLOR, lw=1.35, label="DSSAT")
        ax.scatter(
            obs_time, obs["observed"], color=OBS_COLOR, s=25, zorder=3,
            edgecolor="white", linewidth=0.35, label="Observed",
        )
        plotted_values.extend(sim["simulated"].dropna().astype(float).tolist())
        plotted_values.extend(obs["observed"].dropna().astype(float).tolist())
        ax.set_title(f"TN{tn}")
        ax.set_xlabel("DAP")
        ax.set_ylabel(ylabel)
        _style_axis(ax)
    if variable == "DRY_CUM" and plotted_values:
        upper = max(plotted_values)
        upper = max(upper * 1.05, 1.0)
        for ax in axes.flat[: len(treatments)]:
            ax.set_ylim(0.0, upper)
    for ax in axes.flat[len(treatments):]:
        ax.set_visible(False)
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.94),
        ncol=2, frameon=False,
    )
    fig.suptitle(f"{sid}: {title}", y=0.995, fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.89))
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def _write_manifest(
    out_dir: Path, args: argparse.Namespace, figures: list[Path], seasons: list[dict]
) -> None:
    payload = {
        "artifact_type": "run_diagnostics",
        "source_calibration": str(args.run_dir.resolve()),
        "source_ensemble": str(args.ensemble.resolve()),
        "best_member": str(args.member),
        "parameter_scope": "54 shared parameters; no 25FA offsets",
        "season_bundles": seasons,
        "residual_definition": "simulated - observed",
        "figures": [path.name for path in figures],
        "limitations": [
            "25FA is an external-season diagnostic for the spring-calibrated parameter vector.",
            "Python diagnostic figures are not publication Fig/FigS outputs.",
        ],
    }
    (out_dir / "diagnostic_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--ensemble", type=Path, required=True)
    parser.add_argument("--member", default="59")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--reuse-rerun", action="store_true")
    args = parser.parse_args()
    args.run_dir = args.run_dir.resolve()
    args.ensemble = args.ensemble.resolve()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    seasons = [dict(season) for season in SEASONS]
    autumn_bundle = _prepare_autumn_bundle(out_dir)
    seasons[1]["bundle_path"] = str(autumn_bundle.resolve())
    seasons[1]["bundle_manifest_sha256"] = _sha256(
        autumn_bundle / "input_manifest.json"
    )
    param_path = out_dir / f"best_member_{args.member}_parameters.csv"
    design_path = out_dir / "diagnostic_three_season_design.json"
    _export_member(args.ensemble, args.member, param_path)
    _write_design(design_path, seasons)

    status_path = out_dir / "multiseason_run_status.json"
    if not (args.reuse_rerun and status_path.is_file()):
        command = [
            sys.executable,
            str(ROOT / "src" / "calibration" / "run_multiseason.py"),
            "--design",
            str(design_path),
            "--param-csv",
            str(param_path),
            "--prefix",
            "diagnostic_best59_three_season",
        ]
        subprocess.run(command, cwd=out_dir, check=True)

    comparison, trajectory = _collect(
        out_dir, "diagnostic_best59_three_season", seasons
    )
    comparison.to_csv(out_dir / "diagnostic_comparison_original_scale.csv", index=False)
    trajectory.to_csv(out_dir / "diagnostic_simulation_trajectory.csv", index=False)
    metrics = _write_metrics(comparison, out_dir)
    figures = [
        _plot_scatter(comparison, metrics, out_dir),
        _plot_residuals(comparison, out_dir),
    ]
    for season in seasons:
        sid = season["season_id"]
        yield_path = out_dir / f"diagnostic_{sid.lower()}_cumulative_dry_yield_dynamics.png"
        lai_path = out_dir / f"diagnostic_{sid.lower()}_lai_dynamics.png"
        _facet_dynamics(
            comparison,
            trajectory,
            season=season,
            variable="DRY_CUM",
            title="cumulative dry yield",
            ylabel="kg ha⁻¹",
            out_path=yield_path,
        )
        _facet_dynamics(
            comparison,
            trajectory,
            season=season,
            variable="LAID",
            title="leaf area development",
            ylabel="LAI (m² m⁻²)",
            out_path=lai_path,
        )
        figures.extend([yield_path, lai_path])
    _write_manifest(out_dir, args, figures, seasons)
    print(metrics.to_string(index=False))
    print(f"\nDiagnostics written to: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
