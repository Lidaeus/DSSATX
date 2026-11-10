import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "tools/calibration/write_c31_manuscript.py"

content = SCRIPT_PATH.read_text(encoding="utf-8")

# 1. Update Table 5 rows and headers to include r²
old_t5_code = """                t5_rows.append([
                    s, vname, int(row['n']),
                    f"{row['rmse']:.3f}", f"{row['nrmse_pct']:.2f}",
                    f"{row['bias']:+.3f}", f"{row['nse']:.3f}", f"{row['d_index']:.3f}"
                ])
    t5_md = md(
        ['季节茬口', '生理/采收变量', '观测样本 n', 'RMSE', 'NRMSE (%)', 'Bias', 'NSE', 'd'],
        t5_rows
    )"""

new_t5_code = """                t5_rows.append([
                    s, vname, int(row['n']),
                    f"{row['rmse']:.3f}", f"{row['nrmse_pct']:.2f}",
                    f"{row['bias']:+.3f}", f"{row['r_squared']:.3f}", f"{row['nse']:.3f}", f"{row['d_index']:.3f}"
                ])
    t5_md = md(
        ['季节茬口', '生理/采收变量', '观测样本 n', 'RMSE', 'NRMSE (%)', 'Bias', 'r²', 'NSE', 'd'],
        t5_rows
    )"""

assert old_t5_code in content, "old_t5_code not found!"
content = content.replace(old_t5_code, new_t5_code)

# 2. Update Table 5 note in report_template
old_t5_note = "注：LAI 单位为 m² m⁻²；叶干重、茎干重单位为 kg ha⁻¹；单次采收鲜重与事件累计鲜重单位为 t ha⁻¹。25FA 的营养指标基于剔除 4 天微弱物候拉秧差别的严格同日配对节点计算。"
new_t5_note = "注：LAI 单位为 m² m⁻²；叶干重、茎干重单位为 kg ha⁻¹；单次采收鲜重与事件累计鲜重单位为 t ha⁻¹。$r^2$ 为 Pearson 决定系数；$d$ 为 Willmott 一致性指数；NSE 为 Nash-Sutcliffe 效率系数。单次采收鲜重属于高频离散脉冲变量，受温室田间人工采摘时机在前后 2–4 天扰动引起的离散脉冲时序错位影响，模型评价以 nRMSE、r² 和 d 等指标为主；事件累计鲜重等时序累积值则综合汇报 nRMSE、r²、d 和 NSE 等指标。25FA 的营养指标基于剔除 4 天微弱物候拉秧差别的严格同日配对节点计算。"

content = content.replace(old_t5_note, new_t5_note)

SCRIPT_PATH.write_text(content, encoding="utf-8")
print("Updated Table 5 logic in write_c31_manuscript.py successfully!")
