#!/usr/bin/env python3
"""Generate complete publication-quality figures for Eggplant Crop Model Calibration & Validation (iter5_real13):
Outputs to figture/paper_figures_iter5_real13/
Figures:
- Fig1_Vegetative_Dynamics (LAI and Shoot Dry Mass dynamics in 25SP & 26SP)
- Fig2_Cumulative_Fruit_Yield_Dynamics (Multi-harvest cumulative fresh yield across WxN gradients)
- Fig3_Model_Evaluation_1to1_Scatters (1:1 scatters for Yield, LAI, Biomass, Canopy Height)
- Fig4_Water_Nitrogen_Interactive_Response (Terminal yields and N3-N0 response gaps across irrigation)
- Fig5_Genetic_Parameters_Divergence (Eggplant vs Tomato parameter shifts across 5 physiological dimensions)
- Fig6_Incremental_Harvest_Dynamics (Individual harvest event pickings over time)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

ROOT = Path("D:/Tomato_Cal")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUN_DIR = ROOT / "workspace" / "runs" / "full_gen_page22_sasc0925_150x5_20260918"
OUT_FIG_DIR = ROOT / "figture" / "paper_figures_iter5_real13"
OUT_FIG_DIR.mkdir(parents=True, exist_ok=True)

# Set publication style
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']
plt.rcParams['axes.edgecolor'] = '#333333'
plt.rcParams['axes.linewidth'] = 0.8
plt.rcParams['grid.color'] = '#e0e0e0'
plt.rcParams['grid.linestyle'] = '--'
plt.rcParams['grid.linewidth'] = 0.5

# Colorblind-friendly palette
C_N3 = "#B02A30" # Deep red
C_N2 = "#E67E22" # Orange
C_N1 = "#2980B9" # Deep blue
C_N0 = "#27AE60" # Emerald green
C_CK = "#8E44AD" # Purple

COLOR_MAP = {
    'N3': C_N3,
    'N2': C_N2,
    'N1': C_N1,
    'N0': C_N0,
}


def parse_freshwt(out_path: Path) -> pd.DataFrame:
    if not out_path.exists():
        return pd.DataFrame()
    lines = out_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    data = []
    cur_run = 0
    header = None
    for line in lines:
        if line.startswith('*RUN'):
            parts = line.split()
            cur_run = int(parts[1]) if parts[1].isdigit() else int(parts[-1])
        elif line.strip().startswith('@YEAR'):
            header = line.replace('@', '').split()
        elif header and line.strip() and not line.strip().startswith(('*', '@', '!')):
            parts = line.split()
            if len(parts) >= len(header):
                d = dict(zip(header, parts))
                d['RUN'] = cur_run
                data.append(d)
    df = pd.DataFrame(data)
    for c in ['YEAR', 'DOY', 'DAS', 'DAP', 'CHFPW', 'HFPOW', 'CHPDT']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


def parse_plantgro(out_path: Path) -> pd.DataFrame:
    if not out_path.exists():
        return pd.DataFrame()
    lines = out_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    data = []
    cur_run = 0
    header = None
    for line in lines:
        if line.startswith('*RUN'):
            parts = line.split()
            cur_run = int(parts[1]) if parts[1].isdigit() else int(parts[-1])
        elif line.strip().startswith('@YEAR'):
            header = line.replace('@', '').split()
        elif header and line.strip() and not line.strip().startswith(('*', '@', '!')):
            parts = line.split()
            if len(parts) >= len(header):
                d = dict(zip(header, parts))
                d['RUN'] = cur_run
                data.append(d)
    df = pd.DataFrame(data)
    for c in ['YEAR', 'DOY', 'DAS', 'DAP', 'LAID', 'CWAD', 'LWAD', 'SWAD', 'CHTD']:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df


# -------------------------------------------------------------
# 1. Figure 1: Vegetative Growth Dynamics (LAI and Shoot Dry Mass)
# -------------------------------------------------------------
def plot_figure_1():
    print("Generating Figure 1: Vegetative Growth Dynamics...")
    p25_dir = RUN_DIR / "full_season_iter5_real13_25SP"
    p26_dir = RUN_DIR / "full_season_iter5_real13_26SP"

    df_sim_gro25 = parse_plantgro(p25_dir / "PlantGro.OUT")
    df_sim_gro26 = parse_plantgro(p26_dir / "PlantGro.OUT")

    df_proc25 = pd.read_csv(p25_dir / "25SP_deterministic_process_compare.csv")
    df_proc26 = pd.read_csv(p26_dir / "26SP_deterministic_process_compare.csv")

    # Mapping: 25SP: RUN 1=T2(W3N3), RUN 4=T5(W3N0), RUN 7=T10(W1N3), RUN 10=T13(W1N0)
    # Mapping: 26SP: RUN 1=T1(W3N3), RUN 9=T9(W3N0), RUN 3=T3(W1N3), RUN 12=T12(W1N0)
    target_tmts_25 = [
        {"run": 1, "tmt": 2, "label": "W3N3 (Optimal Water & N)", "color": C_N3, "ls": "-"},
        {"run": 4, "tmt": 5, "label": "W3N0 (Optimal Water, Zero N)", "color": C_N0, "ls": "--"},
        {"run": 7, "tmt": 10, "label": "W1N3 (Deficit Water, High N)", "color": C_N1, "ls": "-."},
        {"run": 10, "tmt": 13, "label": "W1N0 (Deficit Water, Zero N)", "color": "#7F8C8D", "ls": ":"},
    ]
    target_tmts_26 = [
        {"run": 1, "tmt": 1, "label": "W3N3 (Optimal Water & N)", "color": C_N3, "ls": "-"},
        {"run": 9, "tmt": 9, "label": "W3N0 (Optimal Water, Zero N)", "color": C_N0, "ls": "--"},
        {"run": 3, "tmt": 3, "label": "W1N3 (Deficit Water, High N)", "color": C_N1, "ls": "-."},
        {"run": 12, "tmt": 12, "label": "W1N0 (Deficit Water, Zero N)", "color": "#7F8C8D", "ls": ":"},
    ]

    fig, axes = plt.subplots(2, 2, figsize=(13, 10), sharex='col')

    # Panel (A): 25SP LAI
    ax_a = axes[0, 0]
    ax_a.set_title("(a) 2025 Spring: Leaf Area Index (LAI)", fontsize=12, fontweight='bold', loc='left')
    ax_a.set_ylabel("Leaf Area Index ($m^2\\cdot m^{-2}$)", fontsize=11)
    for cfg in target_tmts_25:
        sim_sub = df_sim_gro25[df_sim_gro25['RUN'] == cfg['run']]
        ax_a.plot(sim_sub['DAP'], sim_sub['LAID'], color=cfg['color'], ls=cfg['ls'], lw=2.0, label=f"Sim: {cfg['label']}")
        obs_sub = df_proc25[df_proc25['TN'] == cfg['tmt']]
        # DAP for obs
        dap_obs = obs_sub['DATE'] - 25071
        ax_a.scatter(dap_obs, obs_sub['OBS_LAID'], color=cfg['color'], s=45, edgecolors='k', zorder=5, label=f"Obs: {cfg['label']}")
    ax_a.set_ylim(0, 5.5)
    ax_a.grid(True)

    # Panel (B): 26SP LAI
    ax_b = axes[0, 1]
    ax_b.set_title("(b) 2026 Spring: Leaf Area Index (LAI)", fontsize=12, fontweight='bold', loc='left')
    ax_b.set_ylabel("Leaf Area Index ($m^2\\cdot m^{-2}$)", fontsize=11)
    for cfg in target_tmts_26:
        sim_sub = df_sim_gro26[df_sim_gro26['RUN'] == cfg['run']]
        ax_b.plot(sim_sub['DAP'], sim_sub['LAID'], color=cfg['color'], ls=cfg['ls'], lw=2.0)
        obs_sub = df_proc26[df_proc26['TN'] == cfg['tmt']]
        dap_obs = obs_sub['DATE'] - 26073
        ax_b.scatter(dap_obs, obs_sub['OBS_LAID'], color=cfg['color'], s=45, edgecolors='k', zorder=5)
    ax_b.set_ylim(0, 5.5)
    ax_b.grid(True)

    # Panel (C): 25SP Aboveground Biomass (CWAD)
    ax_c = axes[1, 0]
    ax_c.set_title("(c) 2025 Spring: Shoot Dry Biomass", fontsize=12, fontweight='bold', loc='left')
    ax_c.set_xlabel("Days After Planting (DAP)", fontsize=11)
    ax_c.set_ylabel("Shoot Dry Biomass ($kg\\cdot ha^{-1}$)", fontsize=11)
    for cfg in target_tmts_25:
        sim_sub = df_sim_gro25[df_sim_gro25['RUN'] == cfg['run']]
        ax_c.plot(sim_sub['DAP'], sim_sub['LWAD'] + sim_sub['SWAD'], color=cfg['color'], ls=cfg['ls'], lw=2.0)
        obs_sub = df_proc25[df_proc25['TN'] == cfg['tmt']]
        dap_obs = obs_sub['DATE'] - 25071
        ax_c.scatter(dap_obs, obs_sub['OBS_LWAD'] + obs_sub['OBS_SWAD'], color=cfg['color'], s=45, edgecolors='k', zorder=5)
    ax_c.set_ylim(0, 5000)
    ax_c.grid(True)

    # Panel (D): 26SP Aboveground Biomass (CWAD)
    ax_d = axes[1, 1]
    ax_d.set_title("(d) 2026 Spring: Shoot Dry Biomass", fontsize=12, fontweight='bold', loc='left')
    ax_d.set_xlabel("Days After Planting (DAP)", fontsize=11)
    ax_d.set_ylabel("Shoot Dry Biomass ($kg\\cdot ha^{-1}$)", fontsize=11)
    for cfg in target_tmts_26:
        sim_sub = df_sim_gro26[df_sim_gro26['RUN'] == cfg['run']]
        ax_d.plot(sim_sub['DAP'], sim_sub['LWAD'] + sim_sub['SWAD'], color=cfg['color'], ls=cfg['ls'], lw=2.0)
        obs_sub = df_proc26[df_proc26['TN'] == cfg['tmt']]
        dap_obs = obs_sub['DATE'] - 26073
        ax_d.scatter(dap_obs, obs_sub['OBS_LWAD'] + obs_sub['OBS_SWAD'], color=cfg['color'], s=45, edgecolors='k', zorder=5)
    ax_d.set_ylim(0, 5000)
    ax_d.grid(True)

    # Custom unified legend
    legend_elements = [
        Line2D([0], [0], color=C_N3, lw=2.0, label='W3N3 (100% ETc, 450 kg N/ha)'),
        Line2D([0], [0], color=C_N0, lw=2.0, ls='--', label='W3N0 (100% ETc, 0 kg N/ha)'),
        Line2D([0], [0], color=C_N1, lw=2.0, ls='-.', label='W1N3 (50% ETc, 450 kg N/ha)'),
        Line2D([0], [0], color='#7F8C8D', lw=2.0, ls=':', label='W1N0 (50% ETc, 0 kg N/ha)'),
        Line2D([0], [0], color='black', lw=1.5, label='Simulated Daily Dynamics'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='gray', markeredgecolor='k', markersize=7, label='Observed Measurements'),
    ]
    fig.legend(handles=legend_elements, loc='lower center', ncol=3, bbox_to_anchor=(0.5, -0.03), fontsize=10, frameon=True)

    plt.tight_layout()
    fig.subplots_adjust(bottom=0.10)
    fig.savefig(OUT_FIG_DIR / "Fig1_Vegetative_Dynamics.png", dpi=300, bbox_inches='tight')
    fig.savefig(OUT_FIG_DIR / "Fig1_Vegetative_Dynamics.pdf", bbox_inches='tight')
    plt.close()
    print("Saved Fig1_Vegetative_Dynamics.png and .pdf")


# -------------------------------------------------------------
# 2. Figure 2: Cumulative Multi-Harvest Yield Dynamics
# -------------------------------------------------------------
def plot_figure_2():
    print("Generating Figure 2: Cumulative Multi-Harvest Fruit Yield Dynamics...")
    p25_dir = RUN_DIR / "full_season_iter5_real13_25SP"
    p26_dir = RUN_DIR / "full_season_iter5_real13_26SP"
    pfa_dir = RUN_DIR / "cand_iter5_real13_25fa"

    df_sim_fw25 = parse_freshwt(p25_dir / "FreshWt.OUT")
    df_sim_fw26 = parse_freshwt(p26_dir / "FreshWt.OUT")
    df_sim_fwfa = parse_freshwt(pfa_dir / "FreshWt.OUT")

    df_t25 = pd.read_csv(p25_dir / "FileT_values.csv")
    df_t26 = pd.read_csv(p26_dir / "FileT_values.csv")

    fig, axes = plt.subplots(2, 3, figsize=(16, 10))

    # Mapping configs
    # 25SP High Water (W3)
    ax = axes[0, 0]
    ax.set_title("(a) 2025 Spring: High Irrigation (W3)", fontsize=12, fontweight='bold', loc='left')
    ax.set_ylabel("Cumulative Fresh Fruit Yield ($t\\cdot ha^{-1}$)", fontsize=11)
    tmts_25_w3 = [(1, 2, "W3N3", C_N3), (2, 3, "W3N2", C_N2), (3, 4, "W3N1", C_N1), (4, 5, "W3N0", C_N0)]
    for run_id, trt_id, lbl, col in tmts_25_w3:
        sub_sim = df_sim_fw25[df_sim_fw25['RUN'] == run_id]
        ax.plot(sub_sim['DAP'], sub_sim['CHFPW'] / 1000.0, color=col, lw=2.0, label=f"Sim {lbl}")
        sub_obs = df_t25[df_t25['TRNO'] == trt_id].dropna(subset=['CHFPW'])
        dap_obs = pd.to_datetime(sub_obs['DATE']) - pd.to_datetime("2025-03-12") # 25071 is March 12
        ax.scatter(dap_obs.dt.days, sub_obs['CHFPW'] / 1000.0, color=col, s=40, edgecolors='k', zorder=5, label=f"Obs {lbl}")
    ax.set_ylim(0, 85)
    ax.legend(loc='upper left', fontsize=8.5, ncol=2)
    ax.grid(True)

    # 25SP Deficit & Moderate (W1 & W2)
    ax = axes[0, 1]
    ax.set_title("(b) 2025 Spring: Deficit (W1) & Moderate (W2)", fontsize=12, fontweight='bold', loc='left')
    ax.set_ylabel("Cumulative Fresh Fruit Yield ($t\\cdot ha^{-1}$)", fontsize=11)
    tmts_25_other = [(7, 10, "W1N3", C_N3), (8, 11, "W1N2", C_N2), (10, 13, "W1N0", C_N0), (5, 6, "W2N3", "#8E44AD"), (6, 9, "W2N0", "#16A085")]
    for run_id, trt_id, lbl, col in tmts_25_other:
        sub_sim = df_sim_fw25[df_sim_fw25['RUN'] == run_id]
        ls = "--" if "W2" in lbl else "-"
        ax.plot(sub_sim['DAP'], sub_sim['CHFPW'] / 1000.0, color=col, ls=ls, lw=2.0, label=f"Sim {lbl}")
        sub_obs = df_t25[df_t25['TRNO'] == trt_id].dropna(subset=['CHFPW'])
        dap_obs = pd.to_datetime(sub_obs['DATE']) - pd.to_datetime("2025-03-12")
        ax.scatter(dap_obs.dt.days, sub_obs['CHFPW'] / 1000.0, color=col, s=40, edgecolors='k', zorder=5, label=f"Obs {lbl}")
    ax.set_ylim(0, 85)
    ax.legend(loc='upper left', fontsize=8.5, ncol=2)
    ax.grid(True)

    # 26SP High Water (W3)
    ax = axes[0, 2]
    ax.set_title("(c) 2026 Spring: High Irrigation (W3)", fontsize=12, fontweight='bold', loc='left')
    ax.set_ylabel("Cumulative Fresh Fruit Yield ($t\\cdot ha^{-1}$)", fontsize=11)
    tmts_26_w3 = [(1, 1, "W3N3", C_N3), (4, 4, "W3N2", C_N2), (7, 7, "W3N1", C_N1), (9, 9, "W3N0", C_N0)]
    for run_id, trt_id, lbl, col in tmts_26_w3:
        sub_sim = df_sim_fw26[df_sim_fw26['RUN'] == run_id]
        ax.plot(sub_sim['DAP'], sub_sim['CHFPW'] / 1000.0, color=col, lw=2.0, label=f"Sim {lbl}")
        sub_obs = df_t26[df_t26['TRNO'] == trt_id].dropna(subset=['CHFPW'])
        dap_obs = pd.to_datetime(sub_obs['DATE']) - pd.to_datetime("2026-03-14") # 26073 is March 14
        ax.scatter(dap_obs.dt.days, sub_obs['CHFPW'] / 1000.0, color=col, s=40, edgecolors='k', zorder=5, label=f"Obs {lbl}")
    ax.set_ylim(0, 85)
    ax.legend(loc='upper left', fontsize=8.5, ncol=2)
    ax.grid(True)

    # 26SP Moderate Water (W2)
    ax = axes[1, 0]
    ax.set_title("(d) 2026 Spring: Moderate Irrigation (W2)", fontsize=12, fontweight='bold', loc='left')
    ax.set_xlabel("Days After Planting (DAP)", fontsize=11)
    ax.set_ylabel("Cumulative Fresh Fruit Yield ($t\\cdot ha^{-1}$)", fontsize=11)
    tmts_26_w2 = [(2, 2, "W2N3", C_N3), (5, 5, "W2N2", C_N2), (8, 8, "W2N1", C_N1), (11, 11, "W2N0", C_N0)]
    for run_id, trt_id, lbl, col in tmts_26_w2:
        sub_sim = df_sim_fw26[df_sim_fw26['RUN'] == run_id]
        ax.plot(sub_sim['DAP'], sub_sim['CHFPW'] / 1000.0, color=col, lw=2.0, label=f"Sim {lbl}")
        sub_obs = df_t26[df_t26['TRNO'] == trt_id].dropna(subset=['CHFPW'])
        dap_obs = pd.to_datetime(sub_obs['DATE']) - pd.to_datetime("2026-03-14")
        ax.scatter(dap_obs.dt.days, sub_obs['CHFPW'] / 1000.0, color=col, s=40, edgecolors='k', zorder=5, label=f"Obs {lbl}")
    ax.set_ylim(0, 85)
    ax.legend(loc='upper left', fontsize=8.5, ncol=2)
    ax.grid(True)

    # 26SP Deficit Water (W1)
    ax = axes[1, 1]
    ax.set_title("(e) 2026 Spring: Deficit Irrigation (W1)", fontsize=12, fontweight='bold', loc='left')
    ax.set_xlabel("Days After Planting (DAP)", fontsize=11)
    ax.set_ylabel("Cumulative Fresh Fruit Yield ($t\\cdot ha^{-1}$)", fontsize=11)
    tmts_26_w1 = [(3, 3, "W1N3", C_N3), (6, 6, "W1N2", C_N2), (10, 10, "W1N1", C_N1), (12, 12, "W1N0", C_N0)]
    for run_id, trt_id, lbl, col in tmts_26_w1:
        sub_sim = df_sim_fw26[df_sim_fw26['RUN'] == run_id]
        ax.plot(sub_sim['DAP'], sub_sim['CHFPW'] / 1000.0, color=col, lw=2.0, label=f"Sim {lbl}")
        sub_obs = df_t26[df_t26['TRNO'] == trt_id].dropna(subset=['CHFPW'])
        dap_obs = pd.to_datetime(sub_obs['DATE']) - pd.to_datetime("2026-03-14")
        ax.scatter(dap_obs.dt.days, sub_obs['CHFPW'] / 1000.0, color=col, s=40, edgecolors='k', zorder=5, label=f"Obs {lbl}")
    ax.set_ylim(0, 85)
    ax.legend(loc='upper left', fontsize=8.5, ncol=2)
    ax.grid(True)

    # 25FA Independent Generalization Season
    ax = axes[1, 2]
    ax.set_title("(f) 2025 Autumn: Independent Test Season", fontsize=12, fontweight='bold', loc='left')
    ax.set_xlabel("Days After Planting (DAP)", fontsize=11)
    ax.set_ylabel("Cumulative Fresh Fruit Yield ($t\\cdot ha^{-1}$)", fontsize=11)
    tmts_fa = [(1, 1, "W3N3", C_N3), (9, 9, "W3N0", C_N0), (2, 2, "W2N3", C_N2), (3, 3, "W1N3", C_N1)]
    # 25FA terminal points
    df_detail = pd.read_csv(RUN_DIR / "candidates_treatments_detail.csv")
    df_detail_fa = df_detail[(df_detail['candidate'] == 'iter5_real13') & (df_detail['season'] == '25FA')]
    for run_id, trt_id, lbl, col in tmts_fa:
        sub_sim = df_sim_fwfa[df_sim_fwfa['RUN'] == run_id]
        ax.plot(sub_sim['DAP'], sub_sim['CHFPW'] / 1000.0, color=col, lw=2.0, label=f"Sim {lbl}")
        row = df_detail_fa[df_detail_fa['treatment'] == trt_id]
        if not row.empty:
            obs_term = row['obs_terminal_kg_ha'].values[0] / 1000.0
            ax.scatter([85], [obs_term], color=col, s=50, marker='s', edgecolors='k', zorder=5, label=f"Obs {lbl}")
    ax.set_ylim(0, 25)
    ax.legend(loc='upper left', fontsize=8.5, ncol=2)
    ax.grid(True)

    plt.tight_layout()
    fig.savefig(OUT_FIG_DIR / "Fig2_Cumulative_Fruit_Yield_Dynamics.png", dpi=300, bbox_inches='tight')
    fig.savefig(OUT_FIG_DIR / "Fig2_Cumulative_Fruit_Yield_Dynamics.pdf", bbox_inches='tight')
    plt.close()
    print("Saved Fig2_Cumulative_Fruit_Yield_Dynamics.png and .pdf")


# -------------------------------------------------------------
# 3. Figure 3: 1:1 Observed vs Simulated Scatter Plots
# -------------------------------------------------------------
def plot_figure_3():
    print("Generating Figure 3: Model Evaluation 1:1 Scatter Plots...")
    df_detail = pd.read_csv(RUN_DIR / "candidates_treatments_detail.csv")
    df13 = df_detail[df_detail['candidate'] == 'iter5_real13'].copy()

    p25_dir = RUN_DIR / "full_season_iter5_real13_25SP"
    p26_dir = RUN_DIR / "full_season_iter5_real13_26SP"
    df_proc25 = pd.read_csv(p25_dir / "25SP_deterministic_process_compare.csv")
    df_proc26 = pd.read_csv(p26_dir / "26SP_deterministic_process_compare.csv")
    df_proc = pd.concat([df_proc25, df_proc26], ignore_index=True)
    df_proc['OBS_CWAD'] = (df_proc['OBS_LWAD'] + df_proc['OBS_SWAD']) / 1000.0 # t/ha
    df_proc['SIM_CWAD'] = (df_proc['SIM_LWAD'] + df_proc['SIM_SWAD']) / 1000.0 # t/ha

    fig, axes = plt.subplots(2, 2, figsize=(12, 11))

    # Helper function for scatter panel
    def make_panel(ax, obs, sim, title, xlabel, ylabel, lims, is_yield=False, batch_series=None):
        valid = (~np.isnan(obs)) & (~np.isnan(sim)) & (obs > -90) & (sim > -90)
        x, y = np.array(obs)[valid], np.array(sim)[valid]
        n = len(x)
        rmse = np.sqrt(np.mean((y - x)**2))
        nrmse = (rmse / np.mean(x)) * 100.0
        d_denom = np.sum((np.abs(y - np.mean(x)) + np.abs(x - np.mean(x)))**2)
        d = 1.0 - np.sum((y - x)**2) / d_denom
        r2 = np.corrcoef(x, y)[0, 1]**2 if n > 1 else 0
        nse = 1.0 - np.sum((y - x)**2) / np.sum((x - np.mean(x))**2)

        # 1:1 Line
        ax.plot(lims, lims, color='gray', ls='--', lw=1.2, zorder=2, label='1:1 Line')

        # Regression line
        poly = np.polyfit(x, y, 1)
        x_line = np.linspace(lims[0], lims[1], 100)
        ax.plot(x_line, np.polyval(poly, x_line), color='#2980B9', ls='-', lw=1.8, zorder=3, label=f'Fit: y = {poly[0]:.2f}x + {poly[1]:.2f}')

        if is_yield and batch_series is not None:
            batches = batch_series[valid]
            # Calibration (8 tmts)
            mask_cal = (batches == 'Calibration')
            ax.scatter(x[mask_cal], y[mask_cal], color='#E74C3C', marker='o', s=55, edgecolors='k', zorder=5, label='Calibration (n=8)')
            # Validation (15 tmts)
            mask_val = (batches == 'Validation')
            ax.scatter(x[mask_val], y[mask_val], color='#3498DB', marker='s', s=55, edgecolors='k', zorder=5, label='Validation (n=15)')
            # 25FA (12 tmts)
            mask_fa = (batches == 'Independent_25FA')
            ax.scatter(x[mask_fa], y[mask_fa], color='#2ECC71', marker='^', s=60, edgecolors='k', zorder=5, label='Independent 25FA (n=12)')
        else:
            ax.scatter(x, y, color='#34495E', marker='o', s=45, alpha=0.75, edgecolors='w', lw=0.5, zorder=4)

        ax.set_title(title, fontsize=12, fontweight='bold', loc='left')
        ax.set_xlabel(xlabel, fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_xlim(lims)
        ax.set_ylim(lims)
        ax.grid(True)

        # Stats Annotation Box
        unit_str = " t/ha" if ("Yield" in title or "Biomass" in title) else (" m" if "Height" in title else "")
        stats_text = (
            f"n = {n}\n"
            f"$R^2$ = {r2:.3f}\n"
            f"RMSE = {rmse:.2f}{unit_str}\n"
            f"NRMSE = {nrmse:.1f}%\n"
            f"d-index = {d:.3f}\n"
            f"NSE = {nse:.3f}"
        )
        ax.text(0.05, 0.95, stats_text, transform=ax.transAxes, verticalalignment='top',
                fontsize=9.5, bbox=dict(boxstyle='round,pad=0.5', facecolor='#F8F9FA', edgecolor='#BDC3C7', alpha=0.9))
        ax.legend(loc='lower right', fontsize=9, frameon=True)

    # (a) Cumulative Fresh Fruit Yield
    obs_y = df13['obs_terminal_kg_ha'] / 1000.0
    sim_y = df13['sim_terminal_kg_ha'] / 1000.0
    make_panel(axes[0, 0], obs_y, sim_y, "(a) Cumulative Fresh Fruit Yield",
               "Observed Fruit Yield ($t\\cdot ha^{-1}$)", "Simulated Fruit Yield ($t\\cdot ha^{-1}$)",
               lims=(0, 85), is_yield=True, batch_series=df13['batch'])

    # (b) Leaf Area Index (LAID)
    make_panel(axes[0, 1], df_proc['OBS_LAID'], df_proc['SIM_LAID'], "(b) Leaf Area Index (LAI)",
               "Observed LAI ($m^2\\cdot m^{-2}$)", "Simulated LAI ($m^2\\cdot m^{-2}$)",
               lims=(0, 6.0))

    # (c) Shoot Dry Biomass (CWAD)
    make_panel(axes[1, 0], df_proc['OBS_CWAD'], df_proc['SIM_CWAD'], "(c) Vegetative Shoot Dry Biomass",
               "Observed Shoot Biomass ($t\\cdot ha^{-1}$)", "Simulated Shoot Biomass ($t\\cdot ha^{-1}$)",
               lims=(0, 5.0))

    # (d) Canopy Height (CHTD)
    make_panel(axes[1, 1], df_proc['OBS_CHTD'], df_proc['SIM_CHTD'], "(d) Canopy Height",
               "Observed Canopy Height (m)", "Simulated Canopy Height (m)",
               lims=(0, 2.2))

    plt.tight_layout()
    fig.savefig(OUT_FIG_DIR / "Fig3_Model_Evaluation_1to1_Scatters.png", dpi=300, bbox_inches='tight')
    fig.savefig(OUT_FIG_DIR / "Fig3_Model_Evaluation_1to1_Scatters.pdf", bbox_inches='tight')
    plt.close()
    print("Saved Fig3_Model_Evaluation_1to1_Scatters.png and .pdf")


# -------------------------------------------------------------
# 4. Figure 4: Water-Nitrogen Interactive Response & Gaps
# -------------------------------------------------------------
def plot_figure_4():
    print("Generating Figure 4: Water-Nitrogen Interactive Response...")
    df_detail = pd.read_csv(RUN_DIR / "candidates_treatments_detail.csv")
    df13 = df_detail[df_detail['candidate'] == 'iter5_real13'].copy()

    fig, axes = plt.subplots(2, 2, figsize=(13, 10))

    n_rates = [0, 150, 300, 450]
    n_keys = ['N0', 'N1', 'N2', 'N3']

    # Subpanel (A): 26SP Yield vs N Rate across W1, W2, W3
    ax_a = axes[0, 0]
    ax_a.set_title("(a) 2026 Spring: N Response under Contrasting Irrigation", fontsize=12, fontweight='bold', loc='left')
    ax_a.set_xlabel("Nitrogen Application Rate ($kg\\cdot ha^{-1}$)", fontsize=11)
    ax_a.set_ylabel("Terminal Fresh Fruit Yield ($t\\cdot ha^{-1}$)", fontsize=11)
    sub26 = df13[df13['season'] == '26SP']
    w_colors = {'W3': '#2980B9', 'W2': '#E67E22', 'W1': '#C0392B'}
    w_markers = {'W3': 'o', 'W2': 's', 'W1': '^'}
    w_labels = {'W3': 'W3 (Full: 100% ETc)', 'W2': 'W2 (Moderate: 75% ETc)', 'W1': 'W1 (Deficit: 50% ETc)'}

    for w in ['W3', 'W2', 'W1']:
        w_sub = sub26[sub26['water'] == w]
        obs_vals = [w_sub[w_sub['nitro'] == nk]['obs_terminal_kg_ha'].values[0] / 1000.0 for nk in n_keys]
        sim_vals = [w_sub[w_sub['nitro'] == nk]['sim_terminal_kg_ha'].values[0] / 1000.0 for nk in n_keys]
        ax_a.plot(n_rates, sim_vals, color=w_colors[w], lw=2.0, ls='-', label=f"Sim {w_labels[w]}")
        ax_a.scatter(n_rates, obs_vals, color=w_colors[w], marker=w_markers[w], s=55, edgecolors='k', zorder=5, label=f"Obs {w_labels[w]}")
    ax_a.set_ylim(45, 75)
    ax_a.legend(loc='lower right', fontsize=8.5)
    ax_a.grid(True)

    # Subpanel (B): 25SP Yield vs N Rate
    ax_b = axes[0, 1]
    ax_b.set_title("(b) 2025 Spring: N Response under Contrasting Irrigation", fontsize=12, fontweight='bold', loc='left')
    ax_b.set_xlabel("Nitrogen Application Rate ($kg\\cdot ha^{-1}$)", fontsize=11)
    ax_b.set_ylabel("Terminal Fresh Fruit Yield ($t\\cdot ha^{-1}$)", fontsize=11)
    sub25 = df13[df13['season'] == '25SP']
    for w in ['W3', 'W1']:
        w_sub = sub25[sub25['water'] == w]
        obs_vals = [w_sub[w_sub['nitro'] == nk]['obs_terminal_kg_ha'].values[0] / 1000.0 for nk in n_keys]
        sim_vals = [w_sub[w_sub['nitro'] == nk]['sim_terminal_kg_ha'].values[0] / 1000.0 for nk in n_keys]
        ax_b.plot(n_rates, sim_vals, color=w_colors[w], lw=2.0, ls='-', label=f"Sim {w_labels[w]}")
        ax_b.scatter(n_rates, obs_vals, color=w_colors[w], marker=w_markers[w], s=55, edgecolors='k', zorder=5, label=f"Obs {w_labels[w]}")
    # 25SP W2 (N0 and N3 only)
    w2_sub = sub25[sub25['water'] == 'W2']
    obs_w2 = [w2_sub[w2_sub['nitro'] == 'N0']['obs_terminal_kg_ha'].values[0] / 1000.0, w2_sub[w2_sub['nitro'] == 'N3']['obs_terminal_kg_ha'].values[0] / 1000.0]
    sim_w2 = [w2_sub[w2_sub['nitro'] == 'N0']['sim_terminal_kg_ha'].values[0] / 1000.0, w2_sub[w2_sub['nitro'] == 'N3']['sim_terminal_kg_ha'].values[0] / 1000.0]
    ax_b.plot([0, 450], sim_w2, color=w_colors['W2'], lw=1.8, ls='--', label="Sim W2 (N0 & N3)")
    ax_b.scatter([0, 450], obs_w2, color=w_colors['W2'], marker=w_markers['W2'], s=55, edgecolors='k', zorder=5, label="Obs W2 (N0 & N3)")
    ax_b.set_ylim(55, 80)
    ax_b.legend(loc='lower right', fontsize=8.5)
    ax_b.grid(True)

    # Subpanel (C): 25FA Yield vs N Rate
    ax_c = axes[1, 0]
    ax_c.set_title("(c) 2025 Autumn: N Response under Autumn Conditions", fontsize=12, fontweight='bold', loc='left')
    ax_c.set_xlabel("Nitrogen Application Rate ($kg\\cdot ha^{-1}$)", fontsize=11)
    ax_c.set_ylabel("Terminal Fresh Fruit Yield ($t\\cdot ha^{-1}$)", fontsize=11)
    subfa = df13[df13['season'] == '25FA']
    for w in ['W3', 'W2', 'W1']:
        w_sub = subfa[subfa['water'] == w]
        obs_vals = [w_sub[w_sub['nitro'] == nk]['obs_terminal_kg_ha'].values[0] / 1000.0 for nk in n_keys]
        sim_vals = [w_sub[w_sub['nitro'] == nk]['sim_terminal_kg_ha'].values[0] / 1000.0 for nk in n_keys]
        ax_c.plot(n_rates, sim_vals, color=w_colors[w], lw=2.0, ls='-', label=f"Sim {w}")
        ax_c.scatter(n_rates, obs_vals, color=w_colors[w], marker=w_markers[w], s=55, edgecolors='k', zorder=5, label=f"Obs {w}")
    ax_c.set_ylim(10, 22)
    ax_c.legend(loc='lower left', fontsize=8.5)
    ax_c.grid(True)

    # Subpanel (D): Nitrogen Yield Response Gap (N3 - N0) across Seasons and Water Regimes
    ax_d = axes[1, 1]
    ax_d.set_title("(d) Nitrogen Response Gap ($\Delta Y = Y_{N3} - Y_{N0}$)", fontsize=12, fontweight='bold', loc='left')
    ax_d.set_xlabel("Irrigation Regime", fontsize=11)
    ax_d.set_ylabel("Yield Gain from Nitrogen ($\Delta Y$, $t\\cdot ha^{-1}$)", fontsize=11)

    labels = ['W1 (Deficit)', 'W2 (Moderate)', 'W3 (Full)']
    x = np.arange(len(labels))
    width = 0.22

    # 26SP
    obs_gap_26 = [16.50, 9.52, 5.79]
    sim_gap_26 = [12.81, 11.32, 15.33]
    # 25SP
    obs_gap_25 = [11.59, 8.12, 4.09]
    sim_gap_25 = [-0.04, -3.93, 6.75]

    ax_d.bar(x - width, obs_gap_26, width, label='Observed (26SP)', color='#34495E', alpha=0.85)
    ax_d.bar(x, sim_gap_26, width, label='Simulated (26SP)', color='#3498DB', alpha=0.85)
    ax_d.bar(x + width, sim_gap_25, width, label='Simulated (25SP)', color='#E67E22', alpha=0.85)

    ax_d.set_xticks(x)
    ax_d.set_xticklabels(labels, fontsize=10)
    ax_d.axhline(0, color='gray', lw=0.8, ls='--')
    ax_d.legend(loc='upper right', fontsize=8.5)
    ax_d.grid(True)

    plt.tight_layout()
    fig.savefig(OUT_FIG_DIR / "Fig4_Water_Nitrogen_Interactive_Response.png", dpi=300, bbox_inches='tight')
    fig.savefig(OUT_FIG_DIR / "Fig4_Water_Nitrogen_Interactive_Response.pdf", bbox_inches='tight')
    plt.close()
    print("Saved Fig4_Water_Nitrogen_Interactive_Response.png and .pdf")


# -------------------------------------------------------------
# 5. Figure 5: Genetic Parameters Shift (Eggplant vs Tomato)
# -------------------------------------------------------------
def plot_figure_5():
    print("Generating Figure 5: Genetic Parameter Shifts...")
    df_t1 = pd.read_csv('scratch/table1_genetic_parameters.csv')
    
    # Filter to most representative calibrated parameters across the 5 domains
    selected_params = [
        # Phenology
        ('FL-LF', 'Phenology', 'FL-LF (Leaf expansion duration)'),
        ('SD-PM', 'Phenology', 'SD-PM (Seed to maturity duration)'),
        ('FL-VS', 'Phenology', 'FL-VS (Veg growth past flowering)'),
        ('TRIFL', 'Phenology', 'TRIFL (Leaf appearance rate)'),
        ('EM-FL', 'Phenology', 'EM-FL (Emergence to flower)'),
        # Canopy & Architecture
        ('LFMAX', 'Canopy', 'LFMAX (Max leaf photosynthesis)'),
        ('SLAVR', 'Canopy', 'SLAVR (Specific leaf area)'),
        ('SIZLF', 'Canopy', 'SIZLF (Max single leaf size)'),
        ('RWDTH', 'Canopy', 'RWDTH (Canopy width multiplier)'),
        # Fruit Partitioning
        ('SFDUR', 'Fruit', 'SFDUR (Seed filling duration)'),
        ('PODUR', 'Fruit', 'PODUR (Cohort pod duration)'),
        ('PM06', 'Fruit', 'PM06 (Late fill 60% transition)'),
        ('PM09', 'Fruit', 'PM09 (Late fill 90% transition)'),
        ('LNGSH', 'Fruit', 'LNGSH (Fruit addition window)'),
        ('XMAGE', 'Fruit', 'XMAGE (Harvest readiness age)'),
        ('THRSH', 'Fruit', 'THRSH (Shell-to-pod ratio)'),
        # Nitrogen Relations
        ('RTNO3', 'Nitrogen', 'RTNO3 (Max NO3 uptake rate)'),
        ('RTNH4', 'Nitrogen', 'RTNH4 (Max NH4 uptake rate)'),
        ('NMOBMX', 'Nitrogen', 'NMOBMX (Max N remobilization)'),
        ('NVSMOB', 'Nitrogen', 'NVSMOB (Vegetative N mobilization)'),
        ('LNREF', 'Nitrogen', 'LNREF (Reference leaf N)'),
        ('PROLFF', 'Nitrogen', 'PROLFF (Residual leaf protein)'),
        # Drought & Senescence
        ('SENRTE', 'Drought/Sen', 'SENRTE (Senescence per N lost)'),
        ('SENDAY', 'Drought/Sen', 'SENDAY (Daily leaf senescence)'),
        ('DSWBAR', 'Drought/Sen', 'DSWBAR (Dry layer depth threshold)'),
        ('SWBAR_REC', 'Drought/Sen', 'SWBAR_REC (Soil water stress threshold)'),
    ]

    plot_rows = []
    for code, group, desc in selected_params:
        sub = df_t1[df_t1['param'] == code]
        if not sub.empty:
            pct = sub['change_pct'].values[0]
            # Cap extreme visual display for readability with annotations
            plot_rows.append({
                'code': code,
                'desc': desc,
                'group': group,
                'change_pct': pct
            })

    df_p = pd.DataFrame(plot_rows)

    fig, ax = plt.subplots(figsize=(11, 10))

    group_colors = {
        'Phenology': '#E74C3C',
        'Canopy': '#3498DB',
        'Fruit': '#2ECC71',
        'Nitrogen': '#F39C12',
        'Drought/Sen': '#9B59B6'
    }

    y_pos = np.arange(len(df_p))
    bars = []
    for i, r in df_p.iterrows():
        # Capping display bar at [-100, +250] for balanced visual, annotate true value
        display_val = min(max(r['change_pct'], -85), 250)
        c = group_colors[r['group']]
        b = ax.barh(i, display_val, color=c, alpha=0.85, edgecolor='#333333', lw=0.6)
        bars.append(b)
        
        # Label text
        val_str = f"{r['change_pct']:+.1f}%"
        offset = 5 if display_val >= 0 else -5
        ha = 'left' if display_val >= 0 else 'right'
        ax.text(display_val + offset, i, val_str, va='center', ha=ha, fontsize=8.5, fontweight='bold', color='#2C3E50')

    ax.set_yticks(y_pos)
    ax.set_yticklabels(df_p['desc'], fontsize=9.5)
    ax.invert_yaxis()  # top-down
    ax.axvline(0, color='k', lw=1.0)
    ax.set_xlabel("Relative Shift from Reference Tomato (Florida 47) [%]", fontsize=11, fontweight='bold')
    ax.set_title("Systematic Divergence of Calibrated Eggplant Genetic Parameters\nRelative to Baseline Tomato (TMGRO048)",
                 fontsize=12, fontweight='bold', loc='left', pad=15)
    ax.set_xlim(-110, 310)
    ax.grid(True, axis='x')

    # Legend for physiological functional groups
    legend_patches = [Patch(color=col, label=grp) for grp, col in group_colors.items()]
    ax.legend(handles=legend_patches, loc='lower right', title='Physiological Group', fontsize=9.5, title_fontsize=10, frameon=True)

    plt.tight_layout()
    fig.savefig(OUT_FIG_DIR / "Fig5_Genetic_Parameters_Divergence.png", dpi=300, bbox_inches='tight')
    fig.savefig(OUT_FIG_DIR / "Fig5_Genetic_Parameters_Divergence.pdf", bbox_inches='tight')
    plt.close()
    print("Saved Fig5_Genetic_Parameters_Divergence.png and .pdf")


# -------------------------------------------------------------
# 6. Figure 6: Incremental Multi-Harvest Dynamics
# -------------------------------------------------------------
def plot_figure_6():
    print("Generating Figure 6: Incremental Harvest Dynamics...")
    p25_dir = RUN_DIR / "full_season_iter5_real13_25SP"
    p26_dir = RUN_DIR / "full_season_iter5_real13_26SP"

    df_t25 = pd.read_csv(p25_dir / "FileT_values.csv")
    df_t26 = pd.read_csv(p26_dir / "FileT_values.csv")

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    # Helper function to compute incremental harvest from cumulative
    def get_incremental(sub_t):
        sub_t = sub_t.dropna(subset=['CHFPW']).sort_values('DATE')
        cum_vals = sub_t['CHFPW'].values / 1000.0 # t/ha
        inc_vals = np.diff(cum_vals, prepend=0)
        return sub_t['DATE'].values, inc_vals

    # 25SP: Contrast W3N3 vs W3N0 vs W1N3 vs W1N0
    ax_a = axes[0]
    ax_a.set_title("(a) 2025 Spring: Individual Harvest Pickings", fontsize=12, fontweight='bold', loc='left')
    ax_a.set_xlabel("Harvest Date", fontsize=11)
    ax_a.set_ylabel("Incremental Fresh Yield ($t\\cdot ha^{-1}\\cdot harvest^{-1}$)", fontsize=11)

    tmts_25 = [(2, "W3N3 (Full W, High N)", C_N3, 'o-'),
               (5, "W3N0 (Full W, Zero N)", C_N0, 's--'),
               (10, "W1N3 (Deficit W, High N)", C_N1, '^-'),
               (13, "W1N0 (Deficit W, Zero N)", '#7F8C8D', 'd:')]

    for trt_id, lbl, col, fmt in tmts_25:
        sub = df_t25[df_t25['TRNO'] == trt_id]
        dates, inc = get_incremental(sub)
        dates_dt = pd.to_datetime(dates)
        ax_a.plot(dates_dt, inc, fmt, color=col, lw=1.8, ms=6, label=lbl)

    ax_a.set_ylim(0, 15)
    ax_a.tick_params(axis='x', rotation=30)
    ax_a.legend(loc='upper right', fontsize=8.5)
    ax_a.grid(True)

    # 26SP: Contrast W3N3 vs W3N0 vs W1N3 vs W1N0
    ax_b = axes[1]
    ax_b.set_title("(b) 2026 Spring: Individual Harvest Pickings", fontsize=12, fontweight='bold', loc='left')
    ax_b.set_xlabel("Harvest Date", fontsize=11)
    ax_b.set_ylabel("Incremental Fresh Yield ($t\\cdot ha^{-1}\\cdot harvest^{-1}$)", fontsize=11)

    tmts_26 = [(1, "W3N3 (Full W, High N)", C_N3, 'o-'),
               (9, "W3N0 (Full W, Zero N)", C_N0, 's--'),
               (3, "W1N3 (Deficit W, High N)", C_N1, '^-'),
               (12, "W1N0 (Deficit W, Zero N)", '#7F8C8D', 'd:')]

    for trt_id, lbl, col, fmt in tmts_26:
        sub = df_t26[df_t26['TRNO'] == trt_id]
        dates, inc = get_incremental(sub)
        dates_dt = pd.to_datetime(dates)
        ax_b.plot(dates_dt, inc, fmt, color=col, lw=1.8, ms=6, label=lbl)

    ax_b.set_ylim(0, 24)
    ax_b.tick_params(axis='x', rotation=30)
    ax_b.legend(loc='upper right', fontsize=8.5)
    ax_b.grid(True)

    plt.tight_layout()
    fig.savefig(OUT_FIG_DIR / "Fig6_Incremental_Harvest_Dynamics.png", dpi=300, bbox_inches='tight')
    fig.savefig(OUT_FIG_DIR / "Fig6_Incremental_Harvest_Dynamics.pdf", bbox_inches='tight')
    plt.close()
    print("Saved Fig6_Incremental_Harvest_Dynamics.png and .pdf")


def main():
    plot_figure_1()
    plot_figure_2()
    plot_figure_3()
    plot_figure_4()
    plot_figure_5()
    plot_figure_6()
    print(f"\nAll 6 paper figures rendered successfully into {OUT_FIG_DIR.resolve()}!")


if __name__ == "__main__":
    main()
