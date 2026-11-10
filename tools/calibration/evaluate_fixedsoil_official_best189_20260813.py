"""Two-season diagnostics for fixed-soil joint official calibration (20260813).

Replays best member #189 of the fixed-soil joint official calibration
(e02_v2_fixedsoil_joint_official_25sp26sp_200x5_20260813) on the 25SP+26SP
actual_trial bundles (soil params FIXED, water response included, HARVEST_DRY_TREND
log family active), then renders the full diagnostic figure set:

  * per-season W×N dynamics timeseries + dry-yield increment bars
    (<out>/<season>/, via plot_dynamics.py)
  * cross-season scatter / residual / MSE decomposition
  * metrics heatmaps (RRMSE/R²/NSE/d-index) + RRMSE-by-season bars
  * CHTD + organ-N (SNAM/LNAM) extra pairs
  * response-structure audit + yield-curve source audit

Soil-parameter injection stays ENABLED so the calibrated soil physical params
(SBDM/SLPF/SSKS/SLCL/SLSI) take effect (SLPF fixed at 0.93).

Usage:
    python tools/calibration/evaluate_fixedsoil_official_best189_20260813.py
"""

from __future__ import annotations

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

CASE = "e02_v2_fixedsoil_joint_official_25sp26sp_200x5_20260813"
RUN_DIR = ROOT / "workspace/runs" / CASE
BEST_MEMBER = "189"  # min-Phi realization at final iteration (phi=24666)
SOURCE_ITERATION = 5
BEST_PHI = 24666.0
CALIBRATION_STATE = "completed"
ARTIFACT_TYPE = "two_season_diagnostics_fixedsoil_official_20260813"
EXTRA_LIMITATIONS: list[str] = []
HARVEST_OBJECTIVE = "increment_plus_terminal + HARVEST_DRY_TREND (log)"
SOIL_INJECTION_DESCRIPTION = "enabled (calibrated SBDM/SLPF/SSKS/SLCL/SLSI applied; SLPF fixed 0.93)"
DSSAT_VERSION_DESCRIPTION = "official fixed-soil build"
SOIL_PARAMETER_STATUS = "FIXED (user-approved values, not inverted)"
BUNDLE_NOTE = "actual_trial bundles (same as calibration): v8 25SP / v7 26SP"
PLOT_INCLUDE_ALL_TREATMENTS = False
PLOT_MAPPING_CSV: Path | None = None
EXE = ROOT / "DSCSM048.EXE"
SPE = Path(r"C:\DSSAT48\Genotype\TMGRO048.SPE")
DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"
OBS_REGISTRY = RUN_DIR / f"{CASE}_observation_registry.csv"
FIGTURE = ROOT / "figture"
OUT_ROOT = FIGTURE / "fixedsoil_official_twoseason_20260813_v2"
DET_ROOT = RUN_DIR / "best_member_189_deterministic_20260813"

SEASONS = [
    {"season_id": "25SP", "excode": "XXQL2501",
     "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
     "bundle": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"},
    {"season_id": "26SP", "excode": "XXQL2601",
     "treatments": list(range(1, 13)),
     "bundle": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"},
]
SEASON_IDS = [s["season_id"] for s in SEASONS]
COLORS = {"25SP": "#2878B5", "26SP": "#2A9D55"}


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def _export_member(out_csv: Path) -> int:
    frame = pd.read_csv(RUN_DIR / f"{CASE}.{SOURCE_ITERATION}.par.csv")
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(BEST_MEMBER)
    if int(mask.sum()) != 1:
        raise ValueError(f"best member {BEST_MEMBER} occurs {int(mask.sum())} times")
    row = frame.loc[mask].iloc[0]
    records = []
    for col in frame.columns:
        if col == real_col:
            continue
        v = float(row[col])
        if not math.isfinite(v):
            continue
        records.append({"name": str(col).upper(), "value": v})
    pd.DataFrame(records).to_csv(out_csv, index=False)
    return len(records)


def _write_design(det_root: Path) -> Path:
    payload = {
        "schema_version": 1,
        "design_id": f"{CASE}_best{BEST_MEMBER}_det_20260813",
        "cultivar_identity": "TM0008",
        "observation_policy": "configs/runs/e02_v2_rawdiff_terminal_nresp01_soil02_policy_20260813.csv",
        "group_policy": "configs/runs/t10_rawdiff_terminal_nresp01_soil02_group_policy_20260813.csv",
        "purpose": "deterministic diagnostics; no re-calibration",
        "custom_dssat_executable": str(EXE.resolve()),
        "custom_spe": str(SPE.resolve()),
        "seasonal_parameterization": None,
        "seasons": [{
            "season_id": s["season_id"], "experiment_code": s["excode"],
            "bundle_path": str(s["bundle"]),
            "bundle_manifest_sha256": _sha256(s["bundle"] / "input_manifest.json"),
            "role": "calibration", "treatments": s["treatments"],
        } for s in SEASONS],
    }
    path = det_root / "design.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _swap() -> list[tuple[Path, Path]]:
    replacements = []
    bk_exe = ROOT / "workspace/DSCSM048.EXE.eval_fixedsoil_official_20260813"
    if EXE.resolve() != DEFAULT_EXE.resolve():
        if DEFAULT_EXE.is_file():
            shutil.copy2(DEFAULT_EXE, bk_exe)
        shutil.copy2(EXE, DEFAULT_EXE)
        replacements.append((DEFAULT_EXE, bk_exe))
    target_spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
    if Path(SPE).resolve() != target_spe_base.resolve():
        bk_spe = GENOTYPE_DIR / "TMGRO048.SPE.base.eval_fixedsoil_official_20260813"
        shutil.copy2(target_spe_base, bk_spe)
        shutil.copy2(SPE, target_spe_base)
        replacements.append((target_spe_base, bk_spe))
    plain = GENOTYPE_DIR / "TMGRO048.SPE"
    if plain.is_file() and Path(SPE).resolve() != plain.resolve():
        pb = GENOTYPE_DIR / "TMGRO048.SPE.eval_fixedsoil_official_20260813"
        shutil.copy2(plain, pb)
        shutil.copy2(SPE, plain)
        replacements.append((plain, pb))
    return replacements


def _restore(replacements):
    for live, backup in reversed(replacements):
        if live.exists():
            live.unlink()
        if backup.exists():
            backup.replace(live)


def _run(command: list[str], cwd: Path) -> None:
    print("+ " + subprocess.list2cmdline([str(x) for x in command]), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _run_comparisons(det_root: Path) -> None:
    for season in SEASONS:
        sid = season["season_id"]
        season_dir = det_root / "_seasons" / sid
        filex = next(season_dir.glob("*.TMX"))
        batch = season_dir / "analysis_batch.v48"
        batch.write_text(
            "\n".join(f"{filex.resolve()} {int(tn)} 1 0 0 0" for tn in season["treatments"]) + "\n",
            encoding="utf-8",
        )
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
        tmt = season["bundle"] / f"{season['excode']}.TMT"
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
    if not result.empty:
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
                ok = obs.notna() & sim.notna() & (obs > -90.0) & (sim > -90.0)
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
    organ_n_path = det_root / "organ_n_compare.csv"
    organ_n = pd.read_csv(organ_n_path) if (organ_n_path.is_file() and organ_n_path.stat().st_size > 2) else pd.DataFrame()
    if not organ_n.empty:
        for (season, variable), frame in organ_n.groupby(["season", "variable"], sort=False):
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
        table = table.reindex(columns=SEASON_IDS)
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
                    rgba = image.cmap(image.norm(value))
                    brightness = 0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
                    ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=7,
                            color="black" if brightness > 0.50 else "white")
                else:
                    ax.text(j, i, "NA", ha="center", va="center", fontsize=7, color="#555555")
        fig.colorbar(image, ax=ax, label=label)
        fig.tight_layout()
        path = out_root / f"metrics_heatmap_{metric}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        plots.append(path)
    # Compact RRMSE comparison chart
    subset = metrics[metrics["variable"].isin(order)].copy()
    fig, ax = plt.subplots(figsize=(10.5, 5.2), dpi=180)
    x = np.arange(len(order))
    width = min(0.24, 0.8 / max(len(SEASON_IDS), 1))
    for j, season in enumerate(SEASON_IDS):
        vals = subset[subset["season"] == season].set_index("variable")["rrmse_pct"].reindex(order)
        offset = (j - (len(SEASON_IDS) - 1) / 2) * width
        ax.bar(x + offset, vals.to_numpy(float), width, label=season, color=COLORS[season])
    ax.set_xticks(x, order, rotation=45, ha="right")
    ax.set_ylabel("RRMSE (%)")
    ax.set_title(f"Best-member RRMSE across {len(SEASON_IDS)} seasons")
    ax.grid(True, axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=len(SEASON_IDS))
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
    for variable, group in pairs.groupby("variable", sort=False):
        n_seasons = len(SEASON_IDS)
        fig, axes = plt.subplots(1, n_seasons, figsize=(4.2 * n_seasons, 4.2), dpi=180, sharex=True, sharey=True)
        if n_seasons == 1:
            axes = [axes]
        finite = group[["observed", "simulated"]].to_numpy(float)
        lo = float(np.nanmin(finite)); hi = float(np.nanmax(finite)); pad = max((hi - lo) * 0.06, 1e-6)
        for ax, season in zip(axes, SEASON_IDS):
            sub = group[group["season"] == season]
            if sub.empty:
                ax.set_visible(False); continue
            ax.scatter(sub["observed"], sub["simulated"], color=COLORS[season], s=34, alpha=0.8, edgecolor="white", linewidth=0.3)
            ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#555", lw=0.9)
            ax.set_title(season); ax.set_xlim(lo - pad, hi + pad); ax.set_ylim(lo - pad, hi + pad)
            y = sub["observed"].to_numpy(float); p = sub["simulated"].to_numpy(float); e = p - y
            ax.text(0.04, 0.96, f"n={len(sub)}\nRMSE={np.sqrt(np.mean(e**2)):.3g}\nBias={e.mean():+.3g}", transform=ax.transAxes, va="top", fontsize=8, family="monospace", bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none"})
            ax.grid(True, alpha=0.25); ax.spines[["top", "right"]].set_visible(False)
        axes[0].set_ylabel("Simulated"); fig.text(0.5, 0.02, "Observed", ha="center")
        fig.suptitle(f"{variable}: observed vs simulated")
        fig.tight_layout(rect=(0, 0.05, 1, 0.94))
        path = out_root / f"scatter_{variable}.png"; fig.savefig(path, bbox_inches="tight"); plt.close(fig); outputs.append(path)

        fig, axes = plt.subplots(1, n_seasons, figsize=(4.2 * n_seasons, 4.2), dpi=180, sharex=True, sharey=True)
        if n_seasons == 1:
            axes = [axes]
        residual = group["simulated"] - group["observed"]
        rmax = max(float(np.nanmax(np.abs(residual))), 1e-6)
        for ax, season in zip(axes, SEASON_IDS):
            sub = group[group["season"] == season]
            if sub.empty:
                ax.set_visible(False); continue
            ax.scatter(sub["observed"], sub["simulated"] - sub["observed"], color=COLORS[season], s=34, alpha=0.8, edgecolor="white", linewidth=0.3)
            ax.axhline(0, ls="--", color="#555", lw=0.9); ax.set_title(season); ax.set_xlim(lo - pad, hi + pad); ax.set_ylim(-1.15 * rmax, 1.15 * rmax)
            ax.grid(True, alpha=0.25); ax.spines[["top", "right"]].set_visible(False)
        axes[0].set_ylabel("Simulated − observed"); fig.text(0.5, 0.02, "Observed", ha="center")
        fig.suptitle(f"{variable}: residuals (simulated − observed)")
        fig.tight_layout(rect=(0, 0.05, 1, 0.94))
        path = out_root / f"residual_{variable}.png"; fig.savefig(path, bbox_inches="tight"); plt.close(fig); outputs.append(path)
    return outputs


def _process_extra_pairs(det_root: Path) -> pd.DataFrame:
    """CHTD pairs from each season's process-compare CSV (same shape as organ-N)."""
    frames = []
    for season in SEASONS:
        sid = season["season_id"]
        path = det_root / "_seasons" / sid / f"{sid}_deterministic_process_compare.csv"
        if not path.is_file() or path.stat().st_size <= 2:
            continue
        f = pd.read_csv(path)
        for variable in ["CHTD"]:
            obs_col, sim_col = f"OBS_{variable}", f"SIM_{variable}"
            if obs_col in f and sim_col in f:
                sub = f[["TN", "DATE", obs_col, sim_col]].rename(columns={obs_col: "observed", sim_col: "simulated"})
                sub["season"] = sid
                sub["variable"] = variable
                sub = sub[(sub["observed"] > -90.0) & (sub["simulated"] > -90.0)]
                frames.append(sub)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    DET_ROOT.mkdir(parents=True, exist_ok=True)

    print(
        f"fixed-soil official calibration best member = #{BEST_MEMBER} "
        f"(iteration={SOURCE_ITERATION}, phi={BEST_PHI:g}, state={CALIBRATION_STATE})"
    )
    print(f"{len(SEASONS)}-season actual_trial bundles:")
    for s in SEASONS:
        print(f"  {s['season_id']}  {s['excode']}  TN={s['treatments']}")
        print(f"    bundle: {s['bundle']}")

    params = DET_ROOT / f"best_member_{BEST_MEMBER}_params.csv"
    n_params = _export_member(params)
    # SOIL_SLPF is already 0.93 in the 20260813 build (fixed at build time);
    # no override needed.
    print(f"exported {n_params} parameters -> {params}")

    design = _write_design(DET_ROOT)

    status = DET_ROOT / "multiseason_run_status.json"
    if not status.is_file():
        os.environ["DSSAT_SPE_BASE"] = str(SPE.resolve())
        replacements = _swap()
        try:
            _run([
                sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                "--design", str(design), "--param-csv", str(params),
                "--prefix", f"best{BEST_MEMBER}_det_official",
                "--harvest-var", "CHPDT", "--keep-nitrogen-outputs",
            ], DET_ROOT)
        finally:
            _restore(replacements)
    else:
        print("deterministic run already present; skipping replay")

    _run_comparisons(DET_ROOT)
    organ_n = _organ_n_pairs(DET_ROOT)
    metrics = _metric_rows(DET_ROOT)

    # Canonical dynamics renderer (W×N timeseries + cross-season scatter/
    # residual/MSE decomposition + response audit + yield-curve audit)
    plotter = ROOT / "tools/calibration/plot_dynamics.py"
    registry_arg = ["--registry-csv", str(OBS_REGISTRY)] if OBS_REGISTRY.is_file() else []
    plot_command = [
        sys.executable, str(plotter),
        "--det-root", str(DET_ROOT),
        "--out-root", str(OUT_ROOT),
        "--seasons", ",".join(SEASON_IDS),
    ] + registry_arg
    if PLOT_INCLUDE_ALL_TREATMENTS:
        plot_command.append("--include-all-treatments")
    if PLOT_MAPPING_CSV is not None:
        plot_command.extend(["--mapping-csv", str(PLOT_MAPPING_CSV)])
    _run(plot_command, ROOT)

    metric_plots = _plot_metrics(metrics, OUT_ROOT)
    extra_pairs = _process_extra_pairs(DET_ROOT)
    if not organ_n.empty:
        extra_pairs = pd.concat([extra_pairs, organ_n], ignore_index=True)
    metric_plots.extend(_plot_extra_pairs(extra_pairs, OUT_ROOT))

    manifest = {
        "artifact_type": ARTIFACT_TYPE,
        "source_calibration": str(RUN_DIR),
        "source_iteration": SOURCE_ITERATION,
        "calibration_state": CALIBRATION_STATE,
        "best_member": BEST_MEMBER,
        "best_phi": BEST_PHI,
        "parameter_csv": str(params),
        "parameter_count_exported": n_params,
        "custom_dssat_executable": str(EXE.resolve()),
        "custom_spe": str(SPE.resolve()),
        "soil_injection": SOIL_INJECTION_DESCRIPTION,
        "dssat_version": DSSAT_VERSION_DESCRIPTION,
        "custom_genetic_params": "none (official v4.8 SPE)",
        "soil_params": SOIL_PARAMETER_STATUS,
        "harvest_objective": HARVEST_OBJECTIVE,
        "seasons": [{**s, "bundle": str(s["bundle"])} for s in SEASONS],
        "deterministic_run": str(DET_ROOT),
        "output_root": str(OUT_ROOT),
        "metric_plots": [p.name for p in metric_plots],
        "figures": sorted(str(p.relative_to(OUT_ROOT)) for p in OUT_ROOT.rglob("*.png")),
        "metrics_csv": str((DET_ROOT / "metrics_by_season_variable.csv").resolve()),
        "organ_n_pairs_csv": str((DET_ROOT / "organ_n_compare.csv").resolve()),
        "bundle_note": BUNDLE_NOTE,
        "limitations": [
            "Python run-diagnostics product, not a publication Fig/FigS bundle.",
            (
                "W×N dynamics renderer includes every selected treatment, including incomplete-factorial W2/CK cells."
                if PLOT_INCLUDE_ALL_TREATMENTS else
                "W×N dynamics renderer excludes unmapped 25SP TN9/TN14 from factorial panels; all observations remain in metric CSVs."
            ),
        ] + EXTRA_LIMITATIONS,
    }
    (OUT_ROOT / "diagnostic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\nbest_member={BEST_MEMBER}; exported_parameters={n_params}")
    print(metrics.to_string(index=False))
    print(f"\nDiagnostics written to: {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
