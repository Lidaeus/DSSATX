# CROPGRO 氮响应六个 Windows 版本

本目录提供六个 64 位 Windows 控制台程序，均使用
`x86_64-w64-mingw32-gfortran` 交叉编译，链接时静态纳入 GCC/gfortran 运行库。
PE 文件仍会使用 Windows 系统提供的 CRT API。程序应放入完整的 DSSAT 4.8
运行目录中使用；试验、天气、土壤和 `DSSATPRO.V48` 等运行数据不包含在这些
EXE 中。

## 版本和文件

| 版本 | 程序 | 土壤氮吸收响应 | `NSTRES` |
|---|---|---|---|
| A3 | `dist/windows_a3_20260805/dscsm048_a3.exe` | `C*=max(C-NUPCMN,0)`；`F=C*/(NUPK50+C*)` | DSSAT 原生 |
| A4 | `dist/windows_a4_20260805/dscsm048_a4.exe` | `Ceff=NUPAV*C`；`F=Ceff/(NUPK50+Ceff)` | DSSAT 原生 |
| A3_NR | `dist/windows_a3_nr_20260805/dscsm048_a3_nr.exe` | A3 | 原连续响应 |
| A4_NR | `dist/windows_a4_nr_20260805/dscsm048_a4_nr.exe` | A4 | 原连续响应 |
| A3_NR-ZP | `dist/windows_a3_nr_zp_20260805/dscsm048_a3_nr_zp.exe` | A3 | 零保持连续响应 |
| A4_NR-ZP | `dist/windows_a4_nr_zp_20260805/dscsm048_a4_nr_zp.exe` | A4 | 零保持连续响应 |

连续响应版本均使用：

\[
X=\operatorname{clamp}\left(\frac{SUPPN}{NDMNEW\times NSTFAC},0,1\right).
\]

原 NR 版本为：

\[
f_N=NRMIN+(1-NRMIN)X^{NREXP}.
\]

NR-ZP 版本为：

\[
f_N=(1-NRMIN)X+NRMIN X^{NREXP}.
\]

两者随后都使用 DSSAT 原有的日尺度平滑：
`NSTRES(t)=0.5*fN(t)+0.5*fN(t-1)`。NR-ZP 中 `NRMIN` 的含义是曲率项混合权重，
不再是零供氮时的最低响应因子。

## SPE 配置

每个版本目录都附有 `Genotype/TMGRO048.SPE`、`TMGRO048.CUL` 和
`TMGRO048.ECO`。A3 的修正版使用严格的两参数行：

```text
!*NUPT THRESHOLDED SOIL N UPTAKE RESPONSE PARAMETERS
  8.664  0.50                           NUPK50,NUPCMN
```

这里不能继续使用 A2 的三字段 `NUPK50,NUPQ,NUPCMN`，因为 A3 代码读取的是
`NUPK50,NUPCMN` 两个值。A4 使用：

```text
!*NUPT SOIL N UPTAKE RESPONSE PARAMETERS
  8.664  1.00                           NUPK50,NUPAV
```

NR 和 NR-ZP 的 `!*CARB` 行均包含：

```text
    PD  0.70  0.65  0.70               XPODF, NSTFAC,NREXP,NRMIN
```

率定时可直接修改 `NREXP` 和 `NRMIN`；建议初始边界为 `NREXP=0.25–1.00`、
`NRMIN=0–0.80`。A3 的 `NUPK50`、`NUPCMN` 和 A4 的 `NUPK50`、`NUPAV` 也可按
率定方案修改。

## 使用方法

1. 备份 DSSAT 目录中的原 `DSCSM048.EXE`。
2. 选择一个版本目录，将其中的 EXE 复制到 DSSAT 工作目录，并按需要重命名为
   `DSCSM048.EXE`。
3. 将对应 `Genotype` 文件复制到 DSSAT 的 `Genotype` 目录；不要混用 A3 和 A4
   的 `TMGRO048.SPE`。
4. 在命令行运行，例如：

```bat
DSCSM048.EXE A SVAL0801.EGX
```

建议每个版本使用独立工作目录，以避免输出文件相互覆盖。当前 macOS 构建机
没有 Wine 或原生 Windows，因此已完成 PE 格式和静态链接检查，尚未在 Windows
运行时执行试验回归；首次使用应先运行一组已知 DSSAT 试验并检查
`Summary.OUT` 是否正常结束。

## SHA-256

```text
848f8b0ae78b3e188cf19c650faa269a9cdb6aba8939afdb32d40829e74dd419  dscsm048_a3.exe
71ab9477fcc3f22dcdd7509bce680ad436347ef634ad0fa874279f94f6d813e5  dscsm048_a4.exe
7812c365486619d7c7729d441864e11e16c070fce60289950190b3f5f397aba6  dscsm048_a3_nr.exe
c681d7995646ee4476c1375804d1b670c559333d946254d5bea9a631b0bf8867  dscsm048_a4_nr.exe
2d1bb35912efdeab4e936f9a8a41684f519e45c2af773a61baa49264eeee2276  dscsm048_a3_nr_zp.exe
8aeb8a0210a6835a4db478b2d4abb992672b2b681914aeb0a4c383e1589be9a8  dscsm048_a4_nr_zp.exe
```

构建对应源分支分别为 `feat-cropgro-n-uptake-threshold-a3`、
`feat-cropgro-n-uptake-availability-a4` 和 A4-ZP 分支
`feat-cropgro-nr-zero-preserving`。Windows 构建只改变编译目标，不改变
macOS 率定结果或观测数据。
