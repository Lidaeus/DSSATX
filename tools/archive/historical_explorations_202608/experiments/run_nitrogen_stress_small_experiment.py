#!/usr/bin/env python3
"""Controlled small experiment to verify DSSAT-CROPGRO Nitrogen Stress mechanisms and smoothing strategies.

We test an N-supply gradient (0 to 60 mg/kg initial SNO3) under:
1. Baseline: Default TMGRO048.SPE parameters
2. Exp_A: Broadened protein bounds (lower PROLFF from 0.110 to 0.070, PROSTF from 0.065 to 0.035, PRORTF from 0.060 to 0.030)
3. Exp_B: Smoothed Leaf N-Photosynthesis curve (lower FNPGN(1) from 2.0 to 1.0, LNREF from 4.5 to 3.2, NSLOPE from 0.25 to 0.12)
4. Exp_C: Enhanced N Mobilization Buffer (higher NMOBMX to 0.18, higher NVSMOB to 0.60, lower NSTFAC to 0.50)
5. Exp_D: Full Synergy (A + B + C combined)
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = PROJECT_ROOT / "workspace" / "experiments" / "nitrogen_response_small_exp_20260829"
EXP_DIR.mkdir(parents=True, exist_ok=True)

REF_BUNDLE = PROJECT_ROOT / "data/user/experiments/xxql2501_formal_armab_rrmse_20260828"
SPE_BASE = PROJECT_ROOT / "data/templates/genotype/TMGRO048.SPE.base"
CUL_BASE = PROJECT_ROOT / "data/templates/genotype/TMGRO048.CUL.base"
ECO_BASE = PROJECT_ROOT / "data/templates/genotype/TMGRO048.ECO.base"
DSSAT_EXE = "C:\\DSSAT48\\DSCSM048.EXE"


def setup_workspace(work_dir: Path, spe_content: str, cul_content: str, eco_content: str, sno3_top: float) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    for f in REF_BUNDLE.glob("*"):
        if f.is_file() and f.suffix.upper() not in [".SPE", ".CUL", ".ECO"]:
            shutil.copy(f, work_dir / f.name)
    shutil.copy(PROJECT_ROOT / "data/templates/batch/DSSBatch.v48", work_dir / "DSSBatch.v48")

    (work_dir / "TMGRO048.SPE").write_text(spe_content, encoding="utf-8")
    (work_dir / "TMGRO048.CUL").write_text(cul_content, encoding="utf-8")
    (work_dir / "TMGRO048.ECO").write_text(eco_content, encoding="utf-8")

    tmx_path = work_dir / "XXQL2501.TMX"
    if tmx_path.exists():
        content = tmx_path.read_text(encoding="utf-8")
        lines = []
        for line in content.splitlines():
            # Enable N simulation in simulation controls: NITRO is 'Y'
            if line.startswith(" 1 SN") or line.startswith(" 2 SN") or "   SN " in line:
                line = line.replace("   N   N   N", "   Y   N   N").replace("   N   Y   N", "   Y   Y   N")
            if "   20  ." in line and len(line) >= 28:
                prefix = line[:24]
                lines.append(f"{prefix} {sno3_top:>5.1f}")
            else:
                lines.append(line)
        tmx_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_plantgro_out(pg_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "max_LAID": 0.0,
        "max_CWAD": 0.0,
        "max_SWAD": 0.0,
        "max_LWAD": 0.0,
        "mean_NSTD": 0.0,
        "max_NSTD": 0.0,
        "mean_LN_pct": 0.0,
        "min_LN_pct": 0.0,
    }
    if not pg_path.exists():
        return out

    lines = pg_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    header_line = None
    data_rows = []
    
    for l in lines:
        if l.startswith("@YEAR") or l.startswith("@ YEAR"):
            header_line = l.replace("@", "").split()
        elif header_line and l.strip() and not l.startswith("*") and not l.startswith("!"):
            parts = l.split()
            if len(parts) >= len(header_line):
                data_rows.append(parts[:len(header_line)])

    if header_line and data_rows:
        df = pd.DataFrame(data_rows, columns=header_line)
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
        if "LAID" in df.columns:
            out["max_LAID"] = float(df["LAID"].max())
        if "CWAD" in df.columns:
            out["max_CWAD"] = float(df["CWAD"].max())
        if "SWAD" in df.columns:
            out["max_SWAD"] = float(df["SWAD"].max())
        if "LWAD" in df.columns:
            out["max_LWAD"] = float(df["LWAD"].max())
        if "NSTD" in df.columns:
            out["mean_NSTD"] = float(df["NSTD"].mean())
            out["max_NSTD"] = float(df["NSTD"].max())
        if "LN%D" in df.columns:
            out["mean_LN_pct"] = float(df["LN%D"].mean())
            out["min_LN_pct"] = float(df["LN%D"].min())
    return out


def main() -> None:
    print("Preparing controlled Nitrogen Stress Sensitivity Experiments in CROPGRO...")
    
    spe_base = SPE_BASE.read_text(encoding="utf-8")
    cul_base = CUL_BASE.read_text(encoding="utf-8")
    eco_base = ECO_BASE.read_text(encoding="utf-8")

    n_levels = [1.0, 3.0, 6.0, 10.0, 15.0, 22.0, 32.0, 45.0, 60.0]

    configs = {}
    
    # 1. Baseline
    configs["Baseline"] = spe_base
    
    # 2. Exp_A: Broaden Protein Bounds (lower PROLFF from 0.110 to 0.070, PROSTF from 0.065 to 0.035, PRORTF from 0.060 to 0.030)
    spe_a = spe_base.replace(
        "  .270  .220  .110  .188  .136  .065   PROLFI,PROLFG,PROLFF,PROSTI,PROSTG,PROSTF\n  .144  .119  .060  .210  .150  .110   PRORTI,PRORTG,PRORTF,PROSHI,PROSHG,PROSHF",
        "  .270  .220  .070  .188  .136  .035   PROLFI,PROLFG,PROLFF,PROSTI,PROSTG,PROSTF\n  .144  .119  .030  .210  .150  .110   PRORTI,PRORTG,PRORTF,PROSHI,PROSHG,PROSHF"
    )
    configs["ExpA_Broaden_Protein_Min"] = spe_a
    
    # 3. Exp_B: Smooth Leaf N-Photosynthesis Curve (lower FNPGN(1) from 2.0 to 1.0, LNREF from 4.5 to 3.2, NSLOPE from 0.25 to 0.12)
    spe_b = spe_base.replace(
        "  2.00  4.50  20.0  20.0   QDR             FNPGN(4),TYPPGN-LEAF N EFFECT ON PG",
        "  1.00  3.50  20.0  20.0   QDR             FNPGN(4),TYPPGN-LEAF N EFFECT ON PG"
    ).replace(
        " .0028 .0006 .2500  4.50 1.36              SLWREF,SLWSLO,NSLOPE,LNREF,PGREF",
        " .0028 .0006 .1200  3.20 1.36              SLWREF,SLWSLO,NSLOPE,LNREF,PGREF"
    )
    configs["ExpB_Smooth_LeafN_Curve"] = spe_b
    
    # 4. Exp_C: Enhanced N Mobilization Buffer (NMOBMX to 0.18, NVSMOB to 0.60, NSTFAC to 0.50)
    spe_c = spe_base.replace(
        " 0.022  0.70  .250  .090  0.38  0.15   CMOBMX,CADSTF,CADPR1,NMOBMX,NVSMOB,NRCVR LAST",
        " 0.022  0.70  .250  .180  0.60  0.25   CMOBMX,CADSTF,CADPR1,NMOBMX,NVSMOB,NRCVR LAST"
    ).replace(
        "    PD  0.70  0.65  0.70               XPODF, NSTFAC,NREXP,NRMIN",
        "    PD  0.50  0.65  0.70               XPODF, NSTFAC,NREXP,NRMIN"
    )
    configs["ExpC_Enhanced_N_Buffer"] = spe_c
    
    # 5. Exp_D: Full Synergy (A + B + C combined)
    spe_d = spe_a.replace(
        "  2.00  4.50  20.0  20.0   QDR             FNPGN(4),TYPPGN-LEAF N EFFECT ON PG",
        "  1.00  3.50  20.0  20.0   QDR             FNPGN(4),TYPPGN-LEAF N EFFECT ON PG"
    ).replace(
        " .0028 .0006 .2500  4.50 1.36              SLWREF,SLWSLO,NSLOPE,LNREF,PGREF",
        " .0028 .0006 .1200  3.20 1.36              SLWREF,SLWSLO,NSLOPE,LNREF,PGREF"
    ).replace(
        " 0.022  0.70  .250  .090  0.38  0.15   CMOBMX,CADSTF,CADPR1,NMOBMX,NVSMOB,NRCVR LAST",
        " 0.022  0.70  .250  .180  0.60  0.25   CMOBMX,CADSTF,CADPR1,NMOBMX,NVSMOB,NRCVR LAST"
    ).replace(
        "    PD  0.70  0.65  0.70               XPODF, NSTFAC,NREXP,NRMIN",
        "    PD  0.50  0.65  0.70               XPODF, NSTFAC,NREXP,NRMIN"
    )
    configs["ExpD_Full_Synergy"] = spe_d

    results = []
    for cfg_name, spe_text in configs.items():
        print(f"\n--- Running Configuration: {cfg_name} ---")
        for sno3 in n_levels:
            w_dir = EXP_DIR / f"{cfg_name}_SNO3_{sno3:04.1f}"
            setup_workspace(w_dir, spe_text, cul_base, eco_base, sno3)
            # Run DSSAT
            cmd = [DSSAT_EXE, "B", "DSSBatch.v48"]
            subprocess.run(cmd, cwd=w_dir, capture_output=True, text=True)
            
            out = parse_plantgro_out(w_dir / "PlantGro.OUT")
            out["config"] = cfg_name
            out["sno3_mg_kg"] = sno3
            results.append(out)
            print(f"  SNO3={sno3:4.1f} mg/kg -> max_LAID={out['max_LAID']:.2f}, max_CWAD={out['max_CWAD']:.0f}, mean_NSTD={out['mean_NSTD']:.3f}, max_NSTD={out['max_NSTD']:.3f}, min_LN={out['min_LN_pct']:.2f}%")

    df_res = pd.DataFrame(results)
    csv_out = EXP_DIR / "nitrogen_gradient_experiment_results.csv"
    df_res.to_csv(csv_out, index=False)
    print(f"\nSaved all experiment results to {csv_out}")

    # Plot response curves
    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    for cfg_name, group in df_res.groupby("config"):
        axes[0, 0].plot(group["sno3_mg_kg"], group["mean_NSTD"], marker="o", linewidth=1.5, label=cfg_name)
        axes[0, 1].plot(group["sno3_mg_kg"], group["max_LAID"], marker="s", linewidth=1.5, label=cfg_name)
        axes[1, 0].plot(group["sno3_mg_kg"], group["max_CWAD"], marker="^", linewidth=1.5, label=cfg_name)
        axes[1, 1].plot(group["sno3_mg_kg"], group["max_NSTD"], marker="d", linewidth=1.5, label=cfg_name)

    axes[0, 0].set_title("(a) Mean Nitrogen Stress (NSTD: 0=none, 1=max) vs Soil N")
    axes[0, 0].set_xlabel("Initial Soil SNO3 in 0-20cm (mg/kg)")
    axes[0, 0].set_ylabel("Mean Seasonal NSTD")
    axes[0, 0].grid(True, linestyle="--", alpha=0.5)
    axes[0, 0].legend(fontsize=8)

    axes[0, 1].set_title("(b) Canopy Max LAI Response vs Soil N")
    axes[0, 1].set_xlabel("Initial Soil SNO3 in 0-20cm (mg/kg)")
    axes[0, 1].set_ylabel("Max LAI (m2/m2)")
    axes[0, 1].grid(True, linestyle="--", alpha=0.5)

    axes[1, 0].set_title("(c) Canopy Biomass (CWAD) Response vs Soil N")
    axes[1, 0].set_xlabel("Initial Soil SNO3 in 0-20cm (mg/kg)")
    axes[1, 0].set_ylabel("Max CWAD (kg/ha)")
    axes[1, 0].grid(True, linestyle="--", alpha=0.5)

    axes[1, 1].set_title("(d) Peak Nitrogen Stress (Max NSTD) vs Soil N")
    axes[1, 1].set_xlabel("Initial Soil SNO3 in 0-20cm (mg/kg)")
    axes[1, 1].set_ylabel("Peak NSTD")
    axes[1, 1].grid(True, linestyle="--", alpha=0.5)

    plt.tight_layout()
    fig_path = EXP_DIR / "nitrogen_stress_smoothing_curves.png"
    plt.savefig(fig_path, dpi=300)
    print(f"Saved plot to {fig_path}")


if __name__ == "__main__":
    main()
