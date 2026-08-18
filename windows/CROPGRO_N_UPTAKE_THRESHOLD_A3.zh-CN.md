# CROPGRO 土壤氮吸收 A3（三遗传参数）

本分支 `feat-cropgro-n-uptake-threshold-a3` 基于 A2，采用一个共同的三参数响应函数，同时用于硝态氮和铵态氮。修改范围仍限制在 CROPGRO 的 `NUPTAK.for` 和番茄 `TMGRO048.SPE`，没有新建根系吸收模块，也没有修改 `RTNO3`、`RTNH4` 的平台吸收能力。

## 三个遗传参数

```text
NUPK50   有效浓度达到半响应时的尺度参数（ppm）
NUPQ     曲率参数（无量纲）
NUPCMN   共同最低有效浓度（ppm）
```

对每个有根土层以及两种无机氮分别计算：

\[
C_s^*=\max(C_s-NUPCMN,0)
\]
\[
F_s=\frac{(C_s^*)^{NUPQ}}
{NUPK50^{NUPQ}+(C_s^*)^{NUPQ}}
\]

当 `NUPQ=1` 时，严格退化为粘贴方案中的阈值 Michaelis–Menten 函数：

\[
F_s=\frac{C_s^*}{NUPK50+C_s^*}.
\]

因此 A3 既可以直接使用推荐的 MM 形式，也保留了 A2 曲率率定能力。NO₃⁻ 和 NH₄⁺ 使用完全相同的三个参数；两种形态的差异仍由 DSSAT 原有的 `RTNO3`、`RTNH4` 平台吸收能力决定。

## 初始值和当前 SPE

`Data/Genotype/TMGRO048.SPE` 中的初始值为：

```text
  8.664  1.00  0.50                   NUPK50,NUPQ,NUPCMN
```

其中 `8.664 ppm` 来自原指数函数的半响应浓度 `ln(2)/0.08`；`NUPQ=1` 使第一版与推荐 MM 公式一致；`NUPCMN=0.50 ppm` 是 NO₃⁻、NH₄⁺ 共用的折中阈值。

粘贴材料给出的 `CMINNO3=0.25`、`CMINNH4=0.50` 属于四参数、分形态阈值方案。本 A3 有意不采用两个独立阈值；如果后续证据表明两种形态必须不同，应另行升级为四参数版本，不能把两个值同时塞入同一个 `NUPCMN`。

## 与原 A2 的差异

- A2：`NUPK50`、`NUPQ`，直接对原始 `NO3(L)`、`NH4(L)` 计算 Hill 响应。
- A3：增加共同 `NUPCMN`，先扣除最低有效浓度再计算响应。
- A3 删除了 A2 的 `F<0.04` 置零规则，仅保留 `[0,1]` 数值限幅。
- 原有 `RLV`、土壤水分修正 `SMDFR`、`RTNO3/RTNH4`、作物氮需求 `ANDEM` 和土壤库存限制继续工作。
- 土壤库存下限同步采用 `NUPCMN/KG2PPM(L)`，避免响应函数与库存约束不一致。

## 率定建议

第一轮先固定 `NUPQ=1.0`，率定 `NUPK50` 和 `NUPCMN`；确认数据能够识别曲线位置后，再放开 `NUPQ`。建议安全搜索范围：

```text
NUPK50: 1–40 ppm
NUPQ:   0.50–1.50
NUPCMN: 0–2 ppm
```

不能只用低氮处理同时识别 `NUPK50` 与 `RTNO3/RTNH4`，也不宜只用最终产量率定 `NUPCMN`。应优先使用 N0、N1、N2 处理，并检查植株吸氮、分层无机氮和最终/累计采收量。

## 本机验证

已完成：

1. macOS Release 全量编译；
2. A3 版本两季、N0–N2 共 12 个处理的冒烟运行，全部正常结束；
3. 公式边界满足 `C≤NUPCMN` 时 `F=0`、`C=NUPCMN+NUPK50` 且 `NUPQ=1` 时 `F=0.5`、高浓度时渐近于 1。

本分支暂不包含连续 `NSTRES` 扩展；如需组合版本，应在 A3 基础上单独打开已有的 `CROPGRO_CONTINUOUS_NSTRES` 选项。

## Windows 可执行文件

[dscsm048_a3.exe](/Users/lidaeus/Documents/NewDssat/dist/windows_a3_20260804/dscsm048_a3.exe)

该文件为 `x86_64-w64-mingw32-gfortran` 交叉编译的 64 位 Windows PE 文件，SHA256 为：

```text
848f8b0ae78b3e188cf19c650faa269a9cdb6aba8939afdb32d40829e74dd419
```

发布目录同时包含带有三参数 `TMGRO048.SPE` 的 `Genotype` 子目录。当前环境没有原生 Windows 或 Wine，因此已完成 PE 格式检查，但尚未执行 Windows 原生运行时回归。
