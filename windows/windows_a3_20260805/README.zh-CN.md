# A3 修正版

使用 `dscsm048_a3.exe`，并配套本目录 `Genotype/TMGRO048.SPE`。
土壤氮吸收响应为 `C*=max(C-NUPCMN,0)`、`F=C*/(NUPK50+C*)`；默认
`NUPK50=8.664`、`NUPCMN=0.50`。该版本不启用 `NREXP/NRMIN` 连续
`NSTRES` 分支。运行：`DSCSM048.EXE A SVAL0801.EGX`。
