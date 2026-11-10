#!/usr/bin/env python3
"""Organize all Results, Discussion, Tables, Figures, and Reference documents into paper/ directory."""
import os
import shutil
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path("D:/Tomato_Cal")
PAPER = ROOT / "paper"

SEC_DIR = PAPER / "01_Sections"
TAB_DIR = PAPER / "02_Tables"
FIG_MAIN_DIR = PAPER / "03_Figures" / "Main_Figures"
FIG_SUPP_DIR = PAPER / "03_Figures" / "Supplementary_Figures"
FIG_CUST_DIR = PAPER / "03_Figures" / "Custom_Diagnostic_Figures"
REF_DIR = PAPER / "04_References_and_Data"

for d in [SEC_DIR, TAB_DIR, FIG_MAIN_DIR, FIG_SUPP_DIR, FIG_CUST_DIR, REF_DIR]:
    d.mkdir(parents=True, exist_ok=True)

print("=== 1. Copying Sections ===")
res_src = ROOT / "workspace" / "reports" / "results_writing_c15_tb1_20260920.md"
disc_src = ROOT / "workspace" / "reports" / "discussion_writing_c15_tb1_20260920.md"

res_dst = SEC_DIR / "03_Results_Section_C15.md"
disc_dst = SEC_DIR / "04_Discussion_Section_C15.md"
comb_dst = SEC_DIR / "00_Combined_Results_Discussion.md"

shutil.copy2(res_src, res_dst)
shutil.copy2(disc_src, disc_dst)

res_text = res_src.read_text(encoding="utf-8")
disc_text = disc_src.read_text(encoding="utf-8")

combined_text = f"""# 论文结果与讨论部分综合贯通稿 (基于代表解 C15 与 TB1 基温率定)

> **当前版本**：v2026.09.20  
> **基准率定批次**：`full_gen_13trt_tb1_80_95_150x6_20260920` (PEST++ IES 150 样本 × 6 轮迭代)  
> **代表性代表解**：**C15 (`real_72`)**（目标函数 $\\Phi = 965.74$，$TB1 = 9.21\\ ^\\circ\\text{{C}}$）  
> **学术规范**：结果部分与数据表格严格仅包含作物遗传参数（`.CUL`、`.ECO`、`.SPE`），非遗传参数已彻底隔离。

---

{res_text}

---

{disc_text}
"""
comb_dst.write_text(combined_text, encoding="utf-8")
print("Saved sections to:", SEC_DIR)

print("=== 2. Generating & Copying Tables ===")
# 1) Table 1: Genetic Parameters
params_df = pd.read_csv(ROOT / "workspace/candidates/candidate_c15_real72_grand_champion/params.csv")
pdict = dict(zip(params_df["name"].str.upper(), params_df["value"]))

GENETIC_SPECS = [
    # Phenology & Development
    ("Phenology & Development", "TB1", "TMGRO048.ECO", "Base temperature for vegetative and reproductive development", "°C", 8.0, pdict.get("TB1", 9.21106), "Calibrated"),
    ("Phenology & Development", "EM-FL", "TMGRO048.CUL", "Time between plant emergence and flower appearance", "photothermal days", 24.4, pdict.get("EM-FL", 23.0284), "Calibrated"),
    ("Phenology & Development", "FL-SH", "TMGRO048.CUL", "Time between first flower and first fruit/pod appearance", "photothermal days", 2.2, pdict.get("FL-SH", 2.68844), "Calibrated"),
    ("Phenology & Development", "FL-SD", "TMGRO048.CUL", "Time between first flower and first seed formation", "photothermal days", 19.0, pdict.get("FL-SD", 22.2873), "Calibrated"),
    ("Phenology & Development", "SD-PM", "TMGRO048.CUL", "Time between first seed and physiological maturity", "photothermal days", 45.2, pdict.get("SD-PM", 400.0), "Fixed"),
    ("Phenology & Development", "FL-LF", "TMGRO048.CUL", "Time between first flower and end of leaf expansion", "photothermal days", 52.0, pdict.get("FL-LF", 480.206), "Calibrated"),
    ("Phenology & Development", "FL-VS", "TMGRO048.ECO", "Time from first flower to end of main-stem vegetative growth", "photothermal days", 24.5, pdict.get("FL-VS", 100.0), "Fixed"),
    ("Phenology & Development", "TRIFL", "TMGRO048.ECO", "Rate of leaf appearance on the main stem", "leaves/thermal day", 0.45, pdict.get("TRIFL", 1.300), "Calibrated"),
    ("Phenology & Development", "EM-V1", "TMGRO048.ECO", "Time between plant emergence and appearance of first true leaf", "photothermal days", 22.0, pdict.get("EM-V1", 37.8539), "Calibrated"),
    ("Phenology & Development", "JU-R0", "TMGRO048.ECO", "Time between end of juvenile stage and floral induction", "photothermal days", 5.0, pdict.get("JU-R0", 4.18135), "Fixed"),
    # Canopy & Photosynthesis
    ("Canopy & Photosynthesis", "LFMAX", "TMGRO048.CUL", "Maximum leaf photosynthesis rate at 30°C, 350 vpm CO2, high light", "mg CO2/m2/s", 1.36, pdict.get("LFMAX", 2.4166), "Calibrated"),
    ("Canopy & Photosynthesis", "SLAVR", "TMGRO048.CUL", "Specific leaf area under standard growth conditions", "cm2/g", 300.0, pdict.get("SLAVR", 213.486), "Calibrated"),
    ("Canopy & Photosynthesis", "SIZLF", "TMGRO048.CUL", "Maximum size of fully expanded leaf", "cm2", 300.0, pdict.get("SIZLF", 287.682), "Calibrated"),
    ("Canopy & Photosynthesis", "RWDTH", "TMGRO048.ECO", "Relative canopy width multiplier", "dimensionless", 1.0, pdict.get("RWDTH", 1.5669), "Calibrated"),
    ("Canopy & Photosynthesis", "RHGHT", "TMGRO048.ECO", "Relative canopy height multiplier", "dimensionless", 1.0, pdict.get("RHGHT", 1.0522), "Calibrated"),
    ("Canopy & Photosynthesis", "KCAN", "TMGRO048.SPE", "Canopy light extinction coefficient", "dimensionless", 0.67, pdict.get("KCAN", 0.6454), "Calibrated"),
    ("Canopy & Photosynthesis", "KC_SLOPE", "TMGRO048.SPE", "Slope of light extinction coefficient with LAI", "dimensionless", 0.10, pdict.get("KC_SLOPE", 0.01178), "Fixed"),
    ("Canopy & Photosynthesis", "PGEFF", "TMGRO048.SPE", "Photosynthetic efficiency (initial slope of light response)", "dimensionless", 0.0541, pdict.get("PGEFF", 0.06586), "Calibrated"),
    # Fruit Load & Partitioning
    ("Fruit Load & Partitioning", "XFRT", "TMGRO048.CUL", "Maximum fraction of daily assimilate allocated to fruit", "g/g", 0.78, pdict.get("XFRT", 0.9333), "Calibrated"),
    ("Fruit Load & Partitioning", "WTPSD", "TMGRO048.CUL", "Maximum weight per seed", "g", 0.004, pdict.get("WTPSD", 0.004), "Fixed"),
    ("Fruit Load & Partitioning", "SFDUR", "TMGRO048.CUL", "Seed filling duration for cohort under standard conditions", "photothermal days", 26.0, pdict.get("SFDUR", 45.022), "Calibrated"),
    ("Fruit Load & Partitioning", "PODUR", "TMGRO048.CUL", "Time required to reach final fruit load", "photothermal days", 55.0, pdict.get("PODUR", 9.182), "Calibrated"),
    ("Fruit Load & Partitioning", "THRSH", "TMGRO048.CUL", "Maximum ratio of seed to fruit weight at maturity", "%", 8.5, pdict.get("THRSH", 5.168), "Calibrated"),
    ("Fruit Load & Partitioning", "LNGSH", "TMGRO048.ECO", "Duration of fruit addition on reproductive axes", "photothermal days", 39.0, pdict.get("LNGSH", 20.582), "Calibrated"),
    ("Fruit Load & Partitioning", "PM06", "TMGRO048.ECO", "Proportion of time when seed filling rate drops to 60%", "dimensionless", 0.55, pdict.get("PM06", 0.2239), "Calibrated"),
    ("Fruit Load & Partitioning", "PM09", "TMGRO048.ECO", "Proportion of time when seed filling rate drops to 90%", "dimensionless", 0.75, pdict.get("PM09", 0.306), "Fixed"),
    ("Fruit Load & Partitioning", "XMAGE", "TMGRO048.ECO", "Required fruit age for multi-harvest picking readiness", "photothermal days", 10.0, pdict.get("XMAGE", 17.771), "Calibrated"),
    ("Fruit Load & Partitioning", "FRLFF", "TMGRO048.SPE", "Fraction of vegetative assimilate allocated to leaf", "g/g", 0.30, pdict.get("FRLFF", 0.080), "Calibrated"),
    ("Fruit Load & Partitioning", "FRSTMF", "TMGRO048.SPE", "Fraction of vegetative assimilate allocated to stem", "g/g", 0.49, pdict.get("FRSTMF", 0.8299), "Calibrated"),
    # Nitrogen & Protein Dynamics
    ("Nitrogen & Protein Dynamics", "RTNO3", "TMGRO048.SPE", "Maximum NO3 uptake rate per unit root length", "mg N/cm root/d", 0.012, pdict.get("RTNO3", 0.01468), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "RTNH4", "TMGRO048.SPE", "Maximum NH4 uptake rate per unit root length", "mg N/cm root/d", 0.012, pdict.get("RTNH4", 0.01884), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "NMOBMX", "TMGRO048.SPE", "Maximum daily rate of mobile vegetative N remobilization", "d-1", 0.09, pdict.get("NMOBMX", 0.15427), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "NVSMOB", "TMGRO048.SPE", "Fraction of mobile vegetative N available for fruit mobilization", "dimensionless", 0.38, pdict.get("NVSMOB", 0.56709), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "LNREF", "TMGRO048.SPE", "Reference leaf N concentration for maximum photosynthesis", "%", 4.5, pdict.get("LNREF", 5.1878), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "NSLOPE", "TMGRO048.SPE", "Slope of leaf N effect on photosynthesis", "dimensionless", 0.25, pdict.get("NSLOPE", 0.1205), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "NSTFAC", "TMGRO048.SPE", "Minimum vegetative N stress factor required for fruit addition", "dimensionless", 0.70, pdict.get("NSTFAC", 0.7147), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "FNPGN1", "TMGRO048.SPE", "Lower critical threshold of leaf N effect on canopy photosynthesis", "dimensionless", 2.0, pdict.get("FNPGN1", 0.7059), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "FNPGN2", "TMGRO048.SPE", "Upper critical threshold of leaf N effect on canopy photosynthesis", "dimensionless", 4.5, pdict.get("FNPGN2", 5.1540), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PROLFI", "TMGRO048.SPE", "Initial leaf protein composition", "g protein/g organ", 0.27, pdict.get("PROLFI", 0.31714), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PROLFG", "TMGRO048.SPE", "Leaf protein composition during active vegetative growth", "g protein/g organ", 0.22, pdict.get("PROLFG", 0.16304), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PROLFF", "TMGRO048.SPE", "Final leaf protein composition at complete senescence", "g protein/g organ", 0.11, pdict.get("PROLFF", 0.08187), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PROSTI", "TMGRO048.SPE", "Initial stem protein composition", "g protein/g organ", 0.188, pdict.get("PROSTI", 0.1475), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PROSTG", "TMGRO048.SPE", "Stem protein composition during active vegetative growth", "g protein/g organ", 0.136, pdict.get("PROSTG", 0.16713), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PROSTF", "TMGRO048.SPE", "Final stem protein composition at complete senescence", "g protein/g organ", 0.065, pdict.get("PROSTF", 0.05807), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PRORTI", "TMGRO048.SPE", "Initial root protein composition", "g protein/g organ", 0.144, pdict.get("PRORTI", 0.05827), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PRORTG", "TMGRO048.SPE", "Root protein composition during active growth", "g protein/g organ", 0.119, pdict.get("PRORTG", 0.11552), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PRORTF", "TMGRO048.SPE", "Final root protein composition at complete senescence", "g protein/g organ", 0.060, pdict.get("PRORTF", 0.02731), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PROSHI", "TMGRO048.SPE", "Initial fruit shell protein composition", "g protein/g organ", 0.21, pdict.get("PROSHI", 0.10243), "Calibrated"),
    ("Nitrogen & Protein Dynamics", "PROSHG", "TMGRO048.SPE", "Fruit shell protein composition during active growth", "g protein/g organ", 0.15, pdict.get("PROSHG", 0.11145), "Calibrated"),
    # Drought Stress & Senescence
    ("Drought Stress & Senescence", "RWUMX", "TMGRO048.SPE", "Maximum root water uptake rate", "cm3 water/cm root/d", 0.04, pdict.get("RWUMX", 0.060), "Calibrated"),
    ("Drought Stress & Senescence", "DSWBAR", "TMGRO048.SPE", "Critical dry surface layer depth triggering water stress on fruit addition", "cm", 15.0, pdict.get("DSWBAR", 4.2529), "Calibrated"),
    ("Drought Stress & Senescence", "SWBAR_REC", "TMGRO048.SPE", "Relative soil water threshold for fruit addition (XSWBAR_3)", "dimensionless", 0.25, pdict.get("SWBAR_REC", 0.8370), "Calibrated"),
    ("Drought Stress & Senescence", "YSWBAR_MID", "TMGRO048.SPE", "Mid-point soil water stress factor on fruit addition (YSWBAR_3)", "dimensionless", 1.0, pdict.get("YSWBAR_MID", 0.4988), "Calibrated"),
    ("Drought Stress & Senescence", "SENRTE", "TMGRO048.SPE", "Leaf senescence rate per unit of leaf protein mobilized", "g leaf/g protein loss", 1.0, pdict.get("SENRTE", 3.6548), "Calibrated"),
    ("Drought Stress & Senescence", "SENDAY", "TMGRO048.SPE", "Daily baseline senescence rate of leaves past maximum age", "d-1", 0.02, pdict.get("SENDAY", 0.01039), "Calibrated"),
]

t1_rows = []
for cat, code, f, defn, unit, t_base, e_cal, status in GENETIC_SPECS:
    rel_change = (e_cal - t_base) / t_base * 100
    t1_rows.append({
        "Category": cat,
        "Parameter": code,
        "File": f,
        "Definition_Function": defn,
        "Unit": unit,
        "Tomato_Base": round(t_base, 4),
        "Eggplant_Calibrated": round(e_cal, 4),
        "Relative_Change_pct": round(rel_change, 2),
        "Status": status
    })

t1_df = pd.DataFrame(t1_rows)
t1_df.to_csv(TAB_DIR / "Table1_Genetic_Parameters_Comparison.csv", index=False, encoding="utf-8-sig")

# 2) Table 2: Model Statistical Performance Yield
t2_rows = [
    {"Dimension": "Modeling Phase", "Subgroup": "Calibration (13 tmts)", "n": 13, "Obs_Mean_SD": "67.36 ± 6.99", "Sim_Mean_SD": "67.83 ± 4.75", "RMSE": 3.98, "NRMSE_pct": 5.90, "d_index": 0.8647, "R2": 0.6751, "NSE": 0.6498},
    {"Dimension": "Modeling Phase", "Subgroup": "Validation (10 tmts)", "n": 10, "Obs_Mean_SD": "68.45 ± 3.74", "Sim_Mean_SD": "70.96 ± 3.04", "RMSE": 5.05, "NRMSE_pct": 7.38, "d_index": 0.3774, "R2": 0.0067, "NSE": -1.0299},
    {"Dimension": "Modeling Phase", "Subgroup": "Two-Spring Pooled (23 tmts)", "n": 23, "Obs_Mean_SD": "67.83 ± 5.72", "Sim_Mean_SD": "69.19 ± 4.31", "RMSE": 4.48, "NRMSE_pct": 6.60, "d_index": 0.7699, "R2": 0.4285, "NSE": 0.3595},
    {"Dimension": "Modeling Phase", "Subgroup": "2025 Spring (11 tmts)", "n": 11, "Obs_Mean_SD": "70.52 ± 4.26", "Sim_Mean_SD": "71.11 ± 4.15", "RMSE": 3.83, "NRMSE_pct": 5.43, "d_index": 0.7600, "R2": 0.3086, "NSE": 0.1124},
    {"Dimension": "Modeling Phase", "Subgroup": "2026 Spring (12 tmts)", "n": 12, "Obs_Mean_SD": "65.37 ± 5.92", "Sim_Mean_SD": "67.43 ± 3.80", "RMSE": 4.99, "NRMSE_pct": 7.64, "d_index": 0.6877, "R2": 0.3574, "NSE": 0.2226},
    {"Dimension": "Modeling Phase", "Subgroup": "Independent Blind Test (2025 Autumn)", "n": 12, "Obs_Mean_SD": "16.96 ± 1.85", "Sim_Mean_SD": "14.14 ± 0.84", "RMSE": 3.12, "NRMSE_pct": 18.38, "d_index": 0.5256, "R2": 0.5144, "NSE": -2.0828},
    {"Dimension": "Modeling Phase", "Subgroup": "Grand Pooled (All 35 Treatments)", "n": 35, "Obs_Mean_SD": "50.39 ± 24.95", "Sim_Mean_SD": "50.32 ± 26.74", "RMSE": 4.06, "NRMSE_pct": 8.06, "d_index": 0.9936, "R2": 0.9795, "NSE": 0.9727},
    {"Dimension": "Nitrogen Application Level", "Subgroup": "N3 (360 kg N/ha)", "n": 9, "Obs_Mean_SD": "53.15 ± 26.84", "Sim_Mean_SD": "51.85 ± 28.36", "RMSE": 2.70, "NRMSE_pct": 5.07, "d_index": 0.9973, "R2": 0.9948, "NSE": 0.9886},
    {"Dimension": "Nitrogen Application Level", "Subgroup": "N2 (240 kg N/ha)", "n": 9, "Obs_Mean_SD": "53.69 ± 26.70", "Sim_Mean_SD": "51.74 ± 28.27", "RMSE": 3.65, "NRMSE_pct": 6.80, "d_index": 0.9950, "R2": 0.9891, "NSE": 0.9790},
    {"Dimension": "Nitrogen Application Level", "Subgroup": "N1 (120 kg N/ha)", "n": 8, "Obs_Mean_SD": "48.27 ± 26.29", "Sim_Mean_SD": "49.17 ± 29.06", "RMSE": 4.11, "NRMSE_pct": 8.52, "d_index": 0.9937, "R2": 0.9860, "NSE": 0.9720},
    {"Dimension": "Nitrogen Application Level", "Subgroup": "N0 (0 kg N/ha)", "n": 9, "Obs_Mean_SD": "46.22 ± 23.72", "Sim_Mean_SD": "48.38 ± 26.21", "RMSE": 5.34, "NRMSE_pct": 11.55, "d_index": 0.9871, "R2": 0.9671, "NSE": 0.9430},
    {"Dimension": "Irrigation Regime", "Subgroup": "W3 (Full Irrigation)", "n": 12, "Obs_Mean_SD": "51.47 ± 25.02", "Sim_Mean_SD": "51.05 ± 27.15", "RMSE": 2.98, "NRMSE_pct": 5.79, "d_index": 0.9964, "R2": 0.9927, "NSE": 0.9845},
    {"Dimension": "Irrigation Regime", "Subgroup": "W2 (Moderate Deficit)", "n": 10, "Obs_Mean_SD": "48.84 ± 27.03", "Sim_Mean_SD": "48.07 ± 28.95", "RMSE": 4.42, "NRMSE_pct": 9.06, "d_index": 0.9930, "R2": 0.9779, "NSE": 0.9702},
    {"Dimension": "Irrigation Regime", "Subgroup": "W1 (Deficit Irrigation)", "n": 12, "Obs_Mean_SD": "48.73 ± 25.45", "Sim_Mean_SD": "49.52 ± 27.08", "RMSE": 4.78, "NRMSE_pct": 9.82, "d_index": 0.9909, "R2": 0.9688, "NSE": 0.9615},
]
pd.DataFrame(t2_rows).to_csv(TAB_DIR / "Table2_Model_Statistical_Performance_Yield.csv", index=False, encoding="utf-8-sig")

# 3) Table 3: Water Nitrogen Response Gaps
t3_rows = [
    {"Season": "2026 Spring", "Irrigation": "W3 (Full)", "Obs_N0": 60.89, "Obs_N3": 66.68, "Obs_Gap": 5.79, "Sim_N0": 58.67, "Sim_N3": 68.88, "Sim_Gap": 10.21, "Gap_Bias": 4.42},
    {"Season": "2026 Spring", "Irrigation": "W2 (Moderate)", "Obs_N0": 62.35, "Obs_N3": 71.87, "Obs_Gap": 9.52, "Sim_N0": 62.86, "Sim_N3": 68.88, "Sim_Gap": 6.02, "Gap_Bias": -3.50},
    {"Season": "2026 Spring", "Irrigation": "W1 (Deficit)", "Obs_N0": 51.58, "Obs_N3": 68.08, "Obs_Gap": 16.50, "Sim_N0": 62.81, "Sim_N3": 70.19, "Sim_Gap": 7.38, "Gap_Bias": -9.12},
    {"Season": "2025 Spring", "Irrigation": "W3 (Full)", "Obs_N0": 68.23, "Obs_N3": 72.32, "Obs_Gap": 4.09, "Sim_N0": 67.61, "Sim_N3": 73.42, "Sim_Gap": 5.81, "Gap_Bias": 1.72},
    {"Season": "2025 Spring", "Irrigation": "W2 (Moderate)", "Obs_N0": 67.50, "Obs_N3": 75.62, "Obs_Gap": 8.12, "Sim_N0": 77.62, "Sim_N3": 74.62, "Sim_Gap": -3.00, "Gap_Bias": -11.12},
    {"Season": "2025 Spring", "Irrigation": "W1 (Deficit)", "Obs_N0": 59.55, "Obs_N3": 71.14, "Obs_Gap": 11.59, "Sim_N0": 63.42, "Sim_N3": 68.22, "Sim_Gap": 4.80, "Gap_Bias": -6.79},
    {"Season": "2025 Autumn", "Irrigation": "W3 (Full)", "Obs_N0": 16.97, "Obs_N3": 18.22, "Obs_Gap": 1.25, "Sim_N0": 14.67, "Sim_N3": 14.68, "Sim_Gap": 0.01, "Gap_Bias": -1.24},
    {"Season": "2025 Autumn", "Irrigation": "W2 (Moderate)", "Obs_N0": 16.17, "Obs_N3": 18.99, "Obs_Gap": 2.82, "Sim_N0": 14.74, "Sim_N3": 14.75, "Sim_Gap": 0.01, "Gap_Bias": -2.81},
    {"Season": "2025 Autumn", "Irrigation": "W1 (Deficit)", "Obs_N0": 12.71, "Obs_N3": 15.45, "Obs_Gap": 2.74, "Sim_N0": 13.00, "Sim_N3": 13.00, "Sim_Gap": 0.00, "Gap_Bias": -2.74},
]
pd.DataFrame(t3_rows).to_csv(TAB_DIR / "Table3_Water_Nitrogen_Response_Gaps.csv", index=False, encoding="utf-8-sig")

# 4) Table 4: Vegetative Growth Performance
t4_df = pd.read_csv(ROOT / "workspace/runs/full_gen_13trt_tb1_80_95_150x6_20260920/paper_figures_c15/DEMO_model_performance.metrics.csv")
t4_df.to_csv(TAB_DIR / "Table4_Vegetative_Growth_Performance.csv", index=False, encoding="utf-8-sig")

# 5) Tables Compiled Markdown Report
tab_rep_src = ROOT / "workspace/reports/paper_tables_iter5_real13.md" # reference template
print("Saved tables to:", TAB_DIR)

print("=== 3. Copying Figures ===")
# Main figures from C15 formal R run
c15_fig_dir = ROOT / "workspace/runs/full_gen_13trt_tb1_80_95_150x6_20260920/paper_figures_c15"
fig_mapping = {
    "DEMO_process_dynamics": "Fig1_Process_Dynamics",
    "DEMO_harvest_dynamics": "Fig2_Harvest_Dynamics",
    "DEMO_model_performance": "Fig3_Model_Performance_1to1",
    "DEMO_water_nitrogen_response": "Fig4_Water_Nitrogen_Response",
    "DEMO_leaf_nitrogen": "Fig5_Leaf_Nitrogen_Dynamics",
    "DEMO_all_treatments_cumulative_smooth": "Fig6_All_Treatments_Cumulative",
    "DEMO_phi_convergence": "Fig7_Phi_Convergence",
}

for src_prefix, dst_prefix in fig_mapping.items():
    for ext in [".png", ".pdf", ".svg"]:
        f_src = c15_fig_dir / f"{src_prefix}{ext}"
        f_dst = FIG_MAIN_DIR / f"{dst_prefix}{ext}"
        if f_src.exists():
            shutil.copy2(f_src, f_dst)

# Supplementary figures from posterior figures run
post_fig_dir = ROOT / "workspace/runs/full_gen_13trt_tb1_80_95_150x6_20260920/posterior_figures"
supp_mapping = {
    "DEMO_FigS5_posterior_density": "FigS5a_posterior_density",
    "DEMO_FigS5_posterior_contraction": "FigS5b_posterior_contraction",
    "DEMO_FigS6_spearman_structure": "FigS6_spearman_structure",
    "DEMO_FigS7_candidate_prediction_distance": "FigS7_candidate_prediction_distance",
}

for src_prefix, dst_prefix in supp_mapping.items():
    for ext in [".png", ".pdf", ".svg"]:
        f_src = post_fig_dir / f"{src_prefix}{ext}"
        f_dst = FIG_SUPP_DIR / f"{dst_prefix}{ext}"
        if f_src.exists():
            shutil.copy2(f_src, f_dst)

# Custom diagnostic figures
cust_fig_dir = ROOT / "figture/paper_figures_iter5_real13"
if cust_fig_dir.exists():
    for f in cust_fig_dir.iterdir():
        if f.suffix in [".png", ".pdf"]:
            shutil.copy2(f, FIG_CUST_DIR / f.name)

print("Saved main figures to:", FIG_MAIN_DIR)
print("Saved supplementary figures to:", FIG_SUPP_DIR)
print("Saved custom diagnostic figures to:", FIG_CUST_DIR)

print("=== 4. Copying References & Data ===")
exp_manual = ROOT / "docs/试验背景与数据说明_温室茄子水氮试验.md"
if exp_manual.exists():
    shutil.copy2(exp_manual, REF_DIR / "试验背景与数据说明_温室茄子水氮试验.md")

cand_src = ROOT / "workspace/candidates/candidate_c15_real72_grand_champion"
if cand_src.exists():
    shutil.copy2(cand_src / "params.csv", REF_DIR / "C15_candidate_parameters.csv")
    shutil.copy2(cand_src / "all_35_treatments_final_yield.csv", REF_DIR / "C15_all_35_treatments_final_yield.csv")
    shutil.copy2(cand_src / "metrics_three_seasons.csv", REF_DIR / "C15_metrics_three_seasons.csv")
    shutil.copy2(cand_src / "candidate_manifest.json", REF_DIR / "C15_candidate_manifest.json")

print("Saved references and data to:", REF_DIR)
print("=== Complete! ===")
