import os
import sys
import shutil
import subprocess
import re
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

ROOT_DIR = Path("D:/Tomato_Cal")
WORK_DIR = ROOT_DIR / "workspace/experiments/ssks_grid_20260918"
WORK_DIR.mkdir(parents=True, exist_ok=True)

PARAM_SOURCE = ROOT_DIR / "workspace/runs/full_gen_7l_sasc0945_150x5_20260918/candidate_iter3_real136_params.csv"
SOIL_TEMPLATE = ROOT_DIR / "data/raw/soil/SOIL.SOL"

# Multipliers: 0.05 to 1.20, step 0.05
MULTIPLIERS = [round(0.05 * i, 2) for i in range(1, 25)]

# Treatment list for DSSBatch.v48
BATCH_RUNS = [
    # 25SP (11 treatments)
    ("XXQL2501.TMX", 2, "25SP", "W3N3"),
    ("XXQL2501.TMX", 3, "25SP", "W3N2"),
    ("XXQL2501.TMX", 4, "25SP", "W3N1"),
    ("XXQL2501.TMX", 5, "25SP", "W3N0"),
    ("XXQL2501.TMX", 6, "25SP", "W2N3"),
    ("XXQL2501.TMX", 9, "25SP", "W2N0"),
    ("XXQL2501.TMX", 10, "25SP", "W1N3"),
    ("XXQL2501.TMX", 11, "25SP", "W1N2"),
    ("XXQL2501.TMX", 12, "25SP", "W1N1"),
    ("XXQL2501.TMX", 13, "25SP", "W1N0"),
    ("XXQL2501.TMX", 14, "25SP", "CK"),
    # 26SP (12 treatments)
    ("XXQL2601.TMX", 1, "26SP", "W3N3"),
    ("XXQL2601.TMX", 2, "26SP", "W2N3"),
    ("XXQL2601.TMX", 3, "26SP", "W1N3"),
    ("XXQL2601.TMX", 4, "26SP", "W3N2"),
    ("XXQL2601.TMX", 5, "26SP", "W2N2"),
    ("XXQL2601.TMX", 6, "26SP", "W1N2"),
    ("XXQL2601.TMX", 7, "26SP", "W3N1"),
    ("XXQL2601.TMX", 8, "26SP", "W2N1"),
    ("XXQL2601.TMX", 9, "26SP", "W1N1"),
    ("XXQL2601.TMX", 10, "26SP", "W3N0"),
    ("XXQL2601.TMX", 11, "26SP", "W2N0"),
    ("XXQL2601.TMX", 12, "26SP", "W1N0"),
]

# Field measured yields (kg/ha)
OBS_YIELDS = {
    # 25SP
    ("25SP", 2): 72323.0,
    ("25SP", 3): 73021.0,
    ("25SP", 4): 71380.0,
    ("25SP", 5): 68228.0,
    ("25SP", 6): 75624.0,
    ("25SP", 9): 65860.0,
    ("25SP", 10): 71140.0,
    ("25SP", 11): 70960.0,
    ("25SP", 12): 66320.0,
    ("25SP", 13): 59550.0,
    ("25SP", 14): 71800.0,
    # 26SP
    ("26SP", 1): 86520.0,
    ("26SP", 2): 86326.0,
    ("26SP", 3): 83287.0,
    ("26SP", 4): 78200.0,
    ("26SP", 5): 81000.0,
    ("26SP", 6): 76800.0,
    ("26SP", 7): 75400.0,
    ("26SP", 8): 77100.0,
    ("26SP", 9): 71200.0,
    ("26SP", 10): 69800.0,
    ("26SP", 11): 68385.0,
    ("26SP", 12): 71210.0,
}

def create_batch_file(path: Path):
    lines = [
        "$BATCH(TOMATO_CAL)\n",
        "!\n",
        "! Automated 23-treatment batch for SSKS scaling grid\n",
        "!\n",
        "@FILEX                                                                                        TRTNO     RP     SQ     OP     CO\n"
    ]
    for tmx, trt, _, _ in BATCH_RUNS:
        lines.append(f"{tmx:<92s}{trt:6d}      1      0      0      0\n")
    path.write_text("".join(lines), encoding="utf-8")

def generate_scaled_soil(template_path: Path, out_path: Path, mult: float):
    text = template_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    out_lines = []
    in_target_profile = False
    
    for l in lines:
        if l.startswith("*XXSL2501") or l.startswith("*XXSL2601"):
            in_target_profile = True
        elif in_target_profile and l.startswith("*"):
            in_target_profile = False
            
        if in_target_profile and len(l) > 42 and l.strip() and l.strip()[0].isdigit():
            # Character slice 36 to 42 is SSKS (6 chars, e.g. '  3.50')
            toks = l.split()
            if len(toks) >= 7:
                old_ssks = float(toks[6])
                new_ssks = round(old_ssks * mult, 3)
                l_mod = l[:36] + f"{new_ssks:6.2f}" + l[42:]
                out_lines.append(l_mod)
                continue
        out_lines.append(l)
        
    out_path.write_text("".join(out_lines), encoding="utf-8")

def parse_simulation_outputs(run_dir: Path):
    # Parse FreshWt.OUT
    fwt_file = run_dir / "FreshWt.OUT"
    yields = {}
    if fwt_file.exists():
        current_run = None
        chfpw_idx = None
        with open(fwt_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s.startswith("*RUN"):
                    current_run = int(s.split()[1])
                elif s.startswith("@"):
                    hdr = s.split()
                    chfpw_idx = hdr.index("CHFPW") if "CHFPW" in hdr else None
                elif current_run is not None and chfpw_idx is not None and s and not s.startswith("*"):
                    parts = s.split()
                    if len(parts) > chfpw_idx:
                        try:
                            val = float(parts[chfpw_idx])
                            if 1 <= current_run <= len(BATCH_RUNS):
                                _, trt, season, _ = BATCH_RUNS[current_run - 1]
                                yields[(season, trt)] = max(yields.get((season, trt), 0.0), val)
                        except ValueError:
                            pass

    # Parse PlantGro.OUT for terminal LAI
    pg_file = run_dir / "PlantGro.OUT"
    lais = {}
    if pg_file.exists():
        current_run = None
        laid_idx = None
        with open(pg_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.strip()
                if s.startswith("*RUN"):
                    current_run = int(s.split()[1])
                elif s.startswith("@YEAR"):
                    hdr = s.split()
                    laid_idx = hdr.index("LAID") if "LAID" in hdr else None
                elif current_run is not None and laid_idx is not None and s and not s.startswith("*"):
                    parts = s.split()
                    if len(parts) > laid_idx:
                        try:
                            year = int(float(parts[0]))
                            doy = int(float(parts[1]))
                            date = (year % 100) * 1000 + doy
                            laid_val = float(parts[laid_idx])
                            if 1 <= current_run <= len(BATCH_RUNS):
                                _, trt, season, _ = BATCH_RUNS[current_run - 1]
                                # Store latest date or specific date
                                if (season, trt) not in lais or date >= lais[(season, trt)][0]:
                                    lais[(season, trt)] = (date, laid_val)
                        except Exception:
                            pass
    terminal_lais = {k: v[1] for k, v in lais.items()}
    return yields, terminal_lais

def evaluate_multiplier(mult: float):
    tag = f"run_m_{int(round(mult*100)):03d}"
    run_dir = WORK_DIR / tag
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Generate modified SOIL.SOL
    soil_file = run_dir / "SOIL.SOL"
    generate_scaled_soil(SOIL_TEMPLATE, soil_file, mult)
    shutil.copy(soil_file, run_dir / "SOIL.SOL.base")
    
    # 2. Copy parameter file
    shutil.copy(PARAM_SOURCE, run_dir / "params.csv")
    
    # 3. Create unified 23-treatment batch file
    batch_file = run_dir / "DSSBatch.v48"
    create_batch_file(batch_file)
    
    # 4. Copy raw experiments and weather
    for f in (ROOT_DIR / "data/raw/experiments").glob("*.TM*"):
        shutil.copy(f, run_dir / f.name)
    for f in (ROOT_DIR / "data/raw/weather").glob("*.WTH"):
        shutil.copy(f, run_dir / f.name)
        
    # 5. Run DSSAT
    cmd = [
        sys.executable,
        str(ROOT_DIR / "src/dssat/run_dssat.py"),
        "--param-csv", "params.csv",
        "--batch", "DSSBatch.v48",
        "--harvest-var", "CHPDT",
    ]
    res = subprocess.run(cmd, cwd=run_dir, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[{tag}] Error: {res.stderr[:200]}")
        return None

    yields, lais = parse_simulation_outputs(run_dir)
    
    # Compute metrics
    # 25SP Yields (t/ha)
    y25 = {t: yields.get(("25SP", t), 0.0) / 1000.0 for t in [2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14]}
    # 26SP Yields (t/ha)
    y26 = {t: yields.get(("26SP", t), 0.0) / 1000.0 for t in range(1, 13)}
    
    # 25SP Gradients (t/ha)
    w1_grad_25 = y25[10] - y25[13]  # W1N3 - W1N0
    w1_n2_n0_25 = y25[11] - y25[13] # W1N2 - W1N0
    w1_n1_n0_25 = y25[12] - y25[13] # W1N1 - W1N0
    w2_grad_25 = y25[6] - y25[9]    # W2N3 - W2N0
    w3_grad_25 = y25[2] - y25[5]    # W3N3 - W3N0
    
    # 25SP Water Response Gradients
    water_grad_n3_25 = y25[2] - y25[10]  # W3N3 - W1N3
    water_grad_n0_25 = y25[5] - y25[13]  # W3N0 - W1N0
    
    # 26SP Gradients (t/ha)
    w1_grad_26 = y26[3] - y26[12]   # W1N3 - W1N0
    w2_grad_26 = y26[2] - y26[11]   # W2N3 - W2N0
    w3_grad_26 = y26[1] - y26[10]   # W3N3 - W3N0
    water_grad_n3_26 = y26[1] - y26[3]   # W3N3 - W1N3
    water_grad_n0_26 = y26[10] - y26[12] # W3N0 - W1N0
    
    # Accuracy metrics
    pairs_25 = [(OBS_YIELDS[k], yields[k]) for k in yields if k[0] == "25SP" and k in OBS_YIELDS]
    pairs_26 = [(OBS_YIELDS[k], yields[k]) for k in yields if k[0] == "26SP" and k in OBS_YIELDS]
    pairs_all = [(OBS_YIELDS[k], yields[k]) for k in yields if k in OBS_YIELDS]
    
    def get_stats(pairs):
        if not pairs:
            return -999, -999, -999
        obs = np.array([p[0] for p in pairs])
        sim = np.array([p[1] for p in pairs])
        rmse = np.sqrt(np.mean((obs - sim)**2))
        nrmse = rmse / np.mean(obs) * 100.0
        obs_mean = np.mean(obs)
        denom = np.sum((np.abs(sim - obs_mean) + np.abs(obs - obs_mean))**2)
        d = 1.0 - (np.sum((sim - obs)**2)) / denom if denom > 0 else -999
        ss_res = np.sum((obs - sim)**2)
        ss_tot = np.sum((obs - obs_mean)**2)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else -999
        return nrmse, r2, d
        
    nrmse_25, r2_25, d_25 = get_stats(pairs_25)
    nrmse_26, r2_26, d_26 = get_stats(pairs_26)
    nrmse_all, r2_all, d_all = get_stats(pairs_all)
    
    # LAI
    lai_w3n0 = lais.get(("25SP", 5), -999.0)
    lai_w1n3 = lais.get(("25SP", 10), -999.0)
    lai_w1n0 = lais.get(("25SP", 13), -999.0)
    
    row = {
        "multiplier": mult,
        "25_W1_Grad_t": w1_grad_25,
        "25_W1_N2_N0_t": w1_n2_n0_25,
        "25_W1_N1_N0_t": w1_n1_n0_25,
        "25_W2_Grad_t": w2_grad_25,
        "25_W3_Grad_t": w3_grad_25,
        "25_Water_Grad_N3_t": water_grad_n3_25,
        "25_Water_Grad_N0_t": water_grad_n0_25,
        "25_W1N3_t": y25[10],
        "25_W1N2_t": y25[11],
        "25_W1N1_t": y25[12],
        "25_W1N0_t": y25[13],
        "25_W3N3_t": y25[2],
        "25_W3N0_t": y25[5],
        "25_CK_t": y25[14],
        "25_W3N0_LAI": lai_w3n0,
        "25_W1N3_LAI": lai_w1n3,
        "25_W1N0_LAI": lai_w1n0,
        "26_W1_Grad_t": w1_grad_26,
        "26_W2_Grad_t": w2_grad_26,
        "26_W3_Grad_t": w3_grad_26,
        "26_Water_Grad_N3_t": water_grad_n3_26,
        "26_Water_Grad_N0_t": water_grad_n0_26,
        "NRMSE_25SP": nrmse_25,
        "d_25SP": d_25,
        "NRMSE_26SP": nrmse_26,
        "d_26SP": d_26,
        "NRMSE_All": nrmse_all,
        "d_All": d_all,
    }
    
    print(f"m={mult:4.2f} | 25SP W1_Grad={w1_grad_25:+5.2f}t (W1N3={y25[10]:5.1f}t, W1N0={y25[13]:5.1f}t) | 25SP W3_Grad={w3_grad_25:+5.2f}t | 26SP W1_Grad={w1_grad_26:+5.2f}t | All NRMSE={nrmse_all:5.2f}%")
    return row

def generate_plots(df: pd.DataFrame):
    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), dpi=300)
    
    m = df["multiplier"]
    
    # Subplot 1: 25SP Nitrogen Gradients vs SSKS Multiplier
    ax1 = axes[0, 0]
    ax1.plot(m, df["25_W1_Grad_t"], "o-", color="#C0392B", label="25SP W1 (N3 - N0)", lw=2)
    ax1.plot(m, df["25_W2_Grad_t"], "s-", color="#E67E22", label="25SP W2 (N3 - N0)", lw=1.8)
    ax1.plot(m, df["25_W3_Grad_t"], "^-", color="#2980B9", label="25SP W3 (N3 - N0)", lw=1.8)
    ax1.axhline(4.636, color="black", linestyle="--", alpha=0.7, label="W1 0.4x Target (+4.64t)")
    ax1.axvline(1.0, color="gray", linestyle=":", alpha=0.5, label="Baseline (1.0x)")
    ax1.set_xlabel("SSKS Scaling Factor", fontsize=11)
    ax1.set_ylabel("Yield Nitrogen Response (t/ha)", fontsize=11)
    ax1.set_title("A: 25SP Nitrogen Response Gradients vs SSKS", fontsize=12, fontweight="bold")
    ax1.legend(frameon=True, fontsize=9)
    
    # Subplot 2: 25SP W1 Specific Yield Curves (N3, N2, N1, N0)
    ax2 = axes[0, 1]
    ax2.plot(m, df["25_W1N3_t"], "o-", color="#900C3F", label="W1N3", lw=2)
    ax2.plot(m, df["25_W1N2_t"], "s-", color="#C70039", label="W1N2", lw=1.8)
    ax2.plot(m, df["25_W1N1_t"], "^-", color="#FF5733", label="W1N1", lw=1.8)
    ax2.plot(m, df["25_W1N0_t"], "d-", color="#581845", label="W1N0", lw=2)
    ax2.axvline(1.0, color="gray", linestyle=":", alpha=0.5)
    ax2.set_xlabel("SSKS Scaling Factor", fontsize=11)
    ax2.set_ylabel("Simulated Fresh Yield (t/ha)", fontsize=11)
    ax2.set_title("B: 25SP W1 Water Level Yields Across N Rates", fontsize=12, fontweight="bold")
    ax2.legend(frameon=True, fontsize=9)
    
    # Subplot 3: 26SP Nitrogen Gradients
    ax3 = axes[1, 0]
    ax3.plot(m, df["26_W1_Grad_t"], "o-", color="#27AE60", label="26SP W1 (N3 - N0)", lw=2)
    ax3.plot(m, df["26_W2_Grad_t"], "s-", color="#2980B9", label="26SP W2 (N3 - N0)", lw=1.8)
    ax3.plot(m, df["26_W3_Grad_t"], "^-", color="#8E44AD", label="26SP W3 (N3 - N0)", lw=1.8)
    ax3.axvline(1.0, color="gray", linestyle=":", alpha=0.5)
    ax3.set_xlabel("SSKS Scaling Factor", fontsize=11)
    ax3.set_ylabel("Yield Nitrogen Response (t/ha)", fontsize=11)
    ax3.set_title("C: 26SP Nitrogen Response Gradients vs SSKS", fontsize=12, fontweight="bold")
    ax3.legend(frameon=True, fontsize=9)
    
    # Subplot 4: Dual-Spring NRMSE & d-index
    ax4 = axes[1, 1]
    color = "#2C3E50"
    ax4.set_xlabel("SSKS Scaling Factor", fontsize=11)
    ax4.set_ylabel("Combined NRMSE (%)", color=color, fontsize=11)
    line1 = ax4.plot(m, df["NRMSE_All"], "o-", color=color, lw=2, label="Combined NRMSE")
    ax4.tick_params(axis="y", labelcolor=color)
    
    ax4_twin = ax4.twinx()
    color_d = "#16A085"
    ax4_twin.set_ylabel("Willmott d-index", color=color_d, fontsize=11)
    line2 = ax4_twin.plot(m, df["d_All"], "s-", color=color_d, lw=2, label="Combined d-index")
    ax4_twin.tick_params(axis="y", labelcolor=color_d)
    
    ax4.axvline(1.0, color="gray", linestyle=":", alpha=0.5)
    ax4.set_title("D: Overall Model Precision & Concordance vs SSKS", fontsize=12, fontweight="bold")
    
    lines_combo = line1 + line2
    labels_combo = [l.get_label() for l in lines_combo]
    ax4.legend(lines_combo, labels_combo, loc="upper right", frameon=True, fontsize=9)
    
    plt.tight_layout()
    out_png = WORK_DIR / "ssks_scaling_grid_analysis.png"
    plt.savefig(out_png, dpi=300)
    plt.close()
    print(f"Saved figure to {out_png}")

def main():
    print("================================================================================")
    print("Starting SSKS Scaling Grid Exploration (Range: 0.05 - 1.20, Step: 0.05)")
    print(f"Base Parameters: {PARAM_SOURCE.name}")
    print(f"Working Directory: {WORK_DIR}")
    print("================================================================================")
    
    results = []
    for mult in MULTIPLIERS:
        row = evaluate_multiplier(mult)
        if row:
            results.append(row)
            
    df = pd.DataFrame(results)
    out_csv = WORK_DIR / "ssks_scaling_grid_summary.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nSaved summary CSV to {out_csv}")
    
    generate_plots(df)
    
    print("\n================ TOP MULTIPLIERS BY W1 GRADIENT & NRMSE ================")
    # Sort by W1 gradient descending
    df_sorted = df.sort_values(by="25_W1_Grad_t", ascending=False)
    cols_show = ["multiplier", "25_W1_Grad_t", "25_W1N3_t", "25_W1N0_t", "25_W3_Grad_t", "26_W1_Grad_t", "26_W2_Grad_t", "NRMSE_All", "d_All"]
    print(df_sorted[cols_show].to_string(index=False))

if __name__ == "__main__":
    main()
