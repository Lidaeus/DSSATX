import os
import sys
import json

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def build_volume_09():
    metadata_path = 'docs/archive/doc_archive_metadata_20260920.json'
    with open(metadata_path, 'r', encoding='utf-8') as fp:
        docs = json.load(fp)

    lines = []
    def p(text=""):
        lines.append(text)

    p("# Volume 09: 历史重大科学矛盾演进、真相裁决与 83 篇文档全景溯源矩阵")
    p()
    p("> **知识库分册编号**：`KB-DSSAT-CROPGRO-VOL-09`  ")
    p("> **模块定位**：全景对账、方法学反思、同行交流裁判与历史档案检索总汇  ")
    p("> **覆盖软件与引擎**：DSSAT CSM v4.8.2.000 / CRGRO048 / Open Source Fortran Engine, PEST++ IES v5.2.16  ")
    p("> **溯源覆盖范围**：83 篇已归档历史文档（`docs/archive/`），100% 对应并附带有效链接  ")
    p("> **基准日期**：2026-09-20  ")
    p()
    p("---")
    p()
    p("## 1. 历史重大科学矛盾总览与法医式机理裁决 (Forensic Reconciliation)")
    p()
    p("在长达数月的温室茄子模型率定探索中，面对复杂的无限生长源库关系与水肥一体化土壤环境，研究人员曾提出诸多阶段性假设。后续通过深度查证 DSSAT 底层 Fortran 源代码、执行高精细正交扫描试验并结合田间实测数据对账，彻底消解了以下 **8 大核心科学矛盾**：")
    p()
    p("| 序号 | 科学问题 / 矛盾焦点 | 早期阶段性假说 (已被证伪/淘汰) | 底层查证事实与证伪证据 (源码/实测) | 最终验证真理与工程落地准则 | 对应详细分册 |")
    p("| :---: | :--- | :--- | :--- | :--- | :--- |")
    p("| **1** | **土壤有机质矿化调控** | 试图调节 `SOIL_SLNF` 控制矿化，误以为放宽至 3.0~10.0 能生效 | `InputModule/IPSOIL_Inp.for:485-492` 中 `SLNF > 1.0` 静默重置为 1.0；`SOMDEC_C.for` 证明 CENTURY 模式根本不读 `SLNF` | FileX Section `@A` 注入 `SASC_RATIO = 0.94` 控 SOM3 被动碳库，矿化自 145 压至 88 kg N/ha，消解 N0 假饱 | **Volume 01 (Soil Organic Matter & CENTURY)** |")
    p("| **2** | **25SP W1 产量断崖低估** | 误判为土壤底肥无机氮倒挂或干旱导致吸氮受阻 | 2.5倍底氮正交扫描产量仅变 0.009%，$\\sum WSPD \\equiv 18.007$ 完全死锁，无氮胁迫；查明根系下扎 180cm 吸深层水且表层蒸发过高 | 实施 100cm 根系物理筑坝 (`SRGF(100)=0.20, SRGF(180)=0.0`) + Run 14 蒸发抑制 (`SLU1=1.0mm, EFIR=0.95`)，干旱增产转正为 +5.09 t/ha | **Volume 02 (Soil Water Hydraulics & SOILWAT)** |")
    p("| **3** | **温室移栽苗龄设定** | 经验臆断定植苗龄为 28 或 25 天 (`PAGE = 28/25`) | `PHENOL.for:260` 积温推演表明：`PAGE < 19d` 导致发育滞后减产 70%；7 梯度模拟矩阵证明必须对账真实穴盘生理苗龄 | 查验育苗定植原始农事日志，严格确立并固化 `PAGE = 22.0 d`，消除 3~6 天虚假热量累积 | **Volume 03 (Crop Phenology & TRANS)** |")
    p("| **4** | **物候基温跨季泛化** | 采用低基温 `TB1 = 6.5 ~ 7.5℃`，春季拟合极佳 (NRMSE=5.01%) | 代入秋季盲测 (25FA) 遭遇“低温飞车”，深秋 10~14℃ 下持续灌浆不结茬，产量虚高 60% (27.5t vs 17.0t)，NRMSE 恶化至 63%~104% | 将 `TB1` 搜索域约束在 [8.0, 9.5℃]，Champion C15 收敛于 `TB1 = 9.21℃`，深秋低于 9℃ 自动截茬，盲测 NRMSE 降至 18.38% | **Volume 03 (Crop Phenology & TRANS)** |")
    p("| **5** | **零氮极端早衰脱落** | 误以为缺氮必然导致植株迅速枯死脱落 | `SENES.for:198` 源码杀伤公式：$LFSEN = SENRTE \\times NRUSLF / 0.16$；$SENRTE=6.5$ 导致 1g 氮诱发 40.6g 叶脱落；`FL-LF=400` 锁死无限出叶 | 实施 V5 修复：约束 $SENRTE = 4.40$，$FL-LF = 512 ^\\circ\\text{C}\\cdot\\text{d}$，末期 LAI 由 0.62 恢复至 2.45 (实测 2.53) | **Volume 04 (Crop Growth, Source-Sink & PHOTO)** |")
    p("| **6** | **26SP 初始氮表层虚高** | 原始化验单硝态氮数值直接全剖面等值代入 | 原始化验单列出的是硝酸根分子离子质量，直接代入产生 4.4 倍虚高；0~15cm 表层取样局限导致底肥极化放大 | 严格按分子量比例纯氮折算，并固化 $ICNS\\_26SP = 0.70$ 等效折减系数，增产响应还原度达 97.8% | **Volume 07 (Data Pipeline & Quality Governance)** |")
    p("| **7** | **化肥养分输入完整性** | 历史输入包仅录入尿素，关闭磷模块 (`PHOSP='N'`) | 审查 `*.TMX` Section `@F` 发现田间实际施用的磷肥完全漏录；若开启磷模块因土壤零磷输入触发极端缺磷停滞 | 补齐纯磷 ($P_2O_5$) 施肥记录，澄清 `SMHB='SA012'` (Bray-2法) 与 `SMPX=-99` 合法语义，磷平衡闭合度 $SEASBAL = 0.000$ | **Volume 05 (Nitrogen & Phosphorus Dynamics)** |")
    p("| **8** | **参数率定范式选择** | 沿用传统大田串行分步法 (S1~S5) | 误差单向累积且不可逆调节，S5 阶段 70% 活动参数撞击人工边界死锁，鲜产系统性低估 33%，且 4 角点极端样本丢失中度水氮曲率 | 全面转向 PEST++ IES 全量 70 参数协同反演 (Sobol 150×6)，扩容至 13 代表性处理，实现核心 16 参数 0.0% 零触界高斯收敛 | **Volume 06 (PEST++ Calibration Engineering)** |")
    p()
    p("---")
    p()
    p("## 2. 八大历史重大科学矛盾深度剖析与源码级反思")
    p()
    p("### 2.1 矛盾一：土壤有机质矿化调控 —— `SLNF` 调控假说 vs CENTURY `SASC_RATIO` 被动碳库初始化")
    p("- **问题表象**：在零氮（N0）处理下，模型计算的土壤内生矿化氮供给量过高（全季净矿化量高达 $145.2\\text{ kg N/ha}$），导致 N0 处理植株旺长、生物量与产量模拟值居高不下，无法重现田间实测显著的施氮增产效应（2025春 W1 甚至出现 N0 产量高于 N3 达 $-2,498\\text{ kg/ha}$ 的反向倒挂）。")
    p("- **历史错误假说**：早期尝试通过下调土壤剖面中的 `SLNF`（Soil Fertility Factor，默认 1.0）至 0.4~0.6 来抑制矿化，甚至有提案建议在参数率定中将 `SLNF` 放宽至 3.0~10.0。")
    p("- **底层源码实据**：")
    p("  1. `InputModule/IPSOIL_Inp.for:485-492`：")
    p("     ```fortran")
    p("     IF (SLNF(L) .GT. 1.0) THEN")
    p("         WRITE(MESSAGE(1),'(A,I2,A)') 'Layer ',L,' SLNF > 1.0 reset to 1.0'")
    p("         CALL WARNING(1,'IPSOIL',MESSAGE)")
    p("         SLNF(L) = 1.0")
    p("     ENDIF")
    p("     ```")
    p("     任何 `SLNF > 1.0` 在读取时被强制重置为 1.0，算法在此区间搜索完全无效。")
    p("  2. `SOMDEC_C.for`：在 CENTURY 模式（`MESOM = 'P'`）下，矿化通量由微生物分解动力学计算，根本不读取、也不乘以 `SLNF`！")
    p("- **最终机理真理**：通过在 FileX Section `@A` 注入 `SASC_RATIO = 0.94`（即认定高肥力温室土壤中有 94% 的有机碳处于难以矿化的 SOM3 被动池），背景净矿化量自 $145.2\\text{ kg N/ha}$ 骤降至 **$88.4\\text{ kg N/ha}$**，彻底消除了 N0 假饱，施氮响应保真度达 97.8%。详细推导见 [Volume 01](01_soil_organic_matter_century.md)。")
    p()
    p("### 2.2 矛盾二：25SP W1 产量断崖低估 —— 初始底氮倒挂假说 vs 根系虚假吸水 + 蒸发抑制")
    p("- **问题表象**：25SP W1N3（低水充分施氮）产量断崖式低估，模拟值仅为实测值的 50%，且低于 W1N0（严重干旱下施氮反而减产）。")
    p("- **历史错误假说**：怀疑土壤底肥无机氮化验数值倒挂，或干旱导致根系吸氮受阻。")
    p("- **实证正交扫验证伪**：实施无机氮 $2.5\\times$ 倍数正交扫描，鲜产变动仅 **0.009%**！调取输出文件，全生育期累积水分胁迫天数 $\\sum WSPD \\equiv 18.007$ 发生完全死锁，而氮胁迫因子 $NSTRES \\equiv 1.0$ 全程无缺氮，证实纯属水分受阻。")
    p("- **最终机理真理**：查证 `ROOTWU.for`，原模型允许根系下扎至 180cm 汲取深层积水，导致水分信号失真；同时默认 `SLU1 = 5.5mm` 导致无效蒸发虚高至 45% ET。实施 **100cm 根系物理筑坝** (`SRGF(100)=0.20, SRGF(180)=0.0`) + **Run 14 蒸发抑制** (`SLU1=1.0mm, PMWD=45cm, EFIR=0.95`)，干旱增产强力拉升转正为 **$+5,092.4\\text{ kg/ha}$**。详细推导见 [Volume 02](02_soil_water_hydraulics_soilwat.md)。")
    p()
    p("### 2.3 矛盾三：温室移栽苗龄设定 —— 经验臆断 28d/25d vs 育苗档案严格对账 22.0d")
    p("- **问题表象**：历史文档中苗龄设定混乱（28d、25d、10d 不等），导致初花期与早期生物量拟合极度敏感。")
    p("- **梯度试验实据**：7 梯度模拟矩阵表明，当 `PAGE < 19d` 时，幼苗过小导致初花期严重推迟，结实期缩短，产量崩塌 70%（双春 NRMSE 高达 77.8%）。")
    p("- **最终机理真理**：查验温室育苗播种与定植原始农事日志，严格核对确立 2026 春季穴盘苗苗龄为 **22.0 天**（`PAGE = 22.0`），消除了 3~6 天的热量虚假累积，双春综合误差降至谷底（13.29%）。详细推导见 [Volume 03](03_crop_phenology_trans.md)。")
    p()
    p("### 2.4 矛盾四：物候基温跨季泛化 —— 低基温 `TB1=6.5~7.5℃` 春季过拟合 vs 秋季“低温飞车”")
    p("- **问题表象**：早期优化器将 `TB1` 压低至 6.5~7.5℃，春季拟合极佳（NRMSE < 6%），但代入秋季盲测（25FA）时出现严重的“低温飞车”不结茬狂长，模拟秋产高达 27.5 t/ha（实测仅 17.0 t/ha），秋季盲测 NRMSE 恶化至 63%~104%。")
    p("- **机理确诊**：华北温室深秋气温降至 10~14℃，若基温过低，模型误判每日仍有有效积温，作物持续开花灌浆。")
    p("- **最终机理真理**：将 `TB1` 校准至 **`8.90 ~ 9.21℃`**（C15 收敛于 9.21℃），深秋气温低于 9℃ 时积温归零，模型适时停止灌浆截茬，秋季独立外推盲测 NRMSE 降至 **18.38%**。详细推导见 [Volume 03](03_crop_phenology_trans.md)。")
    p()
    p("### 2.5 矛盾五：零氮（N0）极端早衰脱落 —— 叶片快速凋落雪崩 vs `SENES.for` 氮动员过度杀伤与 V5 修复")
    p("- **问题表象**：在 V4 版本全量率定中，零氮低水处理（26SP W1N0）终熟期模拟 LAI 暴跌至 **0.62**（实测为 2.53），植株秃顶枯死。")
    p("- **Fortran 源码确诊**：`SENES.for:198` 公式 $LFSEN = SENRTE \\times NRUSLF / 0.16$；V4 中 `SENRTE=6.50` 导致 1g 氮动员诱发高达 40.6g 叶片脱落；同时 `DEMAND.for` 中 `FL-LF=400` 锁死了无限出叶更新能力。")
    p("- **最终机理真理**：实施 V5 修复，约束 `SENRTE = 4.40`，放宽 `FL-LF = 512 ℃·d`，激活自然衰老上限 `SENMAX_LATE`，终熟期零氮 LAI 恢复至生理合理的 **2.45**。详细推导见 [Volume 04](04_crop_growth_source_sink_photo.md)。")
    p()
    p("### 2.6 矛盾六：26SP 初始无机氮表层虚高 —— 原始化验直接代入 vs 分子离子折算 + 0.70 缩放")
    p("- **问题表象**：26SP 初始硝态氮化验单高达 85 mg N/kg，若直接代入，作物苗期吸收天量底氮，施氮与否均无缺氮表现。")
    p("- **机理确诊**：化验单给出的是硝酸根分子离子质量（直接使用带来 4.4 倍虚高）；且田间仅采集 0~15cm 滴灌肥力富集层，全剖面等值代入导致底肥虚高。")
    p("- **最终机理真理**：按分子量比例折算纯氮元素（硝态氮乘以 0.2259，铵态氮乘以 0.7765），并固化 **`ICNS_26SP = 0.70`** 作为全剖面等效折减系数，施氮增产与实测完美契合。详细推导见 [Volume 05](05_nitrogen_phosphorus_dynamics.md) 与 [Volume 07](07_data_pipeline_quality_governance.md)。")
    p()
    p("### 2.7 矛盾七：化肥养分完整性 —— 仅施纯氮肥假象 vs 漏录化肥磷审计补全（T0P0）")
    p("- **问题表象**：历史所有试验包仅录入了尿素，磷模块必须关闭（`PHOSP='N'`），否则模型严重报错或停滞。")
    p("- **代码审查澄清**：前期曾误认为 `SMHB=SA012` 是非法代码，`SMPX=-99` 是缺失参数；查证源码证明二者均合法有效，真正原因是 Section `@F` 施肥事件漏录化肥磷。")
    p("- **最终机理真理**：全面补齐三季纯磷（$P_2O_5$）施肥记录，三组对照（P-off、P-on 实际、P-on 充足）通过验收，磷平衡闭合度 $SEASBAL = 0.000$。详细推导见 [Volume 05](05_nitrogen_phosphorus_dynamics.md)。")
    p()
    p("### 2.8 矛盾八：参数率定范式选择 —— 传统大田串行分步（S1~S5）70% 边界死锁 vs 全量 70 参数 PEST++ IES 协同反演")
    p("- **问题表象**：沿用大田经典分步法（S1物候 -> S2冠层 -> S3水分 -> S4氮素 -> S5产量），S5 终期 10 个参数中有 7 个锁死在物理上下界，导数归零，鲜产低估 33%，25SP 施氮反向倒挂。")
    p("- **机理确诊**：无限生长茄果类营养与生殖高度重叠，串行分步强制截断下游反馈，引发不可逆的病态逆向代偿。")
    p("- **最终机理真理**：构建基于 Sobol 序列（150 成员 × 6 轮迭代）的全量 70 主效遗传参数 IES 协同反演架构，扩容至 13 代表性处理（锁定中水适氮曲率），达成核心 16 参数 0.0% 零触界自由高斯收敛。详细推导见 [Volume 06](06_pestpp_calibration_engineering.md) 与 [Volume 08](08_parameter_posterior_equifinality.md)。")
    p()
    p("---")
    p()
    p("## 3. 已消费 83 篇历史文档全景索引与溯源对账矩阵")
    p()
    p("本矩阵完整收录了项目中消费并归档的 **83 篇**历史技术文档，按分类展示其历史贡献、状态及归档后路径（所有链接均指向 `docs/archive/`）：")
    p()
    p("| 序号 | 原始文件名 | 分类子目录 | 核心探索主题与历史贡献 | 状态与消解结论 | 归档目标路径 |")
    p("| :---: | :--- | :--- | :--- | :--- | :--- |")

    idx = 1
    for d in sorted(docs, key=lambda x: (x['category'], x['filename'])):
        fn = d['filename']
        cat = d['category']
        title = d['title'].replace('|', '-')
        status = d['status']
        res = d['resolution_summary'].replace('|', '-')
        subp = d['subpath']
        arch_link = f"../archive/{subp}/{fn}"
        p(f"| {idx} | `{fn}` | {cat} | {title} | **[{status}]** {res} | [`{subp}/{fn}`]({arch_link}) |")
        idx += 1

    p()
    p("---")
    p()
    p("> **结语与同行交流准则**：  ")
    p("> 本分册为 CROPGRO-Eggplant 模型历史演进之集大成裁判卷。后续任何参数引用、试验设计或论文评议，均应以本分册及前序分册（Vol 01~08）为准，严禁重新引入已被证伪的历史旧假说。")

    output_path = "docs/knowledge_base/09_historical_contradictions_and_resolution.md"
    with open(output_path, 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(lines))
    print(f"Volume 09 successfully written to {output_path} ({len(lines)} lines)")

def build_knowledge_base_readme():
    lines = []
    def p(text=""):
        lines.append(text)

    p("# CROPGRO-Eggplant 作物模型机理与参数率定分册知识库 (`docs/knowledge_base/`)")
    p()
    p("> **知识库架构编号**：`KB-DSSAT-CROPGRO-MASTER-INDEX`  ")
    p("> **基准日期**：2026-09-20  ")
    p("> **定位**：温室茄果类作物模型（TMGRO048）科研与工程团队核心技术资产，全面消费 83 篇历史探索文档后的分册手册体系。")
    p()
    p("---")
    p()
    p("## 1. 知识库分册导航矩阵")
    p()
    p("本知识库按照 **DSSAT 底层核心机理模块** 与 **反演算法工程** 划分为 9 大独立专题分册，各分册均包含完整的微分动力学方程、关键 Fortran 源码路径与行号、具体试验数据矩阵与排错实践：")
    p()
    p("| 分册编号 | 手册名称 | 核心 DSSAT 模块 / 工程范畴 | 重点解决之机理难题与排错经验 | 核心分册链接 |")
    p("| :---: | :--- | :--- | :--- | :--- |")
    p("| **Vol 01** | **土壤有机质与 CENTURY 模块** | `CENTURY_SOM` (`CENTURY.for`, `SOMCAS.for`) | 三库碳动力学、`SLNF` 静默重置失效证伪、`SASC_RATIO=0.94` 控矿化解 N0 假饱 | [01_soil_organic_matter_century.md](01_soil_organic_matter_century.md) |")
    p("| **Vol 02** | **土壤水分动力学与 SOILWAT 模块** | `SOILWAT_10LB` (`SOILWAT.for`, `ROOTWU.for`) | 10L-B 微网格参数表、100cm 根系物理筑坝、Run 14 蒸发抑制四协同网格数据 | [02_soil_water_hydraulics_soilwat.md](02_soil_water_hydraulics_soilwat.md) |")
    p("| **Vol 03** | **物候发育与移栽响应模块** | `PHENOL_TRANS` (`PHENOL.for`, `TRANS.for`) | 光温积温 `DTT` 方程、`PAGE` 7 梯度试验矩阵（22d 对账）、`TB1=9.21℃` 破秋季低温飞车 | [03_crop_phenology_trans.md](03_crop_phenology_trans.md) |")
    p("| **Vol 04** | **冠层光合与碳素源库分配模块** | `PHOTO_VEGGR` (`PHOTO.for`, `VEGGR.for`) | 冠层光合方程、`SENES.for` 衰老杀伤公式、V5 修复（SENRTE=4.4, FL-LF=512）解零氮早衰 | [04_crop_growth_source_sink_photo.md](04_crop_growth_source_sink_photo.md) |")
    p("| **Vol 05** | **氮磷养分动力学与平衡模块** | `NUPTAK_MOBIL_PUPTAK` (`NUPTAK.for`, `PUPTAK.for`) | 根系主动吸收动力学、初始氮 `ICNS_26SP=0.70` 扫描实据、T0P0 化肥磷施肥补全与闭合 | [05_nitrogen_phosphorus_dynamics.md](05_nitrogen_phosphorus_dynamics.md) |")
    p("| **Vol 06** | **PEST++ IES 算法与率定工程** | `PESTPP_ENGINEERING` (`build_pest.py`, IES v5.2) | 串行分步法 70% 边界死锁剖析、全量 70 参数协同反演、13 处理扩容曲率锁定、四大门禁 | [06_pestpp_calibration_engineering.md](06_pestpp_calibration_engineering.md) |")
    p("| **Vol 07** | **数据治理管道与不可变资产** | `DATA_PIPELINE` (`tools/experiments/`) | 26122 苗期 LAID 笔误纠偏、化验纯氮分子折算消除 4.4 倍虚高、XXSL2501/2601 双剖面 | [07_data_pipeline_quality_governance.md](07_data_pipeline_quality_governance.md) |")
    p("| **Vol 08** | **参数后验分布与同效异构性** | `POSTERIOR_EQUIFINALITY` | 16 核心参数 0.0% 零触界高斯收敛、Spearman 强代偿网络、同效异构解实证 (real_96 vs 97) | [08_parameter_posterior_equifinality.md](08_parameter_posterior_equifinality.md) |")
    p("| **Vol 09** | **历史矛盾裁决与 83 篇全景溯源** | `FORENSIC_RECONCILIATION` | 8 大重大科学矛盾深度对账与源码真相、83 篇已归档历史文档全景索引与溯源矩阵 | [09_historical_contradictions_and_resolution.md](09_historical_contradictions_and_resolution.md) |")
    p()
    p("---")
    p()
    p("## 2. 知识库与现行系统的关系拓扑")
    p()
    p("```mermaid")
    p("flowchart TD")
    p("    Dev[\"核心开发规范与系统契约<br/>(AGENTS.md, DEVELOPER_GUIDE.md, 项目重构规划.md)\"] --> KB")
    p("    KB[\"模块化分册知识库目录 docs/knowledge_base/<br/>(Vol 01 ~ Vol 09)\"]")
    p("    KB --> Rep[\"现行全景经验圣经<br/>(docs/reports/CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md)\"]")
    p("    KB --> Paper[\"投稿论文主干框架<br/>(docs/reports/温室茄子水氮多目标优化论文框架_打磨稿_20260918.md)\"]")
    p("    KB --> Arch[\"历史归档库 docs/archive/<br/>(83 篇历史文档，完整保留 Git 历史)\"]")
    p("```")
    p()
    p("---")
    p("如需查阅主文档导航，请返回 [docs/README.md](../README.md)。")

    output_path = "docs/knowledge_base/README.md"
    with open(output_path, 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(lines))
    print(f"Master README successfully written to {output_path} ({len(lines)} lines)")

if __name__ == '__main__':
    build_volume_09()
    build_knowledge_base_readme()
