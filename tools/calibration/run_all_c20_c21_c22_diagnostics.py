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
        "id": "C20",
        "real": 126,
        "label": "Candidate C20 (real126 - 3-Season Champion & High-N Depression)",
        "case_dir": PROJECT_ROOT / "scratch/screen_fnpgn3_real_sh2o/iter6_real126",
        "out_dir": PROJECT_ROOT / "figture/candidate_c20_real126_3season_suite"
    },
    {
        "id": "C21",
        "real": 21,
        "label": "Candidate C21 (real21 - Spring High-Precision 7.9% & High-N Depression)",
        "case_dir": PROJECT_ROOT / "scratch/screen_fnpgn3_real_sh2o/iter6_real21",
        "out_dir": PROJECT_ROOT / "figture/candidate_c21_real21_3season_suite"
    },
    {
        "id": "C22",
        "real": 85,
        "label": "Candidate C22 (real85 - Grand Minimum NRMSE 11.89% & Robust Depression)",
        "case_dir": PROJECT_ROOT / "scratch/screen_fnpgn3_real_sh2o/iter6_real85",
        "out_dir": PROJECT_ROOT / "figture/candidate_c22_real85_3season_suite"
    }
]

def prepare_candidate_comparisons(cand):
    case_dir = cand["case_dir"]
    sdir_25sp = case_dir / "25SP"
    sdir_26sp = case_dir / "26SP"
    sdir_25fa = case_dir / "25FA"
    
    proc_vars = ["LAID", "LWAD", "SWAD"]
    
    # Generate compare CSVs
    deterministic_process_compare("25SP", str(sdir_25sp / "DSSBatch.v48"), var_names=proc_vars, run_dir=str(sdir_25sp))
    deterministic_harvest_compare("25SP", str(sdir_25sp / "DSSBatch.v48"), run_dir=str(sdir_25sp))
    
    deterministic_process_compare("26SP", str(sdir_26sp / "DSSBatch_26SP_all.v48"), var_names=proc_vars, run_dir=str(sdir_26sp))
    deterministic_harvest_compare("26SP", str(sdir_26sp / "DSSBatch_26SP_all.v48"), run_dir=str(sdir_26sp))
    
    deterministic_process_compare("25FA", str(sdir_25fa / "DSSBatch_25FA_all.v48"), var_names=proc_vars, run_dir=str(sdir_25fa))
    deterministic_harvest_compare("25FA", str(sdir_25fa / "DSSBatch_25FA_all.v48"), run_dir=str(sdir_25fa))
    
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
    out_comp = PROJECT_ROOT / "figture/candidates_c20_c21_c22_comparison"
    out_comp.mkdir(parents=True, exist_ok=True)
    
    bm_file = PROJECT_ROOT / "workspace/candidates/all_candidates_3season_benchmark_matrix.csv"
    df_bm = pd.read_csv(bm_file)
    
    target_cands = ["C20_real126", "C21_real21", "C22_real85"]
    sub_bm = df_bm[df_bm["candidate"].isin(target_cands)].copy()
    sub_bm.to_csv(out_comp / "candidates_3season_comparison_summary.csv", index=False)
    
    mpl.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial"],
        "axes.unicode_minus": False,
        "figure.dpi": 200,
        "savefig.dpi": 200
    })
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    labels = ["C20 (real126)", "C21 (real21)", "C22 (real85)"]
    cands = ["C20_real126", "C21_real21", "C22_real85"]
    x = np.arange(len(labels))
    width = 0.2
    
    # Subplot 1: NRMSE breakdown across seasons
    ax = axes[0, 0]
    nrmse_25 = [df_bm[df_bm["candidate"]==c]["25SP_NRMSE_pct"].values[0] for c in cands]
    nrmse_26 = [df_bm[df_bm["candidate"]==c]["26SP_NRMSE_pct"].values[0] for c in cands]
    nrmse_fa = [df_bm[df_bm["candidate"]==c]["25FA_NRMSE_pct"].values[0] for c in cands]
    nrmse_gr = [df_bm[df_bm["candidate"]==c]["Grand_NRMSE_pct"].values[0] for c in cands]
    
    ax.bar(x - 1.5*width, nrmse_25, width, label="2025 Spring (25SP)", color="#3498db")
    ax.bar(x - 0.5*width, nrmse_26, width, label="2026 Spring (26SP)", color="#e67e22")
    ax.bar(x + 0.5*width, nrmse_fa, width, label="2025 Autumn Blind (25FA)", color="#2ecc71")
    ax.bar(x + 1.5*width, nrmse_gr, width, label="Grand Pooled (35 Trts)", color="#9b59b6")
    
    ax.set_ylabel("NRMSE (%)", fontsize=11, fontweight="bold")
    ax.set_title("1. Accuracy Across Seasons (NRMSE %)", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.4, axis="y")
    ax.legend(fontsize=9)
    for i in range(len(labels)):
        ax.text(x[i] + 1.5*width, nrmse_gr[i] + 0.3, f"{nrmse_gr[i]:.1f}%", ha="center", fontsize=9, fontweight="bold")
    
    # Subplot 2: Agreement Metrics (d-index & NSE)
    ax = axes[0, 1]
    d_vals = [df_bm[df_bm["candidate"]==c]["Grand_d"].values[0] for c in cands]
    nse_vals = [df_bm[df_bm["candidate"]==c]["Grand_NSE"].values[0] for c in cands]
    
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
        
    # Subplot 3: High-N Yield Depression (Delta Y_N3 - Y_N2, kg/ha)
    ax = axes[1, 0]
    # Read depression deltas
    screen_df = pd.read_csv(PROJECT_ROOT / "scratch/screen_fnpgn3_real_sh2o/fnpgn3_real_sh2o_screening_summary.csv")
    reals = ["iter6_real126", "iter6_real21", "iter6_real85"]
    dep_25w1 = [screen_df[screen_df["label"]==r]["25SP_N3_N2_W1"].values[0] * 1000.0 for r in reals]
    dep_26w1 = [screen_df[screen_df["label"]==r]["26SP_N3_N2_W1"].values[0] * 1000.0 for r in reals]
    
    ax.bar(x - width/2, dep_25w1, width, label="25SP W1 (N3 - N2)", color="#e74c3c")
    ax.bar(x + width/2, dep_26w1, width, label="26SP W1 (N3 - N2)", color="#34495e")
    ax.axhline(0, color="black", lw=1)
    ax.set_ylabel("Yield Difference (kg/ha)", fontsize=11, fontweight="bold")
    ax.set_title("3. High-N Yield Depression (N3 - N2, kg/ha)", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, fontweight="bold")
    ax.grid(True, linestyle="--", alpha=0.4, axis="y")
    ax.legend(fontsize=9)
    for i in range(len(labels)):
        ax.text(x[i] - width/2, dep_25w1[i] - 30, f"{dep_25w1[i]:.0f}", ha="center", fontsize=9, fontweight="bold", color="#e74c3c")
        ax.text(x[i] + width/2, dep_26w1[i] - 30, f"{dep_26w1[i]:.0f}", ha="center", fontsize=9, fontweight="bold", color="#34495e")

    # Subplot 4: Peak 26SP Yield vs Biological Ceiling
    ax = axes[1, 1]
    max_y = [df_bm[df_bm["candidate"]==c]["Max_26SP_Y_t_ha"].values[0] for c in cands]
    bars = ax.bar(x, max_y, width*1.5, color=["#27ae60", "#f39c12", "#e67e22"])
    ax.axhline(75.0, color="red", linestyle="--", lw=2, label="Biological Ceiling (75.0 t/ha)")
    ax.set_ylabel("Max 2026 Spring Yield (t/ha)", fontsize=11, fontweight="bold")
    ax.set_title("4. 2026 Spring Yield Ceiling Verification", fontsize=12, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11, fontweight="bold")
    ax.set_ylim([60, 82])
    ax.grid(True, linestyle="--", alpha=0.4, axis="y")
    ax.legend(fontsize=9, loc="upper left")
    for i in range(len(labels)):
        status = "PASSED" if max_y[i] <= 75.0 else "EXCEEDED"
        color = "#27ae60" if max_y[i] <= 75.0 else "#c0392b"
        ax.text(x[i], max_y[i] + 0.5, f"{max_y[i]:.2f} t/ha\n({status})", ha="center", fontsize=9, fontweight="bold", color=color)
        
    fig.suptitle("Candidate Verification Matrix: C20 (real126) vs C21 (real21) vs C22 (real85)",
                 fontsize=15, fontweight="bold", y=1.02)
    plt.tight_layout()
    comp_png = out_comp / "diagnostic_tri_candidate_comparison.png"
    plt.savefig(comp_png, bbox_inches="tight")
    plt.close()
    print(f"Saved: {comp_png}")

def main():
    print("=" * 75)
    print("Starting Comprehensive 3-Season Diagnostic Suite for C20, C21, C22")
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
    print(f"  - Comparison: {PROJECT_ROOT / 'figture/candidates_c20_c21_c22_comparison'}")
    print("=" * 75)

if __name__ == "__main__":
    main()
