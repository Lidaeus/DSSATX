# SPE 参数对比

以下是用户定制的茄子 SPE 文件与原始番茄 SPE 文件的 diff 结果（`-` 为原始，`+` 为修改后）：

```diff
4c4
<   41.00 61.00  0.67  0.10                   PARMAX,PHTMAX,KCAN, KC_SLOPE, soybean LAST
---
>   41.00 61.00  0.67  0.03                   PARMAX,PHTMAX,KCAN, KC_SLOPE, soybean LAST
52c52
<   0.55  0.21  0.49  0.30  0.80  0.05  WTFSD,PORPT,FRSTMF,FRLFF,ATOP,FRCNOD
---
>   0.55  0.61  0.49  0.30  0.80  0.05  WTFSD,PORPT,FRSTMF,FRLFF,ATOP,FRCNOD
56c56
<   220.  300.  300.   4.1   0.0        FINREF,SLAREF,SIZREF,VSSINK,EVMODC
---
>   220.  300.  300.   1.1   0.0        FINREF,SLAREF,SIZREF,VSSINK,EVMODC
101,103c101,103
<   7.0  22.0  28.0  48.0              1 VEGETATIVE DEVELOPMENT 
<   7.2  22.0  28.0  48.0              2 EARLY REPRODUCTIVE DEVELOPMENT
<   5.2  26.0  28.0  48.0              3 LATE REPRODUCTIVE DEVELOPMENT 
---
>   9.8  23.5  32.0  39.8              1 VEGETATIVE DEVELOPMENT 
>   9.8  23.5  32.0  39.8              2 EARLY REPRODUCTIVE DEVELOPMENT
>   9.8  23.5  32.0  39.8              3 LATE REPRODUCTIVE DEVELOPMENT
```

**关键改动说明**
- `PARMAX`、`PHTMAX` 参数的第四列从 `0.10` 调整为 `0.03`，表明光合最大速率的校准更为保守。
- `WTFSD` 系列系数的第二列从 `0.21` 改为 `0.61`，显著提升了根系对水分的利用效率。
- `VSSINK`（源限制因子）从 `4.1` 降至 `1.1`，这将导致早期叶面积指数（LAI）增长更快，符合对茄子早熟的需求。
- 表型阶段（VEGETATIVE/REPRODUCTIVE）的温度阈值整体上升，说明茄子在更高温度下仍保持相同的发育进度。

这些改动为后续的参数敏感性分析提供了明确的方向。
