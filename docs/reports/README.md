# 开发与科研证据索引

本目录保存阶段实施、真实运行、失败诊断和 code review 记录。它用于复核证据链，不是用户操作入口。

## 当前最重要的里程碑

- [P0 验证报告](P0_verification_report.md)：科研可信性修复的基线验证。
- [P1 Morris 稳定性报告](P1_v4_W2_stability_report.md)：多 seed Morris 稳定性证据。
- [P1 Sobol 报告](P1_v4_W3_sobol_report.md)：N=128 单尺度 Sobol 及后续降级说明。
- [P1 v4 代码审查](P1_v4_代码审查报告.md)：P1/P2 之间的关键可信性审查。
- [P2 T3 分阶段运行](P2_MVP_T3_staged_run_20260718.md)：S1–S4 工具开发运行。
- [P2 T3.1 收口审计](P2_MVP_T3_1_收口审计_20260718.md)：T3 核心产物和哈希收口。
- [P2 T4.2.1 运行审计](P2_MVP_T4_2_1_运行审计_20260719.md)：候选解确定性预测复跑。
- [P2 T4.3 图表接入](P2_MVP_T4_3_图表接入记录_20260719.md)：R 后验/候选解 DEMO 图接入。
- [P2 T4.4 论文包收口](P2_MVP_T4_4_正式论文包证据链收口_20260719.md)：正式 paper bundle provenance 门。

## 解释规则

- 文件名中的“正式”只描述当时的运行命名；最终状态以报告更正、run manifest 和 finalize 为准。
- 失败报告和早期审查保留原文，便于定位为什么形成当前门禁。
- 当前 T3/T4 产物仍为 `tooling_development / science_pending`，不得因为存在完整报告而升级为科研结论。
