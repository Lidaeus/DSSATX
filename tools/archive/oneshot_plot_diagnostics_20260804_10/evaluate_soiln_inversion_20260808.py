"""Two-season diagnostics for soil N inversion best member.

Uses the soil N inversion best member params (328, including inverted IC
SNH4/SNO3) with nresp exe on 25SP+26SP actual_trial bundles, computes fit
metrics, and renders the full diagnostic figure set.

Usage:
    python tools/calibration/evaluate_soiln_inversion_20260808.py
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyemu

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.analyze_results import (
    deterministic_harvest_compare,
    deterministic_process_compare,
)

CASE = "e02_v2_initial_soil_n_25sp26sp_100x4_20260808"
RUN_DIR = ROOT / "workspace/runs" / CASE
BEST_MEMBER = "32"
EXE = ROOT / "windows/windows_nresp_20260806/DSCSM048.EXE"
SPE = ROOT / "windows/windows_nresp_20260806/Genotype/TMGRO048.SPE"
DEFAULT_EXE = ROOT / "workspace/DSCSM048.EXE"
GENOTYPE_DIR = ROOT / "data/templates/genotype"
FIGTURE = ROOT / "figture"
OUT_ROOT = FIGTURE / "soiln_inversion_20260808"

SEASONS = [
    {"season_id": "25SP", "excode": "XXQL2501",
     "treatments": [2, 3, 4, 5, 9, 10, 11, 12, 13, 14],
     "bundle": ROOT / "data/user/experiments/xxql2501_actual_trial_calibration_v8_adap34_plantn_slpf_moisturefix_20260729"},
    {"season_id": "26SP", "excode": "XXQL2601",
     "treatments": list(range(1, 13)),
     "bundle": ROOT / "data/user/experiments/xxql2601_actual_trial_calibration_v7_adap34_plantn_slpf_20260729"},
]


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _export_member(out_csv: Path) -> int:
    frame = pd.read_csv(RUN_DIR / f"{CASE}.4.par.csv")
    real_col = next((c for c in frame.columns if str(c).lower() in {"real_name", "realization"}), None)
    mask = frame[real_col].astype(str).str.replace(r"\.0$", "", regex=True).eq(BEST_MEMBER)
    row = frame.loc[mask].iloc[0]
    records = []
    for col in frame.columns:
        if col == real_col:
            continue
        v = float(row[col])
        if not math.isfinite(v):
            raise ValueError(f"non-finite {col}={v}")
        records.append({"name": str(col).upper(), "value": v})
    pd.DataFrame(records).to_csv(out_csv, index=False)
    return len(records)


def _write_design(det_root: Path) -> Path:
    payload = {
        "schema_version": 1,
        "design_id": f"{CASE}_best{BEST_MEMBER}_det_20260808",
        "cultivar_identity": "TM0008",
        "shared_parameter_scope": "soil N inversion best member deterministic replay",
        "observation_policy": "configs/runs/e02_v2_joint25sp26sp_nosoil_nresp_policy_20260802.csv",
        "group_policy": "configs/runs/t10_v2_joint25sp26sp_nosoil_nresp_group_policy_20260808.csv",
        "purpose": "deterministic diagnostics; no re-calibration",
        "custom_dssat_executable": str(EXE.resolve()),
        "custom_spe": str(SPE.resolve()),
        "seasonal_parameterization": None,
        "seasons": [{
            "season_id": s["season_id"],
            "experiment_code": s["excode"],
            "bundle_path": str(s["bundle"]),
            "bundle_manifest_sha256": _sha256(s["bundle"] / "input_manifest.json"),
            "role": "calibration",
            "treatments": s["treatments"],
        } for s in SEASONS],
    }
    path = det_root / "design.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _swap() -> list[tuple[Path, Path]]:
    replacements = []
    backup_exe = ROOT / "workspace/DSCSM048.EXE.eval_soiln"
    spe_base = GENOTYPE_DIR / "TMGRO048.SPE.base"
    spe_backup = GENOTYPE_DIR / "TMGRO048.SPE.base.eval_soiln"
    shutil.copy2(DEFAULT_EXE, backup_exe)
    shutil.copy2(EXE, DEFAULT_EXE)
    replacements.append((DEFAULT_EXE, backup_exe))
    shutil.copy2(spe_base, spe_backup)
    shutil.copy2(SPE, spe_base)
    replacements.append((spe_base, spe_backup))
    plain = GENOTYPE_DIR / "TMGRO048.SPE"
    if plain.is_file():
        pb = GENOTYPE_DIR / "TMGRO048.SPE.eval_soiln"
        shutil.copy2(plain, pb)
        shutil.copy2(SPE, plain)
        replacements.append((plain, pb))
    return replacements


def _restore(replacements: list[tuple[Path, Path]]) -> None:
    for live, backup in reversed(replacements):
        if live.exists():
            live.unlink()
        if backup.exists():
            backup.replace(live)


def _compute_metrics(det_root: Path) -> pd.DataFrame:
    rows = []
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

        for kind, fname in (("process", f"{sid}_deterministic_process_compare.csv"),
                            ("harvest", f"{sid}_deterministic_harvest_compare.csv")):
            path = season_dir / fname
            if not path.is_file() or path.stat().st_size <= 2:
                continue
            frame = pd.read_csv(path)
            for col in frame.columns:
                if not str(col).startswith("OBS_"):
                    continue
                var = str(col)[4:]
                sim_col = f"SIM_{var}"
                if sim_col not in frame:
                    continue
                obs = pd.to_numeric(frame[col], errors="coerce")
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
                    "season": sid, "kind": kind, "variable": var, "n": int(ok.sum()),
                    "rmse": float(np.sqrt(np.mean(e ** 2))),
                    "rrmse_pct": float(100 * np.sqrt(np.mean(e ** 2)) / np.mean(np.abs(y))) if np.mean(np.abs(y)) else np.nan,
                    "mae": float(np.mean(np.abs(e))), "bias": float(e.mean()),
                    "nse": float(1 - np.sum(e ** 2) / den) if den > 0 else np.nan,
                    "d_index": float(1 - np.sum(e ** 2) / dden) if dden > 0 else np.nan,
                    "r2": float(np.corrcoef(y, p)[0, 1] ** 2) if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0 else np.nan,
                })
    result = pd.DataFrame(rows)
    result.to_csv(det_root / "metrics.csv", index=False)
    return result


def _plot_scatter_residual(metrics_pairs: dict, out_root: Path, titles: dict) -> list[Path]:
    outputs = []
    vars_all = set()
    pairs_by_var = {}
    for label, det_root in metrics_pairs.items():
        for season in SEASONS:
            sid = season["season_id"]
            season_dir = det_root / "_seasons" / sid
            for fname in (f"{sid}_deterministic_process_compare.csv",
                          f"{sid}_deterministic_harvest_compare.csv"):
                path = season_dir / fname
                if not path.is_file():
                    continue
                frame = pd.read_csv(path)
                for col in frame.columns:
                    if str(col).startswith("OBS_"):
                        var = str(col)[4:]
                        sim_col = f"SIM_{var}"
                        if sim_col in frame:
                            key = (var, sid)
                            vars_all.add(var)
                            sub = frame[[col, sim_col]].copy()
                            sub.columns = ["observed", "simulated"]
                            sub = sub[(sub["observed"] != -99) & (sub["simulated"] != -99)].dropna()
                            pairs_by_var.setdefault(key, {})[label] = sub

    for var in sorted(vars_all):
        for season in SEASONS:
            sid = season["season_id"]
            key = (var, sid)
            if key not in pairs_by_var:
                continue
            data = pairs_by_var[key]
            if not data:
                continue
            fig, ax = plt.subplots(figsize=(6, 5), dpi=180)
            for label, pairs in data.items():
                if pairs is None or pairs.empty:
                    continue
                y = pairs["observed"].to_numpy(float)
                p = pairs["simulated"].to_numpy(float)
                ax.scatter(y, p, s=30, alpha=0.7, label=label, edgecolor="white", linewidth=0.3)
            # 1:1 line
            all_vals = []
            for pairs in data.values():
                if pairs is not None and not pairs.empty:
                    all_vals.extend(pairs["observed"].tolist())
                    all_vals.extend(pairs["simulated"].tolist())
            if all_vals:
                lo = min(all_vals); hi = max(all_vals); pad = max((hi - lo) * 0.06, 1e-6)
                ax.plot([lo - pad, hi + pad], [lo - pad, hi + pad], "--", color="#555", lw=0.9)
                ax.set_xlim(lo - pad, hi + pad); ax.set_ylim(lo - pad, hi + pad)
            ax.set_xlabel("Observed"); ax.set_ylabel("Simulated")
            ax.set_title(f"{var} ({sid})", fontsize=10)
            ax.grid(True, alpha=0.25)
            ax.spines[["top", "right"]].set_visible(False)
            fig.tight_layout()
            path = out_root / f"scatter_{var}_{sid}.png"
            fig.savefig(path, bbox_inches="tight")
            plt.close(fig)
            outputs.append(path)

            # Residual
            fig, ax = plt.subplots(figsize=(6, 5), dpi=180)
            for label, pairs in data.items():
                if pairs is None or pairs.empty:
                    continue
                y = pairs["observed"].to_numpy(float)
                r = pairs["simulated"].to_numpy(float) - y
                ax.scatter(y, r, s=30, alpha=0.7, label=label, edgecolor="white", linewidth=0.3)
            ax.axhline(0, ls="--", color="#555", lw=0.9)
            ax.set_xlabel("Observed"); ax.set_ylabel("Simulated − observed")
            ax.set_title(f"{var} residuals ({sid})", fontsize=10)
            ax.grid(True, alpha=0.25)
            ax.spines[["top", "right"]].set_visible(False)
            fig.tight_layout()
            path = out_root / f"residual_{var}_{sid}.png"
            fig.savefig(path, bbox_inches="tight")
            plt.close(fig)
            outputs.append(path)
    return outputs


def _plot_metrics_heatmap(metrics: pd.DataFrame, out_root: Path) -> list[Path]:
    outputs = []
    present = metrics["variable"].drop_duplicates().tolist()
    order = [v for v in ["LAID", "LWAD", "SWAD", "DRY_CUM", "DRY_INC", "CHTD", "LAIX", "ADAP"]
             if v in present]
    order += [v for v in present if v not in order]
    for metric, label in (("rrmse_pct", "RRMSE (%)"), ("nse", "NSE"), ("r2", "R²"), ("d_index", "d-index")):
        table = metrics.pivot_table(index="variable", columns="season", values=metric, aggfunc="mean").reindex(order)
        table = table.reindex(columns=[s["season_id"] for s in SEASONS])
        fig, ax = plt.subplots(figsize=(6, max(3.5, 0.45 * len(order) + 1.2)), dpi=180)
        vals = table.to_numpy(float)
        image = ax.imshow(vals, aspect="auto", cmap="RdYlGn" if metric in ("nse", "r2", "d_index") else "RdYlGn_r")
        ax.set_xticks(range(len(table.columns)), table.columns)
        ax.set_yticks(range(len(table.index)), table.index)
        ax.set_title(f"Soil N inversion: {label}", fontsize=10)
        for i in range(table.shape[0]):
            for j in range(table.shape[1]):
                v = table.iloc[i, j]
                if np.isfinite(v):
                    ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                            color="white" if abs(v) > np.nanpercentile(abs(vals), 55) else "black")
        fig.colorbar(image, ax=ax, label=label)
        fig.tight_layout()
        path = out_root / f"metrics_heatmap_{metric}.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)
    return outputs


def main() -> int:
    out_root = OUT_ROOT
    out_root.mkdir(parents=True, exist_ok=True)

    print(f"soil N inversion best member = #{BEST_MEMBER}")
    det_root = RUN_DIR / f"best_member_{BEST_MEMBER}_deterministic_20260808"
    det_root.mkdir(parents=True, exist_ok=True)

    params = det_root / f"best_member_{BEST_MEMBER}_params.csv"
    n_params = _export_member(params)
    print(f"exported {n_params} params")

    design = _write_design(det_root)
    status = det_root / "multiseason_run_status.json"
    if not status.is_file():
        os.environ["DSSAT_SPE_BASE"] = str(SPE.resolve())
        replacements = _swap()
        try:
            subprocess.run([
                sys.executable, str(ROOT / "src/calibration/run_multiseason.py"),
                "--design", str(design), "--param-csv", str(params),
                "--prefix", f"best{BEST_MEMBER}_det", "--harvest-var", "CHPDT",
                "--keep-nitrogen-outputs",
            ], cwd=str(det_root), check=True)
        finally:
            _restore(replacements)

    metrics = _compute_metrics(det_root)
    print(f"\nmetrics:\n{metrics.to_string(index=False)}")

    # Plot: per-season scatter + residual
    sr_plots = _plot_scatter_residual({"soiln_inv": det_root}, out_root, {"soiln_inv": f"best#{BEST_MEMBER}"})
    # Plot: metrics heatmap
    hm_plots = _plot_metrics_heatmap(metrics, out_root)

    metrics.to_csv(out_root / "metrics_soiln_inversion_20260808.csv", index=False)

    manifest = {
        "artifact_type": "soil_n_inversion_evaluation",
        "run_id": CASE,
        "best_member": BEST_MEMBER,
        "seasons": [s["season_id"] for s in SEASONS],
        "bundles": {s["season_id"]: str(s["bundle"]) for s in SEASONS},
        "custom_dssat": str(EXE.resolve()),
        "figures": sorted(p.name for p in sr_plots + hm_plots),
        "metrics_csv": str(out_root / "metrics_soiln_inversion_20260808.csv"),
    }
    (out_root / "diagnostic_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nWritten to: {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
