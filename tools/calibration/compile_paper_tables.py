#!/usr/bin/env python3
"""Compile all publication manuscript tables for Eggplant Crop Model Calibration & Validation (iter5_real13):
Strictly adheres to the user rule:
"论文的结果部分不应该提及除了遗传参数外的其他参数" -> STRICTLY ONLY CROP GENETIC PARAMETERS (CUL, ECO, SPE).
Outputs:
- workspace/reports/paper_tables_iter5_real13.md
- workspace/reports/tables/Table1_Genetic_Parameters_Comparison.csv
- workspace/reports/tables/Table2_Model_Statistical_Performance_Yield.csv
- workspace/reports/tables/Table3_Water_Nitrogen_Response_Gaps.csv
- workspace/reports/tables/Table4_Vegetative_Growth_Performance.csv
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("D:/Tomato_Cal")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RUN_DIR = ROOT / "workspace" / "runs" / "full_gen_page22_sasc0925_150x5_20260918"
OUT_REPORT_DIR = ROOT / "workspace" / "reports"
OUT_TABLE_CSV_DIR = OUT_REPORT_DIR / "tables"
OUT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
OUT_TABLE_CSV_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------------------
# 1. Table 1: Genetic Parameters Comparison (Tomato vs Eggplant)
# -------------------------------------------------------------
def build_table_1() -> pd.DataFrame:
    cand_csv = RUN_DIR / "candidate_iter5_real13_params.csv"
    df_cand = pd.read_csv(cand_csv)
    cand_dict = dict(zip(df_cand['name'].str.upper(), df_cand['value']))

    frozen_csv = ROOT / "data/parameter_registry/bounds_frozen/eggplant/eggplant_full_gen_page22_sasc0925_20260918.csv"
    df_frozen = pd.read_csv(frozen_csv)
    status_dict = dict(zip(df_frozen['name'].str.upper(), df_frozen['status']))

    # Baseline Tomato (Florida 47) from Genotype4.8.5 (TMGRO048.CUL, TMGRO048.ECO, TMGRO048.SPE)
    params_meta = [
        # Phenology & Developmental Timing
        ('EM-FL', 'CUL', 'Time between plant emergence and flower appearance', 'photothermal days', 24.40),
        ('FL-SH', 'CUL', 'Time between first flower and first fruit/pod appearance', 'photothermal days', 2.20),
        ('FL-SD', 'CUL', 'Time between first flower and first seed formation', 'photothermal days', 19.00),
        ('SD-PM', 'CUL', 'Time between first seed and physiological maturity', 'photothermal days', 45.20),
        ('FL-LF', 'CUL', 'Time between first flower and end of leaf expansion', 'photothermal days', 52.00),
        ('FL-VS', 'ECO', 'Time from first flower to end of main-stem vegetative growth', 'photothermal days', 24.50),
        ('TRIFL', 'ECO', 'Rate of leaf appearance on the main stem', 'leaves/thermal day', 0.45),
        ('EM-V1', 'ECO', 'Time between plant emergence and appearance of first true leaf', 'photothermal days', 22.00),
        ('JU-R0', 'ECO', 'Time between end of juvenile stage and floral induction', 'photothermal days', 5.00),
        
        # Canopy Architecture & Photosynthesis
        ('LFMAX', 'CUL', 'Maximum leaf photosynthesis rate at 30°C, 350 vpm CO2, high light', 'mg CO2/m2/s', 1.36),
        ('SLAVR', 'CUL', 'Specific leaf area under standard growth conditions', 'cm2/g', 300.0),
        ('SIZLF', 'CUL', 'Maximum size of fully expanded leaf', 'cm2', 300.0),
        ('RWDTH', 'ECO', 'Relative canopy width multiplier', 'dimensionless', 1.00),
        ('RHGHT', 'ECO', 'Relative canopy height multiplier', 'dimensionless', 1.00),
        ('KCAN', 'SPE', 'Canopy light extinction coefficient', 'dimensionless', 0.67),
        ('KC_SLOPE', 'SPE', 'Slope of light extinction coefficient with LAI', 'dimensionless', 0.10),
        ('PGEFF', 'SPE', 'Photosynthetic efficiency (initial slope of light response)', 'dimensionless', 0.0541),

        # Multi-Harvest, Reproductive Partitioning & Yield
        ('XFRT', 'CUL', 'Maximum fraction of daily assimilate allocated to fruit', 'g/g', 0.78),
        ('WTPSD', 'CUL', 'Maximum weight per seed', 'g', 0.0040),
        ('SFDUR', 'CUL', 'Seed filling duration for cohort under standard conditions', 'photothermal days', 26.0),
        ('PODUR', 'CUL', 'Time required to reach final fruit load', 'photothermal days', 55.0),
        ('THRSH', 'CUL', 'Maximum ratio of seed to fruit weight at maturity', '%', 8.50),
        ('LNGSH', 'ECO', 'Duration of fruit addition on reproductive axes', 'photothermal days', 39.0),
        ('PM06', 'ECO', 'Proportion of time when seed filling rate drops to 60%', 'dimensionless', 0.55),
        ('PM09', 'ECO', 'Proportion of time when seed filling rate drops to 90%', 'dimensionless', 0.75),
        ('XMAGE', 'ECO', 'Required fruit age for multi-harvest picking readiness', 'photothermal days', 10.0),
        ('FRLFF', 'SPE', 'Fraction of vegetative assimilate allocated to leaf', 'g/g', 0.30),
        ('FRSTMF', 'SPE', 'Fraction of vegetative assimilate allocated to stem', 'g/g', 0.49),

        # Nitrogen Uptake, Allocation & Organ Protein Dynamics
        ('RTNO3', 'SPE', 'Maximum NO3 uptake rate per unit root length', 'mg N/cm root/d', 0.012),
        ('RTNH4', 'SPE', 'Maximum NH4 uptake rate per unit root length', 'mg N/cm root/d', 0.012),
        ('NMOBMX', 'SPE', 'Maximum daily rate of mobile vegetative N remobilization', 'd-1', 0.090),
        ('NVSMOB', 'SPE', 'Fraction of mobile vegetative N available for fruit mobilization', 'dimensionless', 0.380),
        ('LNREF', 'SPE', 'Reference leaf N concentration for maximum photosynthesis', '%', 4.50),
        ('NSLOPE', 'SPE', 'Slope of leaf N effect on photosynthesis', 'dimensionless', 0.250),
        ('NSTFAC', 'SPE', 'Minimum vegetative N stress factor required for fruit addition', 'dimensionless', 0.70),
        ('FNPGN1', 'SPE', 'Lower critical threshold of leaf N effect on canopy photosynthesis', 'dimensionless', 2.00),
        ('FNPGN2', 'SPE', 'Upper critical threshold of leaf N effect on canopy photosynthesis', 'dimensionless', 4.50),
        ('PROLFI', 'SPE', 'Initial leaf protein composition', 'g protein/g organ', 0.270),
        ('PROLFG', 'SPE', 'Leaf protein composition during active vegetative growth', 'g protein/g organ', 0.220),
        ('PROLFF', 'SPE', 'Final leaf protein composition at complete senescence', 'g protein/g organ', 0.110),
        ('PROSTI', 'SPE', 'Initial stem protein composition', 'g protein/g organ', 0.188),
        ('PROSTG', 'SPE', 'Stem protein composition during active vegetative growth', 'g protein/g organ', 0.136),
        ('PROSTF', 'SPE', 'Final stem protein composition at complete senescence', 'g protein/g organ', 0.065),
        ('PRORTI', 'SPE', 'Initial root protein composition', 'g protein/g organ', 0.144),
        ('PRORTG', 'SPE', 'Root protein composition during active growth', 'g protein/g organ', 0.119),
        ('PRORTF', 'SPE', 'Final root protein composition at complete senescence', 'g protein/g organ', 0.060),
        ('PROSHI', 'SPE', 'Initial fruit shell protein composition', 'g protein/g organ', 0.210),
        ('PROSHG', 'SPE', 'Fruit shell protein composition during active growth', 'g protein/g organ', 0.150),

        # Drought Stress & Senescence
        ('RWUMX', 'SPE', 'Maximum root water uptake rate', 'cm3 water/cm root/d', 0.040),
        ('DSWBAR', 'SPE', 'Critical dry surface layer depth triggering water stress on fruit addition', 'cm', 15.00),
        ('SWBAR_REC', 'SPE', 'Relative soil water threshold for fruit addition (XSWBAR_3)', 'dimensionless', 0.25),
        ('YSWBAR_MID', 'SPE', 'Mid-point soil water stress factor on fruit addition (YSWBAR_3)', 'dimensionless', 1.00),
        ('SENRTE', 'SPE', 'Leaf senescence rate per unit of leaf protein mobilized', 'g leaf/g protein loss', 1.00),
        ('SENDAY', 'SPE', 'Daily baseline senescence rate of leaves past maximum age', 'd-1', 0.020),
    ]

    rows = []
    for param, ftype, desc, unit, base_val in params_meta:
        val = cand_dict.get(param, base_val)
        raw_status = status_dict.get(param, 'active' if param in cand_dict else 'fixed')
        status = 'Calibrated' if raw_status == 'active' else 'Fixed'
        change_pct = ((val - base_val) / base_val) * 100.0 if base_val != 0 else 0.0
        rows.append({
            'Category': get_category(param),
            'Parameter': param,
            'File': f"TMGRO048.{ftype}",
            'Description': desc,
            'Unit': unit,
            'Tomato_Base': base_val,
            'Eggplant_Calib': val,
            'Change_pct': change_pct,
            'Status': status
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUT_TABLE_CSV_DIR / "Table1_Genetic_Parameters_Comparison.csv", index=False)
    return df


def get_category(param: str) -> str:
    if param in ['EM-FL', 'FL-SH', 'FL-SD', 'SD-PM', 'FL-LF', 'FL-VS', 'TRIFL', 'EM-V1', 'JU-R0']:
        return 'Phenology & Development'
    elif param in ['LFMAX', 'SLAVR', 'SIZLF', 'RWDTH', 'RHGHT', 'KCAN', 'KC_SLOPE', 'PGEFF']:
        return 'Canopy & Photosynthesis'
    elif param in ['XFRT', 'WTPSD', 'SFDUR', 'PODUR', 'THRSH', 'LNGSH', 'PM06', 'PM09', 'XMAGE', 'FRLFF', 'FRSTMF']:
        return 'Fruit Load & Partitioning'
    elif param in ['RTNO3', 'RTNH4', 'NMOBMX', 'NVSMOB', 'LNREF', 'NSLOPE', 'NSTFAC', 'FNPGN1', 'FNPGN2',
                   'PROLFI', 'PROLFG', 'PROLFF', 'PROSTI', 'PROSTG', 'PROSTF', 'PRORTI', 'PRORTG', 'PRORTF', 'PROSHI', 'PROSHG']:
        return 'Nitrogen & Protein Dynamics'
    else:
        return 'Drought Stress & Senescence'


# -------------------------------------------------------------
# 2. Table 2: Model Statistical Performance for Yield
# -------------------------------------------------------------
def build_table_2() -> pd.DataFrame:
    df_detail = pd.read_csv(RUN_DIR / "candidates_treatments_detail.csv")
    df13 = df_detail[df_detail['candidate'] == 'iter5_real13'].copy()

    def calc_stats_row(subset, group_type, group_name):
        obs = subset['obs_terminal_kg_ha'].values / 1000.0 # t/ha
        sim = subset['sim_terminal_kg_ha'].values / 1000.0 # t/ha
        n = len(obs)
        rmse = np.sqrt(np.mean((sim - obs)**2))
        nrmse = (rmse / np.mean(obs)) * 100.0
        d_denom = np.sum((np.abs(sim - np.mean(obs)) + np.abs(obs - np.mean(obs)))**2)
        d = 1.0 - np.sum((sim - obs)**2) / d_denom
        r2 = np.corrcoef(obs, sim)[0, 1]**2 if n > 1 else np.nan
        nse = 1.0 - np.sum((sim - obs)**2) / np.sum((obs - np.mean(obs))**2)
        return {
            'Group_Type': group_type,
            'Subgroup': group_name,
            'Sample_Size': n,
            'Obs_Mean': np.mean(obs),
            'Obs_SD': np.std(obs, ddof=1) if n > 1 else 0.0,
            'Sim_Mean': np.mean(sim),
            'Sim_SD': np.std(sim, ddof=1) if n > 1 else 0.0,
            'RMSE_t_ha': rmse,
            'NRMSE_pct': nrmse,
            'd_index': d,
            'R2': r2,
            'NSE': nse
        }

    rows = []
    # Modeling Phase
    rows.append(calc_stats_row(df13[df13['batch'] == 'Calibration'], 'Modeling Phase', 'Calibration (25SP + 26SP)'))
    rows.append(calc_stats_row(df13[df13['batch'] == 'Validation'], 'Modeling Phase', 'Validation (25SP + 26SP)'))
    rows.append(calc_stats_row(df13[df13['season'].isin(['25SP', '26SP'])], 'Modeling Phase', 'Two-Spring Pooled (25SP + 26SP)'))
    rows.append(calc_stats_row(df13[df13['batch'] == 'Independent_25FA'], 'Modeling Phase', 'Independent Test (2025 Autumn)'))
    rows.append(calc_stats_row(df13, 'Modeling Phase', 'Grand Pooled (All 35 Treatments)'))

    # Nitrogen Rate Range
    rows.append(calc_stats_row(df13[df13['nitro'] == 'N0'], 'Nitrogen Application Level', 'N0 (0 kg N/ha)'))
    rows.append(calc_stats_row(df13[df13['nitro'] == 'N1'], 'Nitrogen Application Level', 'N1 (150 kg N/ha)'))
    rows.append(calc_stats_row(df13[df13['nitro'] == 'N2'], 'Nitrogen Application Level', 'N2 (300 kg N/ha)'))
    rows.append(calc_stats_row(df13[df13['nitro'] == 'N3'], 'Nitrogen Application Level', 'N3 (450 kg N/ha)'))

    # Irrigation Regime
    rows.append(calc_stats_row(df13[df13['water'] == 'W1'], 'Irrigation Regime', 'W1 (Deficit / 50-60% ETc)'))
    rows.append(calc_stats_row(df13[df13['water'] == 'W2'], 'Irrigation Regime', 'W2 (Moderate / 75-80% ETc)'))
    rows.append(calc_stats_row(df13[df13['water'] == 'W3'], 'Irrigation Regime', 'W3 (Full / 100% ETc)'))

    df = pd.DataFrame(rows)
    df.to_csv(OUT_TABLE_CSV_DIR / "Table2_Model_Statistical_Performance_Yield.csv", index=False)
    return df


# -------------------------------------------------------------
# 3. Table 3: Water-Nitrogen Response Gaps
# -------------------------------------------------------------
def build_table_3() -> pd.DataFrame:
    df_detail = pd.read_csv(RUN_DIR / "candidates_treatments_detail.csv")
    df13 = df_detail[df_detail['candidate'] == 'iter5_real13'].copy()

    rows = []
    season_names = {
        '26SP': '2026 Spring (XXQL2601)',
        '25SP': '2025 Spring (XXQL2501)',
        '25FA': '2025 Autumn (XXQL2502)'
    }
    water_names = {
        'W3': 'W3 (Full Irrigation / 100% ETc)',
        'W2': 'W2 (Moderate Irrigation / 75-80% ETc)',
        'W1': 'W1 (Deficit Irrigation / 50-60% ETc)'
    }

    for season in ['26SP', '25SP', '25FA']:
        sub_s = df13[df13['season'] == season]
        for w in ['W3', 'W2', 'W1']:
            sub_w = sub_s[sub_s['water'] == w]
            n0 = sub_w[sub_w['nitro'] == 'N0']
            n3 = sub_w[sub_w['nitro'] == 'N3']
            if not n0.empty and not n3.empty:
                obs_n0 = n0['obs_terminal_kg_ha'].values[0] / 1000.0
                obs_n3 = n3['obs_terminal_kg_ha'].values[0] / 1000.0
                sim_n0 = n0['sim_terminal_kg_ha'].values[0] / 1000.0
                sim_n3 = n3['sim_terminal_kg_ha'].values[0] / 1000.0
                obs_gap = obs_n3 - obs_n0
                sim_gap = sim_n3 - sim_n0
                gap_error = sim_gap - obs_gap
                rows.append({
                    'Season': season_names[season],
                    'Irrigation_Regime': water_names[w],
                    'Obs_N0_t_ha': obs_n0,
                    'Obs_N3_t_ha': obs_n3,
                    'Obs_N_Gap_t_ha': obs_gap,
                    'Sim_N0_t_ha': sim_n0,
                    'Sim_N3_t_ha': sim_n3,
                    'Sim_N_Gap_t_ha': sim_gap,
                    'Gap_Bias_t_ha': gap_error
                })

    df = pd.DataFrame(rows)
    df.to_csv(OUT_TABLE_CSV_DIR / "Table3_Water_Nitrogen_Response_Gaps.csv", index=False)
    return df


# -------------------------------------------------------------
# 4. Table 4: Vegetative Process Growth Variables Performance
# -------------------------------------------------------------
def build_table_4() -> pd.DataFrame:
    p25_dir = RUN_DIR / "full_season_iter5_real13_25SP"
    p26_dir = RUN_DIR / "full_season_iter5_real13_26SP"
    df25 = pd.read_csv(p25_dir / "25SP_deterministic_process_compare.csv")
    df26 = pd.read_csv(p26_dir / "26SP_deterministic_process_compare.csv")

    df_both = pd.concat([df25, df26], ignore_index=True)
    df25['OBS_CWAD'] = df25['OBS_LWAD'] + df25['OBS_SWAD']
    df25['SIM_CWAD'] = df25['SIM_LWAD'] + df25['SIM_SWAD']
    df26['OBS_CWAD'] = df26['OBS_LWAD'] + df26['OBS_SWAD']
    df26['SIM_CWAD'] = df26['SIM_LWAD'] + df26['SIM_SWAD']
    df_both['OBS_CWAD'] = df_both['OBS_LWAD'] + df_both['OBS_SWAD']
    df_both['SIM_CWAD'] = df_both['SIM_LWAD'] + df_both['SIM_SWAD']

    vars_info = [
        ('LAID', 'Leaf Area Index', 'm2/m2'),
        ('LWAD', 'Leaf Dry Biomass', 'kg/ha'),
        ('SWAD', 'Stem Dry Biomass', 'kg/ha'),
        ('CWAD', 'Shoot Vegetative Dry Biomass', 'kg/ha'),
        ('CHTD', 'Canopy Height', 'm'),
    ]

    seasons = [
        ('2025 Spring', df25),
        ('2026 Spring', df26),
        ('Two-Spring Pooled', df_both),
    ]

    rows = []
    for var_code, var_name, unit in vars_info:
        for s_label, df_s in seasons:
            obs = df_s[f'OBS_{var_code}'].values
            sim = df_s[f'SIM_{var_code}'].values
            valid = (~np.isnan(obs)) & (~np.isnan(sim)) & (obs > -90) & (sim > -90)
            x, y = obs[valid], sim[valid]
            n = len(x)
            rmse = np.sqrt(np.mean((y - x)**2))
            nrmse = (rmse / np.mean(x)) * 100.0 if np.mean(x) != 0 else np.nan
            d_denom = np.sum((np.abs(y - np.mean(x)) + np.abs(x - np.mean(x)))**2)
            d = 1.0 - np.sum((y - x)**2) / d_denom if d_denom != 0 else np.nan
            r2 = np.corrcoef(x, y)[0, 1]**2 if n > 1 else np.nan
            nse = 1.0 - np.sum((y - x)**2) / np.sum((x - np.mean(x))**2) if np.sum((x - np.mean(x))**2) != 0 else np.nan
            rows.append({
                'Variable_Code': var_code,
                'Variable_Name': var_name,
                'Unit': unit,
                'Season': s_label,
                'Sample_Size': n,
                'Obs_Min': np.min(x),
                'Obs_Max': np.max(x),
                'Obs_Mean': np.mean(x),
                'Sim_Mean': np.mean(y),
                'RMSE': rmse,
                'NRMSE_pct': nrmse,
                'd_index': d,
                'R2': r2,
                'NSE': nse
            })

    df = pd.DataFrame(rows)
    df.to_csv(OUT_TABLE_CSV_DIR / "Table4_Vegetative_Growth_Performance.csv", index=False)
    return df


# -------------------------------------------------------------
# 5. Master Markdown Report Generation
# -------------------------------------------------------------
def generate_markdown_report(t1: pd.DataFrame, t2: pd.DataFrame, t3: pd.DataFrame, t4: pd.DataFrame):
    report_path = OUT_REPORT_DIR / "paper_tables_iter5_real13.md"

    md = []
    md.append("# 论文出版标准数据表格汇编：DSSAT-Eggplant 作物模型率定与验证\n")
    md.append("**率定批次编号**: `eval_full_gen_page22_sasc0925_150x5` (候选解 `iter5_real13`)\n")
    md.append("**原始番茄基线参数参考源**: `data/user/ref/Genotype4.8.5/` (`TMGRO048.CUL`, `TM0001 Florida 47`; `TMGRO048.ECO`, `TM0001`; `TMGRO048.SPE`)\n")
    md.append("**学术规范约束遵守声明**: 本报告结果部分与所有数据表格**严格仅报告与对比作物遗传参数**（`.CUL`、`.ECO`、`.SPE`），土壤物理参数与田间管理/初始条件参数已在科学对账规范下完全隔离，不出现在遗传参数对比表中。\n\n")
    md.append("---\n\n")

    # Table 1
    md.append("## 表 1 (Table 1): 茄子遗传参数率定结果与基准番茄品种 (Florida 47) 比较\n")
    md.append("**Table 1: Comparison of calibrated crop genetic parameters for eggplant against the baseline tomato cultivar (Florida 47) in the CROPGRO model.**\n\n")
    md.append("| 生理功能分类 (Category) | 参数代号 (Parameter) | DSSAT模块文件 (File) | 生理生态学定义与功能 (Definition & Function) | 单位 (Unit) | 番茄基准值 (Tomato Base) | 茄子率定值 (Eggplant Calibrated) | 相对变幅 (%) (Relative Change) | 率定状态 (Status) |\n")
    md.append("| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: |\n")
    for _, r in t1.iterrows():
        md.append(f"| {r['Category']} | `{r['Parameter']}` | `{r['File']}` | {r['Description']} | {r['Unit']} | {r['Tomato_Base']:.4g} | {r['Eggplant_Calib']:.4g} | {r['Change_pct']:+.1f}% | {r['Status']} |\n")
    md.append("\n> **注 (Note)**: 所有参数均严格来源于 DSSAT 作物品种定义文件 (`.CUL`)、生态型文件 (`.ECO`) 及物种特性文件 (`.SPE`)。番茄对照基准取自 DSSAT 官方发布的代表性鲜食半有限生长型品种 Florida 47 (`TM0001`)。表中相对变幅定义为 `(Eggplant - Tomato) / Tomato × 100%`。\n\n")
    md.append("---\n\n")

    # Table 2
    md.append("## 表 2 (Table 2): 茄子模型在不同建模阶段与施氮水平下的果实鲜重累计产量模拟统计指标\n")
    md.append("**Table 2: Statistical performance of the calibrated CROPGRO-Eggplant model for cumulative fresh fruit yield across modeling phases, nitrogen application rates, and irrigation regimes.**\n\n")
    md.append("| 分组维度 (Dimension) | 亚组名称 (Subgroup) | 样本量 (n) | 实测均值 ± 标准差 (Obs Mean ± SD, t/ha) | 模拟均值 ± 标准差 (Sim Mean ± SD, t/ha) | RMSE (t/ha) | NRMSE (%) | 一致性指数 (d-index) | 决定系数 ($R^2$) | 纳什效率系数 (NSE) |\n")
    md.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
    for _, r in t2.iterrows():
        r2_str = f"{r['R2']:.3f}" if pd.notnull(r['R2']) else "N/A"
        md.append(f"| {r['Group_Type']} | {r['Subgroup']} | {r['Sample_Size']} | {r['Obs_Mean']:.2f} ± {r['Obs_SD']:.2f} | {r['Sim_Mean']:.2f} ± {r['Sim_SD']:.2f} | {r['RMSE_t_ha']:.2f} | {r['NRMSE_pct']:.2f}% | {r['d_index']:.4f} | {r2_str} | {r['NSE']:.4f} |\n")
    md.append("\n> **注 (Note)**: 统计指标计算采用 Dias 等 (2026) 规范。$NRMSE = (RMSE / \\overline{Obs}) \\times 100\\%$。率定集覆盖 2025 年春季与 2026 年春季代表性极端处理（8个），验证集覆盖两春季其余交叉处理（15个），独立外推集为 2025 年秋季全处理（12个），全样本集共包含 35 个水氮管理组合。\n\n")
    md.append("---\n\n")

    # Table 3
    md.append("## 表 3 (Table 3): 三生长季节不同水分梯度下终茬鲜重产量及氮肥响应间隙 ($N_3 - N_0$)\n")
    md.append("**Table 3: Terminal fresh fruit yields and nitrogen response gaps (N3 - N0) under contrasting irrigation regimes across three distinct growing seasons.**\n\n")
    md.append("| 试验季节 (Season) | 灌溉水梯度 (Irrigation Regime) | 实测 N0 产量 (Obs N0, t/ha) | 实测 N3 产量 (Obs N3, t/ha) | 实测增产差值 (Obs Gap, t/ha) | 模拟 N0 产量 (Sim N0, t/ha) | 模拟 N3 产量 (Sim N3, t/ha) | 模拟增产差值 (Sim Gap, t/ha) | 间隙预测偏差 (Gap Bias, t/ha) |\n")
    md.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
    for _, r in t3.iterrows():
        md.append(f"| {r['Season']} | {r['Irrigation_Regime']} | {r['Obs_N0_t_ha']:.2f} | {r['Obs_N3_t_ha']:.2f} | {r['Obs_N_Gap_t_ha']:+.2f} | {r['Sim_N0_t_ha']:.2f} | {r['Sim_N3_t_ha']:.2f} | {r['Sim_N_Gap_t_ha']:+.2f} | {r['Gap_Bias_t_ha']:+.2f} |\n")
    md.append("\n> **注 (Note)**: $N_3$ 施氮水平为 450 kg N/ha，$N_0$ 为 0 kg N/ha。增产差值定义为 $\\Delta Y = Y_{N3} - Y_{N0}$。间隙预测偏差定义为 $Sim\\ Gap - Obs\\ Gap$。\n\n")
    md.append("---\n\n")

    # Table 4
    md.append("## 表 4 (Table 4): 茄子季内营养生长过程动态变量 (LAI、叶干重、茎干重、地上干重及株高) 模拟精度评估\n")
    md.append("**Table 4: Statistical evaluation of in-season vegetative growth dynamics (LAI, organ dry weights, and plant height) simulated by the calibrated eggplant model.**\n\n")
    md.append("| 过程动态变量 (Variable) | 单位 (Unit) | 生长季节 (Season) | 样本数 (n) | 实测范围 (Obs Range) | 实测均值 (Obs Mean) | 模拟均值 (Sim Mean) | RMSE | NRMSE (%) | 一致性指数 (d-index) | 决定系数 ($R^2$) | 纳什效率 (NSE) |\n")
    md.append("| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
    for _, r in t4.iterrows():
        md.append(f"| {r['Variable_Name']} (`{r['Variable_Code']}`) | {r['Unit']} | {r['Season']} | {r['Sample_Size']} | {r['Obs_Min']:.2f} – {r['Obs_Max']:.2f} | {r['Obs_Mean']:.2f} | {r['Sim_Mean']:.2f} | {r['RMSE']:.2f} | {r['NRMSE_pct']:.2f}% | {r['d_index']:.4f} | {r['R2']:.4f} | {r['NSE']:.4f} |\n")
    md.append("\n> **注 (Note)**: 实测数据来源于 2025 年春季与 2026 年春季多次破坏性生长分析取样（FileT 实测值）。地上部营养干重 (`CWAD`) 采用叶干重 (`LWAD`) 与茎干重 (`SWAD`) 之和。高度 (`CHTD`) 单位为米 (m)。\n")

    report_path.write_text("".join(md), encoding="utf-8")
    print(f"Master markdown report written successfully to {report_path.resolve()}")


def main():
    print("Compiling Table 1: Genetic Parameters...")
    t1 = build_table_1()
    print("Compiling Table 2: Model Statistical Performance for Yield...")
    t2 = build_table_2()
    print("Compiling Table 3: Water-Nitrogen Response Gaps...")
    t3 = build_table_3()
    print("Compiling Table 4: Vegetative Growth Variables Performance...")
    t4 = build_table_4()

    print("Generating comprehensive markdown report...")
    generate_markdown_report(t1, t2, t3, t4)
    print("All tables compiled and exported successfully!")


if __name__ == "__main__":
    main()
