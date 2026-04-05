"""freeze_bounds.py — 从 bounds_proposal 显式批准生成 bounds_frozen。

用法：
    python tools/freeze_bounds.py \\
        --proposal data/parameter_registry/bounds_proposals/eggplant/proposal_20260405.csv \\
        --crop eggplant \\
        --bounds-id eggplant_v1_20260405 \\
        [--notes "首次冻结，基于 Morris SA 结果"]

输出：
    data/parameter_registry/bounds_frozen/eggplant/eggplant_v1_20260405.csv
    data/parameter_registry/bounds_frozen/eggplant/eggplant_v1_20260405.yaml
"""

import argparse
import csv
import os
import shutil
import sys
from datetime import datetime, timezone

# 允许从项目根目录运行时导入 src
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from src.common.param_registry import clamp_to_physical
except ImportError:
    def clamp_to_physical(name, lower, upper):
        return lower, upper


def _safe_float(val):
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def main():
    parser = argparse.ArgumentParser(
        description="从 bounds_proposal 批准生成 bounds_frozen"
    )
    parser.add_argument("--proposal", required=True,
                        help="候选边界文件路径 (CSV)")
    parser.add_argument("--crop", required=True,
                        help="作物名称 (tomato / eggplant)")
    parser.add_argument("--bounds-id", required=True,
                        help="冻结边界的唯一 ID")
    parser.add_argument("--notes", default="",
                        help="审批备注")
    parser.add_argument("--out-dir", default=None,
                        help="输出目录 (默认: data/parameter_registry/bounds_frozen/{crop}/)")
    parser.add_argument("--operator", default=os.environ.get("USERNAME", "unknown"),
                        help="操作者")
    args = parser.parse_args()

    # ── 读取候选边界 ──
    proposal_path = os.path.abspath(args.proposal)
    if not os.path.exists(proposal_path):
        print(f"ERROR: 候选边界文件不存在: {proposal_path}", file=sys.stderr)
        sys.exit(1)

    with open(proposal_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if not rows:
        print("ERROR: 候选边界文件为空", file=sys.stderr)
        sys.exit(1)

    # ── 物理边界截断检查 ──
    clamped_count = 0
    for row in rows:
        name = row.get("name", row.get("parameter_name", ""))
        lb = _safe_float(row.get("lower", row.get("lower_bound")))
        ub = _safe_float(row.get("upper", row.get("upper_bound")))
        lb2, ub2 = clamp_to_physical(name, lb, ub)
        if lb2 != lb or ub2 != ub:
            clamped_count += 1
            if "lower" in row:
                row["lower"] = str(lb2) if lb2 is not None else ""
            if "lower_bound" in row:
                row["lower_bound"] = str(lb2) if lb2 is not None else ""
            if "upper" in row:
                row["upper"] = str(ub2) if ub2 is not None else ""
            if "upper_bound" in row:
                row["upper_bound"] = str(ub2) if ub2 is not None else ""

    if clamped_count > 0:
        print(f"WARNING: {clamped_count} 个参数的边界被截断到物理硬边界范围内。")

    # ── 确定输出目录 ──
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
    if args.out_dir:
        out_dir = os.path.abspath(args.out_dir)
    else:
        out_dir = os.path.join(root, "data", "parameter_registry",
                               "bounds_frozen", args.crop)
    os.makedirs(out_dir, exist_ok=True)

    # ── 写冻结边界 CSV ──
    frozen_csv_path = os.path.join(out_dir, f"{args.bounds_id}.csv")
    with open(frozen_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # ── 写元数据 YAML ──
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    proposal_basename = os.path.basename(proposal_path)
    yaml_path = os.path.join(out_dir, f"{args.bounds_id}.yaml")
    yaml_content = f"""bounds_id: "{args.bounds_id}"
crop: "{args.crop}"
created_at: "{now_str}"
approved_at: "{now_str}"
approved_by: "{args.operator}"
review_status: "approved"
derived_from: "{proposal_basename}"
parameter_count: {len(rows)}
clamped_count: {clamped_count}
notes: "{args.notes}"
"""
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)

    print(f"✓ 冻结边界已生成：")
    print(f"  CSV:  {frozen_csv_path}")
    print(f"  YAML: {yaml_path}")
    print(f"  参数数: {len(rows)}")
    print(f"  bounds_id: {args.bounds_id}")


if __name__ == "__main__":
    main()
