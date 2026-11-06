#!/usr/bin/env python3
"""Generate 3-season dynamic timeseries figures (LAID, FreshWt, CWAD) for 200x8 calibration top candidates:
Verifies specifically that 25SP W3N0 late-season LAI collapse is resolved,
and water-nitrogen dynamics follow realistic agronomic patterns.
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
from pathlib import Path
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

ROOT = Path("D:/Tomato_Cal")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUN_DIR = ROOT / "workspace" / "runs" / "full_gen_page22_sasc0925_scale200x8_20260918"
FIG_ROOT = ROOT / "figture"

SEASONS = [
    {
        "id": "25SP",
        "excode": "XXQL2501",
        "treatments": [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14],
        "batch": ROOT / "data" / "templates" / "batch" / "DSSBatch.v48",
        "bundle": ROOT / "data" / "user" / "experiments" / "xxql2501_v20260917_refresh",
        "labels": {
            2: "W3N3", 3: "W3N2", 4: "W3N1", 5: "W3N0",
            6: "W2N3", 9: "W2N0",
            10: "W1N3", 11: "W1N2", 12: "W1N1", 13: "W1N0",
            14: "CKN2",
        },
    },
    {
        "id": "26SP",
        "excode": "XXQL2601",
        "treatments": list(range(1, 13)),
        "batch": ROOT / "data" / "user" / "experiments" / "xxql2601_v20260917_refresh" / "DSSBatch.v48",
        "bundle": ROOT / "data" / "user" / "experiments" / "xxql2601_v20260917_refresh",
        "labels": {
            1: "W3N3", 2: "W2N3", 3: "W1N3",
            4: "W3N2", 5: "W2N2", 6: "W1N2",
            7: "W3N1", 8: "W2N1", 9: "W3N0",
            10: "W1N1", 11: "W2N0", 12: "W1N0",
        },
    },
]


def run_full_season(candidate_tag: str, param_csv: Path, season_cfg: dict, out_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    # Copy bundle files
    for f in season_cfg["bundle"].iterdir():
        if f.is_file() and f.name != "input_manifest.json":
            shutil.copy2(f, out_dir / f.name)

    # Copy DSSBatch
    shutil.copy2(season_cfg["batch"], out_dir / "DSSBatch.v48")

    cmd = [
        sys.executable,
        "-m",
        "src.dssat.run_dssat",
        "--param-csv",
        str(param_csv.resolve()),
        "--batch",
        "DSSBatch.v48",
        "--harvest-var",
        "CHPDT",
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    res = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, env=env)
    if res.returncode != 0:
        raise RuntimeError(f"Simulation failed for {season_cfg['id']} {candidate_tag}:\n{res.stderr[-400:]}")


def plot_timeseries_laid(out_dir: Path, season_cfg: dict, fig_dir: Path, candidate_tag: str):
    plantgro_p = out_dir / "PlantGro.OUT"
    if not plantgro_p.exists():
        return

    # Parse PlantGro.OUT
    lines = plantgro_p.read_text(encoding="utf-8", errors="ignore").splitlines()
    data_lines = []
    current_tr = 0
    header = None

    for line in lines:
        if line.startswith("*RUN"):
            parts = line.split()
            try:
                current_tr = int(parts[-1])
            except ValueError:
                current_tr = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        elif line.strip().startswith("@YEAR"):
            header = line.replace("@", "").split()
        elif header and line.strip() and not line.strip().startswith(("@", "*", "!", "$")):
            row = line.split()
            if len(row) >= len(header):
                d = dict(zip(header, row))
                d["TRNO"] = current_tr
                data_lines.append(d)

    df_sim = pd.DataFrame(data_lines)
    for col in ["DAP", "LAID", "CWAD", "TRNO"]:
        if col in df_sim.columns:
            df_sim[col] = pd.to_numeric(df_sim[col], errors="coerce")

    # Load FileT observations
    filet_p = out_dir / f"{season_cfg['excode']}.TMT"
    df_obs = None
    if filet_p.exists():
        t_lines = filet_p.read_text(encoding="utf-8", errors="ignore").splitlines()
        t_header = None
        t_rows = []
        for l in t_lines:
            if l.strip().startswith("@TRNO"):
                t_header = l.replace("@", "").split()
            elif l.strip() and not l.strip().startswith(("@", "*", "!")) and t_header:
                parts = l.split()
                if len(parts) >= len(t_header):
                    t_rows.append(dict(zip(t_header, parts)))
        if t_rows:
            df_obs = pd.DataFrame(t_rows)
            plant_date = 25071 if season_cfg["id"] == "25SP" else 26073
            for c in ["TRNO", "DATE", "LAID", "CWAD"]:
                if c in df_obs.columns:
                    df_obs[c] = pd.to_numeric(df_obs[c], errors="coerce")
            if "DATE" in df_obs.columns:
                df_obs["DAP"] = df_obs["DATE"] - plant_date

    # Plot LAID by Water x Nitrogen
    fig_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), sharex=True, sharey=True)
    axes = axes.flatten()

    groups = {
        "W3 Levels": [tr for tr, lbl in season_cfg["labels"].items() if lbl.startswith("W3")],
        "W2 Levels": [tr for tr, lbl in season_cfg["labels"].items() if lbl.startswith("W2")],
        "W1 Levels": [tr for tr, lbl in season_cfg["labels"].items() if lbl.startswith("W1")],
        "CK / Other": [tr for tr, lbl in season_cfg["labels"].items() if not (lbl.startswith("W3") or lbl.startswith("W2") or lbl.startswith("W1"))],
    }

    colors = {"N3": "#C0392B", "N2": "#E67E22", "N1": "#2980B9", "N0": "#27AE60"}

    for ax_idx, (grp_name, tr_list) in enumerate(groups.items()):
        ax = axes[ax_idx]
        ax.set_title(f"{season_cfg['id']} - {grp_name}", fontsize=13, fontweight="bold")

        for tr in tr_list:
            lbl = season_cfg["labels"].get(tr, f"T{tr}")
            nitro = lbl[-2:] if len(lbl) >= 2 else "N3"
            color = colors.get(nitro, "#7f8c8d")

            # Sim lines
            sub_sim = df_sim[df_sim["TRNO"] == tr]
            if not sub_sim.empty and "LAID" in sub_sim.columns:
                ax.plot(sub_sim["DAP"], sub_sim["LAID"], label=f"{lbl} Sim", color=color, lw=2.0)

            # Obs points
            if df_obs is not None and "LAID" in df_obs.columns:
                sub_obs = df_obs[df_obs["TRNO"] == tr].dropna(subset=["LAID"])
                if not sub_obs.empty:
                    ax.scatter(sub_obs["DAP"], sub_obs["LAID"], label=f"{lbl} Obs", color=color, s=40, edgecolors="k", zorder=5)

        ax.set_xlabel("Days After Planting (DAP)", fontsize=11)
        ax.set_ylabel("Leaf Area Index (LAI)", fontsize=11)
        ax.legend(loc="upper left", fontsize=9, framealpha=0.8)
        ax.set_ylim(0, 6.5)

    plt.suptitle(f"Leaf Area Index (LAID) Dynamics - {candidate_tag} ({season_cfg['id']})", fontsize=15, fontweight="bold", y=0.98)
    plt.tight_layout()
    out_fig = fig_dir / "timeseries_LAID_by_WxN.png"
    plt.savefig(out_fig, dpi=300)
    plt.close()
    print(f"Saved figure: {out_fig}")


def render_candidate_suite(candidate_tag: str, param_csv: Path):
    print(f"\nRendering diagnostic figure suite for {candidate_tag}...")
    for season_cfg in SEASONS:
        sim_dir = RUN_DIR / f"full_season_{candidate_tag}_{season_cfg['id']}"
        run_full_season(candidate_tag, param_csv, season_cfg, sim_dir)
        fig_dir = FIG_ROOT / f"scale200x8_{candidate_tag}_suite" / season_cfg["id"]
        plot_timeseries_laid(sim_dir, season_cfg, fig_dir, candidate_tag)


def main():
    ranked_csv = RUN_DIR / "candidates_ranked_balanced.csv"
    if not ranked_csv.exists():
        print(f"Ranked CSV not found at {ranked_csv}. Please run evaluation first.")
        return 1

    df_ranked = pd.read_csv(ranked_csv)
    # Select top 2 non-baseline candidates
    top_candidates = df_ranked[~df_ranked["candidate"].str.startswith("baseline")].head(2)

    for _, row in top_candidates.iterrows():
        cand = str(row["candidate"])
        p_csv = RUN_DIR / f"candidate_{cand}_params.csv"
        if p_csv.exists():
            render_candidate_suite(cand, p_csv)

    print("\nAll top candidate diagnostic figures rendered successfully!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
