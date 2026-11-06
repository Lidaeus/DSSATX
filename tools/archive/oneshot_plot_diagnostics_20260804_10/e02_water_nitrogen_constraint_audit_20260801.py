"""Audit water/nitrogen response constraints for two E02 calibration runs.

This script is intentionally read-only with respect to calibration inputs.  It
recomputes posterior boundary pressure, ensemble response contrasts, and a
descriptive Spearman screen, then writes compact handoff tables and figures.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace" / "diagnostics" / "e02_water_nitrogen_constraint_audit_20260801"

RUN_A = ROOT / "workspace" / "runs" / "e02_wnstress_fourcorner_formal_200x5_20260801_080700"
PREFIX_A = "e02_wnstress_fourcorner_formal_200x5_20260801_080700"
RUN_B = ROOT / "workspace" / "runs" / "e02_joint61_25sp25fa_validic_n012_no_nresponse_formal_200x5_20260801"
PREFIX_B = "e02_joint61_25sp25fa_validic_n012_no_nresponse_formal_200x5_20260801"

KEY_PARAMETERS = [
    "dswbar", "xfrmax", "pormin", "rwumx", "rtexf", "rtno3", "rtnh4",
    "nstfac", "nmobmx", "nvsmob", "nrcvr", "lnref", "nslope", "cmobmx",
    "soil_slpf", "trifl", "lfmax", "xfint", "xfrt",
]

LABELS = {
    "dswbar": "DSWBAR", "xfrmax": "XFRMAX", "pormin": "PORMIN",
    "rwumx": "RWUMX", "rtexf": "RTEXF", "rtno3": "RTNO3",
    "rtnh4": "RTNH4", "nstfac": "NSTFAC", "nmobmx": "NMOBMX",
    "nvsmob": "NVSMOB", "nrcvr": "NRCVR", "lnref": "LNREF",
    "nslope": "NSLOPE", "cmobmx": "CMOBMX", "soil_slpf": "SOIL_SLPF",
    "trifl": "TRIFL", "lfmax": "LFMAX", "xfint": "XFINT", "xfrt": "XFRT",
}


def load_run(run_dir: Path, prefix: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    par = pd.read_csv(run_dir / f"{prefix}.5.par.csv")
    obs = pd.read_csv(run_dir / f"{prefix}.5.obs.csv")
    summary = pd.read_csv(run_dir / "posterior_response_analysis" / "posterior_summary.csv")
    par.columns = [str(c).lower() for c in par.columns]
    obs.columns = [str(c).lower() for c in obs.columns]
    summary["name"] = summary["name"].str.lower()
    return par, obs, summary


def posterior_audit(run_label: str, par: pd.DataFrame, summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for name in KEY_PARAMETERS:
        hit = summary.loc[summary["name"] == name]
        if hit.empty or name not in par:
            continue
        s = hit.iloc[0]
        lo, hi = float(s.lower), float(s.upper)
        span = hi - lo
        vals = pd.to_numeric(par[name], errors="coerce").dropna()
        near_lo = float((vals <= lo + 0.02 * span).mean() * 100.0)
        near_hi = float((vals >= hi - 0.02 * span).mean() * 100.0)
        rows.append(
            {
                "run": run_label,
                "parameter": LABELS[name],
                "parameter_key": name,
                "lower": lo,
                "upper": hi,
                "median": float(s["median"]),
                "p05": float(s.p05),
                "p95": float(s.p95),
                "q90_width_pct": float((float(s.p95) - float(s.p05)) / span * 100.0),
                "near_lower_2pct": near_lo,
                "near_upper_2pct": near_hi,
                "boundary_pressure_pct": max(near_lo, near_hi),
                "pressure_side": "lower" if near_lo >= near_hi else "upper",
            }
        )
    return pd.DataFrame(rows)


def original_scale(obs: pd.DataFrame, col: str) -> pd.Series:
    # The cumulative-harvest observation ensemble is stored as log1p(CHPDT).
    return np.expm1(pd.to_numeric(obs[col], errors="coerce"))


def ensemble_response_a(obs: pd.DataFrame) -> pd.DataFrame:
    v = {c: original_scale(obs, c) for c in [
        "25sp_chpdts_r1_h11", "25sp_chpdts_r2_h11", "25sp_chpdts_r3_h11", "25sp_chpdts_r4_h11",
        "26sp_chpdts_r5_h5", "26sp_chpdts_r6_h5", "26sp_chpdts_r7_h5", "26sp_chpdts_r8_h5",
    ]}
    return pd.DataFrame({
        "nitrogen_effect": (
            (v["25sp_chpdts_r1_h11"] - v["25sp_chpdts_r2_h11"])
            + (v["25sp_chpdts_r3_h11"] - v["25sp_chpdts_r4_h11"])
            + (v["26sp_chpdts_r5_h5"] - v["26sp_chpdts_r7_h5"])
            + (v["26sp_chpdts_r6_h5"] - v["26sp_chpdts_r8_h5"])
        ) / 4.0,
        "water_effect": (
            (v["25sp_chpdts_r2_h11"] - v["25sp_chpdts_r4_h11"])
            + (v["25sp_chpdts_r1_h11"] - v["25sp_chpdts_r3_h11"])
            + (v["26sp_chpdts_r7_h5"] - v["26sp_chpdts_r8_h5"])
            + (v["26sp_chpdts_r5_h5"] - v["26sp_chpdts_r6_h5"])
        ) / 4.0,
    })


def ensemble_response_b(obs: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "25sp_chpdts_r1_h11", "25sp_chpdts_r2_h11", "25sp_chpdts_r3_h11",
        "25sp_chpdts_r5_h11", "25sp_chpdts_r6_h11", "25sp_chpdts_r7_h11",
        "25fa_chpdts_r9_h3", "25fa_chpdts_r11_h3", "25fa_chpdts_r12_h3",
        "25fa_chpdts_r14_h3", "25fa_chpdts_r15_h3", "25fa_chpdts_r17_h3",
    ]
    v = {c: original_scale(obs, c) for c in cols}
    n01 = (
        (v["25sp_chpdts_r2_h11"] - v["25sp_chpdts_r3_h11"])
        + (v["25sp_chpdts_r6_h11"] - v["25sp_chpdts_r7_h11"])
        + (v["25fa_chpdts_r15_h3"] - v["25fa_chpdts_r17_h3"])
        + (v["25fa_chpdts_r12_h3"] - v["25fa_chpdts_r14_h3"])
    ) / 4.0
    n12 = (
        (v["25sp_chpdts_r1_h11"] - v["25sp_chpdts_r2_h11"])
        + (v["25sp_chpdts_r5_h11"] - v["25sp_chpdts_r6_h11"])
        + (v["25fa_chpdts_r11_h3"] - v["25fa_chpdts_r15_h3"])
        + (v["25fa_chpdts_r9_h3"] - v["25fa_chpdts_r12_h3"])
    ) / 4.0
    water = (
        (v["25sp_chpdts_r3_h11"] - v["25sp_chpdts_r7_h11"])
        + (v["25sp_chpdts_r2_h11"] - v["25sp_chpdts_r6_h11"])
        + (v["25sp_chpdts_r1_h11"] - v["25sp_chpdts_r5_h11"])
        + (v["25fa_chpdts_r17_h3"] - v["25fa_chpdts_r14_h3"])
        + (v["25fa_chpdts_r15_h3"] - v["25fa_chpdts_r12_h3"])
        + (v["25fa_chpdts_r11_h3"] - v["25fa_chpdts_r9_h3"])
    ) / 6.0
    return pd.DataFrame({"n01_effect": n01, "n12_effect": n12, "nitrogen_cliff": n01 - n12, "water_effect": water})


def summarize_response(run: str, response: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in response:
        x = response[metric].dropna()
        rows.append({
            "run": run, "metric": metric, "mean": x.mean(), "median": x.median(),
            "p05": x.quantile(0.05), "p95": x.quantile(0.95), "n": len(x),
        })
    return pd.DataFrame(rows)


def spearman_screen(run: str, par: pd.DataFrame, response: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in response:
        for name in KEY_PARAMETERS:
            if name not in par:
                continue
            aligned = pd.concat([par[name], response[metric]], axis=1).dropna()
            rho = aligned.iloc[:, 0].rank().corr(aligned.iloc[:, 1].rank())
            rows.append({
                "run": run, "response_metric": metric, "parameter": LABELS[name],
                "parameter_key": name, "spearman_rho": rho, "abs_rho": abs(rho),
                "n": len(aligned),
            })
    return pd.DataFrame(rows).sort_values(["run", "response_metric", "abs_rho"], ascending=[True, True, False])


def best_member_contrasts(run_dir: Path, run_label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = pd.read_csv(run_dir / "posterior_response_analysis" / "best_member_four_corner_chpdt.csv")
    data = data.dropna(subset=["water_level", "nitrogen_level"]).copy()
    data["n"] = data["nitrogen_level"].str.extract(r"(\d+)").astype(int)
    n_rows = []
    w_rows = []
    for (season, water), g in data.groupby(["season_id", "water_level"]):
        z = g.set_index("n")
        for n0, n1 in zip(sorted(z.index)[:-1], sorted(z.index)[1:]):
            if n1 != n0 + 1:
                continue
            for series in ["observed", "simulated"]:
                n_rows.append({
                    "run": run_label, "season_water_step": f"{season} {water} N{n1}-N{n0}",
                    "season": season, "water": water, "step": f"N{n1}-N{n0}",
                    "series": series, "increment_kg_ha": float(z.loc[n1, series] - z.loc[n0, series]),
                })
    for (season, n), g in data.groupby(["season_id", "n"]):
        z = g.set_index("water_level")
        if {"W1", "W3"}.issubset(z.index):
            for series in ["observed", "simulated"]:
                w_rows.append({
                    "run": run_label, "season_n": f"{season} N{n}", "season": season,
                    "nitrogen": f"N{n}", "series": series,
                    "water_contrast_kg_ha": float(z.loc["W3", series] - z.loc["W1", series]),
                })
    return pd.DataFrame(n_rows), pd.DataFrame(w_rows)


def constraint_recommendations() -> pd.DataFrame:
    rows = [
        ("分数/比例定义域", "NSTFAC、RTEXF、XFRMAX、XFRT、SOIL_SLPF 等限定于 [0,1]", "真实物理/数学定义域", "保留", "防止负比例或超过 100%；不能作为解决曲线形状的调参手段"),
        ("速率非负", "RTNO3、RTNH4、RWUMX、NMOBMX、NRCVR 等不得为负", "真实物理约束", "保留", "当前问题应通过科学工作范围和曲线目标解决，不应开放负值"),
        ("土壤水分顺序", "SLLL < SDUL < SSAT", "真实物理关系", "保留关系，替换实现", "保留逐候选顺序；可取消要求三个独立边界矩形完全不重叠，改用有序变换"),
        ("温度基数顺序", "TB < TO1 <= TO2 < TM", "真实响应曲线拓扑", "保留关系，替换实现", "矩形边界完全分离属于工程简化，可能迫使其他参数补偿"),
        ("发育阶段顺序", "XMAGE < XFPHT；FL-SH < FL-SD；LNGSH/XMAGE <= XMPAGE", "模型语义关系", "保留逐候选关系", "不必把所有边界预先切成互不重叠区间；直接删除会产生无效阶段"),
        ("XFINT 上限 0.50", "SA 约束文件保留历史 IPDMND 风险阈值", "数值风险护栏，不是普适物理定律", "从物理层移除，改为工程告警", "当前注册表已允许 0–1；先做 0.40–0.65 单参数/联合冒烟剖面"),
        ("参考量互斥", "SLAVR/SLAREF、SIZLF/SIZREF 只能激活一个", "可辨识性约束", "不要称为物理约束", "默认仍只率定一个；有独立叶片数据和重参数化后可同时估计"),
        ("分配守恒", "叶+茎分配比例之和 <= 1；DMC 在 [0,1]", "真实质量守恒/定义域", "保留", "直接影响生物量分配，删除会破坏可解释性"),
        ("FRCNOD 固定", "非豆科作物固氮结瘤比例固定/排除", "物种结构约束", "保留", "茄子不应靠释放该参数修正氮响应"),
        ("水氮冻结范围", "如 RTNO3 0.005–0.05、RWUMX 0.02–0.12、LNREF 3–6", "率定工作范围，不是物理边界", "逐项剖面后调整", "不要整体删除；方向应由后验贴边、响应相关和机理共同决定"),
        ("SA 模块约束副本", "_constraints.json 与 param_registry.py 并存", "工程元数据", "合并为单一来源", "当前条目数、单位和部分边界冲突，易把 SA 规则误当正式率定硬约束"),
    ]
    return pd.DataFrame(rows, columns=["constraint", "current_form", "classification", "recommendation", "reason"])


def parameter_actions() -> pd.DataFrame:
    rows = [
        ("RTNO3", "B 末轮大量压在 0.05 上界；N0→N1 陡跳是集合级现象", "不要放宽上界；优先下调/收紧并与 RTNH4、RTEXF 联合剖面", "高"),
        ("NSTFAC", "B 后验接近 1；既有局部剖面显示单独改变影响很小", "保留 [0,1]；不要寄希望于继续放宽，作为联合参数而非主旋钮", "中"),
        ("LNREF", "B 中与 N0→N1 陡峭度 Spearman 约 -0.52；低值对应更大悬崖", "将上界由 6 试探至 8–10，保留下界 3，结合叶氮观测验证", "高"),
        ("RWUMX", "两批末轮中与水分对比为负相关；较高吸水能力会抹平灌水差异", "不向上放宽；优先剖面 0.01–0.08 并检查根区水分过程", "高"),
        ("CMOBMX", "A 中与 N3-N0 强负相关；B 后验靠近 0.05 上界并快速饱和", "与 LNREF、RTNO3 做二维/三维剖面；暂不简单扩大上界", "高"),
        ("RTNH4/RTEXF", "B 未明显贴边但与 N 曲率存在次级相关", "保留较宽工作域，纳入联合剖面，不单独硬收紧", "中"),
        ("DSWBAR/XFRMAX/PORMIN", "当前后验内与水分对比相关较弱或非线性；B 的 XFRMAX 偏高", "可做剖面但不是第一优先；不要仅因物理允许就扩大到全域", "中"),
        ("SOIL_SLPF", "B 最优在 0.90 下界附近，但主要改变总体肥力水平", "先冻结或窄幅剖面；避免用它代替氮曲线形状约束", "低"),
        ("XFINT/XFRT", "B 的 XFINT 偏上、XFRT 偏下；影响果实分配并可能与氮效应补偿", "保留定义域，做联合分配剖面；XFINT 0.50 只作风险阈值", "中"),
    ]
    return pd.DataFrame(rows, columns=["parameter", "evidence", "action", "priority"])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    par_a, obs_a, sum_a = load_run(RUN_A, PREFIX_A)
    par_b, obs_b, sum_b = load_run(RUN_B, PREFIX_B)

    posterior = pd.concat([
        posterior_audit("A 四角", par_a, sum_a),
        posterior_audit("B N0–N2 无响应目标", par_b, sum_b),
    ], ignore_index=True)
    response_a = ensemble_response_a(obs_a)
    response_b = ensemble_response_b(obs_b)
    response_summary = pd.concat([
        summarize_response("A 四角", response_a),
        summarize_response("B N0–N2 无响应目标", response_b),
    ], ignore_index=True)
    correlations = pd.concat([
        spearman_screen("A 四角", par_a, response_a),
        spearman_screen("B N0–N2 无响应目标", par_b, response_b),
    ], ignore_index=True)
    n_a, w_a = best_member_contrasts(RUN_A, "A 四角")
    n_b, w_b = best_member_contrasts(RUN_B, "B N0–N2 无响应目标")
    n_steps = pd.concat([n_a, n_b], ignore_index=True)
    water = pd.concat([w_a, w_b], ignore_index=True)
    constraints = constraint_recommendations()
    actions = parameter_actions()

    posterior.to_csv(OUT / "posterior_key_parameter_audit.csv", index=False, encoding="utf-8-sig")
    response_summary.to_csv(OUT / "ensemble_response_summary.csv", index=False, encoding="utf-8-sig")
    correlations.to_csv(OUT / "posterior_response_spearman_screen.csv", index=False, encoding="utf-8-sig")
    n_steps.to_csv(OUT / "best_member_nitrogen_steps.csv", index=False, encoding="utf-8-sig")
    water.to_csv(OUT / "best_member_water_contrasts.csv", index=False, encoding="utf-8-sig")
    constraints.to_csv(OUT / "constraint_recommendations.csv", index=False, encoding="utf-8-sig")
    actions.to_csv(OUT / "parameter_actions.csv", index=False, encoding="utf-8-sig")

    # Supporting diagnostic figure 1: boundary pressure using one explicit rule.
    focus = posterior[posterior["parameter"].isin(["RTNO3", "NSTFAC", "LNREF", "RWUMX", "CMOBMX", "XFINT", "XFRT", "XFRMAX"])].copy()
    pivot = focus.pivot(index="parameter", columns="run", values="boundary_pressure_pct").fillna(0)
    pivot = pivot.sort_values("B N0–N2 无响应目标", ascending=True)
    ax = pivot.plot.barh(figsize=(8.2, 5.0), color=["#2980B9", "#C0392B"])
    ax.set_xlabel("末轮集合位于边界 2% 范围内的比例 (%)")
    ax.set_ylabel("")
    ax.set_title("关键参数后验边界压力")
    ax.legend(title="运行")
    plt.tight_layout()
    plt.savefig(OUT / "diagnostic_boundary_pressure.png", dpi=180)
    plt.close()

    # Supporting diagnostic figure 2: best-member curve increments for run B.
    b_steps = n_b.copy()
    order = b_steps["season_water_step"].drop_duplicates().tolist()
    p = b_steps.pivot(index="season_water_step", columns="series", values="increment_kg_ha").reindex(order)
    ax = p.plot.bar(figsize=(10.5, 5.0), color=["#707070", "#C0392B"])
    ax.axhline(0, color="black", linewidth=0.7)
    ax.set_ylabel("相邻氮级增产 (kg/ha)")
    ax.set_xlabel("")
    ax.set_title("B 运行最优组的氮响应阶跃")
    ax.tick_params(axis="x", rotation=40)
    plt.tight_layout()
    plt.savefig(OUT / "diagnostic_best_member_nitrogen_steps.png", dpi=180)
    plt.close()

    audit = {
        "generated_at": "2026-08-01",
        "boundary_rule": "distance to lower or upper bound <= 2% of that run's active interval",
        "response_transform": "expm1(final cumulative CHPDT ensemble values)",
        "run_a_members": int(len(par_a)),
        "run_b_members": int(len(par_b)),
        "source_files": [
            str(RUN_A / f"{PREFIX_A}.5.par.csv"), str(RUN_A / f"{PREFIX_A}.5.obs.csv"),
            str(RUN_A / "posterior_response_analysis" / "posterior_summary.csv"),
            str(RUN_B / f"{PREFIX_B}.5.par.csv"), str(RUN_B / f"{PREFIX_B}.5.obs.csv"),
            str(RUN_B / "posterior_response_analysis" / "posterior_summary.csv"),
            str(ROOT / "src" / "common" / "param_registry.py"),
            str(ROOT / "src" / "dssat" / "run_dssat.py"),
            str(ROOT / "configs" / "sa" / "parameter_modules" / "_constraints.json"),
        ],
        "caveats": [
            "Spearman correlations are descriptive within the final IES ensemble and are not causal sensitivities.",
            "Parameters collapsed at a bound can show weak correlation because little posterior variation remains.",
            "Both runs use calibration-domain observations; the findings diagnose response shape but do not establish independent validation performance.",
        ],
    }
    (OUT / "audit_manifest.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    b_summary = response_summary[response_summary["run"].str.startswith("B")].set_index("metric")
    a_summary = response_summary[response_summary["run"].str.startswith("A")].set_index("metric")
    b_pressure = posterior[posterior["run"].str.startswith("B")].set_index("parameter")
    report_datasets = {
        "headline_metrics": [{
            "b_nitrogen_cliff_median": float(b_summary.loc["nitrogen_cliff", "median"]),
            "b_water_effect_median": float(b_summary.loc["water_effect", "median"]),
            "a_nitrogen_effect_median": float(a_summary.loc["nitrogen_effect", "median"]),
            "a_water_effect_median": float(a_summary.loc["water_effect", "median"]),
            "b_rtno3_boundary_pressure": float(b_pressure.loc["RTNO3", "boundary_pressure_pct"]),
            "b_nstfac_boundary_pressure": float(b_pressure.loc["NSTFAC", "boundary_pressure_pct"]),
        }],
        "boundary_chart": focus.to_dict(orient="records"),
        "nitrogen_steps": n_b.to_dict(orient="records"),
        "water_contrasts": w_b.to_dict(orient="records"),
        "ensemble_response": response_summary.to_dict(orient="records"),
        "constraint_recommendations": constraints.to_dict(orient="records"),
        "parameter_actions": actions.to_dict(orient="records"),
    }
    (OUT / "report_datasets.json").write_text(
        json.dumps(report_datasets, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Wrote audit outputs to {OUT}")
    print(json.dumps({
        "run_a_members": len(par_a),
        "run_b_members": len(par_b),
        "output_tables": 7,
        "output_figures": 2,
    }, ensure_ascii=True))


if __name__ == "__main__":
    main()
