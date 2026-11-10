import os
import sys
import json

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

PROTECTED = {
    'AGENTS.md',
    'DEVELOPER_GUIDE.md',
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

def analyze_docs():
    docs_root_files = []
    report_files = []

    for f in os.listdir('docs'):
        p = os.path.join('docs', f).replace('\\', '/')
        if os.path.isfile(p) and f.endswith('.md'):
            docs_root_files.append((p, is_protected(p)))

    for f in os.listdir('docs/reports'):
        p = os.path.join('docs/reports', f).replace('\\', '/')
        if os.path.isfile(p) and f.endswith('.md'):
            report_files.append((p, is_protected(p)))

    print(f"=== DOCS ROOT ({len(docs_root_files)}) ===")
    for p, prot in sorted(docs_root_files):
        tag = "[PROTECT]" if prot else "[ARCHIVE]"
        print(f"  {tag} {p}")

    print(f"\n=== DOCS/REPORTS ({len(report_files)}) ===")
    for p, prot in sorted(report_files):
        tag = "[PROTECT]" if prot else "[ARCHIVE]"
        print(f"  {tag} {p}")

if __name__ == '__main__':
    analyze_docs()
