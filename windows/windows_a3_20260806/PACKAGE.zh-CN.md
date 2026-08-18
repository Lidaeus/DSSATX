# A3 Windows 发布包（2026-08-06）

`DSCSM048.EXE`：A3 阈值平移土壤氮吸收，DSSAT 原生 `NSTRES`。

吸收式：`C*=max(C-NUPCMN,0)`，`F=C*/(NUPK50+C*)`。必须同时使用本目录的
`Genotype/TMGRO048.SPE`。本机已完成对应 macOS 双季回归；Windows 文件为
x86-64 PE 交叉编译产物，尚未执行 Windows 原生回归。完整说明见
`../WINDOWS_N_RESPONSE_RELEASE_20260806.zh-CN.md`。
