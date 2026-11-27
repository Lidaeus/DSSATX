# 2025–2026 春季 2A 联合率定执行记录

61 参数联合率定已完成。第 4 轮成员 69 的复跑 Φ 为 **49.44313**，比上次 11 参数的 **58.23998** 低 **15.1%**。改善主要来自鲜果、LAI 与叶茎干重的绝对观测。2026 年三个水分水平的 N2−N1 末采增量仍偏低，最低 Φ 成员在三组均出现轻微倒挂。

## 率定设置

- 同时使用 2025 春季 8 个处理和 2026 春季 12 个处理。沿用上批 306 项绝对观测、33 项同年同水分同日 N2−N1 累计鲜果差值及其权重。N0 保留在上批绝对目标中，N3 用于诊断。奢侈氮响应关闭。两季均进入同一次率定，以下为样本内结果。
- 启用归档 61 参数设计的 41 个作物卡字段（CUL 5、ECO 5、SPE 31）和 20 个 NIntegration 参数。两季使用同一组读回校验后的参数，原始作物卡和有效记录均经核对。
- 从上次最低 Φ 成员初始化，339 项预检模拟值逐项一致。将 `q_no3_max` 上界 0.0065 扩至 0.0088，将 `pool_beta` 下界 0.10 扩至 0.05，以容纳上次最佳参数。其他边界沿用归档设计。上次 11 参数中的 `refill_substrate_km`、`rnk_vmax_high_no3`、`rnk_km_low_no3` 不在归档 61 项内，固定为上次最佳值。
- PEST++ IES 5.2.27 使用 80 成员、4 次更新、10 个工作进程及种子 20261124。首次集合有 1 个成员前向失败并被剔除，随后 4 轮均无前向失败。整批 619 次成功前向，每次覆盖两季 20 个处理。末代 79 个有效成员。

## 目标函数与梯度

| 参数组 | Φ | 绝对观测 Φ | 差值 Φ | 末采差值 RMSE（t/ha） | N2−N1 为正 |
|---|---:|---:|---:|---:|---:|
| 上次 11 参数最低 Φ | 58.23998 | 57.26067 | 0.97932 | 4.686 | 3/5 |
| 本次最低 Φ（第 4 轮成员 69） | 49.44313 | 48.37338 | 1.06975 | 4.762 | 2/5 |
| 方向候选（第 4 轮成员 9） | 52.54773 | 51.62104 | 0.92669 | 4.487 | 5/5 |

方向候选是 395 条有效成员记录中，五组均满足 N0 < N1 < N2 的 79 条记录里 Φ 最低的成员。该成员也已独立复跑。

| 年份 | 水分 | 实测 N2−N1 | 上次 11 参数 | 本次最低 Φ | 方向候选 |
|---|---|---:|---:|---:|---:|
| 2025 | W1 | +1.643 | +0.189 | +1.259 | +0.484 |
| 2025 | W3 | +2.499 | +2.537 | +2.207 | +2.541 |
| 2026 | W1 | +2.913 | -0.202 | -0.134 | +0.003 |
| 2026 | W2 | +7.240 | -0.178 | -0.303 | +0.144 |
| 2026 | W3 | +6.561 | +0.008 | -0.292 | +0.199 |

单位为 t/ha。最低 Φ 成员的差值误差略增。方向候选消除了倒挂，但在 2026 年 W2、W3 仅增产 0.144 和 0.199 t/ha，低于实测 7.240 和 6.561 t/ha。两组均未通过 26SP 原 2A 农艺门槛。

## 最低 Φ 复跑拟合

R² 为 Pearson 相关系数平方，NRMSE 用实测均值归一化。各指标包含对应季节所有可配对实测点。季末鲜果取最后一次实测采收日。

| 年份 | 指标 | n | R² | NRMSE | NSE |
|---|---|---:|---:|---:|---:|
| 2025 | 累积鲜果 | 72 | 0.919 | 28.61% | 0.726 |
| 2025 | 季末鲜果 | 8 | 0.281 | 9.72% | -0.607 |
| 2025 | LAI | 32 | 0.886 | 32.37% | 0.762 |
| 2025 | 叶干重 | 32 | 0.940 | 35.27% | 0.685 |
| 2025 | 茎干重 | 32 | 0.809 | 41.36% | 0.710 |
| 2026 | 累积鲜果 | 60 | 0.947 | 20.05% | 0.873 |
| 2026 | 季末鲜果 | 12 | 0.477 | 18.21% | -3.135 |
| 2026 | LAI | 48 | 0.801 | 29.05% | 0.759 |
| 2026 | 叶干重 | 48 | 0.866 | 22.33% | 0.849 |
| 2026 | 茎干重 | 48 | 0.779 | 37.42% | 0.676 |

## 守恒与触边

最低 Φ 与方向候选均完成两季原生审计。两个成员合计的最大全季全株氮残差为 2.56×10⁻⁶ g N/m²，最大逐日实际碳账残差为 3.99×10⁻⁶ g CH₂O/m²。氮结算节点 PGAVL 全程非负。

最低 Φ 成员有 8 项精确触边。下界为 `assim_no3_k`、`growth_tau`、`podur`、`stem_a`。上界为 `lnref`、`trifl`、`xfint`、`yswbar3`。触边仅描述集合结果，参数可辨识性需要结合响应敏感度判断。

[迭代记录](ies_history.csv) · [参数设计](stage/parameter_design.csv) · [最低 Φ 参数](min_phi/parameters.csv) · [20 处理季末产量](min_phi/terminal_yields.csv) · [拟合指标](min_phi/fit_metrics.csv) · [原生审计](min_phi/native_receipt.json) · [方向候选](direction_candidate/parameters.csv) · [方向筛查](ensemble_direction_screen.csv)

## 复现

`stage/inputs.zip` 保存两季原生输入，解包到带 `stage_receipt.json` 的目录后得到 `inputs/s25` 与 `inputs/s26`。收据记录了各输入、配置和目标表的原始 SHA-256，归档包括用于起始点核对的上批 11 参数配置及收据。使用相同 DSSAT Release 引擎、PEST++ IES 5.2.27 和 Python 依赖，从仓库根目录执行以下命令。工作目录应为新目录。

```sh
archive=research/calibration/results/25sp_26sp_stage2_n21_joint61
work=build/reproduce-springs-n21-joint61
engine=/path/to/dscsm048
mkdir -p build
cp -R "$archive/stage" "$work"
unzip -q "$work/inputs.zip" -d "$work"
python research/calibration/ies.py --engine "$engine" \
  --inputs "$work/inputs" --template "$work/NIntegration.nml.tpl" \
  --bounds "$work/bounds.csv" --observations "$work/observations.csv" \
  --crop-map "$work/crop_map.csv" --seed 20261124 --members 80 --updates 4 \
  --workers 10 --pestpp-ies pestpp-ies --out "$work/ies"
python research/calibration/replay.py --case "$work/ies" --out "$work/replay"
python research/calibration/assess_stage2_springs.py --engine "$engine" \
  --stage "$work" --replay "$work/replay" --out "$work/audit"
```

复跑已归档成员可将 `assess_stage2_springs.py` 的 `--replay` 指向 `min_phi` 或 `direction_candidate`，并仍使用解包后的 `--stage`。将率定命令的 `--updates` 设为 0 并省去 PEST++ 与工作进程选项可只做本机前向预检。
