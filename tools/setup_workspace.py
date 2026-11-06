"""setup_workspace.py — 阶段 0：初始化目标目录结构 + 生成迁移清单。

职责（重构规划 §11 阶段 0）：
1. 创建目标目录骨架（幂等，已存在则跳过）
2. 输出迁移建议清单（哪些文件建议移到哪个目录）
3. 生成空的参数注册表骨架文件

用法：
    python setup_workspace.py              # 创建目录 + 输出清单
    python setup_workspace.py --dry-run    # 仅输出清单，不创建任何文件/目录
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timezone


# ── 目标目录骨架 ───────────────────────────────────────────────
TARGET_DIRS = [
    "configs",
    "configs/crops",
    "configs/crops/tomato",
    "configs/crops/eggplant",
    "configs/runs",
    "configs/parallel",
    "data",
    "data/raw",
    "data/raw/weather",
    "data/raw/soil",
    "data/raw/experiments",
    "data/raw/observations",
    "data/templates",
    "data/templates/genotype",
    "data/templates/soil",
    "data/templates/batch",
    "data/parameter_registry",
    "data/parameter_registry/baseline",
    "data/parameter_registry/bounds_proposals",
    "data/parameter_registry/bounds_proposals/tomato",
    "data/parameter_registry/bounds_proposals/eggplant",
    "data/parameter_registry/bounds_frozen",
    "data/parameter_registry/bounds_frozen/tomato",
    "data/parameter_registry/bounds_frozen/eggplant",
    "src",
    "src/common",
    "src/dssat",
    "src/sensitivity",
    "src/calibration",
    "src/reporting",
    "tests",
    "workspace",
    "workspace/runs",
    "workspace/artifacts",
    "workspace/releases",
    "workspace/trash",
    "tools",
    "docs",
]


# ── 迁移建议清单 ──────────────────────────────────────────────
# (现有相对路径, 建议目标目录, 说明)
MIGRATION_SUGGESTIONS: list[tuple[str, str, str]] = [
    # ── 文档 ──
    ("README.md",                                  "docs/",                         "主文档保留根目录，同时在 docs/ 放副本或链接"),
    ("DEVELOPER_GUIDE.md",                         "docs/",                         "开发指南"),
    ("CHANGELOG.md",                               "docs/",                         "变更日志"),
    ("CLUSTERING_DESIGN.md",                       "docs/",                         "设计文档"),
    ("VISUALIZATION_DESIGN.md",                    "docs/",                         "设计文档"),
    ("Project_Design_DSSAT_PEST_Calibration.md",   "docs/",                         "设计文档"),
    ("DSSAT番茄模型参数率定方案.md",               "docs/",                         "率定方案文档"),
    ("compare_v16_century_vs_v15_onlyTN5_TN9_TN13.md", "docs/",                    "版本对比文档"),
    ("pestpp_users_manual.md",                     "docs/",                         "PEST++ 用户手册"),
    ("项目重构规划.md",                            "docs/",                         "重构规划（根目录保留主文件）"),

    # ── DSSAT 可执行文件 ──
    ("DSSAT48.exe",                                "（保留根目录或 tools/）",        "DSSAT 主程序（不随代码迁移）"),

    # ── 气象文件 ──
    ("Workspace/UFBR9401.WTH",                    "data/raw/weather/",             "气象数据"),
    ("Workspace/UFGA0601.WTH",                    "data/raw/weather/",             "气象数据"),
    ("Workspace/UFGA0701.WTH",                    "data/raw/weather/",             "气象数据"),

    # ── 土壤文件 ──
    ("Workspace/SOIL.SOL",                         "data/raw/soil/",               "土壤数据"),

    # ── 实验文件 ──
    ("Workspace/UFBR9401.TMX",                     "data/raw/experiments/",         "实验描述文件"),
    ("Workspace/UFBR9401.TMT",                     "data/raw/experiments/",         "时间序列观测"),
    ("Workspace/UFBR9401.TMA",                     "data/raw/experiments/",         "管理信息"),
    ("Workspace/UFGA0602.TMX",                     "data/raw/experiments/",         "实验描述文件"),
    ("Workspace/UFGA0602.TMT",                     "data/raw/experiments/",         "时间序列观测"),
    ("Workspace/UFGA0602.TMA",                     "data/raw/experiments/",         "管理信息"),
    ("Workspace/UFGA0701.TMX",                     "data/raw/experiments/",         "实验描述文件"),
    ("Workspace/UFGA0701.TMT",                     "data/raw/experiments/",         "时间序列观测"),
    ("Workspace/UFGA0701.TMA",                     "data/raw/experiments/",         "管理信息"),
    ("Workspace/XXQL2501.TMX",                     "data/raw/experiments/",         "实验描述文件"),
    ("Workspace/XXQL2501.TMT",                     "data/raw/experiments/",         "时间序列观测"),
    ("Workspace/XXQL2501.TMA",                     "data/raw/experiments/",         "管理信息"),

    # ── 模板文件 ──
    ("Workspace/TMGRO048.CUL.base",                "data/templates/genotype/",      "品种参数基线模板"),
    ("Workspace/TMGRO048.ECO.base",                "data/templates/genotype/",      "生态型参数基线模板"),
    ("Workspace/TMGRO048.SPE.base",                "data/templates/genotype/",      "物种参数基线模板"),

    # ── 批处理模板 ──
    ("Workspace/DSSBatch.v48",                     "data/templates/batch/",         "批处理模板"),
    ("Workspace/DSSBatch_excl_TN5_TN9_TN13.v48",  "data/templates/batch/",         "批处理模板（排除 TN5/9/13）"),
    ("Workspace/DSSBatch_only_TN5_TN9_TN13.v48",  "data/templates/batch/",         "批处理模板（仅 TN5/9/13）"),

    # ── DSSAT 运行时配置 ──
    ("Workspace/DSSATPRO.v48",                     "data/templates/",               "DSSAT 路径配置"),
    ("Workspace/DSSAT48.INH",                      "data/templates/",               "DSSAT 初始化文件"),
    ("Workspace/DSSAT48.INP",                      "data/templates/",               "DSSAT 输入配置"),
    ("Workspace/DSCSM048.EXE",                     "（保留 Workspace/ 或 tools/）", "DSSAT 模型可执行文件"),

    # ── 核心 Python 脚本（阶段 2 迁移） ──
    ("Workspace/build_pest.py",                    "src/calibration/",              "阶段 2 拆分并迁移"),
    ("Workspace/run_dssat.py",                     "src/dssat/",                    "阶段 2 拆分并迁移"),
    ("Workspace/analyze_results.py",               "src/reporting/",               "阶段 2 迁移"),
    ("Workspace/plot_results.py",                  "src/reporting/",               "阶段 2 迁移"),
    ("Workspace/clean_workspace.py",               "tools/",                        "工具脚本"),
    ("Workspace/cluster_parameters.py",            "tools/",                        "工具脚本"),
    ("Workspace/download_pestpp.py",               "tools/",                        "工具脚本"),
    ("Workspace/param_sweep.py",                   "tools/",                        "工具脚本"),

    # ── 敏感性分析代码（阶段 2 迁移） ──
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_generate_param_review_csv.py",
                                                   "src/common/（提取边界逻辑后）", "阶段 1 优先提取 param_registry"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_build_sen_case.py",
                                                   "src/sensitivity/",              "阶段 2 迁移"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_model.py",
                                                   "src/sensitivity/",              "阶段 2 迁移"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_run_sen.py",
                                                   "src/sensitivity/",              "阶段 2 迁移"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_postprocess_morris.py",
                                                   "src/sensitivity/",              "阶段 2 迁移"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_postprocess_sobol.py",
                                                   "src/sensitivity/",              "阶段 2 迁移"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_select_topk_from_morris.py",
                                                   "src/sensitivity/",              "阶段 2 迁移"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Code/sa_prepare_sobol_topk_case.py",
                                                   "src/sensitivity/",              "阶段 2 迁移"),

    # ── 并行工具（已在 tools/） ──
    ("tools/parallel/prepare_agents.py",           "tools/parallel/（保留）",       "阶段 3 增强"),
    ("tools/parallel/run_parallel.py",             "tools/parallel/（保留）",       "阶段 3 增强"),

    # ── 运行时中间文件（不迁移，按需清理） ──
    ("Workspace/TMGRO048.CUL",                     "（运行时生成，不迁移）",        "由 run_dssat.py 动态生成"),
    ("Workspace/TMGRO048.ECO",                     "（运行时生成，不迁移）",        "由 run_dssat.py 动态生成"),
    ("Workspace/TMGRO048.SPE",                     "（运行时生成，不迁移）",        "由 run_dssat.py 动态生成"),
    ("Workspace/Evaluate.OUT.ins",                 "（运行时生成，不迁移）",        "由 build_pest.py 生成"),
    ("Workspace/pest_params.csv.tpl",              "（运行时生成，不迁移）",        "由 build_pest.py 生成"),
    ("Workspace/baseline_params.csv",              "data/parameter_registry/baseline/", "率定基线参数"),
    ("Workspace/best_parameters.csv",              "workspace/artifacts/",          "最优参数结果"),
    ("best_parameters.csv",                        "workspace/artifacts/",          "最优参数结果（根目录副本）"),

    # ── 权重文件 ──
    ("Workspace/tomato_cal.weights.csv",           "configs/runs/",                 "权重配置"),

    # ── 已有结果目录 ──
    ("Workspace/Calibration_Results/",             "workspace/artifacts/（归档）",   "历史率定结果"),
    ("Workspace/Visualization_Results/",           "workspace/artifacts/（归档）",   "历史可视化结果"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Output/",
                                                   "workspace/artifacts/（归档）",   "历史 SA 输出"),
    ("Workspace/Sensitivity_Analyze/SA_Project_Docs/",
                                                   "docs/sensitivity/",             "SA 文档"),
]


# ── 参数注册表骨架 ─────────────────────────────────────────────
REGISTRY_HEADER = [
    "parameter_name",
    "crop",
    "parameter_family",    # CUL / ECO / SPE / SOIL / INIT / MANAGEMENT
    "target_file",
    "section",
    "dtype",
    "format_width",
    "format_precision",
    "base_value",
    "physical_lower",
    "physical_upper",
    "default_step",
    "calibration_stage",
    "enabled_by_default",
    "description",
]


def _project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def create_dirs(root: str, *, dry_run: bool = False) -> list[str]:
    """创建目标目录骨架，返回已创建（或将创建）的目录列表。"""
    created = []
    for d in TARGET_DIRS:
        full = os.path.join(root, d)
        exists = os.path.isdir(full)
        if not exists:
            if not dry_run:
                os.makedirs(full, exist_ok=True)
            created.append(d)
    return created


def print_migration_plan(root: str) -> None:
    """输出迁移建议清单。"""
    print()
    print("=" * 80)
    print("  迁移建议清单")
    print("=" * 80)
    print(f"{'现有路径':<65} {'建议目标':<35} {'说明'}")
    print("-" * 140)
    for src, dst, note in MIGRATION_SUGGESTIONS:
        src_full = os.path.join(root, src.replace("/", os.sep))
        exists = os.path.exists(src_full)
        marker = "  " if exists else "✗ "
        print(f"{marker}{src:<63} {dst:<35} {note}")
    print("-" * 140)
    print("  说明：✗ 表示源文件/目录不存在（可能已经清理或尚未生成）")
    print()


def create_registry_skeleton(root: str, *, dry_run: bool = False) -> str:
    """在 data/parameter_registry/baseline/ 下生成空的注册表骨架 CSV。"""
    out_path = os.path.join(root, "data", "parameter_registry", "baseline",
                            "parameter_registry_skeleton.csv")
    if dry_run:
        return out_path
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if not os.path.exists(out_path):
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(REGISTRY_HEADER)
    return out_path


def create_init_files(root: str, *, dry_run: bool = False) -> list[str]:
    """在 src/ 各子目录下创建 __init__.py，使其成为 Python 包。"""
    src_dirs = [
        "src",
        "src/common",
        "src/dssat",
        "src/sensitivity",
        "src/calibration",
        "src/reporting",
    ]
    created = []
    for d in src_dirs:
        init_path = os.path.join(root, d, "__init__.py")
        if not os.path.exists(init_path):
            if not dry_run:
                os.makedirs(os.path.dirname(init_path), exist_ok=True)
                with open(init_path, "w", encoding="utf-8") as f:
                    f.write("")
            created.append(init_path)
    return created


def main():
    parser = argparse.ArgumentParser(
        description="阶段 0：初始化目标目录结构并生成迁移清单"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅输出迁移清单，不创建任何文件或目录",
    )
    args = parser.parse_args()

    root = _project_root()
    dry_run = args.dry_run

    mode_label = "DRY-RUN（仅预览）" if dry_run else "执行模式"
    print(f"\n[setup_workspace] {mode_label}")
    print(f"项目根目录: {root}")
    print(f"时间: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print()

    # 1. 创建目录
    created = create_dirs(root, dry_run=dry_run)
    if created:
        print(f"{'将创建' if dry_run else '已创建'} {len(created)} 个新目录：")
        for d in created:
            print(f"  + {d}/")
    else:
        print("所有目标目录已存在，无需创建。")

    # 2. 创建 __init__.py
    init_files = create_init_files(root, dry_run=dry_run)
    if init_files:
        print(f"\n{'将创建' if dry_run else '已创建'} {len(init_files)} 个 __init__.py：")
        for p in init_files:
            print(f"  + {os.path.relpath(p, root)}")

    # 3. 生成参数注册表骨架
    reg_path = create_registry_skeleton(root, dry_run=dry_run)
    print(f"\n参数注册表骨架：{os.path.relpath(reg_path, root)}")

    # 4. 输出迁移建议清单
    print_migration_plan(root)

    if not dry_run:
        print("[setup_workspace] 目录结构初始化完成。")
        print("下一步：按迁移清单逐步移动文件（阶段 2），或先执行阶段 1（边界治理）。")
    else:
        print("[setup_workspace] DRY-RUN 完成。以上为预览，未做任何修改。")
        print("移除 --dry-run 参数后再次运行以实际创建目录。")


if __name__ == "__main__":
    main()
