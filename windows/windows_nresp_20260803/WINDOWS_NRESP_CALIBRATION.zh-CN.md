# Windows 版 CROPGRO 氮响应参数速查

本版本保留两个可率定的物种级参数，写在 `Genotype/TMGRO048.SPE` 的 `XPODF` 行：

```text
PD  0.70  0.65  0.70       XPODF, NSTFAC,NREXP,NRMIN
                   |          |       |
                 NSTFAC      NREXP   NRMIN
```

## 参数含义

| 参数 | 含义 | 推荐搜索范围 | 建议初值 |
|---|---|---:|---:|
| `NREXP` | 供氮/需氮比的曲率指数；1 为原始线性响应，低于 1 会软化低氮到正常氮的陡变 | 0.50–1.00 | 0.65 |
| `NRMIN` | 最低经验氮响应因子；用于避免低氮段过早塌陷，不是土壤最低氮浓度 | 0.60–0.80 | 0.70 |

模型使用：

```text
X = clamp(SUPPN / (NDMNEW × NSTFAC), 0, 1)
N_RESPONSE = NRMIN + (1 − NRMIN) × X^NREXP
```

当 `NREXP=1` 且 `NRMIN=0` 时，退回原始 CROPGRO 响应。

## 文件层级

这两个参数属于 CROPGRO 物种级氮响应，因此放在 `SPE` 是合适的。不要同时复制到 `CUL` 或 `ECO`，否则会产生重复来源。若以后确实要做品种/生态型专属率定，应将参数移入对应的 `CUL/ECO` 记录并同步修改读取代码，不能只增加字段名。

## 大规模率定

参数表使用普通两列 CSV：

```csv
name,value
NREXP,0.65
NRMIN,0.70
```

Windows 批量率定时，确保每个候选参数文件都使用这两个规范名称。推荐先固定其他遗传参数，仅率定 `NREXP` 和 `NRMIN`；之后再联合 `FNPGN1/FNPGN2` 等叶片氮光合参数。

如果使用 PEST++，在 `TMGRO048.SPE.tpl` 中保持 `XPODF` 行的三个数值位置不变，将第二、第三个可率定值命名为 `NREXP`、`NRMIN`；不要把参数名改回带下划线的形式。模型命令可使用：

```text
dscsm048_nresp.exe B DSSBatch.v48
```

每个 realization 运行前应从模板生成独立的 `TMGRO048.SPE`，避免并行任务共享同一个 SPE 文件。

评价建议：

- 终端累计产量：RMSE、RRMSE；
- 累计采收过程：NSE、Willmott `d`；
- 同时检查低氮、中氮、高氮处理的产量排序，避免只优化总体误差。

Windows 版可执行文件由 `windows-nresp` CMake preset 构建，输出为 `build-windows-nresp/bin/dscsm048.exe`。
