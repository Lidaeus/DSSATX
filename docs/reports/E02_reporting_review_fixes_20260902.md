# 文档与绘图修复验收、输入交接（2026-09-02）

## 已执行

1. Python旧publication入口降为diagnostic，仅显式指定确定性目录和映射；输出到新的空目录，不覆盖旧图。删除未验证的站立果质量闭合图及Spread Ratio图，不复制错误结论。
2. 新增`src/reporting/ies_plot_provenance.py`：检查同一目录/case/明确迭代的先验、后验、PST列与边界、原始逐成员Phi、成员身份和文件哈希。缺先验明确失败，不替代。advanced诊断入口同样校验，并用真实先验IQR计算收缩，保留负收缩（扩张）。同批次来源一致性通过不等于科学晋级。
3. `equifinality.py`后验自动选择按整数迭代号，而非字符串排序；只有第0轮时拒绝当作后验。Python预览入口完全取消自动选候选/运行目录。
4. `metrics.py`提供raw/state/signed三类配对校验。状态量在换单位前剔除负值与非有限值；原始−99容差识别；有符号差值不再被“大于−90”误删。
5. 响应结构图改为末态配对与分季同水层相邻N差值误差；不同末次日期不比较，零观测差不进入符号一致率。停止Spread Ratio方向正确性结论。
6. R中迁入显式季节×变量1:1布局；指标按季分开、误差棒端点纳入等轴范围。条件动态图增量采收不画连续线，保留累计事件线；修正诊断处理被标成验证、SE被裁切的问题。
7. 以真实PST/观测注册表纠正v48文档；PAGE/PENV允许继续联合率定至最终版固定。SSKS=1.2–2.8仅列为数量级可能的待溯源范围，不写成当前输入或实测。

## LAI bundle同步结果及后续必须执行的规则

目录：`data/user/experiments/lai0629_synced_20260902/`。
映射：`bundle_successors.json`（原始source → successor）。下轮新设计、敏感性分析及重放必须采用successor；不得照抄旧设计中的原始bundle路径。

扫描范围为`data/user/experiments`非归档26SP输入包，以及当前氮倍率扫描的`bundles_v2`。46个缺补齐值的可用输入包已创建版本化successor；4个已补齐包直接保留。每包补齐26180日期的12个LAI值及相应不确定性记录。
未覆盖原始文件、已完成run/agent快照或历史manifest；不追溯修改已完成率定的目标点数与指标。下一轮实际LAI点数需由新PST的正权重观测重新验收。

两份历史目录不得用于新一轮：

- `xxql2601_repfilter_v1_20260818`：TMT既有定宽损坏，无法安全定位LAI字段；未顺带重建全部输入。
- `xxql2601_sa_controlled_tn12_w1_candidate_20260721`：不是完整的当前12处理bundle，缺同步必需文件。

全部46份successor均已复核：TMT仅目标6字符字段改变；FileT其他单元格不变；uncertainty其他日期/变量记录不变；TMX、TMA、FileA、SOIL、天气及果实含水率数据未改变，manifest哈希全部匹配。

## 后验来源与历史图件状态

- 真实v48第4轮200成员通过新增一致性校验（先验200/后验200）。没有据此自动宣告science_validated。
- `e02_formal_v46_page28_25_opt_20260901`被拒绝：Phi文件不是可互证的IES逐成员记录。其确定性结果可以保留，但暂停后验和不确定性结论。
- 协作者须补充：IES命令、完整日志、原PST、先验来源、最终迭代及成员表、生成脚本、哈希。不要从其他批次拷贝集合补洞。
- 现有图文件原样保留但不作为论文证据。默认不画模拟不确定性区间。

## Antigravity委派与独立验收

按用户要求委派R布局迁移；委派工具两次超时。R轴范围的部分补丁已落盘，主代理检查后接续完成季节布局、误差棒与增量几何，并独立执行R回归测试及DEMO渲染检查。不把超时当作完整交付，也不声称全部Python布局已迁完。

Python聚焦测试72项通过；R4.5.2布局回归通过。R仅出现机器locale启动警告，未影响测试。新增测试位于`tests/test_reporting_pair_validity.py`、`tests/test_ies_plot_sources_and_lai_sync.py`、`tests/test_reporting_layout_regression.R`。
QA产物：`workspace/reports/reporting_review_20260902/`，仅诊断/DEMO，不是重新率定或论文证据。

## 初始氮基准已获用户澄清（2026-09-02）

用户确认此前25SP文件名为口误：26SP初始硝态氮、铵态氮应引用 `D:/Tomato_Cal/data/user/ref/26SP硝态氮铵态氮校准值.xlsx`，0–60 cm固定为该表基准的0.34倍，深层保持原配置。不跨季映射。
已补齐LAI的对应输入为 `data/user/experiments/lai0629_synced_20260902/s0p34_215131eb`；其缩放清单记录的参考文件和倍率正是26SP表与0.34，TMX与原s0p34一致，不再乘一次0.34。后续使用该输入时不得继续释放额外ICNS26缩放；若注入链保留此乘数，应固定为1.0。历史率定配置与快照不追溯修改。
本次没有启动率定或DSSAT，也没有修改正在开发的v50/v51工作。
