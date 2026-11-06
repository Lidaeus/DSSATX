"""Create the canonical portable-report artifact for the 2026-08-29 run."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RUN_REL = "workspace/runs/e02_formal_yield_rebalanced_post_official_200x6_20260829"
RUN = ROOT / RUN_REL
SUMMARY = RUN / "result_summary_20260829"
REPORT = ROOT / "workspace/reports/e02_formal_yield_rebalanced_post_20260829"


def records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.where(pd.notna(frame), None).to_json(orient="records"))


def markdown_table(frame: pd.DataFrame) -> str:
    display = frame.copy()
    for column in display.select_dtypes(include="number").columns:
        display[column] = display[column].map(lambda value: f"{value:.3f}" if pd.notna(value) else "")
    headers = [str(column) for column in display.columns]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in display.itertuples(index=False, name=None))
    return "\n".join(lines)


def main() -> int:
    REPORT.mkdir(parents=True, exist_ok=True)
    result = json.loads((SUMMARY / "result_summary.json").read_text(encoding="utf-8"))
    conv_raw = pd.read_csv(SUMMARY / "phi_convergence_summary.csv")
    phi_sql = """SELECT iteration, '最低 Phi' AS series, minimum AS phi
FROM phi_convergence_summary
UNION ALL
SELECT iteration, '中位 Phi' AS series, median AS phi
FROM phi_convergence_summary
ORDER BY iteration, series"""
    with sqlite3.connect(":memory:") as connection:
        conv_raw.to_sql("phi_convergence_summary", connection, index=False)
        conv_long = pd.read_sql_query(phi_sql, connection)
    conv = conv_raw.rename(
        columns={"minimum": "phi_min", "median": "phi_median", "mean": "phi_mean"}
    )[["iteration", "phi_min", "phi_median", "phi_mean"]]
    metrics = pd.read_csv(SUMMARY / "metrics_by_season_role_variable.csv")
    metrics = metrics.loc[
        metrics["role"].eq("all22")
        & metrics["variable"].isin(["LAID", "LWAD", "SWAD", "DRY_CUM", "FRESH_CUM"]),
        ["season", "variable", "n", "rrmse_pct", "bias", "nse", "d_index", "r2"],
    ].copy()
    terminal = pd.read_csv(SUMMARY / "terminal_comparison_to_previous_member103.csv")
    terminal = terminal.loc[
        terminal["role"].eq("calibration") & terminal["variable"].eq("TERMINAL_DRY_CUM"),
        ["season", "rrmse_pct_current", "rrmse_pct_baseline103", "bias_current", "bias_baseline103"],
    ].copy()
    terminal_long = terminal.melt(
        id_vars="season", value_vars=["rrmse_pct_current", "rrmse_pct_baseline103"],
        var_name="candidate", value_name="rrmse_pct",
    )
    terminal_long["candidate"] = terminal_long["candidate"].map(
        {"rrmse_pct_current": "本轮成员153", "rrmse_pct_baseline103": "上一轮成员103"}
    )
    response = pd.read_csv(SUMMARY / "water_nitrogen_response_metrics.csv")[[
        "season", "contrast", "stratum", "n", "rrmse_pct", "bias", "nse", "d_index", "r2"
    ]]
    boundary = pd.read_csv(SUMMARY / "best_member_and_ensemble_boundary_pressure.csv")
    boundary = boundary.loc[
        boundary["best_member_near_boundary_2pct"],
        ["parameter", "value", "lower", "upper", "final_ensemble_near_boundary_fraction_2pct"],
    ].head(20)
    now = datetime.now(timezone.utc).isoformat()

    sources = [
        {"id": "src_summary", "label": "Formal calibration result summary",
         "path": f"{RUN_REL}/result_summary_20260829/result_summary.json"},
        {"id": "src_convergence", "label": "PEST-IES Phi convergence",
         "path": f"{RUN_REL}/result_summary_20260829/phi_convergence_summary.csv",
         "query": {"engine": "SQLite", "language": "sql", "sql": phi_sql,
                   "description": "Reshape iteration-level minimum and median Phi into long form for the convergence chart.",
                   "tables_used": ["phi_convergence_summary"],
                   "filters": ["iterations 0 through 6"],
                   "metric_definitions": ["minimum = minimum realization-level actual Phi per iteration; median = median realization-level actual Phi per iteration"]}},
        {"id": "src_metrics", "label": "Official DSSAT 22-treatment deterministic metrics",
         "path": f"{RUN_REL}/result_summary_20260829/metrics_by_season_role_variable.csv"},
        {"id": "src_terminal", "label": "Terminal-yield comparison with prior member 103",
         "path": f"{RUN_REL}/result_summary_20260829/terminal_comparison_to_previous_member103.csv"},
        {"id": "src_response", "label": "Water and nitrogen response metrics",
         "path": f"{RUN_REL}/result_summary_20260829/water_nitrogen_response_metrics.csv"},
        {"id": "src_boundary", "label": "Selected-member and posterior boundary audit",
         "path": f"{RUN_REL}/result_summary_20260829/best_member_and_ensemble_boundary_pressure.csv"},
    ]
    artifact = {
        "surface": "report",
        "manifest": {
            "version": 1,
            "surface": "report",
            "title": "2026-08-29 正式率定结果与22处理确定性评价",
            "description": "官方 DSSAT、200 realizations、6轮 PEST-IES 的结果审计。",
            "generatedAt": now,
            "sources": sources,
            "cards": [
                {"id": "card_phi", "dataset": "headline", "sourceId": "src_summary",
                 "metrics": [{"label": "最低实际 Phi", "field": "selected_phi", "format": "number"}]},
                {"id": "card_25rrmse", "dataset": "headline", "sourceId": "src_summary",
                 "metrics": [{"label": "25SP末期干产量RRMSE", "field": "rrmse25", "format": "number"}]},
                {"id": "card_26rrmse", "dataset": "headline", "sourceId": "src_summary",
                 "metrics": [{"label": "26SP末期干产量RRMSE", "field": "rrmse26", "format": "number"}]},
                {"id": "card_gate", "dataset": "headline", "sourceId": "src_summary",
                 "metrics": [{"label": "双季门槛合格候选数", "field": "gate_candidates", "format": "number"}]},
            ],
            "charts": [
                {"id": "chart_phi", "title": "Phi收敛轨迹", "subtitle": "各轮成员最低值与中位数",
                 "type": "line", "dataset": "convergence", "sourceId": "src_convergence",
                 "intent": "trend", "question": "PEST-IES集合与最优成员是否随迭代收敛？",
                 "rationale": "折线图最适合比较两个Phi统计量在七轮迭代中的变化。",
                 "encodings": {
                     "x": {"field": "iteration", "type": "ordinal", "label": "迭代轮次"},
                     "y": {"field": "phi", "type": "quantitative", "label": "实际 Phi", "format": "number"},
                     "color": {"field": "series", "type": "nominal", "label": "统计量"}
                 }, "layout": "full"},
                {"id": "chart_terminal", "title": "校准处理末期干产量RRMSE",
                 "subtitle": "当前成员153与上一轮成员103；虚线门槛为25%",
                 "type": "bar", "dataset": "terminal", "sourceId": "src_terminal",
                 "intent": "comparison", "question": "本轮是否比上一轮更接近25%的末期产量门槛？",
                 "rationale": "分组柱状图清楚比较两季、两候选的RRMSE与固定门槛。",
                 "encodings": {
                     "x": {"field": "season", "type": "nominal", "label": "季节"},
                     "y": {"field": "rrmse_pct", "type": "quantitative", "label": "RRMSE", "format": "number", "unit": "%"},
                     "color": {"field": "candidate", "type": "nominal", "label": "候选"}
                 },
                 "referenceLines": [{"axis": "y", "value": 25, "label": "验收门槛"}],
                 "layout": "full"},
            ],
            "tables": [
                {"id": "table_metrics", "title": "22处理全局拟合指标",
                 "subtitle": "两季全部处理；RRMSE为百分数，Bias保持变量原单位",
                 "dataset": "metrics", "sourceId": "src_metrics", "density": "spacious",
                 "defaultSort": {"field": "season", "direction": "asc"}, "columns": [
                     {"field": "season", "label": "季节", "type": "text"},
                     {"field": "variable", "label": "变量", "type": "text"},
                     {"field": "n", "label": "n", "format": "number"},
                     {"field": "rrmse_pct", "label": "RRMSE (%)", "format": "number"},
                     {"field": "nse", "label": "NSE", "format": "number"},
                     {"field": "d_index", "label": "d-index", "format": "number"},
                     {"field": "r2", "label": "R²", "format": "number"},
                     {"field": "bias", "label": "Bias", "format": "number"},
                 ]},
                {"id": "table_response", "title": "水氮响应结构指标",
                 "subtitle": "按季节、响应对比和水氮层级分别计算",
                 "dataset": "response", "sourceId": "src_response", "density": "dense",
                 "defaultSort": {"field": "season", "direction": "asc"}, "columns": [
                     {"field": "season", "label": "季节", "type": "text"},
                     {"field": "contrast", "label": "响应", "type": "text"},
                     {"field": "stratum", "label": "层级", "type": "text"},
                     {"field": "n", "label": "n", "format": "number"},
                     {"field": "rrmse_pct", "label": "RRMSE (%)", "format": "number"},
                     {"field": "nse", "label": "NSE", "format": "number"},
                     {"field": "bias", "label": "Bias", "format": "number"},
                 ]},
                {"id": "table_boundary", "title": "成员153的2%边界压力参数",
                 "subtitle": "仅列出接近上下界的参数；后验边界比例用于区分个体与群体压力",
                 "dataset": "boundary", "sourceId": "src_boundary", "density": "dense",
                 "defaultSort": {"field": "final_ensemble_near_boundary_fraction_2pct", "direction": "desc"},
                 "columns": [
                     {"field": "parameter", "label": "参数", "type": "text"},
                     {"field": "value", "label": "成员值", "format": "number"},
                     {"field": "lower", "label": "下界", "format": "number"},
                     {"field": "upper", "label": "上界", "format": "number"},
                     {"field": "final_ensemble_near_boundary_fraction_2pct", "label": "后验近界比例", "format": "number"},
                 ]},
            ],
            "blocks": [
                {"id": "title", "type": "markdown", "body": "# 2026-08-29 正式率定结果与22处理确定性评价"},
                {"id": "summary", "type": "markdown", "sourceId": "src_summary", "body":
                 "## 技术摘要\n\nPEST-IES工程运行成功，但科学验收未通过。最低Phi成员为第4轮#153；25SP末期干产量RRMSE降至18.64%，26SP仍为48.59%，且全部迭代中没有任何成员同时满足两季≤25%的硬门槛。因此#153只能作为本批次的诊断最佳成员，不能晋级为正式科学最优参数。"},
                {"id": "headline_strip", "type": "metric-strip", "cardIds": ["card_phi", "card_25rrmse", "card_26rrmse", "card_gate"]},
                {"id": "conv_text", "type": "markdown", "body":
                 "## 优化在第4轮达到最低值\n\n最低Phi由先验的360.48降至352.02，但第5–6轮最低值回升。中位Phi持续下降，说明集合整体收敛；最低成员没有同步满足26SP产量门槛，说明当前权重下的综合最优仍可用冠层和器官状态补偿产量尺度误差。"},
                {"id": "conv_chart", "type": "chart", "chartId": "chart_phi"},
                {"id": "fit_text", "type": "markdown", "sourceId": "src_metrics", "body":
                 "## 冠层与25SP产量改善，但26SP产量仍系统偏低\n\n22处理确定性复跑显示：25SP的LAI、叶重、茎重和累积干产量NSE分别为0.893、0.871、0.854和0.820；26SP对应为0.738、0.490、0.796和0.281。26SP累积干产量虽较上一轮有所改善，但末期高产水平仍显著低估。"},
                {"id": "fit_table", "type": "table", "tableId": "table_metrics"},
                {"id": "terminal_text", "type": "markdown", "sourceId": "src_terminal", "body":
                 "## 产量尺度改善不足以通过硬门槛\n\n与上一轮成员103相比，25SP末期RRMSE改善5.43个百分点，26SP只改善2.51个百分点。26SP平均末期偏差仍为-1783.7 kg ha⁻¹，表明问题主要是尺度性低估，而不是随机离散。"},
                {"id": "terminal_chart", "type": "chart", "chartId": "chart_terminal"},
                {"id": "response_text", "type": "markdown", "sourceId": "src_response", "body":
                 "## 水氮响应形状仍未恢复\n\n多数分层响应NSE仍为负值。尤其26SP的N3−N0与W3−W1响应不能可靠复现实测差异；因此不能将本轮整体NSE改善解释为水氮响应结构已经校准成功。"},
                {"id": "response_table", "type": "table", "tableId": "table_response"},
                {"id": "boundary_text", "type": "markdown", "sourceId": "src_boundary", "body":
                 "## 边界压力仍然广泛\n\n成员153有29个激活参数落在边界2%范围内，最终集合中有46个参数的近界成员比例达到20%以上。WTFSD触及上界0.60，PARMAX触及下界35，而PHTMAX并未触界；这支持优先检查果实分配/同化相关边界与参数可辨识性，而不是继续单独归因于PHTMAX。"},
                {"id": "boundary_table", "type": "table", "tableId": "table_boundary"},
                {"id": "limitations", "type": "markdown", "body":
                 "## 方法与限制\n\nRRMSE按校准处理的季节末期累积干产量计算；NSE用于时间序列或响应形状描述，不用于处理间末期产量验收。全部图表来自官方DSSAT对成员153的确定性复跑，覆盖25SP 10个和26SP 12个处理，未绘制后验不确定性区间。25FA不参与本报告。"},
                {"id": "next", "type": "markdown", "body":
                 "## 建议的下一步\n\n1. 不晋级成员153为科学最优；保留其冠层参数与25SP产量改善作为局部锚点。\n2. 对WTFSD、PARMAX及与后期同化/果实分配直接相关的近界参数做受控剖面，确认能否提高26SP高产处理而不破坏25SP。\n3. 将26SP末期干产量硬门槛转为候选生成阶段的显式筛选/约束策略；仅增加静态权重已证明不足。\n4. 在产量尺度通过后再恢复N/W响应结构优化，避免以更差的总体尺度换取局部对比。"},
            ],
        },
        "snapshot": {
            "version": 1, "generatedAt": now, "status": "ready", "datasets": {
                "headline": [{"selected_phi": result["selected_phi"],
                              "rrmse25": result["25sp_terminal_rrmse_pct"],
                              "rrmse26": result["26sp_terminal_rrmse_pct"],
                              "gate_candidates": result["both_gates_pass_candidates"]}],
                "convergence": records(conv_long), "metrics": records(metrics),
                "terminal": records(terminal_long), "response": records(response),
                "boundary": records(boundary),
            }
        },
        "sources": sources,
    }
    # The portable artifact validator currently requires SQL provenance for
    # native cards/charts/tables.  This report is file-backed, so retain exact
    # file provenance and use sourced markdown tables instead of inventing SQL.
    artifact["manifest"].pop("cards", None)
    artifact["manifest"].pop("charts", None)
    artifact["manifest"].pop("tables", None)
    artifact["manifest"]["charts"] = [{
        "id": "chart_phi", "title": "Phi收敛轨迹", "subtitle": "各轮成员最低值与中位数",
        "type": "line", "dataset": "convergence", "sourceId": "src_convergence",
        "intent": "trend", "question": "PEST-IES集合与最优成员是否随迭代收敛？",
        "rationale": "折线图用于比较最低值与中位值在七轮迭代中的变化。",
        "encodings": {
            "x": {"field": "iteration", "type": "ordinal", "label": "迭代轮次"},
            "y": {"field": "phi", "type": "quantitative", "label": "实际 Phi", "format": "number"},
            "color": {"field": "series", "type": "nominal", "label": "统计量"},
        }, "layout": "full",
    }]
    compact_metrics = metrics.rename(columns={
        "season": "季节", "variable": "变量", "n": "n", "rrmse_pct": "RRMSE(%)",
        "nse": "NSE", "d_index": "d-index", "r2": "R²", "bias": "Bias",
    })
    compact_terminal = terminal.rename(columns={
        "season": "季节", "rrmse_pct_current": "本轮RRMSE(%)",
        "rrmse_pct_baseline103": "上一轮RRMSE(%)", "bias_current": "本轮Bias",
        "bias_baseline103": "上一轮Bias",
    })
    compact_response = response.rename(columns={
        "season": "季节", "contrast": "响应", "stratum": "层级", "n": "n",
        "rrmse_pct": "RRMSE(%)", "nse": "NSE", "bias": "Bias",
    })[["季节", "响应", "层级", "n", "RRMSE(%)", "NSE", "Bias"]]
    compact_boundary = boundary.rename(columns={
        "parameter": "参数", "value": "成员值", "lower": "下界", "upper": "上界",
        "final_ensemble_near_boundary_fraction_2pct": "后验近界比例",
    })
    artifact["manifest"]["blocks"] = [
        {"id": "title", "type": "markdown", "body": "# 2026-08-29 正式率定结果与22处理确定性评价"},
        {"id": "summary", "type": "markdown", "sourceId": "src_summary", "body":
         "## 技术摘要\n\nPEST-IES工程运行成功，但科学验收未通过。最低Phi成员为第4轮#153（Phi=352.015）；25SP末期干产量RRMSE为18.64%，26SP仍为48.59%，全部迭代中没有任何成员同时满足两季≤25%的硬门槛。因此#153只能作为本批次的诊断最佳成员，不能晋级为正式科学最优参数。"},
        {"id": "convergence", "type": "markdown", "sourceId": "src_convergence", "body":
         "## 优化在第4轮达到最低值\n\n最低Phi由先验的360.48降至352.02，但第5–6轮最低值回升；集合中位Phi持续下降至410.21。整体集合收敛并未转化为26SP产量门槛合格，说明综合目标仍允许其他目标族补偿产量尺度误差。\n\n" +
         markdown_table(conv.rename(columns={"iteration": "轮次", "phi_min": "最低Phi", "phi_median": "中位Phi", "phi_mean": "均值Phi"}))},
        {"id": "convergence_chart", "type": "chart", "chartId": "chart_phi"},
        {"id": "fit", "type": "markdown", "sourceId": "src_metrics", "body":
         "## 冠层与25SP产量改善，但26SP产量仍系统偏低\n\n22处理确定性复跑显示：25SP的LAI、叶重、茎重和累积干产量NSE分别为0.893、0.871、0.854和0.820；26SP对应为0.738、0.490、0.796和0.281。26SP累积干产量虽较上一轮改善，但末期高产水平仍明显低估。\n\n" + markdown_table(compact_metrics)},
        {"id": "terminal", "type": "markdown", "sourceId": "src_terminal", "body":
         "## 末期产量改善不足以通过硬门槛\n\n相对成员103，25SP末期RRMSE改善5.43个百分点，26SP只改善2.51个百分点。26SP平均末期Bias仍为-1783.7 kg ha⁻¹，表明主要是尺度性低估。\n\n" + markdown_table(compact_terminal)},
        {"id": "response", "type": "markdown", "sourceId": "src_response", "body":
         "## 水氮响应形状仍未恢复\n\n多数分层响应NSE仍为负值，尤其26SP的N3−N0与W3−W1响应不能可靠复现实测差异；不能将整体NSE改善解释为响应结构已经校准成功。\n\n" + markdown_table(compact_response)},
        {"id": "boundary", "type": "markdown", "sourceId": "src_boundary", "body":
         "## 边界压力仍然广泛\n\n成员153有29个激活参数位于边界2%范围，最终集合有46个参数的近界成员比例达到20%以上。WTFSD触及上界0.60，PARMAX触及下界35，而PHTMAX并未触界；应优先检查果实分配/同化相关边界和参数可辨识性。\n\n" + markdown_table(compact_boundary)},
        {"id": "limitations", "type": "markdown", "body":
         "## 方法与限制\n\nRRMSE按校准处理的季节末期累积干产量计算；NSE用于时间序列或响应形状描述，不用于处理间末期产量验收。全部指标来自官方DSSAT对成员153的确定性复跑，覆盖25SP 10个和26SP 12个处理；默认未绘制后验不确定性区间，25FA不在本报告范围。"},
        {"id": "next", "type": "markdown", "body":
         "## 建议的下一步\n\n1. 不晋级成员153为科学最优；保留其冠层参数与25SP产量改善作为局部锚点。\n2. 对WTFSD、PARMAX及后期同化/果实分配近界参数做受控剖面，确认能否提高26SP高产处理而不破坏25SP。\n3. 把26SP末期干产量门槛转为候选生成阶段的显式筛选/约束；仅提高静态权重已经证明不足。\n4. 产量尺度通过后再恢复N/W响应结构优化，避免以更差的总体尺度换取局部对比。"},
    ]
    (REPORT / "artifact.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(REPORT / "artifact.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
