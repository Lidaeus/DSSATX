# A3-NR-ZP Windows 发布包（2026-08-06）

`DSCSM048.EXE`：A3 阈值平移土壤氮吸收，加零保持 NR 响应：
`fN=(1-NRMIN)*X+NRMIN*X**NREXP`。当 `NREXP=1` 时 `NRMIN` 不可辨识，代码将
其规范化为 0，率定时也应固定/移除。必须同时使用本目录的 `Genotype` 文件。
Windows 原生回归尚未执行。完整说明见
`../WINDOWS_N_RESPONSE_RELEASE_20260806.zh-CN.md`。
