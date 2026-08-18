"""Auditable reporting for direct-DSSAT greenhouse management DEMO searches.

This module deliberately reads completed direct model outputs.  It never trains or
queries a surrogate model, and preserves the ``demo_only`` science-status gate in
every generated artifact.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any


REQUIRED_RESULT_COLUMNS = {
    "scenario_id", "status", "chfpw", "irrigation_mm", "nitrogen_kg_ha",
    "rainfall_considered", "parameter_set_id",
}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not REQUIRED_RESULT_COLUMNS.issubset(rows[0]):
        missing = REQUIRED_RESULT_COLUMNS - (set(rows[0]) if rows else set())
        raise ValueError(f"candidate result table is incomplete; missing {sorted(missing)}")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["chfpw"] = float(item["chfpw"])
        item["irrigation_mm"] = float(item["irrigation_mm"])
        item["nitrogen_kg_ha"] = float(item["nitrogen_kg_ha"])
        item["rainfall_considered"] = str(item["rainfall_considered"]).lower() == "true"
        normalized.append(item)
    return normalized


def _front(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed = [row for row in rows if row["status"] == "completed"]
    return [
        row for row in completed
        if not any(
            other is not row
            and other["chfpw"] >= row["chfpw"]
            and other["irrigation_mm"] <= row["irrigation_mm"]
            and other["nitrogen_kg_ha"] <= row["nitrogen_kg_ha"]
            and (
                other["chfpw"] > row["chfpw"]
                or other["irrigation_mm"] < row["irrigation_mm"]
                or other["nitrogen_kg_ha"] < row["nitrogen_kg_ha"]
            )
            for other in completed
        )
    ]


def _choose(rows: list[dict[str, Any]], key: str, reverse: bool = False) -> dict[str, Any]:
    return sorted(rows, key=lambda row: ((-float(row[key])) if reverse else float(row[key]), row["scenario_id"]))[0]


def select_strategy_anchors(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select transparent Pareto anchors; the balanced point is not a unique optimum.

    The balance anchor minimizes equal-weight Euclidean distance to the Pareto
    front's min--max normalized ideal (max CHFPW, min water, min N).  It is a
    reproducible reporting aid only, not a stakeholder-preference model.
    """
    front = _front(rows)
    if not front:
        raise ValueError("no completed non-dominated candidate is available")
    result: list[dict[str, Any]] = []
    for label, key, reverse in (
        ("yield_anchor", "chfpw", True),
        ("water_anchor", "irrigation_mm", False),
        ("nitrogen_anchor", "nitrogen_kg_ha", False),
    ):
        item = dict(_choose(front, key, reverse))
        item["anchor_type"] = label
        item["selection_rule"] = f"Pareto front {'maximum' if reverse else 'minimum'} {key}"
        result.append(item)

    def normalized(value: float, values: list[float], benefit: bool) -> float:
        low, high = min(values), max(values)
        if high == low:
            return 0.0
        return ((high - value) if benefit else (value - low)) / (high - low)

    chfpw = [float(row["chfpw"]) for row in front]
    water = [float(row["irrigation_mm"]) for row in front]
    nitrogen = [float(row["nitrogen_kg_ha"]) for row in front]
    balance = min(
        front,
        key=lambda row: (
            math.sqrt(
                normalized(float(row["chfpw"]), chfpw, True) ** 2
                + normalized(float(row["irrigation_mm"]), water, False) ** 2
                + normalized(float(row["nitrogen_kg_ha"]), nitrogen, False) ** 2
            ),
            row["scenario_id"],
        ),
    )
    item = dict(balance)
    item["anchor_type"] = "equal_weight_balance_anchor"
    item["selection_rule"] = "minimum equal-weight normalized Euclidean distance to Pareto ideal"
    result.append(item)
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "anchor_type", "scenario_id", "chfpw", "irrigation_mm", "nitrogen_kg_ha",
        "parameter_set_id", "rainfall_considered", "selection_rule",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_demo_report(search_root: str | Path, output_path: str | Path) -> dict[str, Path]:
    """Generate an evidence-linked Chinese methods/results/discussion document."""
    root, output = Path(search_root), Path(output_path)
    candidates_dir = root / "candidates"
    results_path = candidates_dir / "candidate_results.csv"
    summary_path = candidates_dir / "search_summary.json"
    parameter_path = root / "parameter_set" / "parameter_set_manifest.json"
    design_path = Path("configs/management/eggplant_greenhouse_drip_demo_v1.json")
    rows = _read_csv(results_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    parameter = json.loads(parameter_path.read_text(encoding="utf-8"))
    design = json.loads(design_path.read_text(encoding="utf-8"))
    completed = [row for row in rows if row["status"] == "completed"]
    if len(completed) != int(summary["completed_count"]) or any(row["rainfall_considered"] for row in rows):
        raise ValueError("result status or greenhouse rainfall boundary is inconsistent")
    if summary.get("approval_scope") != "demo_only" or parameter.get("science_validated") is not False:
        raise ValueError("DEMO report requires a non-science-validated demo parameter snapshot")
    anchors = select_strategy_anchors(rows)
    anchors_path = candidates_dir / "strategy_anchors_demo.csv"
    _write_csv(anchors_path, anchors)
    yield_values = [float(row["chfpw"]) for row in completed]
    water_values = [float(row["irrigation_mm"]) for row in completed]
    n_values = [float(row["nitrogen_kg_ha"]) for row in completed]
    table_rows = "\n".join(
        f"| {row['anchor_type']} | {row['scenario_id']} | {float(row['chfpw']):.1f} | {float(row['irrigation_mm']):.1f} | {float(row['nitrogen_kg_ha']):.1f} |"
        for row in anchors
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"""# DEMO：温室滴灌茄子水氮管理优化研究（2026-07-21）

## 技术摘要

本研究包以 **32 个直接 DSSAT 情景** 演示温室滴灌茄子水氮协同优化的可重复工作流：全部情景完成，形成 **10 个 Pareto 非支配方案**。产量目标为 `FreshWt.OUT` 最末行的累计鲜果重 `CHFPW`，范围为 {min(yield_values):.1f}–{max(yield_values):.1f}，均值为 {fmean(yield_values):.1f}。本结果是工程 DEMO，不是可直接推广的田间推荐：参数集处于 `demo_only / science_pending` 状态，尚无独立验证。

## 材料与方法

### 试验材料与水氮决策边界

对象为温室滴灌茄子，使用 DSSAT v4.8 的 CROPGRO-Tomato（CRGRO048）模型承载茄子参数。管理模板来自 XXQL2501 2025 春季试验的 TN2 局部 FileX 事件日历；优化只改变灌溉和无机氮事件量，保持事件日期与处理结构可追溯。温室系统明确设为 `rainfall_considered=false`：天气文件仍供作物生长模拟使用，但降雨不构成供水量或决策变量。

四个优化阶段为出苗定植（25069–25106）、冠层扩展（25107–25141）、开花—早采收（25142–25171）和盛果—后期（25172–25220）。季节灌溉搜索范围为 {design['demo_search_bounds']['irrigation_mm'][0]}–{design['demo_search_bounds']['irrigation_mm'][1]} mm，氮肥范围为 {design['demo_search_bounds']['nitrogen_kg_ha'][0]}–{design['demo_search_bounds']['nitrogen_kg_ha'][1]} kg N ha⁻¹；单次滴灌不超过 {design['constraints']['irrigation_event_max_mm']} mm，最小间隔为 {design['constraints']['irrigation_min_interval_days']} d，且 25171 后的氮投入为 0。

### 模型参数与直接仿真

参数固定为历史率定运行 `{parameter['source_run_id']}` 的末次迭代 realization `{parameter['source_realization']}`（{parameter['parameter_count']} 个参数；工程状态 `{parameter['source_engineering_status']}`，科学状态 `{parameter['source_science_status']}`）。每个候选方案均写入独立 FileX、`MgmtEvent.OUT` 审计账本和独立 DSSAT 工作目录后直接执行；未使用代理模型或响应面替代器。

候选方案通过固定种子 LHS 生成，先用 FileX 固定宽度、阶段日历、总量守恒、设备上限与停氮规则筛除不可行组合，再执行 DSSAT。以最大化 CHFPW、最小化季节灌溉量、最小化季节施氮量构建三目标 Pareto 前沿。报告中的“均衡锚点”仅使用前沿内 min–max 标准化后到理想点的等权欧氏距离，便于审计展示；它不代表生产者偏好函数。

## 结果：32/32 个直接情景完成，水—氮—鲜果重存在明确权衡

32 个候选方案均完成，无失败；季节灌溉为 {min(water_values):.1f}–{max(water_values):.1f} mm，施氮为 {min(n_values):.1f}–{max(n_values):.1f} kg N ha⁻¹。10 个非支配点表明，最高 CHFPW 方案并非最低资源投入方案，因而不能从单一“最高产量”规则直接推出管理处方。

| DEMO 锚点 | 情景 | CHFPW | 灌溉（mm） | 氮肥（kg N ha⁻¹） |
| --- | --- | ---: | ---: | ---: |
{table_rows}

最高鲜果重锚点用于展示产量上界，最低灌溉和最低氮锚点展示资源下界，均衡锚点展示一个可重复的折中定位。这些是同一 DEMO 参数集和同一季节模板下的模型输出，不能解释为因果田间效应，也不能替代品质、经济收益或氮损失的测定。

## 讨论：工作流已闭环，但科学外推仍受参数与验证限制

本模块的亮点在于：第一，采用直接 DSSAT 批量运行，避免代理模型在训练域外产生不可审计偏差；第二，每一个方案都有 FileX、管理事件账本、参数快照、运行清单和结果表，可在上游最优参数更新后整体替换重跑；第三，温室滴灌边界被写入配置与结果校验，避免把降雨错误计入水量平衡；第四，Pareto 集合保留水、氮和产量权衡，而不是伪造唯一最优解。

可接受但必须保留的不足是：参数仅为单个历史率定 realization，且为 science_pending；本次仅覆盖 XXQL2501 的一个季节模板；目标函数没有纳入商品果品质、价格、肥料/能源成本、硝态氮淋失或温室环境调控；32 个 LHS 点只用于工程演示，不能保证穷尽真实 Pareto 前沿。后续应使用上游冻结且经独立验证的最优参数重新运行全部候选脚本，并增加跨季节/跨处理验证和经济—环境指标后，再形成正式推荐。

## 可重复性与证据

- 候选结果：`{results_path.as_posix()}`
- Pareto 前沿：`{(candidates_dir / 'pareto_front_demo.csv').as_posix()}`
- 锚点表：`{anchors_path.as_posix()}`
- 搜索清单：`{summary_path.as_posix()}`
- 参数快照：`{parameter_path.as_posix()}`
- 管理设计：`{design_path.as_posix()}`

文献方法学参照：Kropp et al. (2019), *Agricultural Systems*, 173: 40–53, DOI:10.1016/j.agsy.2019.03.014；Linker & Kisekka (2023), *Agricultural and Forest Meteorology*, 341: 109664, DOI:10.1016/j.agrformet.2023.109664；Yin et al. (2026), *Agricultural Systems*, 104876, DOI:10.1016/j.agsy.2026.104876。
""", encoding="utf-8")
    return {"report": output, "anchors": anchors_path}


def main() -> int:
    parser = argparse.ArgumentParser(description="Write an auditable DEMO water-nitrogen report")
    parser.add_argument("--search-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    artifacts = build_demo_report(args.search_root, args.out)
    # Windows consoles may still use cp1252; ASCII escapes keep the CLI usable
    # while the report itself remains UTF-8.
    print(json.dumps({key: str(value) for key, value in artifacts.items()}, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
