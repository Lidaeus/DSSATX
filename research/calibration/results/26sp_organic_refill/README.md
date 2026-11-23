# 26SP 茎叶有机氮回补诊断

使用 [80×4 最优成员 4](../26sp_80x4/README.md) 的 61 个冻结参数复跑。田间成对试验覆盖 12 个水氮处理。开启组仅指定叶、茎有机氮回补容量增量 0.015、0.010 g N/g DM 和 4 d 回补时标。两组通过碳氮守恒审计，关闭组复现冻结基线。

- [5 页诊断图册](../../../../output/pdf/organic_refill_26sp/diagnostic_atlas.pdf)
- [日序列绘图数据](atlas_source.csv)和[施氮差距汇总](gradient_summary.csv)
- [田间成对复跑收据](field_replay_receipt.json)及[渲染后的配置](configs/)
- [逐项决策与执行报告](../../../root_n_kernel/p1_4864/organic_refill_execution.zh.md)及[11 组对照收据](contrast_receipt.json)
- [器官氮诊断](organ_n_diagnostics.csv)及[叶氮观测口径对照](leaf_n_observation_envelope.csv)
- [归档校验值](archive_manifest.json)

## 田间成对结果

7 月 17 日末期，叶片的 N3−N1 有机氮浓度差在三种水分下都收窄，茎的同一差值略有扩大。叶、茎的 N3−N2 有机氮浓度差在三种水分下都收窄。下表单位为干重百分点。

| 水分 | 叶 N3−N1（关闭 → 开启） | 茎 N3−N1（关闭 → 开启） | 叶 N3−N2（开启） | 茎 N3−N2（开启） |
| --- | ---: | ---: | ---: | ---: |
| W1 | 0.186 → 0.168 | 0.083 → 0.109 | 0.018 | 0.012 |
| W2 | 0.080 → 0.056 | 0.036 → 0.037 | 0.004 | 0.002 |
| W3 | 0.187 → 0.170 | 0.084 → 0.106 | 0.007 | 0.004 |

图册第 3 页显示相邻施氮水平的同日差值，第 4 页显示站存有机氮库存，第 5 页显示假定无机氮完全回收时的浓度端点。回补设置保持为默认关闭的研究选项。

## 复现

使用 80×4 归档对应的 SASC70 输入和包含回补开关的隔离构建。

```sh
python research/root_n_kernel/p1_4864/replay_organic_refill.py \
  --engine /path/to/experimental/dscsm048 \
  --inputs /path/to/frozen-26sp-ies/inputs \
  --reference /path/to/archived-80x4-field-replay \
  --trial field-zero --trial field-capacity-rate \
  --out build/organic-refill/field-pair-replay
```

图册可直接从归档数据重绘。绘图依赖见 [requirements.txt](../../../n_diagnostics/requirements.txt)。在没有可自动检测的 CJK 字体时，使用 `--font` 指定。

```sh
python research/calibration/results/26sp_organic_refill/render_atlas.py \
  --out build/organic-refill/reproduced-atlas.pdf
```
