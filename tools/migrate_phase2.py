"""migrate_phase2.py — 阶段 2：目录重组与代码迁移。

执行步骤：
1. 复制数据文件到 data/raw/
2. 复制模板文件到 data/templates/
3. 复制文档到 docs/
4. 移动工具脚本到 tools/
5. 移动 SA 代码到 src/sensitivity/
6. 移动核心脚本到 src/ 各子目录，并在原位置留薄入口

用法：
    python migrate_phase2.py --dry-run    # 仅预览
    python migrate_phase2.py              # 执行迁移
"""

import argparse
import os
import shutil
import sys


def _project_root():
    return os.path.dirname(os.path.abspath(__file__))


# ── 迁移规则 ──────────────────────────────────────────────────
# (src_relative, dst_relative, action)
# action: "copy" = 复制(保留原位), "move" = 移动, "move+stub" = 移动并留 stub

MIGRATIONS = [
    # ── 气象文件 → data/raw/weather/ (copy) ──
    ("Workspace/UFBR9401.WTH",  "data/raw/weather/UFBR9401.WTH",  "copy"),
    ("Workspace/UFGA0601.WTH",  "data/raw/weather/UFGA0601.WTH",  "copy"),
    ("Workspace/UFGA0701.WTH",  "data/raw/weather/UFGA0701.WTH",  "copy"),

    # ── 土壤文件 → data/raw/soil/ (copy) ──
    ("Workspace/SOIL.SOL",      "data/raw/soil/SOIL.SOL",         "copy"),

    # ── 实验文件 → data/raw/experiments/ (copy) ──
    ("Workspace/UFBR9401.TMX",  "data/raw/experiments/UFBR9401.TMX",  "copy"),
    ("Workspace/UFBR9401.TMT",  "data/raw/experiments/UFBR9401.TMT",  "copy"),
    ("Workspace/UFBR9401.TMA",  "data/raw/experiments/UFBR9401.TMA",  "copy"),
    ("Workspace/UFGA0602.TMX",  "data/raw/experiments/UFGA0602.TMX",  "copy"),
    ("Workspace/UFGA0602.TMT",  "data/raw/experiments/UFGA0602.TMT",  "copy"),
    ("Workspace/UFGA0602.TMA",  "data/raw/experiments/UFGA0602.TMA",  "copy"),
    ("Workspace/UFGA0701.TMX",  "data/raw/experiments/UFGA0701.TMX",  "copy"),
    ("Workspace/UFGA0701.TMT",  "data/raw/experiments/UFGA0701.TMT",  "copy"),
    ("Workspace/UFGA0701.TMA",  "data/raw/experiments/UFGA0701.TMA",  "copy"),
    ("Workspace/XXQL2501.TMX",  "data/raw/experiments/XXQL2501.TMX",  "copy"),
    ("Workspace/XXQL2501.TMT",  "data/raw/experiments/XXQL2501.TMT",  "copy"),
    ("Workspace/XXQL2501.TMA",  "data/raw/experiments/XXQL2501.TMA",  "copy"),

    # ── 模板文件 → data/templates/ (copy) ──
    ("Workspace/TMGRO048.CUL.base",  "data/templates/genotype/TMGRO048.CUL.base",  "copy"),
    ("Workspace/TMGRO048.ECO.base",  "data/templates/genotype/TMGRO048.ECO.base",  "copy"),
    ("Workspace/TMGRO048.SPE.base",  "data/templates/genotype/TMGRO048.SPE.base",  "copy"),
    ("Workspace/DSSBatch.v48",                     "data/templates/batch/DSSBatch.v48",                     "copy"),
    ("Workspace/DSSBatch_excl_TN5_TN9_TN13.v48",  "data/templates/batch/DSSBatch_excl_TN5_TN9_TN13.v48",  "copy"),
    ("Workspace/DSSBatch_only_TN5_TN9_TN13.v48",  "data/templates/batch/DSSBatch_only_TN5_TN9_TN13.v48",  "copy"),
    ("Workspace/DSSATPRO.v48",   "data/templates/DSSATPRO.v48",    "copy"),
    ("Workspace/DSSAT48.INH",    "data/templates/DSSAT48.INH",     "copy"),
    ("Workspace/DSSAT48.INP",    "data/templates/DSSAT48.INP",     "copy"),

    # ── 权重 → configs/runs/ (copy) ──
    ("Workspace/tomato_cal.weights.csv",  "configs/runs/tomato_cal.weights.csv",  "copy"),

    # ── 基线参数 → data/parameter_registry/baseline/ (copy) ──
    ("Workspace/baseline_params.csv", "data/parameter_registry/baseline/baseline_params.csv", "copy"),

    # ── 文档 → docs/ (copy, 根目录保留原件) ──
    ("DEVELOPER_GUIDE.md",                          "docs/DEVELOPER_GUIDE.md",                          "copy"),
    ("CHANGELOG.md",                                "docs/CHANGELOG.md",                                "copy"),
    ("CLUSTERING_DESIGN.md",                        "docs/CLUSTERING_DESIGN.md",                        "copy"),
    ("VISUALIZATION_DESIGN.md",                     "docs/VISUALIZATION_DESIGN.md",                     "copy"),
    ("Project_Design_DSSAT_PEST_Calibration.md",    "docs/Project_Design_DSSAT_PEST_Calibration.md",    "copy"),
    ("DSSAT番茄模型参数率定方案.md",                "docs/DSSAT番茄模型参数率定方案.md",                "copy"),
    ("compare_v16_century_vs_v15_onlyTN5_TN9_TN13.md", "docs/compare_v16_century_vs_v15_onlyTN5_TN9_TN13.md", "copy"),
    ("pestpp_users_manual.md",                      "docs/pestpp_users_manual.md",                      "copy"),

    # ── 工具脚本 → tools/ (move) ──
    ("Workspace/clean_workspace.py",     "tools/clean_workspace.py",     "move"),
    ("Workspace/cluster_parameters.py",  "tools/cluster_parameters.py",  "move"),
    ("Workspace/download_pestpp.py",     "tools/download_pestpp.py",     "move"),
    ("Workspace/param_sweep.py",         "tools/param_sweep.py",         "move"),

    # ── SA 代码 → src/sensitivity/ (move+stub) ──
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_build_sen_case.py",
     "src/sensitivity/sa_build_sen_case.py", "move"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_model.py",
     "src/sensitivity/sa_model.py", "move"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_run_sen.py",
     "src/sensitivity/sa_run_sen.py", "move"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_postprocess_morris.py",
     "src/sensitivity/sa_postprocess_morris.py", "move"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_postprocess_sobol.py",
     "src/sensitivity/sa_postprocess_sobol.py", "move"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_postprocess_sobol_interpret.py",
     "src/sensitivity/sa_postprocess_sobol_interpret.py", "move"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_select_topk_from_morris.py",
     "src/sensitivity/sa_select_topk_from_morris.py", "move"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_prepare_sobol_topk_case.py",
     "src/sensitivity/sa_prepare_sobol_topk_case.py", "move"),
    # sa_generate_param_review_csv.py: 边界逻辑已提取到 param_registry.py，
    # 原脚本作为"从 DSSAT 文件同步基线"的工具保留
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_generate_param_review_csv.py",
     "src/sensitivity/sa_generate_param_review_csv.py", "move"),

    # ── 可视化/分析脚本 → src/reporting/ (move+stub) ──
    ("Workspace/analyze_results.py",     "src/reporting/analyze_results.py",     "move+stub"),
    ("Workspace/plot_results.py",        "src/reporting/plot_results.py",        "move+stub"),

    # ── 核心脚本 → src/ (move+stub) ──
    ("Workspace/build_pest.py",   "src/calibration/build_pest.py",   "move+stub"),
    ("Workspace/run_dssat.py",    "src/dssat/run_dssat.py",          "move+stub"),
]


STUB_TEMPLATE = '''"""Stub entry point — redirects to src/{module_path}.

This file was auto-generated by migrate_phase2.py.
The actual implementation has moved to: {dst_relative}
"""
import os
import sys

# Add project root to path so src/ is importable
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Execute the actual module
_actual = os.path.join(_project_root, {dst_repr})
exec(open(_actual, encoding="utf-8").read())
'''


def run_migration(root, *, dry_run=False):
    """Execute all migrations."""
    stats = {"copy": 0, "move": 0, "stub": 0, "skip": 0, "missing": 0}

    for src_rel, dst_rel, action in MIGRATIONS:
        src = os.path.join(root, src_rel.replace("/", os.sep))
        dst = os.path.join(root, dst_rel.replace("/", os.sep))

        if not os.path.exists(src):
            print(f"  SKIP (not found): {src_rel}")
            stats["missing"] += 1
            continue

        if os.path.exists(dst):
            print(f"  SKIP (exists):    {dst_rel}")
            stats["skip"] += 1
            continue

        os.makedirs(os.path.dirname(dst), exist_ok=True)

        if action == "copy":
            if not dry_run:
                shutil.copy2(src, dst)
            print(f"  COPY: {src_rel} → {dst_rel}")
            stats["copy"] += 1

        elif action == "move":
            if not dry_run:
                shutil.move(src, dst)
            print(f"  MOVE: {src_rel} → {dst_rel}")
            stats["move"] += 1

        elif action == "move+stub":
            if not dry_run:
                shutil.copy2(src, dst)
                # Create stub at original location
                dst_repr = repr(dst_rel.replace("/", os.sep))
                module_path = dst_rel.replace("/", ".").replace(".py", "")
                stub = STUB_TEMPLATE.format(
                    module_path=module_path,
                    dst_relative=dst_rel,
                    dst_repr=dst_repr,
                )
                with open(src, "w", encoding="utf-8") as f:
                    f.write(stub)
            print(f"  MOVE+STUB: {src_rel} → {dst_rel}")
            stats["move"] += 1
            stats["stub"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(description="阶段 2: 目录重组与代码迁移")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = _project_root()
    mode = "DRY-RUN" if args.dry_run else "EXECUTE"

    print(f"\n[migrate_phase2] {mode}")
    print(f"项目根目录: {root}\n")

    stats = run_migration(root, dry_run=args.dry_run)

    print(f"\n统计: copied={stats['copy']}, moved={stats['move']}, "
          f"stubs={stats['stub']}, skipped={stats['skip']}, "
          f"missing={stats['missing']}")

    if not args.dry_run:
        print("\n[migrate_phase2] 迁移完成。")
        print("注意：核心脚本（build_pest.py etc）原位置已替换为 stub 入口。")
        print("请运行 build_pest.py --help 验证 stub 是否工作正常。")
    else:
        print("\n[migrate_phase2] DRY-RUN 完成。移除 --dry-run 以实际执行迁移。")


if __name__ == "__main__":
    main()
