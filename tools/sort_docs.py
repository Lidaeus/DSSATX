import os
import shutil

root = r"d:\Tomato_Cal"
trash_dir = os.path.join(root, "workspace", "trash", "Sensitivity_Analyze_Old")

docs_dir = os.path.join(root, "docs")
bg_dir = os.path.join(docs_dir, "background_knowledge")
reports_dir = os.path.join(docs_dir, "reports")
sa_docs_dir = os.path.join(docs_dir, "sa_project")

os.makedirs(bg_dir, exist_ok=True)
os.makedirs(reports_dir, exist_ok=True)
os.makedirs(sa_docs_dir, exist_ok=True)

def _move(src, dst):
    if os.path.exists(src):
        try:
            shutil.move(src, dst)
        except Exception as e:
            print(f"Error moving {src} to {dst}: {e}")

# 1. Background knowledge
for md in ["CUL_Comparison.md", "ECO_Comparison.md", "SPE_Comparison.md", "Summary.md", "需要进行敏感性分析的遗传参数.txt"]:
    _move(os.path.join(trash_dir, md), os.path.join(bg_dir, md))

for d in ["DSSAT_Output_Interpretation", "Tomato_ECO_Parameter_Analysis", "Tomato_SPE_Parameter_Analysis"]:
    _move(os.path.join(trash_dir, d), os.path.join(bg_dir, d))

# 2. SA project docs
sa_src = os.path.join(trash_dir, "SA_Project_Docs")
if os.path.exists(sa_src):
    for f in os.listdir(sa_src):
        if f.startswith("04_") or f.startswith("05_") or f.startswith("06_"):
            # These are analysis/strategy reports
            _move(os.path.join(sa_src, f), os.path.join(reports_dir, f))
        else:
            # Archival/Reference scheme docs 
            name = f
            if f in ["01_敏感性分析项目设计文档.md", "07_Morris_Sobol_运行教程.md"]:
                name = "ARCHIVED_" + f
            _move(os.path.join(sa_src, f), os.path.join(sa_docs_dir, name))

# Also move out the older report from root docs
_move(os.path.join(docs_dir, "ARCHIVED_compare_v16_vs_v15_report.md"), os.path.join(reports_dir, "ARCHIVED_compare_v16_vs_v15_report.md"))

print("Documents successfully reorganized into docs/background_knowledge, docs/reports, and docs/sa_project")
