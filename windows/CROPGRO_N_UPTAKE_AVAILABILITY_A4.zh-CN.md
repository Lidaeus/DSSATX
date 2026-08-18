# CROPGRO 土壤氮吸收 A4（有效性系数版本）

A4 基于 A3，将固定的最低浓度扣除项 `C-NUPCMN` 改为比例有效性项。NO₃⁻ 和 NH₄⁺ 使用同一组三个新增/率定参数：

```text
NUPK50   有效浓度达到半响应时的尺度参数（ppm）
NUPQ     曲率参数（无量纲）
NUPAV    有效性系数 A_s = 1 - Rate_s，范围 0–1
```

对每个有根土层和两种无机氮分别计算：

\[
C_{s,eff}=NUPAV\,C_s
\]
\[
F_s=\frac{(C_{s,eff})^{NUPQ}}
{NUPK50^{NUPQ}+(C_{s,eff})^{NUPQ}}.
\]

当 `NUPQ=1` 时，严格得到：

\[
F_s=\frac{NUPAV C_s}{NUPK50+NUPAV C_s},
\]

即粘贴内容中的有效浓度 Michaelis–Menten 形式。`NUPQ` 保留是为了兼容 A2/A3 的曲率率定能力；第一轮率定建议固定 `NUPQ=1`。

## 当前初始值

```text
  8.664  1.00  1.00                   NUPK50,NUPQ,NUPAV
```

`NUPAV=1` 表示不额外折减；`NUPAV<1` 时，相当于把同一土层的有效氮浓度按比例降低。环境差异仍通过 DSSAT 的土壤无机氮状态 `C_s`、根系分布和水分因子 `SMDFR` 进入模型；A4 没有再添加一个独立的水分经验函数，避免与原有水分修正重复计权。

A4 不再使用 `NUPCMN`，也不把固定 `Cmin` 作为响应函数的阈值。土壤库存保护仍保留 DSSAT 原有的 NO₃⁻ 0.25 ppm、NH₄⁺ 0.50 ppm 最低残留限制，因为它是库存质量平衡约束，不是浓度响应函数的 `Cmin`。

## 代码和率定接口

- 核心修改：`Plant/CROPGRO/NUPTAK.for`；
- 番茄参数：`Data/Genotype/TMGRO048.SPE`；
- `NUPAV` 已加入率定工作区的参数注册和 SPE 直接注入白名单；
- 原有 `RTNO3`、`RTNH4`、`RLV`、`SMDFR`、`ANDEM` 和土壤库存限制保持不变；
- 未启用 NNI 或连续 `NSTRES` 扩展。

建议的第一轮搜索范围：

```text
NUPK50: 1–40 ppm
NUPQ:   固定 1.00，或 0.50–1.50
NUPAV:  0.50–1.00
```

在低氮、中氮和高氮处理中同时检查最终产量、累计采收序列、植株吸氮量以及分层 NO₃-N/NH₄-N。`NUPAV` 与 `NUPK50` 在低浓度区可能存在相关性，因此不能只用单一低氮处理识别。

## 验证和 Windows 文件

A4 已完成 macOS Release 全量编译和 Windows 64 位 PE 交叉编译。当前环境没有原生 Windows 或 Wine，因此 Windows 文件已通过 PE 格式校验；模型运行验证使用本机 DSSAT 运行器完成。

[dscsm048_a4.exe](/Users/lidaeus/Documents/NewDssat/dist/windows_a4_20260804/dscsm048_a4.exe)

SHA256：

```text
71ab9477fcc3f22dcdd7509bce680ad436347ef634ad0fa874279f94f6d813e5
```

发布目录中的 `Genotype/TMGRO048.SPE` 已包含 `NUPK50,NUPQ,NUPAV` 三参数行。
