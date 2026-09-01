"""Run the 26SP best member through all three experiments and render diagnostics.

The calibration run used only 26SP.  This entry point replays its best shared
genetic vector on the current 25SP/25FA/26SP actual-trial bundles with the
custom N-response DSSAT build, then delegates the chart rendering to the
canonical Python run-diagnostics renderer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
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

from src.reporting.analyze_results import (
    _read_tmt_process_obs,
    deterministic_harvest_compare,
    deterministic_process_compare,
)

BEST_RUN = ROOT / "workspace/runs/eggplant_26sp_w1w2_n012_postprecal_allgenetic_20260804"
BEST_CASE = "eggplant_26sp_w1w2_n012_postprecal_allgenetic_20260804"
CUSTOM_EXE = ROOT / "windows/windows_nresp_20260803/dscsm048_nresp.exe"
CUSTOM_SPE = ROOT / "windows/windows_nresp_20260803/Genotype/TMGRO048.SPE"
DSSAT_TOMATO = Path(r"C:\DSSAT48\TOMATO")

SEASONS = [
    {
        "season_id": "25SP",
        "experiment_code": "XXQL2501",
        "bundle_path": "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729",
        "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
    },
    {
        "season_id": "25FA",
        "experiment_code": "XXQL2502",
        "bundle_path": "data/user/experiments/xxql2502_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "treatments": list(range(1, 13)),
    },
    {
        "season_id": "26SP",
        "experiment_code": "XXQL2601",
        "bundle_path": "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729",
        "treatments": list(range(1, 13)),
    },
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _best_member(run_dir: Path, case: str) -> str:
    phi = pd.read_csv(run_dir / f"{case}.phi.actual.csv")
    final = phi.iloc[-1]
    slots = pd.to_numeric(final.iloc[6:], errors="coerce")
    if slots.empty or not np.isfinite(slots.to_numpy(float)).any():
        raise RuntimeError("final phi row has no finite realization values")
    return str(slots.idxmin())


def _export_member(run_dir: Path, case: str, member: str, out_csv: Path) -> int:
    source = run_dir / f"{case}.4.par.csv"
    frame = pd.read_csv(source)
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    if real_col is None:
        raise ValueError(f"{source} has no realization column")
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(str(member))
    if int(mask.sum()) != 1:
        raise ValueError(f"best member {member} occurs {int(mask.sum())} times in {source}")
    row = frame.loc[mask].iloc[0]
    records = []
    for column in frame.columns:
        if column == real_col:
            continue
        value = float(row[column])
        if not math.isfinite(value):
            raise ValueError(f"best member {member}: non-finite {column}={value}")
        records.append({"name": str(column).upper(), "value": value})
    pd.DataFrame(records).to_csv(out_csv, index=False)
    return len(records)


def _write_design(out_dir: Path, case: str, member: str) -> Path:
    seasons = []
    for item in SEASONS:
        bundle = ROOT / item["bundle_path"]
        seasons.append({
            **item,
            "role": "calibration",
            "bundle_manifest_sha256": _sha256(bundle / "input_manifest.json"),
        })
    payload = {
        "schema_version": 1,
        "design_id": f"{case}_best{member}_three_season_custom_diagnostics_20260804",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "shared genetic vector from 26SP post-precalibration best member",
        "observation_policy": "configs/runs/e02_plantn_chpdtlog_noadap_no_nresponse_v1.csv",
        "group_policy": "configs/runs/t10_plantn_harvestdry250_no_nresponse_v1.csv",
        "purpose": "three-season deterministic diagnostics only; no re-calibration",
        "custom_dssat_executable": str(CUSTOM_EXE.resolve()),
        "custom_spe": str(CUSTOM_SPE.resolve()),
        "seasons": seasons,
    }
    path = out_dir / "design.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _set_env() -> None:
    os.environ["DSSAT_CUSTOM_EXE"] = str(CUSTOM_EXE.resolve())
    os.environ["DSSAT_SPE_BASE"] = str(CUSTOM_SPE.resolve())
    os.environ["DSSAT_SOIL_BASE"] = str((ROOT / SEASONS[0]["bundle_path"] / "SOIL.SOL").resolve())
    os.environ["DSSAT_BATCH_FILEX_ROOT"] = str(DSSAT_TOMATO)
    os.environ["DSSAT_KEEP_RUNS"] = "1"
    os.environ["DSSAT_DISABLE_SOIL_INJECTION"] = "1"
    os.environ["DSSAT_FILEX_MAP"] = json.dumps({
        f"{s['experiment_code']}.TMX": str((ROOT / s["bundle_path"] / f"{s['experiment_code']}.TMX").resolve())
        for s in SEASONS
    })


def _backup_filex(out_dir: Path) -> Path:
    backup = out_dir / "dssat_tomato_backup"
    backup.mkdir(parents=True, exist_ok=True)
    for season in SEASONS:
        name = f"{season['experiment_code']}.TMX"
        source = DSSAT_TOMATO / name
        if source.is_file():
            shutil.copy2(source, backup / name)
    return backup


def _restore_filex(backup: Path) -> None:
    DSSAT_TOMATO.mkdir(parents=True, exist_ok=True)
    backed = {p.name for p in backup.glob("*.TMX")}
    for season in SEASONS:
        name = f"{season['experiment_code']}.TMX"
        target = DSSAT_TOMATO / name
        source = backup / name
        if source.is_file():
            shutil.copy2(source, target)
        elif name not in backed and target.is_file():
            target.unlink()


def _run(command: list[str], cwd: Path) -> None:
    print("+ " + subprocess.list2cmdline([str(x) for x in command]), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _run_comparisons(det_root: Path) -> None:
    for season in SEASONS:
        sid = season["season_id"]
        season_dir = det_root / "_seasons" / sid
        # The runtime batch intentionally points to C:\\DSSAT48\\TOMATO so the
        # custom executable can resolve FileX.  For post-processing, point a
        # small analysis-only batch at the localized FileX so analyze_results
        # also finds the matching local TMT observations (and never falls back
        # to a stale global experiment file).
        filex = next(season_dir.glob("*.TMX"))
        batch = season_dir / "analysis_batch.v48"
        batch.write_text(
            "\n".join(
                f"{filex.resolve()} {int(tn)} 1 0 0 0"
                for tn in season["treatments"]
            )
            + "\n",
            encoding="utf-8",
        )
        # Include plant height in the process comparison; the CLI default only
        # contains LAI and leaf/stem mass.
        deterministic_process_compare(
            sid, str(batch),
            var_names=["L#SD", "LAID", "LWAD", "SWAD", "CHTD"],
            run_dir=str(season_dir),
        )
        deterministic_harvest_compare(sid, str(batch), run_dir=str(season_dir))


def _organ_n_pairs(det_root: Path) -> pd.DataFrame:
    """Read SNAMS/LNAMS from PestTmtGrow and pair them to FileT observations."""
    pattern = re.compile(
        r"RUN\s+(\d+)\s+TN\s+(\d+)\s+DATE\s+(\d+).*?"
        r"@SNAMS@\s+([-+0-9.]+).*?@LNAMS@\s+([-+0-9.]+)"
    )
    rows = []
    for season in SEASONS:
        sid = season["season_id"]
        sdir = det_root / "_seasons" / sid
        tmt = ROOT / season["bundle_path"] / f"{season['experiment_code']}.TMT"
        observed = _read_tmt_process_obs(str(tmt), ["SNAM", "LNAM"])
        out = sdir / "PestTmtGrow.OUT"
        if not out.is_file():
            continue
        for line in out.read_text(errors="ignore").splitlines():
            match = pattern.search(line)
            if not match:
                continue
            run, tn, date = int(match.group(1)), int(match.group(2)), int(match.group(3))
            point = next((p for p in observed.get(tn, []) if int(p["DATE"]) == date), None)
            if point is None:
                continue
            for variable, obs_key, group_index in (("SNAM", "OBS_SNAM", 4), ("LNAM", "OBS_LNAM", 5)):
                try:
                    obs = float(point.get(obs_key, -99))
                    sim = float(match.group(group_index))
                except (TypeError, ValueError):
                    continue
                if not np.isfinite(obs) or not np.isfinite(sim) or obs == -99 or sim <= -98:
                    continue
                rows.append({"season": sid, "kind": "organ_n", "variable": variable,
                             "RUN": run, "TN": tn, "DATE": date,
                             "observed": obs, "simulated": sim})
    result = pd.DataFrame(rows)
    result.to_csv(det_root / "organ_n_compare.csv", index=False)
    return result


def _metric_rows(det_root: Path) -> pd.DataFrame:
    rows = []
    for season in SEASONS:
        sid = season["season_id"]
        sdir = det_root / "_seasons" / sid
        for kind, filename in (("process", f"{sid}_deterministic_process_compare.csv"),
                               ("harvest", f"{sid}_deterministic_harvest_compare.csv")):
            path = sdir / filename
            if not path.is_file() or path.stat().st_size <= 2:
                continue
            frame = pd.read_csv(path)
            for column in frame.columns:
                if not str(column).startswith("OBS_"):
                    continue
                variable = str(column)[4:]
                sim_col = f"SIM_{variable}"
                if sim_col not in frame:
                    continue
                obs = pd.to_numeric(frame[column], errors="coerce")
                sim = pd.to_numeric(frame[sim_col], errors="coerce")
                ok = obs.notna() & sim.notna() & (obs != -99) & (sim != -99)
                if not bool(ok.any()):
                    continue
                y = obs.loc[ok].to_numpy(float)
                p = sim.loc[ok].to_numpy(float)
                e = p - y
                den = float(np.sum((y - y.mean()) ** 2))
                dden = float(np.sum((np.abs(p - y.mean()) + np.abs(y - y.mean())) ** 2))
                rows.append({
                    "season": sid, "kind": kind, "variable": variable, "n": int(ok.sum()),
                    "rmse": float(np.sqrt(np.mean(e ** 2))),
                    "rrmse_pct": float(100 * np.sqrt(np.mean(e ** 2)) / np.mean(np.abs(y))) if np.mean(np.abs(y)) else np.nan,
                    "mae": float(np.mean(np.abs(e))), "bias": float(e.mean()),
                    "nse": float(1 - np.sum(e ** 2) / den) if den > 0 else np.nan,
                    "d_index": float(1 - np.sum(e ** 2) / dden) if dden > 0 else np.nan,
                    "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0 else np.nan,
                })
    organ_n = pd.read_csv(det_root / "organ_n_compare.csv") if (det_root / "organ_n_compare.csv").is_file() else pd.DataFrame()
    for (season, variable), frame in organ_n.groupby(["season", "variable"], sort=False) if not organ_n.empty else []:
        y = frame["observed"].to_numpy(float)
        p = frame["simulated"].to_numpy(float)
        e = p - y
        den = float(np.sum((y - y.mean()) ** 2))
        dden = float(np.sum((np.abs(p - y.mean()) + np.abs(y - y.mean())) ** 2))
        rows.append({
            "season": season, "kind": "organ_n", "variable": variable, "n": len(frame),
            "rmse": float(np.sqrt(np.mean(e ** 2))),
            "rrmse_pct": float(100 * np.sqrt(np.mean(e ** 2)) / np.mean(np.abs(y))) if np.mean(np.abs(y)) else np.nan,
            "mae": float(np.mean(np.abs(e))), "bias": float(e.mean()),
            "nse": float(1 - np.sum(e ** 2) / den) if den > 0 else np.nan,
            "d_index": float(1 - np.sum(e ** 2) / dden) if dden > 0 else np.nan,
            "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0 else np.nan,
        })
    result = pd.DataFrame(rows)
    result.to_csv(det_root / "metrics_by_season_variable.csv", index=False)
    return result


def _plot_metrics(metrics: pd.DataFrame, out_root: Path) -> list[Path]:
    plots = []
    present = metrics["variable"].drop_duplicates().tolist()
    order = [v for v in ["LAID", "LWAD", "SWAD", "DRY_CUM", "DRY_INC", "CHTD", "SNAM", "LNAM", "LAIX", "ADAP"] if v in present]
    order += [v for v in present if v not in order]
    for metric, label in (("rrmse_pct", "RRMSE (%)"), ("r2", "R²"), ("nse", "NSE"), ("d_index", "d-index")):
        table = metrics.pivot(index="variable", columns="season", values=metric).reindex(order)
        table = table.reindex(columns=["25SP", "25FA", "26SP"])
        fig, ax = plt.subplots(figsize=(8.6, max(3.8, 0.42 * len(order) + 1.4)), dpi=180)
        image = ax.imshow(table.to_numpy(float), aspect="auto", cmap="viridis")
        ax.set_xticks(range(len(table.columns)), table.columns)
        ax.set_yticks(range(len(table.index)), table.index)
        ax.set_xlabel("Season")
        ax.set_ylabel("Variable")
        ax.set_title(f"Best-member fit metric: {label}")
        for i in range(table.shape[0]):
            for j in range(table.shape[1]):
                value = table.iloc[i, j]
                if np.isfinite(value):
                    ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=7,
                            color="white" if value < np.nanpercentile(table.to_numpy(float), 55) else "black")
        fig.colorbar(image, ax=ax, label=label)
        fig.tight_layout()
        path = out_root / f"metrics_heatmap_{metric}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        plots.append(path)
    # One compact NRMSE comparison chart gives an immediate season-level view.
    subset = metrics[metrics["variable"].isin(order)].copy()
    fig, ax = plt.subplots(figsize=(10.5, 5.2), dpi=180)
    x = np.arange(len(order))
    width = 0.24
    colors = {"25SP": "#2878B5", "25FA": "#D95F02", "26SP": "#2A9D55"}
    for j, season in enumerate(["25SP", "25FA", "26SP"]):
        vals = subset[subset["season"] == season].set_index("variable")["rrmse_pct"].reindex(order)
        ax.bar(x + (j - 1) * width, vals.to_numpy(float), width, label=season, color=colors[season])
    ax.set_xticks(x, order, rotation=45, ha="right")
    ax.set_ylabel("RRMSE (%)")
    ax.set_title("Best-member RRMSE across three experiments")
    ax.grid(True, axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=3)
    fig.tight_layout()
    path = out_root / "metrics_rrmse_by_season.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    plots.append(path)
    return plots


def _plot_extra_pairs(pairs: pd.DataFrame, out_root: Path) -> list[Path]:
    """Render CHTD and organ-N observed-vs-simulated/residual panels."""
    outputs = []
    if pairs.empty:
        return outputs
    colors = {"25SP": "#2878B5", "25FA": "#D95F02", "26SP": "#2A9D55"}
    for variable, group in pairs.groupby("variable", sort=False):
        fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.2), dpi=180, sharex=True, sharey=True)
        finite = group[["observed", "simulated"]].to_numpy(float)
        lo = float(np.nanmin(finite)); hi = float(np.nanmax(finite)); pad = max((hi - lo) * 0.06, 1e-6)
        for ax, season in zip(axes, ["25SP", "25FA", "26SP"]):
            sub = group[group["season"] == season]
            if sub.empty:
                ax.set_visible(False); continue
            ax.scatter(sub["observed"], sub["simulated"], color=colors[season], s=34, alpha=0.8, edgecolor="white", linewidth=0.3)
            ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#555", lw=0.9)
            ax.set_title(season); ax.set_xlim(lo - pad, hi + pad); ax.set_ylim(lo - pad, hi + pad)
            y = sub["observed"].to_numpy(float); p = sub["simulated"].to_numpy(float); e = p - y
            ax.text(0.04, 0.96, f"n={len(sub)}\nRMSE={np.sqrt(np.mean(e**2)):.3g}\nBias={e.mean():+.3g}", transform=ax.transAxes, va="top", fontsize=8, family="monospace", bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"})
            ax.grid(True, alpha=0.25); ax.spines[["top", "right"]].set_visible(False)
        axes[0].set_ylabel("Simulated"); fig.text(0.5, 0.02, "Observed", ha="center")
        fig.suptitle(f"{variable}: observed vs simulated")
        fig.tight_layout(rect=(0, 0.05, 1, 0.94))
        path = out_root / f"scatter_{variable}.png"; fig.savefig(path, bbox_inches="tight"); plt.close(fig); outputs.append(path)

        fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.2), dpi=180, sharex=True, sharey=True)
        residual = group["simulated"] - group["observed"]
        rmax = max(float(np.nanmax(np.abs(residual))), 1e-6)
        for ax, season in zip(axes, ["25SP", "25FA", "26SP"]):
            sub = group[group["season"] == season]
            if sub.empty:
                ax.set_visible(False); continue
            ax.scatter(sub["observed"], sub["simulated"] - sub["observed"], color=colors[season], s=34, alpha=0.8, edgecolor="white", linewidth=0.3)
            ax.axhline(0, ls="--", color="#555", lw=0.9); ax.set_title(season); ax.set_xlim(lo - pad, hi + pad); ax.set_ylim(-1.15 * rmax, 1.15 * rmax)
            ax.grid(True, alpha=0.25); ax.spines[["top", "right"]].set_visible(False)
        axes[0].set_ylabel("Simulated − observed"); fig.text(0.5, 0.02, "Observed", ha="center")
        fig.suptitle(f"{variable}: residuals (simulated − observed)")
        fig.tight_layout(rect=(0, 0.05, 1, 0.94))
        path = out_root / f"residual_{variable}.png"; fig.savefig(path, bbox_inches="tight"); plt.close(fig); outputs.append(path)
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=BEST_RUN)
    parser.add_argument("--case", default=BEST_CASE)
    parser.add_argument("--member", default=None)
    parser.add_argument("--det-root", type=Path, default=None)
    parser.add_argument("--out-root", type=Path, default=None)
    parser.add_argument("--reuse-rerun", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    member = str(args.member or _best_member(run_dir, args.case))
    det_root = (args.det_root or (ROOT / "workspace/runs" / f"{args.case}_best{member}_three_season_custom")).resolve()
    out_root = (args.out_root or (ROOT / "figures/diagnostics" / det_root.name)).resolve()
    det_root.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)
    design = _write_design(det_root, args.case, member)
    params = det_root / f"best_member_{member}_parameters.csv"
    n_params = _export_member(run_dir, args.case, member, params)

    _set_env()
    backup = _backup_filex(det_root)
    try:
        status = det_root / "multiseason_run_status.json"
        if not (args.reuse_rerun and status.is_file()):
            _run([
                sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                "--design", str(design), "--param-csv", str(params),
                "--prefix", f"best{member}_three_season_custom", "--harvest-var", "CHPDT",
                "--keep-nitrogen-outputs",
            ], det_root)
        _run_comparisons(det_root)
        _organ_n_pairs(det_root)
        metrics = _metric_rows(det_root)
        plotter = ROOT / "tools/calibration/plot_dynamics.py"
        _run([
            sys.executable, str(plotter), "--det-root", str(det_root),
            "--out-root", str(out_root), "--seasons", "25SP,25FA,26SP",
        ], ROOT)
        metric_plots = _plot_metrics(metrics, out_root)
        extra_pairs = pd.read_csv(det_root / "organ_n_compare.csv")
        process_extra = []
        for season in SEASONS:
            path = det_root / "_seasons" / season["season_id"] / f"{season['season_id']}_deterministic_process_compare.csv"
            if path.is_file() and path.stat().st_size > 2:
                frame = pd.read_csv(path)
                for variable in ["CHTD"]:
                    obs_col, sim_col = f"OBS_{variable}", f"SIM_{variable}"
                    if obs_col in frame and sim_col in frame:
                        sub = frame[["TN", "DATE", obs_col, sim_col]].rename(columns={obs_col: "observed", sim_col: "simulated"})
                        sub["season"] = season["season_id"]; sub["variable"] = variable
                        sub = sub[(sub["observed"] != -99) & (sub["simulated"] != -99)]
                        process_extra.append(sub)
        if process_extra:
            extra_pairs = pd.concat([extra_pairs, *process_extra], ignore_index=True)
        metric_plots.extend(_plot_extra_pairs(extra_pairs, out_root))
        manifest = {
            "artifact_type": "run_diagnostics",
            "source_calibration": str(run_dir),
            "best_member": member,
            "parameter_csv": str(params),
            "parameter_count_exported": n_params,
            "custom_dssat_executable": str(CUSTOM_EXE.resolve()),
            "custom_spe": str(CUSTOM_SPE.resolve()),
            "seasons": SEASONS,
            "deterministic_run": str(det_root),
            "output_root": str(out_root),
            "metric_plots": [p.name for p in metric_plots],
            "figures": sorted(str(p.relative_to(out_root)) for p in out_root.rglob("*.png")),
            "metrics_csv": str((det_root / "metrics_by_season_variable.csv").resolve()),
            "organ_n_pairs_csv": str((det_root / "organ_n_compare.csv").resolve()),
            "limitations": [
                "This is a Python run-diagnostics product, not a publication Fig/FigS bundle.",
                "The 26SP calibration bundle has no active organ-N observations; three-season charts only show organ-N where the FileT bundle contains observations.",
                "The canonical W×N dynamics renderer excludes unmapped 25SP TN9 and TN14 from factorial panels; all observations remain in metric CSVs.",
            ],
        }
        (out_root / "diagnostic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"best_member={member}; exported_parameters={n_params}")
        print(metrics.to_string(index=False))
        print(f"Diagnostics written to: {out_root}")
        return 0
    finally:
        _restore_filex(backup)


if __name__ == "__main__":
    raise SystemExit(main())
