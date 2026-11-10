import os
import sys
import json
import re

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

PROTECTED = {
    'AGENTS.md',
    'DEVELOPER_GUIDE.md',
    'docs/DEVELOPER_GUIDE.md',
    'DSSAT并行隔离与输入路径规范.md',
    'docs/DSSAT并行隔离与输入路径规范.md',
    '项目重构规划.md',
    'requirements.txt',
    'docs/README.md',
    'docs/CHANGELOG.md',
    'docs/科研图表设计与开发计划.md',
    'docs/项目状态与科研启动清单.md',
    'docs/敏感性分析与率定用户指南.md',
    'docs/权重设计方案改进提案.md',
    'docs/数据来源与配置规范手册_v1_20260808.md',
    'docs/目录与输入资产规范.md',
    'docs/项目代码净化方案.md',
    'docs/试验背景与数据说明_温室茄子水氮试验.md',
    'docs/reports/README.md',
    'docs/reports/CROPGRO_Eggplant模型参数率定与水氮机理经验知识总结_20260920.md',
    'docs/reports/温室茄子水氮多目标优化论文框架_打磨稿_20260918.md',
}

def is_protected(path):
    p = path.replace('\\', '/').strip('./')
    if p in PROTECTED:
        return True
    if p.startswith('docs/CROPGRO_N_MECHANISM/') or p.startswith('docs/CROPGRO_WATER_MECHANISM/') or p.startswith('docs/reference/'):
        return True
    if p.startswith('docs/archive/'):
        return True
    return False

def assign_category_and_resolution(path):
    fname = os.path.basename(path)
    fname_lower = fname.lower()
    
    # Defaults
    category = "calibration_methodology"
    subpath = "calibration_methodology"
    dssat_module = "ENGINEERING"
    status = "SUPERSEDED_EVOLVED"
    contradiction_topic = "General"
    resolution_summary = ""

    # 1. Soil Organic Matter (CENTURY / CERES-SOM / SASC / SLNF)
    if any(k in fname_lower for k in ['sasc', 'slnf', 'century', 'som', 'n0_n3产量倒挂']):
        dssat_module = "CENTURY_SOM"
        category = "dssat_modules/soil_organic_matter"
        subpath = "dssat_modules/soil_organic_matter"
        if 'slnf' in fname_lower:
            contradiction_topic = "SLNF矿化调控假说"
            status = "SUPERSEDED_FALSE"
            resolution_summary = "Fortran源码验证SLNF>1.0被静默重置为1.0且CENTURY忽略SLNF；最终通过SASC_RATIO=0.94初始化SOM3被动池成功压实矿化。"
        elif 'n0_n3产量倒挂' in fname_lower:
            contradiction_topic = "N0-N3施氮产量倒挂"
            status = "SUPERSEDED_FALSE"
            resolution_summary = "早期误判为底肥无机氮倒挂，实证证明为内生背景矿化过高导致假饱+水分受阻；通过SASC控矿化及水分平衡彻底消除倒挂。"
        else:
            contradiction_topic = "CENTURY-SASC惰性碳库初始化"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "确立SASC_RATIO=0.94为控制设施大棚高有机碳内生矿化的决定性机理，背景矿化自145降至88 kg N/ha。"

    # 2. Soil Water & Hydraulics (SOILWAT / 10L-B / SRGF / SLDR / SSKS / Evap)
    elif any(k in fname_lower for k in ['srgf', 'soilwat', 'ssks', 'sldr', 'slll', 'slu1', '滴灌蒸发', '土壤水分', '土壤剖面', '土壤参数']):
        dssat_module = "SOILWAT"
        category = "dssat_modules/soil_water_hydraulics"
        subpath = "dssat_modules/soil_water_hydraulics"
        if 'ssks' in fname_lower:
            contradiction_topic = "导水率SSKS敏感性断点"
            status = "SUPERSEDED_EVOLVED"
            resolution_summary = "早期测试发现SSKS敏感性存在阈值断点；后续在10L-B网格中采用环刀原状土实测Ks分层映射，无需人为拟合。"
        elif 'srgf' in fname_lower:
            contradiction_topic = "深层根系虚假吸水与100cm筑坝"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "查明原模型允许根系扎至180cm吸取深层水导致干旱处理失真；确立100cm根系物理筑坝(SRGF=0)，真实还原水分胁迫。"
        elif '滴灌蒸发' in fname_lower:
            contradiction_topic = "表层滴灌蒸发抑制(Run 14)"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "确认滴灌地膜覆盖下第一阶段蒸发极限SLU1=1.0mm与灌溉效率EFIR=0.95，修复25SP W1表层水失真。"
        else:
            contradiction_topic = "土壤水动力学参数体系"
            status = "SUPERSEDED_EVOLVED"
            resolution_summary = "对比历史stage4备份与当前土壤参数，确立10层原状土实测容重(1.364 g/cm3)与保水保序参数序列。"

    # 3. Crop Phenology & Seedling Age (TRANS / PHENOL / PAGE / TB1)
    elif any(k in fname_lower for k in ['page', 'tb1', '苗龄', '0629期lai']):
        dssat_module = "CRGRO_PHENOL_TRANS"
        category = "dssat_modules/crop_phenology"
        subpath = "dssat_modules/crop_phenology"
        if 'page' in fname_lower or '苗龄' in fname_lower:
            contradiction_topic = "育苗苗龄PAGE设定矛盾"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "纠正历史28天与25天臆断，依据育苗定植日志严格对账确立PAGE=22.0天，彻底解除苗期热量积算偏差。"
        elif '0629期lai' in fname_lower:
            contradiction_topic = "26SP LAI取样数据修补"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "对0629期实测缺失LAI进行多项式无偏插值，恢复冠层生长序列完整度。"
        else:
            contradiction_topic = "物候基温TB1跨季泛化"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "推翻早期6.5~7.5℃春季过拟合设定，确立TB1=8.9~9.21℃，秋季降温适时停止灌浆截茬，消除秋季飞车。"

    # 4. Crop Growth, Source-Sink & Senescence (PHOTO / VEGGR / DEMAND / SENES)
    elif any(k in fname_lower for k in ['photo', 'senescence', '衰老', '碳素', '光合', '生长指标']):
        dssat_module = "CRGRO_PHOTO_VEGGR"
        category = "dssat_modules/crop_growth_source_sink"
        subpath = "dssat_modules/crop_growth_source_sink"
        if '生长指标' in fname_lower:
            contradiction_topic = "生长指标时间序列非单调"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "排查抽样单株个体变异导致的非单调波动，确立群体均值审计与单株折算口径。"
        elif '衰老' in fname_lower or 'senescence' in fname_lower:
            contradiction_topic = "零氮极端早衰与叶面积雪崩"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "在V5中约束SENRTE=4.4，激活FL-LF并平衡NMINEP，彻底治愈N0末期叶面积跌穿至0.62的崩溃现象。"
        else:
            contradiction_topic = "光合碳分配与源库平衡"
            status = "SUPERSEDED_EVOLVED"
            resolution_summary = "诊断官方光合模型LFMAX、SLAVR与碳氮输出路径，为全量遗传率定提供源库边界约束。"

    # 5. Nitrogen & Phosphorus Dynamics (NUPTAK / MOBIL / PUPTAK / P0)
    elif any(k in fname_lower for k in ['磷', 'phosp', '组织磷', '氮响应', 'nitrogen', '1p5n', 'soil_n_scale']):
        dssat_module = "CRGRO_NUPTAK_PUPTAK"
        category = "dssat_modules/nitrogen_phosphorus_dynamics"
        subpath = "dssat_modules/nitrogen_phosphorus_dynamics"
        if '磷' in fname_lower or 'phosp' in fname_lower:
            contradiction_topic = "磷输入遗漏与隐性缺磷排查"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "T0P0重大审计发现三季试验输入包中化肥磷被遗漏；全量补齐P2O5施肥记录，消除隐藏的非水氮限制因子。"
        elif 'soil_n_scale' in fname_lower or '1p5n' in fname_lower:
            contradiction_topic = "26SP初始矿质氮缩放系数"
            status = "CONFIRMED_MECHANISM"
            resolution_summary = "系统扫描初始氮梯度，明确26SP化验取样过浅导致表层放大，最终将缩放系数固定在0.70并冻结。"
        else:
            contradiction_topic = "氮吸收与转运机制调控"
            status = "SUPERSEDED_EVOLVED"
            resolution_summary = "探索Dias2026与V40在不同施氮水平下的响应，建立全生育期临界氮稀释曲线约束。"

    # 6. Data Pipeline & Experimental Bundles
    elif any(k in fname_lower for k in ['双地块土壤方案', 'tmt_tma', '数据重构', '数据链', '数值系', '气象文件']):
        dssat_module = "DATA_PIPELINE"
        category = "data_pipeline"
        subpath = "data_pipeline"
        contradiction_topic = "数据流清洗与双地块剖面重构"
        status = "CONFIRMED_MECHANISM"
        resolution_summary = "修正26122 LAID录入笔误(1.88->0.319)，纯氮原子量折算消除4.4倍虚高，划分XXSL2501/2601双地块剖面。"

    # 7. Historical Runs - E02 Series
    elif 'e02' in fname_lower:
        dssat_module = "CALIBRATION_E02"
        category = "historical_runs/e02_series"
        subpath = "historical_runs/e02_series"
        contradiction_topic = "E02基准多臂试验探索"
        status = "SUPERSEDED_EVOLVED"
        resolution_summary = "完成v37~v52多臂探索，沉淀C01~C04候选集，揭示串行分阶段率定70%触界死锁弊端，为全量率定奠基。"

    # 8. Historical Runs - Full Genetic V1~V8
    elif any(k in fname_lower for k in ['全量主效遗传参数', '200x7', 'c05_real26', 'v8_ref', 'v6验收', 'v53统一包', '率定探索实验记录']):
        dssat_module = "CALIBRATION_FULL_GENETIC"
        category = "historical_runs/full_genetic_v1_v8"
        subpath = "historical_runs/full_genetic_v1_v8"
        contradiction_topic = "全量主效遗传参数协同反演演进"
        status = "SUPERSEDED_EVOLVED"
        resolution_summary = "自V1至V8_ref打通70参数Sobol协同反演，目标函数Phi降破1000，解决产量严重低估并建立C05候选基准。"

    # 9. Sensitivity Analysis
    elif any(k in fname_lower for k in ['敏感性', 'morris', 'sobol']):
        dssat_module = "SENSITIVITY_ANALYSIS"
        category = "sensitivity_analysis_historical"
        subpath = "sensitivity_analysis_historical"
        contradiction_topic = "Morris/Sobol全局敏感性分析"
        status = "SUPERSEDED_EVOLVED"
        resolution_summary = "完成三季全生育期物候、冠层与产量敏感性因子筛选，确立解释98%以上方差的70个主效遗传参数集。"

    # 10. Reviews & Governance
    elif any(k in fname_lower for k in ['静态分析', '净化', '剔除', '交付报告', '审查备忘录', '审计', '核对', '项目评审']):
        dssat_module = "GOVERNANCE"
        category = "reviews_and_governance"
        subpath = "reviews_and_governance"
        contradiction_topic = "代码与数据工程质量审计"
        status = "CONFIRMED_MECHANISM"
        resolution_summary = "完成三轮代码静态净化、异常重复样本剔除、三季试验配置对账，确立只读不可变资产契约。"

    # 11. Calibration Methodology & Others
    else:
        dssat_module = "METHODOLOGY"
        category = "calibration_methodology"
        subpath = "calibration_methodology"
        contradiction_topic = "率定范式与目标函数优化"
        status = "SUPERSEDED_EVOLVED"
        resolution_summary = "确立PEST++ IES算法超参，废弃传统分步法，建立兼顾双春拟合与秋季外推盲测的多目标反演架构。"

    return {
        'path': path,
        'filename': fname,
        'category': category,
        'subpath': subpath,
        'dssat_module': dssat_module,
        'status': status,
        'contradiction_topic': contradiction_topic,
        'resolution_summary': resolution_summary
    }

def collect_all_docs():
    docs_to_archive = []
    for f in os.listdir('docs'):
        p = os.path.join('docs', f).replace('\\', '/')
        if os.path.isfile(p) and f.endswith('.md') and not is_protected(p):
            docs_to_archive.append(p)
    for f in os.listdir('docs/reports'):
        p = os.path.join('docs/reports', f).replace('\\', '/')
        if os.path.isfile(p) and f.endswith('.md') and not is_protected(p):
            docs_to_archive.append(p)

    metadata_list = []
    for p in sorted(docs_to_archive):
        info = assign_category_and_resolution(p)
        # read title and size
        info['size_bytes'] = os.path.getsize(p)
        with open(p, 'r', encoding='utf-8', errors='ignore') as fp:
            for line in fp:
                line_str = line.strip()
                if line_str and not line_str.startswith('<!--'):
                    info['title'] = line_str.lstrip('#').strip()
                    break
            else:
                info['title'] = os.path.basename(p)
        metadata_list.append(info)

    with open('doc_archive_metadata.json', 'w', encoding='utf-8') as fp:
        json.dump(metadata_list, fp, ensure_ascii=False, indent=2)

    print(f"Successfully processed {len(metadata_list)} documents into doc_archive_metadata.json")

if __name__ == '__main__':
    collect_all_docs()
