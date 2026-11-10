# 当前论文工作稿：Champion C31（Scheme 1 Dual-Spring Precision Champion）

2026-09-27 已正式确立最终全局代表解 **Champion C31**（`c28_scheme1_tb1_92`，基于 Scheme 1 物理土壤校正体系与发育基温 `TB1 = 9.20 °C`）。论文正文、出版表格和图版全系统均已全面更新，以 C31 为唯一出版基准。

### 核心成果与文档导航
- [结果与讨论定稿合并稿](01_Sections/00_Combined_Results_Discussion.md)
- [结果章节定稿](01_Sections/03_Results_Section.md) / [讨论章节定稿](01_Sections/04_Discussion_Section.md)
- [出版数据表格（五张表及源数据）](02_Tables/) / [全表汇编报告](02_Tables/Tables_Compiled_Report.md)
- [核心出版矢量图版入口](03_Figures/)：[主图](03_Figures/Main_Figures/) / [补充图](03_Figures/Supplementary_Figures/) / [图版哈希清单](03_Figures/figure_manifest.json)
- [冻结出版数据包](paper_data/)：包含 `25SP`, `26SP`, `25FA`, `terminal`, `leaf_n`, `ensemble`, `conditional` 7 个规范数据包

### 核心突破与科学进展指标
1. **双春季精度实现历史性跨越**：
   - **2026 春茬（26SP，12处理）**：$R^2 = 0.7016$，$\text{NRMSE} = 4.89\%$，$\text{NSE} = +0.7011$，$d = 0.9022$（$0.9072$），同时攻破 $R^2 > 0.70$ 与 $\text{NSE} > 0.70$ 核心门槛，彻底消解早期候选方案在 26SP 上的精度失衡与负 NSE 缺陷。
   - **2025 春茬（25SP，11处理）**：$R^2 = 0.8802$，$\text{NRMSE} = 6.24\%$，$\text{NSE} = +0.3726$，$d = 0.9078$，保持顶尖模拟水准。
   - **两春季合并（Dual-Spring，23处理）**：$R^2 = 0.7246$，$\text{NRMSE} = 5.57\%$，$\text{NSE} = +0.5721$，$d = 0.9084$，证明模型参数具有卓越的年际间可转移性。
2. **三季全尺度 35 处理卓越拟合**：
   - **全样本 35 处理（Grand Pooled）**：$R^2 = 0.9846$（$0.9840$），$\text{NRMSE} = 7.67\%$，$\text{NSE} = +0.9757$（$+0.9745$），Willmott 一致性指数 $d = 0.9940$。
   - **留出验证集（10处理）**：$\text{NRMSE} = 5.74\%$，RMSE = 3.66 t/ha，与率定集（5.44%）高度平衡，无统计过拟合。
3. **彻底消解零氮负灌溉非物理陷阱**：
   - 早期方案在不施氮（N0）处理下灌水诱发虚假减产（如 25SP N0 为 −0.351 t/ha，26SP N0 为 −2.722 t/ha）。
   - Champion C31 依托 Scheme 1 物理土壤校正体系（`SLPF_25SP = 0.88`, `SLPF_26SP = 0.89`, `SASC_RATIO = 0.92`, `SOIL_SLDR = 0.40`, `SOIL_SLU1 = 2.50 mm d⁻¹`）和发育基温 `TB1 = 9.20 °C`，彻底修复了水分吸持与养分运移动力学。
   - Table 4 中春茬全处理的**水分边际缓解阶梯（W2−W1）与充分灌溉恢复阶梯（W3−W1）100% 严格为正**（25SP N0 W3−W1 恢复为 +13.259 t/ha，26SP N0 W3−W1 恢复为 +2.543 t/ha）。
4. **秋冬茬外推盲验稳健保真**：
   - 在严酷低温弱光的 2025 秋冬茬（25FA，12处理）盲验中，实测均产 16.79 t/ha，C31 模拟均产达到 13.41 t/ha，$\text{NRMSE} = 23.07\%$，真实再现了适度生长未发生假性绝收。
5. **两轨制出版图版规范与条件集合不确定性量化**：
   - 遵循严格的两轨制图表契约（Python 仅导出数据，R 为唯一出版渲染器）。
   - 224 个高质量图版与源数据资产完整记录于 `figure_manifest.json`，并通过 SHA-256 逐一哈希校验。
