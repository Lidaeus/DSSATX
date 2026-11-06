import os
import sys
import json
import subprocess

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def migrate_docs():
    with open('doc_archive_metadata.json', 'r', encoding='utf-8') as fp:
        docs = json.load(fp)

    print(f"Loaded {len(docs)} documents to archive.")

    # 1. Ensure archive subdirectories exist
    for d in docs:
        dest_dir = os.path.join('docs', 'archive', d['subpath']).replace('\\', '/')
        os.makedirs(dest_dir, exist_ok=True)

    # 2. Execute git mv for each file
    success_count = 0
    fail_count = 0
    for d in docs:
        src = d['path']
        dest = os.path.join('docs', 'archive', d['subpath'], d['filename']).replace('\\', '/')
        
        # Check if source exists
        if not os.path.exists(src):
            print(f"Warning: source file not found: {src}")
            fail_count += 1
            continue

        cmd = ['git', 'mv', src, dest]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if res.returncode == 0:
            success_count += 1
        else:
            err_msg = (res.stderr or '').strip()
            print(f"git mv failed for {src}: {err_msg}. Attempting os.rename...")
            try:
                os.rename(src, dest)
                subprocess.run(['git', 'add', dest], check=True, encoding='utf-8', errors='replace')
                if os.path.exists(src):
                    subprocess.run(['git', 'rm', '-f', src], check=True, encoding='utf-8', errors='replace')
                success_count += 1
            except Exception as e:
                print(f"Error moving {src} to {dest}: {e}")
                fail_count += 1

    print(f"Migration completed: {success_count} succeeded, {fail_count} failed.")

    # 3. Write ARCHIVE_MANIFEST_20260920.md
    manifest_lines = []
    manifest_lines.append("# 文档归档清单 (2026-09-20 历史全量率定与机理探索文档)")
    manifest_lines.append("")
    manifest_lines.append("> 归档日期：2026-09-20  ")
    manifest_lines.append("> 归档范围：83 篇历史率定、多臂试验、敏感性分析与数据治理探索文档  ")
    manifest_lines.append("> 归档目的：集中消费历史文档经验，消解前后机理矛盾，腾清当前生产工作区，完整保留 Git 历史追溯能力。  ")
    manifest_lines.append("> **权威替代入口**：[DSSAT_CROPGRO_参数率定与机理问题分类知识库.md](../DSSAT_CROPGRO_参数率定与机理问题分类知识库.md) 与 [CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md](../reports/CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md)。")
    manifest_lines.append("")
    manifest_lines.append("## 分类统计")
    manifest_lines.append("")
    
    cats = {}
    for d in docs:
        cats.setdefault(d['category'], []).append(d)
        
    for c, items in sorted(cats.items()):
        manifest_lines.append(f"- **`{c}`**：共 {len(items)} 篇")
    manifest_lines.append("")
    manifest_lines.append("## 归档详细明细表")
    manifest_lines.append("")
    manifest_lines.append("| 序号 | 文件名 | 归档后路径 | 分类 | 历史状态 | 核心结论与消解说明 |")
    manifest_lines.append("| :---: | :--- | :--- | :--- | :--- | :--- |")

    for i, d in enumerate(sorted(docs, key=lambda x: (x['category'], x['filename'])), 1):
        fn = d['filename']
        dest = f"{d['subpath']}/{fn}"
        cat = d['category']
        st = d['status']
        res = d['resolution_summary'].replace('|', '-')
        manifest_lines.append(f"| {i} | `{fn}` | [`{dest}`]({dest}) | {cat} | **{st}** | {res} |")

    manifest_lines.append("")
    manifest_lines.append("---")
    manifest_lines.append("归档操作执行完毕。")

    manifest_path = "docs/archive/ARCHIVE_MANIFEST_20260920.md"
    with open(manifest_path, 'w', encoding='utf-8') as fp:
        fp.write('\n'.join(manifest_lines))
    print(f"Archive manifest written to {manifest_path}")

    # 4. Update docs/archive/README.md
    update_archive_readme()

    # 5. Update docs/reports/README.md
    update_reports_readme()

def update_archive_readme():
    readme_path = "docs/archive/README.md"
    content = """# 已淘汰与历史归档文档库

本目录集中保存已完成、被替代或仅作为迁移输入的历史技术文档。所有文件均保留原始文件名与完整 Git 历史，供后续开发与同行交流追溯设计演变。

## 核心使用限制与警示

- **严禁直接复用**：不得直接复制归档文档中的参数取值范围、Top-K 列表、目标函数权重、运行规模或中间状态到新试验；
- **严禁作为入口**：不得把归档脚本或命令视为当前有效运行入口；
- **严禁作为科学结论**：不得引用已淘汰的阶段性假说（如 `SLNF` 调控矿化、W1 缺氮倒挂、`TB1` 低温拟合等）作为学术结论；
- **权威真理查阅**：所有关于机理机制、参数率定与工程准则的最新定论，必须直接查阅：
  - [DSSAT_CROPGRO_参数率定与机理问题分类知识库.md](../DSSAT_CROPGRO_参数率定与机理问题分类知识库.md)
  - [CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md](../reports/CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md)

## 归档目录结构分类

### 1. DSSAT 生理与土壤模块机理归档 (`dssat_modules/`)
- [dssat_modules/soil_organic_matter/](dssat_modules/soil_organic_matter/)：CENTURY SOM、SASC 惰性碳、SLNF 矿化调控假说与历史 N0 倒挂报告；
- [dssat_modules/soil_water_hydraulics/](dssat_modules/soil_water_hydraulics/)：SOILWAT 水分动力学、10L-B 微网格、100cm SRGF 根系筑坝、滴灌蒸发抑制 (Run 14)；
- [dssat_modules/crop_phenology/](dssat_modules/crop_phenology/)：TRANS 移栽、PAGE 苗龄 (22d) 对账、TB1 基温跨季泛化；
- [dssat_modules/crop_growth_source_sink/](dssat_modules/crop_growth_source_sink/)：PHOTO 光合、VEGGR 营养器官生长、单果灌浆与采收分配；
- [dssat_modules/nitrogen_phosphorus_dynamics/](dssat_modules/nitrogen_phosphorus_dynamics/)：NUPTAK 吸氮、MOBIL 动员、SENES 衰老脱落与 T0P0 磷素施肥补全。

### 2. 率定方法学与数据管道 (`calibration_methodology/`, `data_pipeline/`)
- [calibration_methodology/](calibration_methodology/)：PEST++ IES 反演算法配置、Sobol 初始集合、13 处理扩容与四大科学门禁；
- [data_pipeline/](data_pipeline/)：XXSL2501 与 XXSL2601 双地块独立剖面重构、26122 LAID 笔误纠偏、无机氮纯氮折算、TMT/TMA 数据链对账。

### 3. 历史运行与阶段性交接 (`historical_runs/`)
- [historical_runs/e02_series/](historical_runs/e02_series/)：E02 从头率定系列、v37~v52 多臂探索与阶段性候选集 C01~C04；
- [historical_runs/full_genetic_v1_v8/](historical_runs/full_genetic_v1_v8/)：全量主效遗传参数协同率定 V1~V8_ref 演变过程与验收报告。

### 4. 敏感性分析与质量审查 (`sensitivity_analysis_historical/`, `reviews_and_governance/`)
- [sensitivity_analysis_historical/](sensitivity_analysis_historical/)：2026年7-8月 Morris 与 Sobol 全局敏感性分析历史报告；
- [reviews_and_governance/](reviews_and_governance/)：代码静态审查、异常重复剔除与不可变资产审查备忘录。

### 5. 早期归档资产 (2026-07-29 以前)
- [completed_plans/](completed_plans/) / [designs/](designs/) / [handoffs/](handoffs/) / [paper_drafts/](paper_drafts/)：更早期的构想与草稿。

## 批次归档清单索引
- **2026-09-20 集中大归档（83 篇）**：[ARCHIVE_MANIFEST_20260920.md](ARCHIVE_MANIFEST_20260920.md)
- **2026-07-29 早期归档清单**：[ARCHIVE_MANIFEST_20260729.md](ARCHIVE_MANIFEST_20260729.md)

当前系统入口请返回 [主文档索引](../README.md)。
"""
    with open(readme_path, 'w', encoding='utf-8') as fp:
        fp.write(content.strip() + '\n')
    print(f"Updated {readme_path}")

def update_reports_readme():
    readme_path = "docs/reports/README.md"
    content = """# 运行报告与机理知识库目录 (`docs/reports/`)

本目录保存当前最新、活跃且经过严格同行审阅的**机理知识总结、论文写作框架与权威数据对账成果**。

> **历史文档归档说明 (2026-09-20)**：  
> 历史探索过程中的 50+ 篇阶段性试验报告、多臂探索记录及早期假说推翻文档，已按照 **DSSAT 核心模块（CENTURY/SOILWAT/PHENOL/PHOTO/NUPTAK）与工程问题** 完整分类归档至 [`docs/archive/`](../archive/) 目录下，详细映射见 [归档清单 (2026-09-20)](../archive/ARCHIVE_MANIFEST_20260920.md)。

---

## 核心现行技术与知识资产

### 1. 核心知识库与经验总结（每日必读）
- **[CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md](CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md)**  
  *全景知识圣经（455行，约5.4万字）*：覆盖数据管道不可变冻结、CENTURY SASC 控矿化、100cm SRGF 根系筑坝、TB1 物候基温泛化、13 处理扩容与四大科学门禁、十大黄金准则 Ten Golden Rules 及排查树。
- **[DSSAT_CROPGRO_参数率定与机理问题分类知识库.md](../DSSAT_CROPGRO_参数率定与机理问题分类知识库.md)**  
  *按 DSSAT 模块与反演工程问题分类* 的历史经验消费全典，系统剖析 8 大历史科学矛盾真相并提供 83 篇已归档文档全景溯源。

### 2. 论文写作与结构框架
- **[温室茄子水氮多目标优化论文框架_打磨稿_20260918.md](温室茄子水氮多目标优化论文框架_打磨稿_20260918.md)**  
  *SCI 投稿论文主干框架*：涵盖研究背景、材料与方法（双地块剖面与 PEST++ IES 算法）、结果（双春精度、秋季外推、水氮响应曲面、同效异构性）及讨论。

---

## 归档追溯入口

如需调阅特定历史阶段（E02 v37~v52、V1~V8 全量探索、初始矿质氮扫描等）的原始试验过程与原始数据：
- 查阅 [历史归档索引](../archive/README.md)
- 查阅 [2026-09-20 历史全量归档清单](../archive/ARCHIVE_MANIFEST_20260920.md)
"""
    with open(readme_path, 'w', encoding='utf-8') as fp:
        fp.write(content.strip() + '\n')
    print(f"Updated {readme_path}")

if __name__ == '__main__':
    migrate_docs()
