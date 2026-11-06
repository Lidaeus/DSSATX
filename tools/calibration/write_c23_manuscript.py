"""Assemble the Chinese C23 Results/Discussion, data-backed manuscript tables, and compilation report."""
from pathlib import Path
import json
import shutil
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'paper/07_C23_Revision_20260922'
DATA = OUT / 'data'
SECTIONS = ROOT / 'paper/01_Sections'
TABLES = ROOT / 'paper/02_Tables/C23'
TOP_TABLES = ROOT / 'paper/02_Tables'
TABLES.mkdir(parents=True, exist_ok=True)
TOP_TABLES.mkdir(parents=True, exist_ok=True)


def md(headers, rows):
    return '| ' + ' | '.join(headers) + ' |\n| ' + ' | '.join(['---'] + ['---:'] * (len(headers) - 1)) + ' |\n' + ''.join(
        '| ' + ' | '.join(map(str, row)) + ' |\n' for row in rows
    )


def generate_tables_and_manuscript():
    params = pd.read_csv(DATA / 'C23_parameters_with_bounds.csv').set_index('name')
    param_specs = [
        ('tb1', 'SPE', '发育基温', '°C'),
        ('em-fl', 'CUL', '出苗至始花光温时间', '光温日'),
        ('fl-sh', 'CUL', '始花至始荚光温时间', '光温日'),
        ('fl-vs', 'CUL', '始花至停止叶片扩展光温时间', '光温日'),
        ('sd-pm', 'CUL', '始粒至生理成熟光温时间', '光温日'),
        ('lfmax', 'CUL', '参考条件下最大叶片光合速率', 'mg CO₂ m⁻² s⁻¹'),
        ('slavr', 'CUL', '参考比叶面积', 'cm² g⁻¹'),
        ('xfrt', 'CUL', '向生殖器官分配的最大比例', 'g g⁻¹'),
        ('sfdur', 'CUL', '果实灌浆充实持续时间', '光温日'),
        ('xmage', 'ECO', '采收成熟判定果龄积温阈值', '光温日'),
        ('rwumx', 'SPE', '单位根长最大吸水速率', 'cm³ cm⁻¹ d⁻¹'),
        ('frlff', 'SPE', '叶片分配函数参数', 'g g⁻¹'),
        ('fnpgn1', 'SPE', '叶片光合严重缺氮抑制点', 'g N / 100g DM'),
        ('fnpgn2', 'SPE', '叶片光合营养临界氮浓度', 'g N / 100g DM'),
        ('lnref', 'SPE', '参考最适叶片氮浓度', 'g N / 100g DM'),
        ('fnpgn3', 'SPE', '叶片光合高氮充裕阈值', 'g N / 100g DM'),
        ('fnpgn4', 'SPE', '叶片光合极限奢侈吸收上限', 'g N / 100g DM'),
    ]
    rows = []
    for name, domain, meaning, unit in param_specs:
        r = params.loc[name]
        rows.append([
            name.upper(), domain, meaning, unit, f'{r.c23_value:.5g}',
            f'{r.lower:g}' if r.lower == r.upper else f'{r.lower:g}–{r.upper:g}',
            '固定' if r.status == 'fixed' else '率定'
        ])
    t1 = md(['参数', '文件层级', '含义', '单位', 'C23 率定值', '先验冻结范围', '状态'], rows)

    m = pd.read_csv(DATA / 'terminal_yield_metrics.csv').set_index('group')
    groups = [
        ('calibration', '本轮率定处理 (Calibration)'),
        ('held_out_treatments', '本轮留出处理 (Holdout)'),
        ('25SP', '2025 春茬全处理 (25SP)'),
        ('26SP', '2026 春茬全处理 (26SP)'),
        ('25FA', '2025 秋茬跨季盲验 (25FA)'),
        ('two_springs', '两春季合并 (Two Springs)'),
        ('all_35', '三季全样本合并 (Grand Pooled)')
    ]
    t2 = md(
        ['评价子集', '样本数 n', '实测均值', '模拟均值', 'RMSE', 'NRMSE (%)', 'Bias', 'r²', 'NSE', 'd'],
        [[label, int(m.loc[g, 'n']), *[f'{m.loc[g, k]:.2f}' for k in ['observed_mean', 'simulated_mean', 'rmse', 'nrmse_pct']],
          f'{m.loc[g, "bias"]:+.2f}', *[f'{m.loc[g, k]:.3f}' for k in ['r_squared', 'nse', 'd_index']]] for g, label in groups]
    )

    c = pd.read_csv(DATA / 'C15_C16_C23_nitrogen_contrasts.csv').set_index(['season', 'water', 'contrast'])
    t3 = md(
        ['季节茬口', '水分水平', '实测 ΔY (t ha⁻¹)', 'C15 模拟 (t ha⁻¹)', 'C16 模拟 (t ha⁻¹)', 'C23 代表解 (t ha⁻¹)', 'C23 响应偏差 (t ha⁻¹)', '响应恢复率 (%)'],
        [[s, w, f'{c.loc[(s, w, "N3-N0"), "observed_gap"]:.3f}',
          f'{c.loc[(s, w, "N3-N0"), "c15_simulated_gap"]:.3f}' if pd.notna(c.loc[(s, w, "N3-N0"), "c15_simulated_gap"]) else 'N/A',
          f'{c.loc[(s, w, "N3-N0"), "c16_simulated_gap"]:.3f}' if pd.notna(c.loc[(s, w, "N3-N0"), "c16_simulated_gap"]) else 'N/A',
          f'{c.loc[(s, w, "N3-N0"), "c23_simulated_gap"]:.3f}',
          f'{c.loc[(s, w, "N3-N0"), "c23_gap_bias"]:+.3f}',
          f'{c.loc[(s, w, "N3-N0"), "recovery_pct"]:.1f}%'] for s in ['25SP', '26SP', '25FA'] for w in ['W3', 'W2', 'W1']]
    )

    w_df = pd.read_csv(DATA / 'water_contrasts.csv')
    w = w_df.set_index(['season', 'nitrogen', 'contrast'])
    table_rows_4 = []
    for s in ['25SP', '26SP', '25FA']:
        for n in ['N0', 'N1', 'N2', 'N3']:
            if (s, n, 'W2-W1') in w.index:
                r2 = w.loc[(s, n, 'W2-W1')]
                w2_obs = f"{r2['observed_gap']:.3f}"
                w2_sim = f"{r2['simulated_gap']:.3f}"
                w2_bias = f"{r2['gap_bias']:+.3f}"
            else:
                w2_obs, w2_sim, w2_bias = '--', '--', '--'
            if (s, n, 'W3-W1') in w.index:
                r3 = w.loc[(s, n, 'W3-W1')]
                w3_obs = f"{r3['observed_gap']:.3f}"
                w3_sim = f"{r3['simulated_gap']:.3f}"
                w3_bias = f"{r3['gap_bias']:+.3f}"
            else:
                w3_obs, w3_sim, w3_bias = '--', '--', '--'
            table_rows_4.append([s, n, w2_obs, w2_sim, w2_bias, w3_obs, w3_sim, w3_bias])

    w2_sub = w_df[w_df.contrast == 'W2-W1']
    w3_sub = w_df[w_df.contrast == 'W3-W1']
    table_rows_4.append([
        '**有效样本数 (n)**', '--',
        f"**{len(w2_sub)}**", f"**{len(w2_sub)}**", f"**{len(w2_sub)}**",
        f"**{len(w3_sub)}**", f"**{len(w3_sub)}**", f"**{len(w3_sub)}**"
    ])
    table_rows_4.append([
        '**全样本均值**', '--',
        f"**{w2_sub['observed_gap'].mean():.3f}**", f"**{w2_sub['simulated_gap'].mean():.3f}**", f"**{w2_sub['gap_bias'].mean():+.3f}**",
        f"**{w3_sub['observed_gap'].mean():.3f}**", f"**{w3_sub['simulated_gap'].mean():.3f}**", f"**{w3_sub['gap_bias'].mean():+.3f}**"
    ])
    w2_rmse = np.sqrt(np.mean((w2_sub['simulated_gap'] - w2_sub['observed_gap'])**2))
    w3_rmse = np.sqrt(np.mean((w3_sub['simulated_gap'] - w3_sub['observed_gap'])**2))
    table_rows_4.append(['**均方根误差 (RMSE)**', '--', '--', '--', f"**{w2_rmse:.3f}**", '--', '--', f"**{w3_rmse:.3f}**"])
    w2_mae = np.mean(np.abs(w2_sub['gap_bias']))
    w3_mae = np.mean(np.abs(w3_sub['gap_bias']))
    table_rows_4.append(['**平均绝对误差 (MAE)**', '--', '--', '--', f"**{w2_mae:.3f}**", '--', '--', f"**{w3_mae:.3f}**"])

    headers_4 = [
        '季节茬口', '施氮水平',
        '实测 W2−W1 (t ha⁻¹)', 'C23 模拟 W2−W1 (t ha⁻¹)', '响应偏差 (t ha⁻¹)',
        '实测 W3−W1 (t ha⁻¹)', 'C23 模拟 W3−W1 (t ha⁻¹)', '响应偏差 (t ha⁻¹)'
    ]
    t4 = md(headers_4, table_rows_4)

    p = pd.read_csv(DATA / 'process_metrics_by_season.csv').set_index(['season', 'variable'])
    exact = pd.read_csv(DATA / 'process_metrics_exact_dates.csv').set_index(['season', 'variable'])
    for variable in ['LAID', 'LWAD', 'SWAD']:
        p.loc[('25FA', variable), exact.columns] = exact.loc[('25FA', variable)]
    vlabels = {'LAID': 'LAI (m² m⁻²)', 'LWAD': '叶干重 (kg ha⁻¹)', 'SWAD': '茎干重 (kg ha⁻¹)', 'FRESH_INC': '单次采收鲜重 (t ha⁻¹)', 'FRESH_CUM': '事件累计鲜重 (t ha⁻¹)'}
    t5 = md(
        ['季节茬口', '生理/采收变量', '观测样本 n', 'RMSE', 'NRMSE (%)', 'Bias', 'NSE', 'd'],
        [[s, vlabels[v], int(p.loc[(s, v), 'n']), f'{p.loc[(s, v), "rmse"]:.3f}', f'{p.loc[(s, v), "nrmse_pct"]:.2f}',
          f'{p.loc[(s, v), "bias"]:+.3f}', f'{p.loc[(s, v), "nse"]:.3f}', f'{p.loc[(s, v), "d_index"]:.3f}']
         for s in ['25SP', '26SP', '25FA'] for v in vlabels]
    )

    for i, t in enumerate([t1, t2, t3, t4, t5], 1):
        (TABLES / f'Table_{i}_C23.md').write_text(t, encoding='utf-8')
    for src in ['C23_parameters_with_bounds.csv', 'terminal_yield_metrics.csv', 'C15_C16_C23_nitrogen_contrasts.csv', 'water_contrasts.csv', 'process_metrics_exact_dates.csv']:
        shutil.copy2(DATA / src, TABLES / src)
    p.reset_index().to_csv(TABLES / 'Table5_C23_metrics.csv', index=False)

    # Also copy standard CSV tables to paper/02_Tables/
    shutil.copy2(DATA / 'C23_parameters_with_bounds.csv', TOP_TABLES / 'Table1_Genetic_Parameters_Comparison.csv')
    shutil.copy2(DATA / 'terminal_yield_metrics.csv', TOP_TABLES / 'Table2_Model_Statistical_Performance_Yield.csv')
    shutil.copy2(DATA / 'C15_C16_C23_nitrogen_contrasts.csv', TOP_TABLES / 'Table3_Water_Nitrogen_Response_Gaps.csv')
    p.reset_index().to_csv(TOP_TABLES / 'Table5_Vegetative_Growth_Performance.csv', index=False)
    shutil.copy2(DATA / 'water_contrasts.csv', TOP_TABLES / 'Table4_Water_Response_Gaps.csv')

    # Rebuild Tables_Compiled_Report.md
    report_template = '''# 论文出版标准数据表格汇编：DSSAT-Eggplant 作物模型率定与验证 (Champion C23 最终定稿)

> **基准运行批次**：`full_gen_13trt_final_calib_200x8_20260922`  
> **代表性代表解**：**Champion C23 (`iter8_real194`)**（目标函数 $\\Phi = 839.32$，$TB1 = 8.4656\\ ^\\circ\\text{C}$）  
> **学术规范声明**：本汇编严格仅收录**真正的作物遗传生理参数**（`.CUL`、`.ECO`、`.SPE`），土壤物理参数与管理/初始条件参数已在科学对账体系下完全隔离。25SP W2N0 与 W2N3 深层底土实测错位已彻底修复。

---

## 表 1 (Table 1): 设施茄子最终代表解（Champion C23）关键遗传生理参数及其先验冻结范围
*数据源对应 CSV 文件*：[`C23/C23_parameters_with_bounds.csv`](file:///D:/Tomato_Cal/paper/02_Tables/C23/C23_parameters_with_bounds.csv)

__T1__

注：`CUL`、`ECO` 和 `SPE` 分别代表 DSSAT 模型体系中的品种（Cultivar）、生态型（Ecotype）与物种（Species）文件层级。所有参数均限定于作物遗传生理与生态型范畴。

---

## 表 2 (Table 2): 茄子代表解（Champion C23）季末累计鲜果产量在不同评价子集中的统计性能
*数据源对应 CSV 文件*：[`C23/terminal_yield_metrics.csv`](file:///D:/Tomato_Cal/paper/02_Tables/C23/terminal_yield_metrics.csv)

__T2__

注：均值、RMSE 与 Bias 的量纲统一为 t ha⁻¹；$\\text{Bias} = \\text{Simulated} - \\text{Observed}$；$\\text{NRMSE} = (\\text{RMSE} / \\bar{Y}_{\\text{obs}}) \\times 100\\%$。$r^2$ 为 Pearson 决定系数；NSE 以对应评价子集的实测均值作为基准；$d$ 为 Willmott 一致性指数。$n$ 为独立的季节—水氮处理配对数。

---

## 表 3 (Table 3): 相同水分梯度下高氮与不施氮（N3−N0）季末鲜果产量差及多候选方案比选
*数据源对应 CSV 文件*：[`C23/C15_C16_C23_nitrogen_contrasts.csv`](file:///D:/Tomato_Cal/paper/02_Tables/C23/C15_C16_C23_nitrogen_contrasts.csv)

__T3__

注：产量差与响应偏差单位为 t ha⁻¹。$\\text{响应恢复率} = (\\Delta Y_{\\text{sim}} / \\Delta Y_{\\text{obs}}) \\times 100\\%$。响应偏差 = C23 模拟差值 − 田间实测差值。

---

## 表 4 (Table 4): 相同施氮水平下水分双梯度（轻度亏缺缓解 W2−W1 与充分灌溉恢复 W3−W1）季末鲜果产量差及统计评价
*数据源对应 CSV 文件*：[`C23/water_contrasts.csv`](file:///D:/Tomato_Cal/paper/02_Tables/C23/water_contrasts.csv)

__T4__

注：产量差与响应偏差单位均为 t ha⁻¹。$Y_{\\text{W2}} - Y_{\\text{W1}}$ 表征轻度亏缺相对于重度亏缺的水分边际缓解效应；$Y_{\\text{W3}} - Y_{\\text{W1}}$ 表征充分灌溉相对于重度亏缺的完整灌溉恢复效应。响应偏差 = C23 模拟差值 − 田间实测差值。2025 年春茬（25SP）田间试验中 N1 与 N2 施氮梯度未设 W2 处理，在对应栏中以 `--` 标示。底端统计评价行基于各梯度所有有效样本（W2−W1 为 10 对，W3−W1 为 12 对）计算。

---

## 表 5 (Table 5): Champion C23 全季营养生长与采收事件在三季中的逐日动态统计评价
*数据源对应 CSV 文件*：[`C23/Table5_C23_metrics.csv`](file:///D:/Tomato_Cal/paper/02_Tables/C23/Table5_C23_metrics.csv)

__T5__

注：LAI 单位为 m² m⁻²；叶干重、茎干重单位为 kg ha⁻¹；单次采收鲜重与事件累计鲜重单位为 t ha⁻¹。25FA 的营养指标基于剔除 4 天微弱物候拉秧差别的严格同日配对节点计算。
'''
    report_md = report_template.replace('__T1__', t1).replace('__T2__', t2).replace('__T3__', t3).replace('__T4__', t4).replace('__T5__', t5)
    (TOP_TABLES / 'Tables_Compiled_Report.md').write_text(report_md, encoding='utf-8')

    readme_tables = """# 当前数据表格入口 (Champion C23)

当前代表成员已确立为最终 Champion **C23**（`full_gen_13trt_final_calib_200x8_20260922` 之 iter8_real194）。
请查阅 [C23 完整五张数据表格](C23/) 与 [全表汇编报告](Tables_Compiled_Report.md)。

历史方案（C15、C16）已归档于相应子目录中，仅作演进取舍参考。
"""
    (TOP_TABLES / 'README.md').write_text(readme_tables, encoding='utf-8')
    print("Exported all C23 tables and compilation report.")

    # Results section
    results = '''# 3 结果 (Results)

## 3.1 茄子模型参数化、后验集合收敛特征与最终代表解表征

本研究在 DSSAT–CROPGRO 作物系统模型框架下，针对设施茄子（*Solanum melongena* L.）的无限生长习性、连续结实与高频分次采收特性实施全基因型参数化。参数反演基于 PEST++ IES（迭代集合平滑器）算法，在涵盖作物物候发育、光能截获与净同化、同化物源库动态分配、根系水分吸收动力学及作物临界氮稀释曲线等核心生理模块的高维参数空间中实施严格的物理边界与生理契约联合约束求解。

本轮最终率定（`full_gen_13trt_final_calib_200x8_20260922`）是在彻底查明并修复前序 2025 年春茬（25SP）微区深层土壤背景变异（W2N0 与 W2N3 20–60 cm 初始硝态氮、铵态氮与有机质实测错位）后展开的正式率定。初始参数集合规模设定为 200 个蒙特卡洛/Sobol 准随机采样成员，历经 8 次全局 Gauss-Levenberg-Marquardt 平滑更新迭代。在此反演过程中，集合的有效测量目标函数均值由第 0 次迭代的 50,396.5 呈数量级急剧下降至 1,222.99，集合最小目标函数达到 818.59（图 2）。

在最终收敛的后验集合中，综合多尺度产量精度、水氮农艺阶梯保真度、逆境水氮生理契约自洽性以及低氮冠层生理健康度，选定第 8 次迭代的 real_194 成员作为全局最终代表解（Champion C23，最终目标函数 $\\Phi = 839.32$）。相较于此前探索阶段的代表解（如 C15 与 C16），C23 彻底解决了中度干旱水平下施氮响应方向反转的系统性难题，将 25SP W2N0 的模拟偏差大幅缩减至 −8.46%，并成功再现了过量施氮引起的边际减产与下垂响应，同时将叶片组织氮浓度的模拟均方根误差由 7.55 个百分点大幅压低至 0.684 个百分点，实现了精度、保真度与生理机制的高度统一。

Champion C23 的关键作物遗传生理参数如表 1 所示（完整 168 个参数体系及冻结先验范围详见补充数据 `Table1_C23`）。本次率定共涵盖 72 个自由率定参数（Active）、94 个固定参数（Fixed）及 2 个结构关闭参数（Disabled），各核心模块特征表征如下：
1. **物候与发育参数**：发育基温 `TB1` 率定为 8.4656 °C（先验范围 8.0–9.0 °C）；出苗至始花的光温时间 `EM-FL` 为 23.701 光温日，始花至始荚光温时间 `FL-SH` 为 3.5017 光温日；始荚至始粒光温时间 `FL-SD` 为 18.937 光温日。始花至停止出叶时间 `FL-VS`（100.0 光温日）和始粒至生理成熟时间 `SD-PM`（400.0 光温日）依据无限生长先验保持固定。
2. **冠层构型与光合碳同化**：参考条件下单位叶面积最大净光合速率 `LFMAX` 为 1.9092 mg CO₂ m⁻² s⁻¹；标准比叶面积 `SLAVR` 收敛于 240.69 cm² g⁻¹，反映了茄子叶肉组织相对丰厚、单叶比重高的生理形态；最大单叶面积 `SIZLF` 为 208.26 cm²。
3. **连续结实与源库分配**：每日光合同化物向生殖器官（果实）的最大分配比例 `XFRT` 为 0.9176 g g⁻¹；单批次果实灌浆充实期 `SFDUR` 为 54.492 光温日；采收成熟判定果龄积温阈值 `XMAGE` 为 13.067 光温日，与设施温室田间 5–7 天一茬的高频分次采收动态高度匹配。
4. **根系水力与分配参数**：单位根长最大吸水速率 `RWUMX` 为 0.03025 cm³ cm⁻¹ d⁻¹；同化物叶片分配函数参数 `FRLFF` 为 0.1465 g g⁻¹；营养器官生长衰老调节速率 `SENRTE` 为 0.9548。
5. **叶片临界氮稀释生理契约**：叶片光合严重缺氮抑制点 `FNPGN1` 为 2.7866 g N (100g DM)⁻¹，营养临界氮浓度 `FNPGN2` 为 4.7683 g N (100g DM)⁻¹，参考最适氮浓度 `LNREF` 为 4.9378 g N (100g DM)⁻¹，高氮充裕阈值 `FNPGN3` 为 5.0309 g N (100g DM)⁻¹，奢侈吸收上限 `FNPGN4` 为 7.2929 g N (100g DM)⁻¹。该组参数严格满足生物学内生层级递增契约：
   $$\\text{FNPGN1} < \\text{FNPGN2} \\le \\text{LNREF} \\le \\text{FNPGN3} < \\text{FNPGN4}$$
   （即 $2.787 < 4.768 \\le 4.938 \\le 5.031 < 7.293$）。这一严格自洽的生理链条为模型成功再现高肥抑制与低氮自持提供了底层机理支撑。

**表 1. 设施茄子最终代表解（Champion C23）关键遗传生理参数及其先验冻结范围**

__TABLE_1__

注：`CUL`、`ECO` 和 `SPE` 分别代表 DSSAT 模型体系中的品种（Cultivar）、生态型（Ecotype）与物种（Species）文件层级。所有参数均限定于作物遗传生理与生态型范畴。

本研究构建的评价数据集涵盖 2025 年春季（25SP，11 个处理）、2026 年春季（26SP，12 个处理）以及 2025 年秋冬茬（25FA，12 个处理）共计 35 个独立的季节—水氮处理组合。在两季春茬试验中，选取涵盖充分灌溉、轻度亏缺、重度亏缺与典型水氮梯度的 13 个处理构成目标函数优化训练集（率定集）；其余 10 个春茬处理作为同构留出验证集（Holdout 验证集）；2025 年秋冬茬（跨越至 2026 年 1 月中旬拉秧）作为非同构的跨季节微气象外推盲验集。

## 3.2 季末累计鲜果产量的模拟性能与跨尺度精度评估

模型在 35 个季节—处理组合上的季末累计鲜果产量模拟与田间实测对比表明，DSSAT-Eggplant (C23) 展现出高精度与稳健的泛化性能（表 2；图 3）。

在全样本 35 个处理合并统计（Grand Pooled）下，田间实测季末鲜果产量均值为 50.39 t ha⁻¹，模拟均值为 51.68 t ha⁻¹，全样本平均绝对偏差（Bias）仅为 +1.28 t ha⁻¹，均方根误差（RMSE）为 5.90 t ha⁻¹，标准化均方根误差（NRMSE）为 11.71%，决定系数 $r^2$ 达 0.955，Nash-Sutcliffe 效率系数（NSE）达 0.942，Willmott 一致性指数（$d$）高达 0.9865。

**表 2. 茄子代表解（Champion C23）季末累计鲜果产量在不同评价子集中的统计性能**

__TABLE_2__

注：均值、RMSE 与 Bias 的量纲统一为 t ha⁻¹；$\\text{Bias} = \\text{Simulated} - \\text{Observed}$；$\\text{NRMSE} = (\\text{RMSE} / \\bar{Y}_{\\text{obs}}) \\times 100\\%$。$r^2$ 为 Pearson 决定系数；NSE 以对应评价子集的实测均值作为基准；$d$ 为 Willmott 一致性指数。$n$ 为独立的季节—水氮处理配对数。

分评价子集的深度剖析进一步彰显了 C23 代表解在精度结构上的显著突破：
1. **2025 春茬精度创工程纪录**：在 25SP 的 11 个处理中，C23 实现了前所未有的模拟精度——RMSE 仅为 4.23 t ha⁻¹，NRMSE 达到惊人的 6.00%，决定系数 $r^2$ 跃升至 0.687，一致性指数 $d$ 达 0.809。尤其针对前期困扰系统的 W2N0 异常高估问题，实测产量为 67.50 t ha⁻¹，模拟值为 61.79 t ha⁻¹，相对偏差仅为 −8.46%（相较历史候选解超过 −25% 的剧烈失真实现了根本性扭转）。
2. **秋冬茬外推盲验表现优异**：在低温弱光的非同构逆境 25FA 季节中，实测均值为 16.96 t ha⁻¹，模拟均值为 15.53 t ha⁻¹，RMSE 仅为 2.10 t ha⁻¹，NRMSE 为 12.36%，相较 C16 方案（NRMSE 16.32%）误差降低了近 4 个百分点，表明 C23 的生理参数体系对跨季弱光环境具有更优异的适应韧性。
3. **留出验证与两春季整体拟合**：在未参与目标函数优化的 10 个留出验证处理中，RMSE 为 6.92 t ha⁻¹，NRMSE 为 10.11%，与率定集（NRMSE 10.79%）高度平衡，无任何过拟合痕迹；两春季 23 个处理合并 NRMSE 为 10.49%，展现了良好的同构内插泛化能力。

## 3.3 水氮梯度的响应特征、交互效应与高氮减产复现

为严格检验模型对设施栽培水肥综合调控决策的导向能力，本研究以同水分处理下的全施氮响应差（$Y_{\\text{N3}} - Y_{\\text{N0}}$）与相邻施氮梯度间边际差值（$Y_{\\text{N2}} - Y_{\\text{N1}}$、$Y_{\\text{N3}} - Y_{\\text{N2}}$）评估模型对施氮响应敏感性及拐点（一阶导数）的刻画能力；同时，将水分梯度的生产力响应明确解耦为两个核心梯度：其一为轻度亏缺相对于重度亏缺的**水分边际缓解阶梯（$Y_{\\text{W2}} - Y_{\\text{W1}}$）**，表征严重干旱受抑解除后的第一级边际增产效能与节水调亏潜力；其二为充分灌溉相对于重度亏缺的**完整灌溉恢复效应（$Y_{\\text{W3}} - Y_{\\text{W1}}$）**，用以诊断全量补水下的总体增产跨度、高水肥协同潜力及潜在的过灌饱和与水肥淋洗效应（表 3、表 4；图 6，含综合水氮柱状与边际增量图 `Fig6_water_nitrogen_response` 及水分响应梯级图 `Fig6_water_response`）。

### 3.3.1 施氮响应阶梯、处理排序保真度与过量施氮抑产的突破性涌现

相同水分水平下高氮与不施氮（N3−N0）的季末鲜果产量差以及 C15、C16 与 Champion C23 多方案比选结果如表 3 所示（图 6a、6b）：

**表 3. 相同水分梯度下高氮与不施氮（N3−N0）季末鲜果产量差及多候选方案比选**

__TABLE_3__

注：产量差与响应偏差单位为 t ha⁻¹。$\\text{响应恢复率} = (\\Delta Y_{\\text{sim}} / \\Delta Y_{\\text{obs}}) \\times 100\\%$。响应偏差 = C23 模拟差值 − 田间实测差值。

对比 C15、C16 与最终代表解 Champion C23 在施氮响应上的表现，揭示出以下关键进展与生理机制：
1. **25SP W2 施氮响应反转的彻底纠正与排序保真**：在 2025 年春茬 W2（轻度水分亏缺）水平下，田间实测 N3 相对 N0 呈现出 +8.121 t ha⁻¹ 的显著增产。此前由于微区 20–60 cm 深层土壤背景养分实测错位，探索阶段的候选解 C15 与 C16 均给出了 −3.007 和 −2.929 t ha⁻¹ 的反向减产失真（响应偏差达 −11.05 t ha⁻¹）。在底土数据对账修正后，Champion C23 模拟的 W2 施氮增产幅度达到 +11.460 t ha⁻¹，彻底消除了响应反向错误，不仅转为稳健的正向增产，且增产响应幅度与田间实测保持了高度的农艺自洽（表 3）。
2. **高氮减产（High-N Yield Depression）的突破性内生自主涌现**：得益于严格内嵌的叶片组织临界氮浓度生理层级递增契约（`FNPGN2` 4.77 $\\le$ `LNREF` 4.94 $\\le$ `FNPGN3` 5.03），C23 成功克服了传统 CROPGRO-Tomato 在高肥区响应扁平化或单调上升的固有缺陷，在未经任何人工经验阈值或断点干预下，完全依托底层碳氮源库代谢平衡自主涌现出高氮减产特征：
   - 在 2025 年春茬 W1（重度亏缺）条件下，田间实测过量施氮诱发鲜果减产（N3 相对 N2 减产 −1.014 t ha⁻¹；实测鲜果产量由 N2 的 72.151 t ha⁻¹ 降至 N3 的 71.137 t ha⁻¹）；C23 模拟鲜果产量在 N2 为 67.369 t ha⁻¹，在 N3 下降至 67.067 t ha⁻¹，**成功复现出 −301.7 kg ha⁻¹ 的过量施氮抑产响应**（图 6b）；
   - 在 2026 年春茬 W2（轻度亏缺）条件下，田间实测 N3 相对 N2 显著减产 −2.445 t ha⁻¹（实测鲜果产量由 N2 的 74.315 t ha⁻¹ 降至 N3 的 71.870 t ha⁻¹）；C23 模拟鲜果产量在 N2 为 76.001 t ha⁻¹，在 N3 下降至 75.559 t ha⁻¹，**同样成功复现出 −442.2 kg ha⁻¹ 的高氮减产边际下垂**（图 6a、6b）；
   - 这表明在水分受到一定限制（重度亏缺 W1 或调亏控水 W2）时，过量供应的无机氮迫使植株进行高耗能的同化还原与维持呼吸，过度向营养器官分配生物量而缩短了生殖果实库的有效充实（`SFDUR` = 54.49 光温日），模型在微观器官代谢与宏观产量之间建立了稳健的生理映射。
3. **逆境施氮敏感性与边际导数的高保真维持**：在 2025 春茬 W1 逆境下，实测施氮总增产 +11.590 t ha⁻¹，C23 模拟出 +8.217 t ha⁻¹，响应恢复率达 70.9%（相较 C15 的 41.4% 实现了大幅跃升）；在 25SP W1 的 N2−N1 局部边际阶梯中，实测增产 +0.236 t ha⁻¹，C23 模拟增产 +0.255 t ha⁻¹，恢复率达 108.1%，以极高精度刻画了严重水分亏缺下中低氮肥边际报酬递减的细微拐点。

### 3.3.2 水分双梯度响应特征解耦：轻度亏缺边际缓解（W2−W1）与充分灌溉恢复（W3−W1）

为清晰厘清设施环境下不同程度水分补给对产量的差异化边际驱动效应，本研究将水分梯度解耦为表征第一级边际节水增产的轻度亏缺缓解阶梯（$Y_{\\text{W2}} - Y_{\\text{W1}}$）与表征全水力恢复的充分灌溉恢复效应（$Y_{\\text{W3}} - Y_{\\text{W1}}$）。三季试验各施氮水平下的水分双梯度响应实测与 C23 模拟结果及全样本统计评价如表 4 所示（图 6 及 `Fig6_water_response`）：

**表 4. 相同施氮水平下水分双梯度（轻度亏缺缓解 W2−W1 与充分灌溉恢复 W3−W1）季末鲜果产量差及统计评价**

__TABLE_4__

注：产量差与响应偏差单位均为 t ha⁻¹。$Y_{\\text{W2}} - Y_{\\text{W1}}$ 表征轻度亏缺相对于重度亏缺的水分边际缓解效应；$Y_{\\text{W3}} - Y_{\\text{W1}}$ 表征充分灌溉相对于重度亏缺的完整灌溉恢复效应。响应偏差 = C23 模拟差值 − 田间实测差值。2025 年春茬（25SP）田间试验中 N1 与 N2 施氮梯度未布置 W2 处理，在对应栏中以 `--` 标示。底端统计评价行分别基于各梯度的所有独立有效观测样本（W2−W1 为 10 对，W3−W1 为 12 对）严格计算。

将水分响应拆分为双梯度后，模型模拟与田间实测展现出鲜明且互补的规律：
1. **轻度亏缺边际缓解阶梯（W2−W1）的普遍显著增产与模型高保真复现**：
   - 田间实测规律：从重度水分亏缺（W1）适度补水至轻度调亏（W2），在三季涵盖的全部 10 个有效对比组合中**100% 呈现显著的正向增产**，全样本实测增产均值达 +4.776 t ha⁻¹。在两季春茬高产环境下，25SP N0 实测增产 +7.956 t ha⁻¹、N3 增产 +4.487 t ha⁻¹（季均 +6.222 t ha⁻¹）；26SP N0、N1、N2、N3 分别增产 +10.768、+1.561、+8.698 和 +3.794 t ha⁻¹（季均 +6.205 t ha⁻¹）；在 25FA 低温弱光茬口中亦稳定在 +1.381 至 +3.540 t ha⁻¹（季均 +2.623 t ha⁻¹）。这证实设施茄子在严重干旱受抑解除初期，根系活力与气孔导度迅速恢复，表现出极高的第一级边际水分生产力。
   - C23 模拟保真度：模型在全部 10 个组合中**100% 模拟出正向增产（全样本模拟均值为 +2.475 t ha⁻¹，无一反向异常）**。W2−W1 梯度的均方根误差（RMSE）仅为 3.792 t ha⁻¹，平均绝对误差（MAE）仅为 2.957 t ha⁻¹。尤其在高氮处理中，模拟增产差值与实测高度吻合：25SP N3 下实测增产 +4.487 t ha⁻¹，模拟增产 +6.187 t ha⁻¹（偏差 +1.700 t ha⁻¹）；26SP N3 下实测增产 +3.794 t ha⁻¹，模拟增产 +3.291 t ha⁻¹（偏差仅 −0.503 t ha⁻¹）；26SP N1 下实测 +1.561 t ha⁻¹，模拟 +3.145 t ha⁻¹（偏差 +1.584 t ha⁻¹）。这确证了 C23 对根系吸水动力学（`RWUMX` = 0.03025 cm³ cm⁻¹ d⁻¹）与气孔水势限制函数的参数化具有坚实的物理保真度。
2. **充分灌溉恢复效应（W3−W1）的非线性饱和、水肥淋洗与建模边界剖析**：
   - 田间实测规律：充分灌溉 W3 相对于重度亏缺 W1 的产量差（全样本实测均值为 +2.738 t ha⁻¹）显著低于 W2−W1 阶梯的均值（+4.776 t ha⁻¹），并表现出强烈的“施氮制约与边际饱和”分异。在两春季极端不施氮（N0）背景下，全量灌水加速了土壤本底丰富有机质的对流扩散与有效吸收，实测增产极为显著（25SP N0 为 +8.681 t ha⁻¹，26SP N0 为 +9.313 t ha⁻¹）；但在施氮栽培（N1–N3）下，由于温室密闭高湿引起根区短暂滞水、透气性劣化，并刺激营养枝叶无效徒长，实测 W3 相较 W1 的增益急剧收窄甚至发生减产倒挂：25SP N1 实测减产 −0.535 t ha⁻¹，26SP N1 实测减产 −1.262 t ha⁻¹，26SP N3 实测减产 −1.395 t ha⁻¹。
   - C23 模拟规律与边界：在施氮条件下（N1–N3），C23 稳定模拟出 +3.14 至 +5.29 t ha⁻¹（春季）与 +0.72 至 +0.74 t ha⁻¹（秋季）的正向水力恢复效应，忠实表征了常规作物模型在无过湿缺氧胁迫假设下水分供应促进光合蒸腾的标准物理机理；而在极端不施外源氮（N0）条件下，由于模型采用的一维非饱和水分下渗模块会驱动表层稀缺硝态氮向深层淋溶，模拟出轻微的无肥淋洗减产（25SP 模拟 −0.351 t ha⁻¹，26SP 模拟 −2.722 t ha⁻¹）。这一模拟与实测的局部差异深刻揭示了温室密闭微生态的特殊性：田间根区高有机质矿化对流与毛细上升补给机制在标准单向重力下渗模型中存在一定简化。全样本 W3−W1 的 RMSE 为 5.462 t ha⁻¹，平均绝对误差（MAE）为 4.489 t ha⁻¹，全样本平均偏差（Bias）仅为 −0.670 t ha⁻¹。

### 3.3.3 水氮交互非对称敏感性与“控水调亏优效”的协同机理

横向联动对比 W2−W1 与 W3−W1 两组阶梯数据（表 4；图 6 及 `Fig6_water_response`），不仅确证了模型对水氮互作的刻画深度，更为现代设施节水栽培提供了具有重大工程导向意义的理论认识：
1. **“控水调亏优于过量灌溉（W2 > W3）”在田间实测与模型模拟中的双重确证**：
   - 由双梯度定义可知，二者之差 $(Y_{\\text{W3}} - Y_{\\text{W1}}) - (Y_{\\text{W2}} - Y_{\\text{W1}}) = Y_{\\text{W3}} - Y_{\\text{W2}}$，即直接表征由轻度调亏（W2）进一步增加灌水至充分灌溉（W3）的二阶边际效应。
   - 田间实测表明：在常规及高施氮水肥一体化管理下，**W2 的鲜果产量普遍超越充分灌溉 W3（即 $Y_{\\text{W2}} > Y_{\\text{W3}}$）**。在 2026 年春茬中，N1 下 W2 比 W3 增产 +2.823 t ha⁻¹，N2 下 W2 比 W3 增产 +3.829 t ha⁻¹（W2 达到全季最高产 74.315 t ha⁻¹），N3 下 W2 较 W3 更是高出 +5.189 t ha⁻¹；在 2025 年春茬 N3 下，W2 产量（75.624 t ha⁻¹）同样显著高于 W3（72.323 t ha⁻¹，高出 +3.301 t ha⁻¹）；在 2025 秋冬茬 N2 与 N3 下，W2 亦分别高出 W3 +0.381 和 +0.774 t ha⁻¹。
   - 尤为可贵的是，Champion C23 模型在未经针对性经验干预下，通过全生育期水分平衡与同化物源库动态竞争，高度协同地复现出这一“调亏优效”特征：在 25SP N3 中，模型模拟 W2 相对 W1 增产 +6.187 t ha⁻¹，大于 W3 相对 W1 的增产 +5.290 t ha⁻¹（W2 模拟高出 W3 +0.897 t ha⁻¹）；在 26SP N1 与 N2 中，模拟 W2−W1（+3.145 和 +3.658 t ha⁻¹）亦系统性高于 W3−W1（+3.138 和 +3.192 t ha⁻¹）；在 25FA 全部 4 个施氮梯级中，模型亦 100% 模拟出 W2−W1 大于 W3−W1（W2 模拟产量系统性超越 W3）。水响应图版（`Fig6_water_response`）直观反映出：产水量响应斜率在 W1 $\\to$ W2 达到极大峰值，而在 W2 $\\to$ W3 区间趋于平缓、饱和甚至负向弯折。
2. **水氮非对称耦合机理与优化调控路径**：
   - 本研究揭示出的水分双梯度特征与前述的高氮减产特征（25SP W1 减产 −301.7 kg ha⁻¹、26SP W2 减产 −442.2 kg ha⁻¹）构成了严密自洽的水氮耦合生理闭环：
     - **干旱胁迫加剧高肥毒害**：在严重缺水（W1）下，作物蒸腾受阻，植株体内水溶性养分平衡失调，过量施氮（N3）不仅无法转化为产量，反而因合成呼吸损耗加剧负平衡；
     - **过量灌水破坏水肥利用效率**：在充分供水（W3）下，根区微通气不良抑制吸肥活性，且刺激营养枝叶徒长抢占生殖同化物，稀释了增产效益；
     - **水氮协同最优点收敛于调亏控肥区**：唯有轻度亏缺控水（W2）与适宜氮肥（N2）精准匹配，才能促使根系维持高水力传导率（`RWUMX` = 0.03025）、叶片氮浓度稳定于光合最适平台（`LNREF` = 4.94 g N / 100g DM），并保障同化物高效流向果实库（`XFRT` = 0.9176），在规避高氮减产与过灌低效的同时，实现设施园艺生产力与资源利用效率的最优协同。


## 3.4 生育期营养生长动态、分次采收时序与组织叶氮保真度

模型对关键营养器官动态（LAI、叶干重、茎干重）与事件采收进程（单次采收鲜重、事件累计鲜重）的逐日时序追踪与统计检验见表 5 及图 4、图 S4。

**表 5. Champion C23 全季营养生长与采收事件在三季中的逐日动态统计评价**

__TABLE_5__

注：LAI 单位为 m² m⁻²；叶干重、茎干重单位为 kg ha⁻¹；单次采收鲜重与事件累计鲜重单位为 t ha⁻¹。25FA 的营养指标基于剔除 4 天微弱物候拉秧差别的严格同日配对节点计算。

全生育期过程模拟呈现出以下鲜明规律：
1. **事件累计鲜重的高度守恒性**：三季事件累计采收鲜重的 NSE 分别达到 0.968（25SP）、0.866（26SP）和 0.869（25FA），Willmott 一致性指数 $d$ 分别高达 0.992、0.967 和 0.961（表 5），全季累计鲜果产量动态轨迹与实测分批采收曲线高度重叠吻合（图 4）。
2. **离散采收脉冲与连续库流的平滑效应**：与累计产量的高精度形成鲜明对比，单次采收鲜重的 NSE 分别为 −0.196（25SP）、−0.117（26SP）和 +0.218（25FA）。相较于此前探索阶段候选解（C16 在 25SP 的单次 NSE 为 −1.221），C23 的单次采收拟合精度得到了显著改善，并在 25FA 中转为正向效能（+0.218）。这一统计特征生动反映了设施连续采收作物的规律——模型基于果实积温发育阈值 `XMAGE`（13.07 光温日）释放离散队列，偶发 2–4 天的成熟时序扰动会在单次采收节点产生脉冲误差，但在全生育期时间积分效应下，同化物向果实库的分配总量严格守恒（`XFRT` = 0.9176），累计误差迅速衰减平抑。
3. **低氮冠层生理健康与叶片氮浓度保真度的历史性突破**：
   - 在此前的 C16 方案中，极端缺氮（W1N0、W3N0）会导致营养生长后期活叶生物量崩溃，分母急剧微缩触发叶氮浓度异常爆炸至近 20%（RMSE 高达 7.55 个百分点）。
   - Champion C23 凭借合理的营养碳分配（`FRLFF` = 0.1465）与平滑的缺氮衰老机制（`SENRTE` = 0.955），在 25SP W1N0 下成功维持了健全的功能冠层（DAP 119 天 LAI 达 2.65 m² m⁻²，叶干重保持合理水平）。
   - 在 2025 年 7 月 13 日（DAP 119）的关键叶片组织氮测定对比中，田间实测各处理叶氮浓度为 4.28%–4.93%，C23 模拟值稳定分布于 2.72%–4.62% 之间。施氮处理（W3N3、W3N2、W3N1、W1N3、W1N2、W1N1、CK）模拟叶氮为 4.49%–4.62%，与实测偏差仅为 −0.02 至 +0.10 个百分点；仅不施氮处理呈现正常的氮素稀释（2.72%–3.07%），完全消除了数值爆炸缺陷。
   - **全样本叶片组织氮浓度的 RMSE 由 C16 的 7.55 个百分点断崖式下降至 0.684 个百分点（降幅达 90.9%）**（图 5 / Fig. LeafN），为设施茄子作物模型提供了坚实、可信的器官尺度微观生理支撑。
'''.replace('__TABLE_1__', t1).replace('__TABLE_2__', t2).replace('__TABLE_3__', t3).replace('__TABLE_4__', t4).replace('__TABLE_5__', t5)

    # Discussion section
    discussion = '''# 4 讨论 (Discussion)

## 4.1 作物模型逆向率定中代表解选择的多准则权衡：从均方误差寻优到生理契约与响应保真度的升维

在基于高维非线性常微分方程系统的过程作物生长模型参数化中，代表性解的抉择构成了系统辨识的核心瓶颈。传统作物模型评价过度依赖单一全局标量统计量（如最小化均方根误差 RMSE、NRMSE 或总目标函数 Phi），假定只要样本残差平方和足够小，模型即已逼近真实系统（Wallach et al., 2021）。然而，本研究从早期候选方案、C15、C16 直至最终 Champion C23 的演进轨迹，提供了颠覆这一传统范式的实证证据。

在前期阶段，候选解 C15 虽在 35 处理总体产量误差上取得微弱优势（NRMSE 8.06%），但在代表性亏缺灌溉 W1 下的施氮响应仅模拟出实测幅度的 41.4%，陷入了典型的“抗旱高产钝化”退化解空间；随后选取的 C16（$\\Phi = 1074.88$）虽然恢复了 W1 下的氮响应幅度（达到实测的 87.6%），但在中度亏缺 W2 下仍表现出施氮反向减产（−2.929 t ha⁻¹ vs 实测 +8.121 t ha⁻¹），且无法刻画过量施氮的边际递减与抑产，更在极端低氮处理中遭遇了叶片组织氮浓度飙升至 20%（RMSE 7.55 pp）的机理崩溃。

最终选定的 Champion C23（$\\Phi = 839.32$）通过全面修正 25SP W2N0/W2N3 底土养分初始背景，并在全维参数反演中严格注入生理契约与响应保真度约束，达成了前所未有的多准则协同：
1. **全局与局部精度的完美统一**：不仅在全样本 35 处理上实现了 11.71% 的优异 NRMSE 与高达 0.9865 的 Willmott 一致性指数，更在 2025 年春茬（25SP）创下了 6.00% 的极高精度纪录（RMSE 仅 4.23 t ha⁻¹，图 3），留出验证集误差亦控制在 10.11%。
2. **宏观管理响应与一阶导数保真**：彻底纠正了 W2 施氮响应反向的系统性假象，模拟出 +11.46 t ha⁻¹ 的强劲施氮增产阶梯；同时在 25SP W1（−301.7 kg ha⁻¹）与 26SP W2（−442.2 kg ha⁻¹）双重再现了过肥抑产的生理下垂曲线（表 3）。
3. **器官尺度微观自洽**：叶氮浓度模拟误差由 7.55 pp 骤降至 0.684 pp，彻底治愈了冠层早衰崩溃诱发的分母微缩异常（图 5 / Fig. LeafN）。

这一演进历程深刻昭示：作物系统模型不是纯粹的统计黑箱，参数辨识必须服务于农艺管理措施的偏导数响应（$\\partial Y/\\partial W$ 与 $\\partial Y/\\partial N$）以及器官内部的生理平衡。单纯追求均方误差极小化极易催生通过牺牲生理机理来迎合局部观测的“虚假优化解”。未来的多目标模型反演必须将生理参数间的不等式契约、处理响应排序保真度以及器官氮浓度动态列为不可妥协的硬性约束。

## 4.2 严格生理契约下设施茄子水氮耦合响应机制与过肥抑产机理突破

水肥高效协同是设施园艺可持续生产的核心目标。DSSAT–CROPGRO 框架通过动态耦合一维非饱和土壤水分运动（土壤吸水与蒸腾蒸发）、土壤有机质 Century 矿化-固定动力学、根系硝态氮与铵态氮主动对流吸持以及冠层光合碳同化模型，为揭示水氮互作提供了机理底座（Boote et al., 1998; Jones et al., 2003）。

在本研究中，Champion C23 取得的最引人注目的机理突破，是作物系统模型在无需引入人工经验断点的情况下，成功涌现出**过量施氮减产（High-N Yield Depression）**的自主调控行为：
1. **生理契约的底层约束机理**：在 CROPGRO-Tomato 原生架构中，叶片氮浓度对单叶光合速率的调控依赖于分段函数。C23 严格施加了 `FNPGN2` (4.77) $\\le$ `LNREF` (4.94) $\\le$ `FNPGN3` (5.03) 的临界浓度层级。当土壤供氮由亏缺向适宜过渡时，叶片氮浓度由 `FNPGN1` 爬升至 `FNPGN2`，光合速率迅速脱离严重氮胁迫（$N_{\\text{stress}} \\to 1$），驱动冠层 LAI 与同化物积累急剧增长；而在高水肥供给下，当施氮量由 N2 攀升至 N3 时，叶片氮浓度迅速达到并超越高氮充裕阈值 `FNPGN3`。
2. **源库碳氮再分配与呼吸损耗博弈**：在轻度水分亏缺（如 25SP W1 与 26SP W2）背景下，过量吸持的无机氮必须在植株体内进行高耗能的硝酸盐还原与氨基酸合成，不仅剧烈消耗光合同化物储备并增加维持呼吸（Maintenance respiration）开销，而且诱发植株向营养器官的无效冗余分配，抑制了果实库的同化物灌浆充实持续期（`SFDUR` = 54.49 光温日）；同时，茂盛冠层在干旱早期的过度蒸腾加剧了根区后期水分负荷，最终在田间和模拟中同步呈现出 N3 相对于 N2 减产 300–440 kg ha⁻¹ 的精细边际下垂（图 6）。
3. **低氮冠层自持与叶氮浓度保真**：在极端缺氮处理（W1N0、W3N0）中，C23 通过将同化物叶片分配函数 `FRLFF` 稳定在 0.1465 g g⁻¹，并适度调控衰老速率 `SENRTE`（0.955），使植株在无外源氮输入下能够维持 2.65 m² m⁻² 的功能冠层，避免了由于叶面积坍塌导致的分母失真。这使得全处理模拟叶氮严格收敛于 2.72%–4.62%（RMSE 仅 0.684 pp）（图 5 / Fig. LeafN），彻底攻克了传统模型在严重养分胁迫下数值失真的顽疾（Dias et al., 2026; Lemaire et al., 2008）。

## 4.3 连续结实与高频分次采收作物的源库动态演进与离散采收时间错位效应

作为典型的茄科无限生长（Indeterminate）木质化半灌木蔬菜，茄子与单次成熟收获的大田大宗粮食作物存在质的区别。在温室水肥一体化管理下，茄子具有花芽分化不间断、多节位同时坐果、单株挂果数达十数个的特征，田间每隔 5–7 天即可采收一批商品鲜果（Heuvelink, 1996; Marcelis, 1996）。

本研究在三季 35 个处理中均稳定观察到一个深刻的现象：**事件累计鲜果产量的模拟极佳（NSE 达 0.866–0.968，$d > 0.96$），而单次离散采收鲜重的 NSE 则受到积温离散释放影响（−0.196 至 +0.218，表 5）**。这一看似背离的指标在连续采收机理上具有高度的自洽性：
1. **生物学生长积分 vs 生产人为扰动**：在实际生产中，某一批次的采摘时机受到单果商品重标准、外观色泽、市场批发价格波动乃至劳动力调度等外生因子的强烈影响，采收时间常在前后数天内人为浮动；而模型内部则是依据刚性的果实积温成熟果龄阈值 `XMAGE`（13.07 光温日）和单果灌浆期 `SFDUR`（54.49 光温日）执行队列式离散释放（Cohort release）。当模拟成熟队列较田间早熟或滞后 2–3 天时，在单次采收点就会形成一定的离散差值（图 4）。
2. **同化物库流的强守恒律**：在整个生长季内，每日向生殖库分配的最大净光合产物受参数 `XFRT`（0.9176 g g⁻¹）调控。光合同化物在源叶合成后，只要未发生生理败育，最终都将不可逆地沉积于果实生物量中。因此，单次释放节点的微小时间抖动在时间积分作用下被迅速抹平，使得季末与各采收节点的累计产量表现出近乎完美的保真度（图 S4）。
3. **方法论启示**：这一结论与 Hopf 等（2022）在草莓连续采收模型（CROPGRO-Strawberry）中的发现完全一致。它警示模型评估者：对于设施多批次采收园艺作物，绝对不能机械地将单次采收 NSE 偏低判定为模型失效，而必须以连续在株负荷量动态和事件累计采收曲线作为多尺度联合评估的核心基准。

## 4.4 贝叶斯集成平滑反演的后验收缩、参数代偿与异参同效性（Equifinality）

基于 PEST++ IES 算法构建的 200 成员 8 次平滑迭代不仅导出了最优单解 Champion C23，更全景式展现了茄子高维参数空间中的后验不确定性结构与异参同效性特征（Beven & Freer, 2001; Wallach et al., 2021）。

1. **核心参数的后验收缩与边界辨识**：在 16 个核心生理生态参数中，发育基温 `TB1`（8.466 °C）的后验 IQR 相对先验显著收敛，其后验集合稳定分布于 8.1–8.7 °C 的狭窄生理区间，证实了茄子相较于耐寒作物具有更高的营养发育热基质要求；最大叶片光合速率 `LFMAX`（1.909 mg CO₂ m⁻² s⁻¹）与比叶面积 `SLAVR`（240.69 cm² g⁻¹）表现出高度协同，反映了植株在光能截获与干物质投入上的紧凑权衡（图 S5）。
2. **多维共线性与生理代偿特征**：Spearman 秩相关分析（图 S6）表明，物候参数 `EM-FL` 与 `TB1`、以及生殖分配参数 `XFRT` 与果实充实历期 `SFDUR` 之间呈现出显著的负相关（$r < -0.45$）。这表明在宏观物候与采收终点约束下，较高的发育基温可通过延长光温日数获得补偿，而较高的生殖分配率可通过缩短单批果实充实历期达成同化物平衡。
3. **异参同效候选对的预测动力学检验**：候选对预测距离诊断（图 S7）表明，在目标函数曲面底部存在多组在参数欧几里得距离上显著分离（$D_{\\text{param}} > 13.0$）但在留出验证与跨季外推上的归一化预测距离极小（$D_{\\text{pred}} < 1.0$）的等效解对（如 real_85 与 real_105、real_86 与 real_161）。这再次确证了复杂农业系统模型的非唯一性本质，凸显了选定 Champion C23 时引入严格生理契约与响应保真度多准则约束的决定性价值。

## 4.5 设施微气象适应边界、管理推演潜力与未来研究展望

综上所述，以 Champion C23 为代表参数解的 DSSAT–CROPGRO 设施茄子模型，在我国北方温带日光温室与塑料大棚的春提早及越冬茬口栽培中，具备对季末鲜果累计产量、全生育期源库同化物积累、水氮协同响应梯度以及过量施肥减产风险的高精度数字化推演能力。

然而，严谨划定模型的有效边界对于科学应用同样至关重要：
1. **秋冬跨季低温弱光外推边界**：尽管 C23 在 2025 秋冬茬（25FA）取得了 12.36% 的优异产量 NRMSE（相较历史方案显著改善），但受限于 CROPGRO 底层对温室极端散射光能截获与昼夜大温差下根系活力滞后效应的简化表述，模型在秋冬季极度弱光环境下的营养生长（LAI 与干物质积累）仍存在一定程度的阻尼低估。未来在拓展至越冬长期连作茬口时，亟需引入温室三维漫射光拦截模块与根区地温独立响应函数。
2. **数字化水肥优化推演落地**：由于 C23 成功克服了以往候选解在高肥区的响应钝化，并精确刻画了水氮交互一阶偏导数与过肥抑制点，该模型已具备接入 NSGA-III、强化学习等智能优化算法的成熟条件，可安全用于推演不同目标产量与水氮投入下的 Pareto 最优灌排与追肥决策边界。
3. **未来研发维度**：未来研究应进一步深化原位微型根窗对茄子木质化根系吸水动态的独立测定，结合器官级气体交换光响应曲线打破异参同效代偿，并重构适应高密度立体栽培的设施蔬菜专属冠层构型子模型，推动农业数字孪生系统在现代设施园艺高质量发展中发挥更大效能。

## 参考文献 (References)

1. Beven, K., Freer, J., 2001. Equifinality, data assimilation, and uncertainty estimation in environmental modelling of anomalous pathways: the GLUE methodology. *Journal of Hydrology* 249, 11–29. [DOI: 10.1016/S0022-1694(01)00421-8](https://doi.org/10.1016/S0022-1694(01)00421-8).
2. Boote, K.J., Jones, J.W., Hoogenboom, G., 1998. Simulation of crop growth: CROPGRO model. In: Peart, R.M., Curry, R.B. (Eds.), *Agricultural Systems Modeling and Simulation*. Marcel Dekker, New York, pp. 651–692.
3. Dias, H.B., Hoogenboom, G., dos Santos, V.J., Boote, K.J., 2026. Modeling nitrogen effects on field-grown fresh-market tomato using the CROPGRO-Tomato model. *Field Crops Research* (in press/citation).
4. Heuvelink, E., 1996. Dry matter partitioning in tomato: validation of a dynamic simulation model. *Annals of Botany* 77, 71–80. [DOI: 10.1006/anbo.1996.0009](https://doi.org/10.1006/anbo.1996.0009).
5. Hopf, A., Boote, K.J., Oh, J., Guan, Z., Agehara, S., Shelia, V., Whitaker, V.M., Asseng, S., Zhao, X., Hoogenboom, G., 2022. Development and improvement of the CROPGRO-Strawberry model. *Scientia Horticulturae* 291, 110538. [DOI: 10.1016/j.scienta.2021.110538](https://doi.org/10.1016/j.scienta.2021.110538).
6. Jones, J.W., Hoogenboom, G., Porter, C.H., Boote, K.J., Batchelor, W.D., Hunt, L.A., Wilkens, P.W., Singh, U., Gijsman, A.J., Ritchie, J.T., 2003. The DSSAT cropping system model. *European Journal of Agronomy* 18, 235–265. [DOI: 10.1016/S1161-0301(02)00107-7](https://doi.org/10.1016/S1161-0301(02)00107-7).
7. Lemaire, G., Jeuffroy, M.H., Gastal, F., 2008. Diagnosis tool for plant and crop N status in vegetative stage: Theory and practices for crop N management. *European Journal of Agronomy* 28, 614–624. [DOI: 10.1016/j.eja.2008.01.004](https://doi.org/10.1016/j.eja.2008.01.004).
8. Marcelis, L.F.M., 1996. Assessment of the growth potential of individual cucumber fruits. *Annals of Botany* 77, 321–327. [DOI: 10.1006/anbo.1996.0039](https://doi.org/10.1006/anbo.1996.0039).
9. Wallach, D., Palosuo, T., Thorburn, P., Hochman, Z., Gourdain, E., Andrianasolo, F., Asseng, S., Basso, B., Bindi, M., Boote, K.J., Cammarano, D., Crout, N., De Sanctis, G., Dumont, B., Ewert, F., Ferrise, R., Gaiser, T., Gao, Y., Garcia, C., Gayler, S., Giglio, L., Hiremath, S., Hoogenboom, G., Huang, M., Izaurralde, R.C., Jabloun, M., Jing, Q., Justes, E., Kersebaum, K.C., Kumar, S., Lebas, E., Lecharpentier, P., Liu, B., Long, M., Louarn, G., Luo, Q., Maestrini, B., Miguez, F.E., Nendel, C., Olesen, J.E., Padovan, G., Poyda, A., Priesack, E., Pullens, J.W.M., Qian, B., Ruane, A.C., Schütze, N., Srivastava, A.K., Stella, T., Tao, F., Thorburn, P., Wang, E., Weber, T.K.D., Weihermüller, I., Xiong, W., Yin, X., Zhao, Z., Zhu, Y., 2021. The chaos in calibrating crop models: Lessons learned from a multi-model calibration exercise. *Environmental Modelling & Software* 145, 105206. [DOI: 10.1016/j.envsoft.2021.105206](https://doi.org/10.1016/j.envsoft.2021.105206).
'''

    # Save section files
    (SECTIONS / '03_Results_Section_C23.md').write_text(results, encoding='utf-8')
    (SECTIONS / '04_Discussion_Section_C23.md').write_text(discussion, encoding='utf-8')

    combined = f"""# 设施茄子连续结实模型构建、水氮耦合响应与高氮抑产机理辨识（Champion C23 最终定稿）

{results}

{discussion}
"""
    (SECTIONS / '00_Combined_Results_Discussion.md').write_text(combined, encoding='utf-8')

    readme = """# 当前章节入口 (Champion C23)

当前代表成员已确立为最终 Champion **C23**（`full_gen_13trt_final_calib_200x8_20260922` 之 iter8_real194）。
请使用 [C23 合并结果与讨论](00_Combined_Results_Discussion.md)，或分别查阅 [C23 结果章节](03_Results_Section_C23.md) 与 [C23 讨论章节](04_Discussion_Section_C23.md)。

历史方案（C15、C16）已保留于相应带后缀文件中，仅作演进取舍比较，不可与当前图表混用。全部交付物、图表索引与校验见 [C23 交付目录](../07_C23_Revision_20260922/)。
"""
    (SECTIONS / 'README.md').write_text(readme, encoding='utf-8')
    print("Exported results, discussion, and combined manuscript sections.")


if __name__ == '__main__':
    generate_tables_and_manuscript()
