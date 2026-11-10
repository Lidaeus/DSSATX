import os
import sys
import shutil
import subprocess
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib as mpl

PROJECT_ROOT = Path("D:/Tomato_Cal")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.reporting.analyze_results import deterministic_process_compare, deterministic_harvest_compare
from tools.calibration.plot_diagnostic_custom import (
    plot_candidate_nitrogen_response,
    plot_candidate_low_n_canopy,
    MAPPING_CSV
)

# Candidate configurations
CANDIDATES = [
    {
        "id": "C23",
        "real": "194",
        "label": "Candidate C23 (real194 - Spring Precision 6.00% & Strict Physiological Contract)",
        "case_dir": PROJECT_ROOT / "scratch/screen_final_200x8/iter8_real194",
        "out_dir": PROJECT_ROOT / "figture/candidate_c23_real194_3season_suite"
    },
    {
        "id": "C24",
        "real": "130",
        "label": "Candidate C24 (real130 - Grand Minimum NRMSE 11.22% & d=0.9874)",
        "case_dir": PROJECT_ROOT / "scratch/screen_final_200x8/iter8_real130",
        "out_dir": PROJECT_ROOT / "figture/candidate_c24_real130_3season_suite"
    },
    {
        "id": "C25",
        "real": "85",
        "label": "Candidate C25 (real85 - Final Post-Swap Evolution & 25SP NRMSE=7.28%)",
        "case_dir": PROJECT_ROOT / "scratch/screen_final_200x8/iter8_real85",
        "out_dir": PROJECT_ROOT / "figture/candidate_c25_real85_3season_suite"
    }
]

def prepare_candidate_comparisons(cand):
    case_dir = cand["case_dir"]
    sdir_25sp = case_dir / "25SP"
    sdir_26sp = case_dir / "26SP"
    sdir_25fa = case_dir / "25FA"
    
    proc_vars = ["LAID", "LWAD", "SWAD"]
    
    # Ensure yield file exists as all_35_treatments_final_yield.csv
    src_y = case_dir / f"iter8_real{cand['real']}_35trt_yield.csv"
    dst_y = case_dir / "all_35_treatments_final_yield.csv"
    if src_y.exists() and not dst_y.exists():
        shutil.copy2(src_y, dst_y)
    
    # Generate compare CSVs
    deterministic_process_compare("25SP", str(sdir_25sp / "DSSBatch.v48"), var_names=proc_vars, run_dir=str(sdir_25sp))
    deterministic_harvest_compare("25SP", str(sdir_25sp / "DSSBatch.v48"), run_dir=str(sdir_25sp))
    
    deterministic_process_compare("26SP", str(sdir_26sp / "DSSBatch.v48"), var_names=proc_vars, run_dir=str(sdir_26sp))
    deterministic_harvest_compare("26SP", str(sdir_26sp / "DSSBatch.v48"), run_dir=str(sdir_26sp))
    
    deterministic_process_compare("25FA", str(sdir_25fa / "DSSBatch.v48"), var_names=proc_vars, run_dir=str(sdir_25fa))
    deterministic_harvest_compare("25FA", str(sdir_25fa / "DSSBatch.v48"), run_dir=str(sdir_25fa))
    
    # Setup _seasons folder for plot_dynamics.py
    seasons_dir = case_dir / "_seasons"
    seasons_dir.mkdir(parents=True, exist_ok=True)
    
    for s, s_src in [("25SP", sdir_25sp), ("26SP", sdir_26sp), ("25FA", sdir_25fa)]:
        s_dest = seasons_dir / s
        s_dest.mkdir(parents=True, exist_ok=True)
        for fname in [f"{s}_deterministic_process_compare.csv", f"{s}_deterministic_harvest_compare.csv", "PlantGro.OUT", "FreshWt.OUT"]:
            src_f = s_src / fname
            if src_f.exists():
                shutil.copy2(src_f, s_dest / fname)

def run_candidate_dynamics(cand):
    case_dir = cand["case_dir"]
    out_dir = cand["out_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "tools/calibration/plot_dynamics.py"),
        "--det-root", str(case_dir),
        "--out-root", str(out_dir),
        "--seasons", "25SP,26SP,25FA",
        "--mapping-csv", str(MAPPING_CSV),
        "--include-all-treatments"
    ]
    print(f"[{cand['id']}] Running plot_dynamics.py -> {out_dir}")
    res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[{cand['id']}] Error running plot_dynamics:\n", res.stderr)
        raise RuntimeError(f"plot_dynamics failed for {cand['id']}")
    print(f"[{cand['id']}] plot_dynamics complete.")

def run_targeted_diagnostics(cand):
    out_dir = cand["out_dir"]
    # 1. High-N Yield Depression Diagnostic
    plot_candidate_nitrogen_response(
        cand["case_dir"],
        cand["label"],
        out_dir / "diagnostic_high_n_yield_depression.png"
    )
    # 2. Low-N Canopy Health Diagnostic
    plot_candidate_low_n_canopy(
        cand["case_dir"],
        cand["label"],
        out_dir / "diagnostic_low_n_canopy_health.png"
    )

def generate_tri_candidate_comparison():
    out_comp = PROJECT_ROOT / "figture/candidates_c23_c24_c25_comparison"
    out_comp.mkdir(parents=True, exist_ok=True)
    
    # Load screening summary
    screen_df = pd.read_csv(PROJECT_ROOT / "scratch/screen_final_200x8/final_200x8_screening_summary.csv")
    reals = ["iter8_real194", "iter8_real130", "iter8_real85"]
    labels = ["C23 (real194)", "C24 (real130)", "C25 (real85)"]
    
    sub_df = screen_df[screen_df["label"].isin(reals)].copy()
    sub_df["candidate_id"] = ["C24" if "130" in l else ("C23" if "194" in l else "C25") for l in sub_df["label"]]
    sub_df.to_csv(out_comp / "candidates_3season_comparison_summary.csv", index=False)
    
    mpl.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans", "Arial"],
        "axes.unicode_minus": False,
        "figure.dpi": 200,
        "savefig.dpi": 200
    })
    
    fig, axes = plt.subplots(2, 2, figsize=(15, 11))
    x = np.arange(len(labels))
    width = 0.2
    
    # Subplot 1: NRMSE breakdown across seasons
    ax = axes[0, 0]
    nrmse_25 = [sub_df[sub_df["label"]==r]["25SP_NRMSE"].values[0] for r in reals]
    nrmse_26 = [sub_df[sub_df["label"]==r]["26SP_NRMSE"].values[0] for r in reals]
    nrmse_fa = [sub_df[sub_df["label"]==r]["25FA_NRMSE"].values[0] for r in reals]
    nrmse_gr = [sub_df[sub_df["label"]==r]["Grand_NRMSE"].values[0] for r in reals]
    
    ax.bar(x - 1.5*width, nrmse_25, width, label="2025 Spring (25SP, 11 Trts)", color="#3498db")
    ax.bar(x - 0.5*width, nrmse_26, width, label="2026 Spring (26SP, 12 Trts)", color="#e67e22")
    ax.bar(x + 0.5*width, nrmse_fa, width, label="2025 Autumn Blind (25FA, 12 Trts)", color="#2ecc71")
    ax.bar(x + 1.5*width, nrmse_gr, width, label="Grand Pooled (35 Trts)", color="#9b59b6")
    
    ax.set_ylabel("NRMSE (%)", fontsize=11, fontweight="bold")
    ax.set_title("1. Accuracy Across Seasons (NRMSE %)", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.4, axis="y")
    ax.legend(fontsize=9)
    for i in range(len(labels)):
        ax.text(x[i] - 1.5*width, nrmse_25[i] + 0.3, f"{nrmse_25[i]:.1f}%", ha="center", fontsize=8.5, fontweight="bold", color="#2980b9")
        ax.text(x[i] + 1.5*width, nrmse_gr[i] + 0.3, f"{nrmse_gr[i]:.1f}%", ha="center", fontsize=8.5, fontweight="bold", color="#8e44ad")
    
    # Subplot 2: Agreement Metrics (d-index & NSE)
    ax = axes[0, 1]
    d_vals = [sub_df[sub_df["label"]==r]["Grand_d_index"].values[0] for r in reals]
    nse_vals = [sub_df[sub_df["label"]==r]["Grand_NSE"].values[0] for r in reals]
    
    ax.bar(x - width/2, d_vals, width, label="Grand Willmott d-index", color="#1abc9c")
    ax.bar(x + width/2, nse_vals, width, label="Grand NSE", color="#e74c3c")
    ax.set_ylabel("Metric Value", fontsize=11, fontweight="bold")
    ax.set_title("2. Agreement & Efficiency (d-index & NSE)", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, fontweight="bold")
    ax.set_ylim([0.90, 1.00])
    ax.grid(True, linestyle="--", alpha=0.4, axis="y")
    ax.legend(fontsize=9, loc="lower right")
    for i in range(len(labels)):
        ax.text(x[i] - width/2, d_vals[i] + 0.002, f"{d_vals[i]:.4f}", ha="center", fontsize=9, fontweight="bold")
        ax.text(x[i] + width/2, nse_vals[i] + 0.002, f"{nse_vals[i]:.4f}", ha="center", fontsize=9, fontweight="bold")
        
    # Subplot 3: 25SP W2 Inversion Fix & W2 N Response Gap (N3 - N0, t/ha)
    ax = axes[1, 0]
    w2_gap = [sub_df[sub_df["label"]==r]["25SP_W2_Ngap"].values[0] for r in reals]
    w2n0_bias = [sub_df[sub_df["label"]==r]["25SP_W2N0_bias%"].values[0] for r in reals]
    
    ax.bar(x - width/2, w2_gap, width, label="25SP W2 N Response Gap (N3 - N0, t/ha)", color="#27ae60")
    ax.bar(x + width/2, w2n0_bias, width, label="25SP W2N0 Yield Bias (%)", color="#e67e22")
    ax.axhline(0, color="black", lw=1)
    ax.set_ylabel("Value (t/ha or %)", fontsize=11, fontweight="bold")
    ax.set_title("3. 25SP W2 Inversion Fix: Robust Gap & W2N0 Bias Convergence", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.4, axis="y")
    ax.legend(fontsize=9, loc="upper right")
    for i in range(len(labels)):
        ax.text(x[i] - width/2, w2_gap[i] + 0.3, f"+{w2_gap[i]:.1f} t/ha", ha="center", fontsize=9, fontweight="bold", color="#27ae60")
        ax.text(x[i] + width/2, w2n0_bias[i] - 1.5, f"{w2n0_bias[i]:.1f}%", ha="center", fontsize=9, fontweight="bold", color="#d35400")

    # Subplot 4: High-N Yield Depression (Delta Y_N3 - Y_N2, kg/ha)
    ax = axes[1, 1]
    dep_25w1 = [sub_df[sub_df["label"]==r]["25SP_N3_N2_W1"].values[0] * 1000.0 for r in reals]
    dep_26w3 = [sub_df[sub_df["label"]==r]["26SP_N3_N2_W3"].values[0] * 1000.0 for r in reals]
    
    ax.bar(x - width/2, dep_25w1, width, label="25SP W1 (N3 - N2, kg/ha)", color="#e74c3c")
    ax.bar(x + width/2, dep_26w3, width, label="26SP W3 (N3 - N2, kg/ha)", color="#34495e")
    ax.axhline(0, color="black", lw=1)
    ax.set_ylabel("Yield Difference (kg/ha)", fontsize=11, fontweight="bold")
    ax.set_title("4. High-N Yield Depression (N3 - N2, kg/ha)", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.4, axis="y")
    ax.legend(fontsize=9, loc="upper right")
    for i in range(len(labels)):
        ax.text(x[i] - width/2, dep_25w1[i] - 35, f"{dep_25w1[i]:.0f} kg", ha="center", fontsize=9, fontweight="bold", color="#c0392b")
        ax.text(x[i] + width/2, (dep_26w3[i] + 35 if dep_26w3[i] >= 0 else dep_26w3[i] - 35), f"{dep_26w3[i]:+.0f} kg", ha="center", fontsize=9, fontweight="bold", color="#2c3e50")
        
    fig.suptitle("Final Calibration Verification Matrix: C23 (real194) vs C24 (real130) vs C25 (real85)",
                 fontsize=15, fontweight="bold", y=1.02)
    plt.tight_layout()
    comp_png = out_comp / "diagnostic_tri_candidate_comparison.png"
    plt.savefig(comp_png, bbox_inches="tight")
    plt.close()
    print(f"Saved: {comp_png}")

def main():
    print("=" * 75)
    print("Starting Comprehensive 3-Season Diagnostic Suite for C23, C24, C25")
    print("=" * 75)
    
    for cand in CANDIDATES:
        print(f"\n>>> Processing {cand['label']}...")
        prepare_candidate_comparisons(cand)
        run_candidate_dynamics(cand)
        run_targeted_diagnostics(cand)
        
    print("\n>>> Generating Tri-Candidate Comparative Diagnostic...")
    generate_tri_candidate_comparison()
    
    print("\n" + "=" * 75)
    print("All Diagnostic Suites Successfully Generated!")
    print("Output locations:")
    for cand in CANDIDATES:
        print(f"  - {cand['id']}: {cand['out_dir']}")
    print(f"  - Comparison: {PROJECT_ROOT / 'figture/candidates_c23_c24_c25_comparison'}")
    print("=" * 75)

if __name__ == "__main__":
    main()
