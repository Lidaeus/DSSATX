import argparse
import os

import matplotlib
import pandas as pd
from matplotlib.ticker import ScalarFormatter


def _load_pyplot():
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


plt = _load_pyplot()


def _default_case_dir():
    workspace_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    return os.path.join(workspace_dir, "workspace", "runs", "sa_output", "sen_case")


def _read_mio(mio_path):
    df = pd.read_csv(mio_path)
    cols = {c.lower(): c for c in df.columns}

    obs_col = (
        cols.get("observation_name")
        or cols.get("obsnme")
        or cols.get("obsname")
        or cols.get("observation")
    )
    par_col = (
        cols.get("parameter_name")
        or cols.get("parnme")
        or cols.get("parname")
        or cols.get("parameter")
    )

    mustar_col = cols.get("mu*") or cols.get("mu_star") or cols.get("mustar")
    sen_abs_col = cols.get("sen_mean_abs")
    sigma_col = (
        cols.get("sigma")
        or cols.get("sen_std_dev")
        or cols.get("sen_std")
        or cols.get("std_dev")
        or cols.get("std")
    )

    if obs_col is None or par_col is None:
        raise ValueError(f"Unexpected mio columns: {list(df.columns)}")

    if sen_abs_col is not None:
        rename_map = {obs_col: "obs", par_col: "par", sen_abs_col: "score"}
        if sigma_col is not None:
            rename_map[sigma_col] = "sigma"
        out = df.rename(columns=rename_map).copy()
        out["score_kind"] = "sen_mean_abs"
    elif mustar_col is not None:
        rename_map = {obs_col: "obs", par_col: "par", mustar_col: "score"}
        if sigma_col is not None:
            rename_map[sigma_col] = "sigma"
        out = df.rename(columns=rename_map).copy()
        out["score_kind"] = "mu_star"
    else:
        raise ValueError(f"Unexpected mio columns: {list(df.columns)}")

    out["obs"] = out["obs"].astype(str)
    out["par"] = out["par"].astype(str).str.upper()
    out["score"] = pd.to_numeric(out["score"], errors="coerce")
    if "sigma" in out.columns:
        out["sigma"] = pd.to_numeric(out["sigma"], errors="coerce")
    else:
        out["sigma"] = pd.NA
    return out


def _indicator_key(obs_name):
    s = str(obs_name)
    u = s.strip().upper()
    if u.startswith("TN"):
        s2 = s.split("_", 1)[1] if "_" in s else s
        return str(s2).strip().upper()
    if u.startswith("MEAN_"):
        return str(s[len("MEAN_") :]).strip().upper()
    return u


def _save_multi(fig, out_base, formats, dpi=600):
    fmts = [f.strip().lstrip(".") for f in (formats or []) if str(f).strip()]
    if not fmts:
        fmts = ["png"]
    for fmt in fmts:
        fp = f"{out_base}.{fmt}"
        if fmt.lower() in {"png", "jpg", "jpeg", "tif", "tiff"}:
            fig.savefig(fp, dpi=int(dpi))
        else:
            fig.savefig(fp)


def _format_axis_scientific(ax):
    fmt = ScalarFormatter(useMathText=True)
    fmt.set_powerlimits((-3, 3))
    ax.yaxis.set_major_formatter(fmt)
    ax.ticklabel_format(axis="y", style="sci", scilimits=(-3, 3))


def select_topk(
    mio_path,
    out_csv_path,
    k_per_indicator=12,
    max_total=15,
    cum_threshold=0.88,
    interaction_ratio=1.0,
    indicators=None,
    out_dir=None,
    formats=None,
    dpi=600,
    base_font_size=10,
):
    df = _read_mio(mio_path)
    df["key"] = df["obs"].map(_indicator_key)

    if indicators is None:
        indicators = [
            "YIELD_HWAMS",
            "LAI_AUC",
            "LAI_PEAK",
            "FRUITD_END",
            "STEM_END_SWAD",
            "LEAF_END_LWAD",
            "CWAMS",
            "HIAMS",
            "ADAPS",
            "PDFPS",
            "MDAPS",
        ]

    df = df[df["key"].isin(indicators)].copy()
    if df.empty:
        raise ValueError("No indicators found in mio for selection")

    per_indicator = []
    per_indicator_top = {}
    for ind in indicators:
        g = df[df["key"] == ind].dropna(subset=["score"])
        if g.empty:
            continue
        agg = (
            g.groupby("par", as_index=False)
            .agg(score=("score", "mean"), sigma=("sigma", "mean"))
            .sort_values("score", ascending=False, kind="stable")
            .reset_index(drop=True)
        )
        if agg.empty:
            continue
        total = float(agg["score"].sum())
        if total > 0:
            agg["cum_frac"] = agg["score"].cumsum() / total
            pick = agg[agg["cum_frac"] <= float(cum_threshold)].copy()
            if pick.empty:
                pick = agg.head(1).copy()
        else:
            pick = agg.head(1).copy()

        if k_per_indicator is not None:
            pick = pick.head(int(k_per_indicator)).copy()
        pick["indicator"] = ind
        per_indicator.append(pick)
        per_indicator_top[ind] = str(agg.loc[0, "par"]).strip().upper()

    if not per_indicator:
        raise ValueError("No indicators found in mio for selection")

    per_df = pd.concat(per_indicator, ignore_index=True)
    per_params = set(per_df["par"].astype(str).str.upper().tolist())

    interaction_params = set()
    interaction_df = pd.DataFrame(columns=["par", "score", "sigma", "ratio"])
    if df["sigma"].notna().any():
        inter = (
            df.dropna(subset=["score", "sigma"])
            .groupby("par", as_index=False)
            .agg(score=("score", "mean"), sigma=("sigma", "mean"))
        )
        inter = inter[inter["score"] > 0]
        if not inter.empty:
            inter["ratio"] = inter["sigma"] / inter["score"]
            interaction_df = inter.copy()
            inter = inter[inter["ratio"] >= float(interaction_ratio)]
            interaction_params = set(inter["par"].astype(str).str.upper().tolist())

    selected_params = per_params.union(interaction_params)
    overall = (
        df.dropna(subset=["score"])
        .groupby("par", as_index=False)
        .agg(score=("score", "mean"), sigma=("sigma", "mean"))
        .sort_values("score", ascending=False, kind="stable")
        .reset_index(drop=True)
    )
    overall["par"] = overall["par"].astype(str).str.upper()
    overall = overall[overall["par"].isin(selected_params)].copy()

    if max_total is not None:
        must_keep = [per_indicator_top.get(ind) for ind in indicators if per_indicator_top.get(ind)]
        order = overall["par"].tolist()
        final = []
        for p in order:
            if p in must_keep and p not in final:
                final.append(p)
        for p in order:
            if p not in final:
                final.append(p)
            if len(final) >= int(max_total):
                break
        overall = overall[overall["par"].isin(final)].copy()
        overall["rank"] = overall["par"].map({p: i + 1 for i, p in enumerate(final)})
        overall = overall.sort_values("rank", kind="stable").drop(columns=["rank"])

    os.makedirs(os.path.dirname(out_csv_path), exist_ok=True)
    score_kind = str(df["score_kind"].dropna().iloc[0]) if "score_kind" in df.columns and df["score_kind"].notna().any() else "score"
    overall = overall.rename(columns={"score": f"{score_kind}_mean", "sigma": "sigma_mean"})
    if "sigma_mean" in overall.columns:
        overall["sigma_ratio"] = pd.to_numeric(overall["sigma_mean"], errors="coerce") / pd.to_numeric(
            overall[f"{score_kind}_mean"], errors="coerce"
        )
    overall.to_csv(out_csv_path, index=False, encoding="utf-8-sig")

    out_dir = os.path.normpath(out_dir) if out_dir else os.path.dirname(os.path.abspath(out_csv_path))
    os.makedirs(out_dir, exist_ok=True)
    fmts = [s.strip() for s in str(formats or "png,svg").split(",") if s.strip()]
    base_font_size = max(6, int(base_font_size))
    plt.rcParams.update({"font.size": base_font_size})

    overall_full = (
        df.dropna(subset=["score"])
        .groupby("par", as_index=False)["score"]
        .mean()
        .sort_values("score", ascending=False, kind="stable")
        .reset_index(drop=True)
    )
    if not overall_full.empty:
        overall_full["rank"] = range(1, len(overall_full) + 1)
        total = float(overall_full["score"].sum())
        overall_full["cum_frac"] = overall_full["score"].cumsum() / total if total > 0 else 0.0

        k_cum = int(overall_full.loc[overall_full["cum_frac"] >= float(cum_threshold), "rank"].min() or len(overall_full))
        k_max = int(max_total) if max_total is not None else None
        drops = (overall_full["score"] - overall_full["score"].shift(-1)).fillna(0.0)

        fig, ax = plt.subplots(figsize=(7.2, 4.8))
        ax.plot(
            overall_full["rank"],
            overall_full["score"],
            color="#2E6F9E",
            linewidth=1.6,
            marker="o",
            markersize=3.5,
            label="Mean sensitivity",
        )
        if k_max is not None:
            ax.axvline(k_max, color="#C84B31", linewidth=1.2, label=f"K max = {k_max}")
        if k_cum is not None:
            ax.axvline(k_cum, color="#4C9F70", linewidth=1.2, label=f"K at cum {cum_threshold:.2f}")
        ax.set_title("Morris elbow: sensitivity & marginal drop")
        ax.set_xlabel("Rank")
        ax.set_ylabel("Mean sensitivity")
        ax.grid(color="#D0D0D0", linewidth=0.6, alpha=0.8)
        ax.set_axisbelow(True)
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        _format_axis_scientific(ax)

        ax2 = ax.twinx()
        ax2.bar(
            overall_full["rank"],
            drops,
            width=0.8,
            color="#E8C08C",
            alpha=0.6,
            edgecolor="#C9A26B",
            label="Marginal drop",
        )
        ax2.set_ylabel("Marginal drop")
        ax2.spines["top"].set_visible(False)
        _format_axis_scientific(ax2)

        handles1, labels1 = ax.get_legend_handles_labels()
        handles2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(handles1 + handles2, labels1 + labels2, loc="upper right", frameon=False)
        ax.text(
            0.02,
            0.96,
            f"cum({k_cum}) = {overall_full.loc[overall_full['rank'] == k_cum, 'cum_frac'].iloc[0]:.2f}" if k_cum else "",
            transform=ax.transAxes,
            ha="left",
            va="top",
        )

        _save_multi(fig, os.path.join(out_dir, "morris_topk_elbow"), formats=fmts, dpi=dpi)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(7.2, 4.8))
        ax.plot(
            overall_full["rank"],
            overall_full["cum_frac"],
            color="#2E6F9E",
            linewidth=1.8,
            marker="o",
            markersize=3.5,
            label="Cumulative contribution",
        )
        ax.fill_between(
            overall_full["rank"],
            0.0,
            overall_full["cum_frac"],
            color="#2E6F9E",
            alpha=0.12,
            label="Accumulated area",
        )
        ax.axhline(float(cum_threshold), color="#C84B31", linewidth=1.2, label=f"Threshold = {cum_threshold:.2f}")
        if k_max is not None:
            ax.axvline(k_max, color="#C84B31", linewidth=1.2, label=f"K max = {k_max}")
        if k_cum is not None:
            ax.axvline(k_cum, color="#4C9F70", linewidth=1.2, label=f"K at cum {cum_threshold:.2f}")
            ax.scatter([k_cum], [float(cum_threshold)], s=26, color="#4C9F70", zorder=3)
        ax.set_title("Morris cumulative contribution")
        ax.set_xlabel("Rank")
        ax.set_ylabel("Cumulative contribution")
        ax.set_ylim(0, 1.02)
        ax.grid(color="#D0D0D0", linewidth=0.6, alpha=0.8)
        ax.set_axisbelow(True)
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)
        ax.legend(loc="lower right", frameon=False)
        _save_multi(fig, os.path.join(out_dir, "morris_topk_cum_contribution"), formats=fmts, dpi=dpi)
        plt.close(fig)

    if not interaction_df.empty:
        interaction_df["par"] = interaction_df["par"].astype(str).str.upper()
        interaction_df = interaction_df.sort_values("ratio", ascending=False, kind="stable")
        interaction_df["reclaimed"] = interaction_df["par"].isin(interaction_params)
        interaction_df = interaction_df.rename(
            columns={"score": f"{score_kind}_mean", "sigma": "sigma_mean", "ratio": "sigma_ratio"}
        )
        interaction_df.to_csv(
            os.path.join(out_dir, "morris_topk_interaction_reclaimed.csv"), index=False, encoding="utf-8-sig"
        )

    method_md = _build_method_text(
        score_kind=score_kind,
        cum_threshold=float(cum_threshold),
        interaction_ratio=float(interaction_ratio),
        max_total=max_total,
        k_per_indicator=k_per_indicator,
        indicators=indicators,
    )
    with open(os.path.join(out_dir, "morris_topk_method_summary.md"), "w", encoding="utf-8") as f:
        f.write(method_md.rstrip() + "\n")
    return overall


def _build_method_text(
    score_kind,
    cum_threshold,
    interaction_ratio,
    max_total,
    k_per_indicator,
    indicators,
):
    indicator_list = ", ".join([str(x) for x in indicators])
    max_total_txt = "" if max_total is None else f"并将全局保留数量限制为 {int(max_total)}"
    k_txt = "" if k_per_indicator is None else f"每个指标组最多保留 {int(k_per_indicator)} 个参数"
    return (
        "# Morris Top-K 选择标准化说明\n\n"
        "## 引言（Gap发现）\n"
        "针对茄子 DSSAT 模型高维参数空间，直接在 Sobol 阶段开展全参数 Sensitivity analysis 计算成本高且不易解释。"
        "为解决筛选阶段难以同时捕捉直接效应与非线性交互的问题，本研究采用 Morris 进行初筛，并在 Top-K 规则中显式引入交互补偿。\n\n"
        "## 材料方法（试验设计 + 模型描述）\n"
        "试验设计基于既有水氮优化试验与多指标观测体系，指标组包括："
        f"{indicator_list}。"
        "模型关键过程涵盖 Thermal time 驱动物候、冠层结构与干物质分配等模块，并考虑 Genotype-by-environment interaction 的非线性响应。"
        "Morris 输出的敏感性度量采用 \"{score_kind}\"（μ* 等价指标），交互强度采用 σ。\n\n"
        "Top-K 选择采用三层漏斗：\n"
        f"1) 指标内累计贡献阈值：按 {score_kind} 排序，累计贡献达到 {cum_threshold:.2f} 截止；{k_txt}。\n"
        f"2) 交互补偿：对 σ/μ* ≥ {interaction_ratio:.2f} 的参数进行捞回，确保非线性与交互项进入 Sobol。\n"
        f"3) 全局约束：在覆盖各指标核心参数的前提下，{max_total_txt}。\n\n"
        "## 结果（标定验证 + 优化结果）\n"
        "Morris 结果输出包含肘部图与累计贡献曲线，用于证明 Top-K 的边界选择具有可解释的拐点特征。"
        "交互捞回清单用于报告非线性驱动参数进入 Sobol 的依据。"
        "后续标定评价采用 RMSE、NRMSE 与 d-index，优先比较不同 Top-K 规则在目标指标上的拟合稳定性与跨环境一致性。\n\n"
        "## 讨论（生理机制阐述）\n"
        "高 σ/μ* 参数通常对应强交互或阶段性响应，如 Thermal time 与冠层结构参数对 LAI 峰值与物候期的耦合。"
        "通过交互补偿避免遗漏关键机制参数，有助于解释水氮情景下的非线性响应与 Genotype-by-environment interaction。\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", default=None)
    parser.add_argument("--k", type=int, default=12)
    parser.add_argument("--max-total", type=int, default=15)
    parser.add_argument("--cum-threshold", type=float, default=0.88)
    parser.add_argument("--interaction-ratio", type=float, default=1.0)
    parser.add_argument("--out", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--formats", default="png,svg")
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument("--base-font-size", type=int, default=10)
    args = parser.parse_args()

    case_dir = os.path.normpath(args.case_dir) if args.case_dir else _default_case_dir()
    mio_path = os.path.join(case_dir, "sa_sen_morris.mio")
    out_csv = (
        os.path.normpath(args.out)
        if args.out
        else os.path.join(os.path.dirname(case_dir), "morris_results", "topk_params.csv")
    )
    df = select_topk(
        mio_path=mio_path,
        out_csv_path=out_csv,
        k_per_indicator=args.k,
        max_total=args.max_total,
        cum_threshold=args.cum_threshold,
        interaction_ratio=args.interaction_ratio,
        out_dir=args.out_dir,
        formats=args.formats,
        dpi=args.dpi,
        base_font_size=args.base_font_size,
    )
    print(f"Wrote {len(df)} params: {out_csv}")


if __name__ == "__main__":
    main()
