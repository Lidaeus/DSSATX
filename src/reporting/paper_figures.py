"""Generate traceable, publication-oriented core figures.

Historical outputs are supported only through an explicit demo flag. Future
pipelines should write the tidy comparison contract defined in figure_data.py.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

from src.reporting.figure_data import (
    adapt_legacy_comparison_outputs,
    performance_metrics,
    read_comparison_table,
    read_phi_ensemble,
)
from src.reporting.figure_style import (
    load_figure_profile,
    mm_to_inches,
    panel_label,
    publication_style,
    save_figure,
    sha256_file,
)


def _letters() -> Iterable[str]:
    for code in range(ord("a"), ord("z") + 1):
        yield chr(code)


def _clean_axis(ax) -> None:
    ax.tick_params(top=False, right=False)
    ax.margins(x=0.03, y=0.06)


def _demo_note(fig, enabled: bool) -> None:
    if enabled:
        fig.text(
            0.995,
            0.002,
            "Legacy data — layout demo only",
            ha="right",
            va="bottom",
            color="#666666",
            fontsize=5,
        )


def _role_style(role: str, palette: Mapping[str, str]) -> dict[str, Any]:
    role = str(role).lower()
    if role == "validation":
        return {"label": "Validation", "color": palette["validation"], "marker": "^", "face": "none"}
    if role == "calibration":
        return {"label": "Calibration", "color": palette["calibration"], "marker": "o", "face": palette["calibration"]}
    return {"label": "Legacy unsplit", "color": palette["neutral"], "marker": "o", "face": "none"}


def _metric_annotation_position(subset: pd.DataFrame, lower: float, upper: float) -> tuple[float, float, str]:
    """Choose the less occupied right-hand corner without hiding dense data."""
    span = max(upper - lower, 1e-12)
    x = (subset["observed"].to_numpy(dtype=float) - lower) / span
    y = (subset["simulated"].to_numpy(dtype=float) - lower) / span
    bottom_count = int(np.sum((x > 0.52) & (y < 0.42)))
    top_count = int(np.sum((x > 0.52) & (y > 0.58)))
    if top_count < bottom_count:
        return 0.97, 0.96, "top"
    return 0.97, 0.04, "bottom"


def plot_model_performance(
    comparison: pd.DataFrame,
    variables: list[str],
    output_base: Path,
    profile: Mapping[str, Any],
    *,
    demo: bool,
) -> tuple[list[Path], pd.DataFrame]:
    available = [variable for variable in variables if variable in set(comparison["variable"])]
    if not available:
        raise ValueError("None of the requested performance variables are available")
    ncols = min(2, len(available))
    nrows = int(math.ceil(len(available) / ncols))
    width = mm_to_inches(float(profile["double_column_width_mm"]))
    height = min(mm_to_inches(float(profile["max_height_mm"])), 2.35 * nrows)
    palette = profile["palette"]
    with publication_style(profile):
        fig, axes = plt.subplots(nrows, ncols, figsize=(width, height), squeeze=False)
        letters = _letters()
        metrics_rows: list[dict[str, Any]] = []
        for ax, variable in zip(axes.flat, available):
            subset = comparison[comparison["variable"] == variable].copy()
            inferential_roles = subset["dataset_role"].isin(["calibration", "validation"])
            if inferential_roles.any():
                subset = subset.loc[inferential_roles].copy()
            for role, role_frame in subset.groupby("dataset_role", sort=False):
                style = _role_style(role, palette)
                ax.scatter(
                    role_frame["observed"],
                    role_frame["simulated"],
                    s=14,
                    marker=style["marker"],
                    facecolors=style["face"],
                    edgecolors=style["color"],
                    linewidths=0.65,
                    alpha=0.88,
                    label=style["label"],
                )
            values = np.r_[subset["observed"].to_numpy(), subset["simulated"].to_numpy()]
            lower = min(0.0, float(np.nanmin(values)))
            upper = float(np.nanmax(values))
            padding = 0.05 * (upper - lower) if upper > lower else 1.0
            lower -= padding
            upper += padding
            ax.plot([lower, upper], [lower, upper], color="#333333", linewidth=0.65, zorder=0)
            ax.set_xlim(lower, upper)
            ax.set_ylim(lower, upper)
            ax.set_aspect("equal", adjustable="box")
            unit = str(subset["unit"].iloc[0])
            label = str(subset["variable_label"].iloc[0])
            suffix = f" ({unit})" if unit else ""
            ax.set_xlabel(f"Observed{suffix}")
            ax.set_ylabel(f"Simulated{suffix}")
            ax.text(0.03, 0.96, label, transform=ax.transAxes, ha="left", va="top", fontweight="bold")
            metrics = performance_metrics(subset)
            metrics_rows.append({"variable": variable, **metrics})
            text_x, text_y, vertical = _metric_annotation_position(subset, lower, upper)
            ax.text(
                text_x,
                text_y,
                f"n = {metrics['n']}\nRMSE = {metrics['rmse']:.3g}\nBias = {metrics['bias']:.3g}",
                transform=ax.transAxes,
                ha="right",
                va=vertical,
                color="#333333",
                linespacing=1.25,
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.88, "pad": 1.2},
            )
            panel_label(ax, next(letters), profile)
            _clean_axis(ax)
        for ax in axes.flat[len(available) :]:
            ax.set_visible(False)
        handles, labels = [], []
        for current_ax in axes.flat[: len(available)]:
            current_handles, current_labels = current_ax.get_legend_handles_labels()
            for handle, label in zip(current_handles, current_labels):
                if label not in labels:
                    handles.append(handle)
                    labels.append(label)
        if len(handles) > 1:
            fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 1.01), ncol=len(handles), frameon=False)
        _demo_note(fig, demo)
        fig.subplots_adjust(left=0.09, right=0.99, bottom=0.09, top=0.94, wspace=0.28, hspace=0.34)
        paths = save_figure(fig, output_base, profile, metadata={"Title": "Observed versus simulated performance"})
        plt.close(fig)
    return paths, pd.DataFrame(metrics_rows)


def plot_selected_dynamics(
    comparison: pd.DataFrame,
    variables: list[str],
    treatments: list[str],
    output_base: Path,
    profile: Mapping[str, Any],
    *,
    demo: bool,
) -> tuple[list[Path], pd.DataFrame]:
    available_variables = [item for item in variables if item in set(comparison["variable"])]
    available_treatments = [item for item in treatments if item in set(comparison["treatment"].astype(str))]
    if not available_variables or not available_treatments:
        raise ValueError("Requested dynamics variables or treatments are unavailable")
    nrows = len(available_variables)
    ncols = len(available_treatments)
    width = mm_to_inches(float(profile["double_column_width_mm"]))
    height = min(mm_to_inches(float(profile["max_height_mm"])), max(2.4, 1.75 * nrows))
    palette = profile["palette"]
    with publication_style(profile):
        fig, axes = plt.subplots(nrows, ncols, figsize=(width, height), squeeze=False, sharex=False)
        letters = _letters()
        exported: list[pd.DataFrame] = []
        for row_index, variable in enumerate(available_variables):
            for col_index, treatment in enumerate(available_treatments):
                ax = axes[row_index, col_index]
                subset = comparison[
                    (comparison["variable"] == variable)
                    & (comparison["treatment"].astype(str) == str(treatment))
                ].sort_values("time")
                if subset.empty:
                    ax.set_visible(False)
                    continue
                exported.append(subset)
                ax.plot(
                    subset["time"],
                    subset["simulated"],
                    color=palette["simulated"],
                    linestyle="-",
                    label="Simulated",
                    zorder=2,
                )
                ax.scatter(
                    subset["time"],
                    subset["observed"],
                    s=13,
                    marker="o",
                    facecolors="white",
                    edgecolors=palette["observed"],
                    linewidths=0.7,
                    label="Observed",
                    zorder=3,
                )
                unit = str(subset["unit"].iloc[0])
                if col_index == 0:
                    label = str(subset["variable_label"].iloc[0])
                    ax.set_ylabel(f"{label}\n({unit})" if unit else label)
                if row_index == 0:
                    ax.text(0.5, 1.03, f"Treatment {treatment}", transform=ax.transAxes, ha="center", va="bottom")
                if row_index == nrows - 1:
                    ax.set_xlabel(str(subset["time_label"].iloc[0]))
                panel_label(ax, next(letters), profile)
                _clean_axis(ax)
        handles, labels = [], []
        for ax in axes.flat:
            if ax.get_visible():
                handles, labels = ax.get_legend_handles_labels()
                if handles:
                    break
        if handles:
            fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 1.01), ncol=2, frameon=False)
        _demo_note(fig, demo)
        fig.subplots_adjust(left=0.10, right=0.99, bottom=0.12, top=0.90, wspace=0.28, hspace=0.34)
        paths = save_figure(fig, output_base, profile, metadata={"Title": "Selected treatment dynamics"})
        plt.close(fig)
    return paths, pd.concat(exported, ignore_index=True)


def plot_phi_convergence(
    phi: pd.DataFrame,
    output_base: Path,
    profile: Mapping[str, Any],
    *,
    demo: bool,
) -> tuple[list[Path], pd.DataFrame]:
    summary = (
        phi.groupby("iteration")["phi"]
        .agg(
            n="count",
            q05=lambda values: values.quantile(0.05),
            q25=lambda values: values.quantile(0.25),
            median="median",
            q75=lambda values: values.quantile(0.75),
            q95=lambda values: values.quantile(0.95),
        )
        .reset_index()
    )
    width = mm_to_inches(float(profile["column_width_mm"]))
    palette = profile["palette"]
    with publication_style(profile):
        fig, ax = plt.subplots(figsize=(width, width * 0.72))
        x = summary["iteration"].to_numpy(dtype=float)
        ax.fill_between(x, summary["q05"], summary["q95"], color=palette["uncertainty"], alpha=0.20, linewidth=0, label="5–95%")
        ax.fill_between(x, summary["q25"], summary["q75"], color=palette["uncertainty"], alpha=0.42, linewidth=0, label="IQR")
        ax.plot(x, summary["median"], color=palette["simulated"], marker="o", label="Median")
        ax.set_xlabel("IES iteration")
        ax.set_ylabel("Measurement Φ")
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        if float(summary["q95"].max()) / max(float(summary["q05"].min()), 1e-12) >= 100:
            ax.set_yscale("log")
        ax.legend(frameon=False, ncol=3, loc="best")
        _clean_axis(ax)
        _demo_note(fig, demo)
        fig.subplots_adjust(left=0.16, right=0.98, bottom=0.16, top=0.96)
        paths = save_figure(fig, output_base, profile, metadata={"Title": "IES Phi convergence"})
        plt.close(fig)
    return paths, summary


def _write_source_data(path: Path, frame: pd.DataFrame) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def _write_manifest(
    path: Path,
    *,
    run_id: str,
    profile: Mapping[str, Any],
    demo: bool,
    artifacts: list[Path],
    sources: list[Path],
) -> Path:
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profile_id": profile["profile_id"],
        "data_status": "legacy_layout_demo" if demo else "science_validated",
        "artifacts": [
            {"path": str(item.resolve()), "sha256": sha256_file(item)}
            for item in artifacts
            if item.is_file()
        ],
        "sources": [
            {"path": str(item.resolve()), "sha256": sha256_file(item)}
            for item in sources
            if item.is_file()
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _csv_list(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate traceable publication core figures")
    parser.add_argument("--prefix", required=True, help="Run ID or historical file prefix")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--comparison-csv", help="Canonical tidy comparison CSV")
    source.add_argument("--legacy-results-dir", help="Directory containing historical wide comparison CSVs")
    parser.add_argument("--phi-csv", default=None, help="PEST++ *.phi.actual.csv")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--formats", default=None, help="Override profile formats, comma separated")
    parser.add_argument("--variables", default="LAID,LWAD,SWAD,FRESH_INC")
    parser.add_argument("--timeseries-variables", default="LAID,FRESH_INC")
    parser.add_argument("--treatments", default="2,13")
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args(argv)

    profile = load_figure_profile(args.profile)
    if args.formats:
        profile["formats"] = _csv_list(args.formats)
    sources: list[Path] = []
    if args.comparison_csv:
        comparison_path = Path(args.comparison_csv)
        comparison = read_comparison_table(comparison_path)
        sources.append(comparison_path)
    else:
        results_dir = Path(args.legacy_results_dir)
        comparison = adapt_legacy_comparison_outputs(results_dir, args.prefix)
        sources.extend(Path(item) for item in comparison["source_file"].unique())

    statuses = set(comparison["data_status"].astype(str))
    demo = statuses != {"science_validated"}
    if demo and not args.allow_unvalidated_demo:
        parser.error(
            "Input data are not science_validated; pass --allow-unvalidated-demo to create "
            "clearly labelled layout previews"
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "demo" if demo else "figure"
    artifacts: list[Path] = []

    performance_paths, metrics = plot_model_performance(
        comparison,
        _csv_list(args.variables),
        out_dir / f"{stem}_model_performance",
        profile,
        demo=demo,
    )
    artifacts.extend(performance_paths)
    artifacts.append(_write_source_data(out_dir / f"{stem}_model_performance.source.csv", comparison))
    artifacts.append(_write_source_data(out_dir / f"{stem}_model_performance.metrics.csv", metrics))

    dynamics_paths, dynamics_data = plot_selected_dynamics(
        comparison,
        _csv_list(args.timeseries_variables),
        _csv_list(args.treatments),
        out_dir / f"{stem}_selected_dynamics",
        profile,
        demo=demo,
    )
    artifacts.extend(dynamics_paths)
    artifacts.append(_write_source_data(out_dir / f"{stem}_selected_dynamics.source.csv", dynamics_data))

    if args.phi_csv:
        phi_path = Path(args.phi_csv)
        phi = read_phi_ensemble(phi_path)
        sources.append(phi_path)
        phi_paths, phi_summary = plot_phi_convergence(
            phi, out_dir / f"{stem}_phi_convergence", profile, demo=demo
        )
        artifacts.extend(phi_paths)
        artifacts.append(_write_source_data(out_dir / f"{stem}_phi_convergence.source.csv", phi))
        artifacts.append(_write_source_data(out_dir / f"{stem}_phi_convergence.summary.csv", phi_summary))

    manifest = _write_manifest(
        out_dir / "figure_manifest.json",
        run_id=args.prefix,
        profile=profile,
        demo=demo,
        artifacts=artifacts,
        sources=sources,
    )
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
