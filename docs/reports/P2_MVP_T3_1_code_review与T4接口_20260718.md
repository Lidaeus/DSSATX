# P2-MVP T3.1 code review 与 T4 最小接口（2026-07-18）

## 审查结论

T3.1 的严格 frozen-bound 恢复、IES resume fail-fast、核心产物清单和干净 S4 重跑均成立。独立复核结果为 16/16 哈希一致、40/40 成员保留、`engineering_validated/science_pending`。审计记录中的末轮 mean Phi 曾误写为 `760.956`；实际 `phi.actual.csv` 为 `791.927`，已更正。

本轮同时修复两个下游风险：artifact manifest 改用跨平台 POSIX 相对路径，并新增真正执行 SHA-256 校验的读取门。产物缺失、路径逃逸、重复或哈希不一致时，T4 不会继续。

## T4 已实现

### 处理级 validation 接口

`src.reporting.validation_metrics` 明确从 run manifest 指向的冻结输入包读取观测，从代表确定性复跑读取模拟，不使用旧 `workspace/XXQL2501.TMT` 回退。输出：

- `comparison.csv`：canonical 观测—模拟长表；
- `metrics_by_role_variable.csv`：逐角色逐变量 RMSE、MAE、bias 和显式 range-NRMSE；
- `validation_results_manifest.json`：绑定 run、finalize、artifact、input 和 validation split 哈希。

当前 demo QA 得到 400 个有限配对：calibration 240、validation 80、diagnostic 80。这里只核对角色、数据接口和计算可执行性，不解释指标好坏。

### 最小条件集合接口

`src.reporting.posterior_summary` 输出：

- 全部可调参数的 prior/conditional 边际与收缩/边界诊断；
- Spearman 参数相关；
- 最多 3 对“Phi 接近、参数距离较远”的候选解。

当前 demo 正确保留 6 个可调参数的边际诊断，并把后验数值退化的 `NMOBMX` 标记为 collapsed；相关分析只使用 5 个仍有数值变化的参数。3 对候选解的 `prediction_distance` 均保持缺失，分类固定为 `candidate_pair_prediction_pending`，不能称为功能异参同效。

## 下一阶段

T4 下一小步仅实现候选解参数 CSV 导出、2–3 对 validation/diagnostic 确定性复跑和 prediction distance 回填。当前 bounds 与工具开发 ensemble 不作科学解释；不扩展 PCA/VIF、聚类、t-SNE 或一键工作流框架。
