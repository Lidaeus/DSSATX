import argparse
import os
import re

import matplotlib
import pandas as pd
from matplotlib.colors import Normalize
from matplotlib.ticker import ScalarFormatter


def _load_pyplot():
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


plt = _load_pyplot()


def _default_case_dir():
    workspace_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    return os.path.join(workspace_dir, "workspace", "runs", "sa_output", "sen_case")


def _find_sobol_si_csv(case_dir):
    for fn in ["sa_sen_sobol.sobol.si.csv", "sa_sen_sobol.sobol.si.csv"]:
        p = os.path.join(case_dir, fn)
        if os.path.exists(p):
            return p
    for fn in sorted(os.listdir(case_dir)):
        u = fn.lower()
        if ("sobol" in u) and u.endswith(".si.csv"):
            return os.path.join(case_dir, fn)
    return None


def _find_sobol_sti_csv(case_dir):
    for fn in ["sa_sen_sobol.sobol.sti.csv", "sa_sen_sobol.sobol.sti.csv"]:
        p = os.path.join(case_dir, fn)
        if os.path.exists(p):
            return p
    for fn in sorted(os.listdir(case_dir)):
        u = fn.lower()
        if ("sobol" in u) and u.endswith(".sti.csv"):
            return os.path.join(case_dir, fn)
    return None


def _sobol_wide_to_long(df_wide, value_name):
    if df_wide is None or df_wide.empty:
        return pd.DataFrame(columns=["obs", "par", value_name])
    cols = list(df_wide.columns)
    obs_col = None
    for c in cols:
        if str(c).strip().lower() in {"output", "obs", "observation", "observation_name"}:
            obs_col = c
            break
    if obs_col is None:
        obs_col = cols[0]
    tmp = df_wide.rename(columns={obs_col: "obs"}).copy()
    tmp["obs"] = tmp["obs"].astype(str)
    long = tmp.melt(id_vars=["obs"], var_name="par", value_name=value_name)
    long["par"] = long["par"].astype(str).str.upper()
    long[value_name] = pd.to_numeric(long[value_name], errors="coerce")
    return long


def _indicator_key(obs_name):
    s = str(obs_name).strip()
    u = s.upper()
    if u.startswith("TN") and "_" in s:
        s = s.split("_", 1)[1]
        u = s.upper()
    if u.startswith("MEAN_"):
        s = s[5:]
    return str(s).strip()


def _normalize_key(key):
    return str(key).strip().lower()


_DAP_RE = re.compile(r"^(?P<metric>.+)_dap(?P<dap>\d{2,3})$", flags=re.IGNORECASE)


def _time_group_key(key):
    k = _normalize_key(key)
    m = _DAP_RE.match(k)
    if not m:
        return k
    return f"{m.group('metric')}_dap"


def _extract_dap(key):
    k = _normalize_key(key)
    m = _DAP_RE.match(k)
    if not m:
        return None, None
    return m.group("metric"), float(m.group("dap"))


def _apply_pub_style(base_font_size=10):
    plt.rcParams.update(
        {
            "font.size": base_font_size,
            "axes.titlesize": base_font_size + 2,
            "axes.labelsize": base_font_size + 1,
            "xtick.labelsize": base_font_size,
            "ytick.labelsize": base_font_size,
            "legend.fontsize": base_font_size,
            "axes.linewidth": 0.8,
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.minor.width": 0.6,
            "ytick.minor.width": 0.6,
            "xtick.major.size": 3.5,
            "ytick.major.size": 3.5,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.02,
        }
    )


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
    ax.xaxis.set_major_formatter(fmt)
    ax.ticklabel_format(axis="x", style="sci", scilimits=(-3, 3))


def _barh_topn(df2, value_col, label_col, title, xlabel, out_base, formats, dpi=600):
    fig, ax = plt.subplots(figsize=(7.2, max(3.2, 0.22 * len(df2))))
    ax.barh(df2[label_col][::-1], df2[value_col][::-1], color="#2E6F9E", edgecolor="#1F2D3A", linewidth=0.4)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.grid(axis="x", color="#D0D0D0", linewidth=0.6, alpha=0.8)
    ax.set_axisbelow(True)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    _format_axis_scientific(ax)
    _save_multi(fig, out_base, formats=formats, dpi=dpi)
    plt.close(fig)


def _fmt_score(x):
    try:
        v = float(x)
    except Exception:
        return ""
    if v == 0.0:
        return "0"
    av = abs(v)
    if av >= 1e4 or av < 1e-2:
        return f"{v:.3e}"
    return f"{v:.4g}"


def _df_to_markdown_table(df):
    df2 = df.copy()
    for c in df2.columns:
        df2[c] = df2[c].astype(str)
    header = "| " + " | ".join(df2.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(df2.columns)) + " |"
    rows = ["| " + " | ".join(r) + " |" for r in df2.values.tolist()]
    return "\n".join([header, sep] + rows)


def _write_onepage_tables(out_dir, top_n=20, indicator_top=3):
    out_dir = os.path.normpath(out_dir)
    overall_path = os.path.join(out_dir, "sobol_overall_parameter_ranking.csv")
    ind_path = os.path.join(out_dir, "sobol_top20_all_indicators.csv")
    if not os.path.exists(overall_path) or not os.path.exists(ind_path):
        return

    overall = pd.read_csv(overall_path)
    ind = pd.read_csv(ind_path)
    score_cols = [c for c in overall.columns if c.lower() not in {"par"}]
    score_col = score_cols[0] if score_cols else "score"

    overall_top = overall.head(int(top_n)).copy()
    overall_top[score_col] = overall_top[score_col].map(_fmt_score)
    overall_top.insert(0, "rank", range(1, len(overall_top) + 1))
    overall_md = _df_to_markdown_table(overall_top[["rank", "par", score_col]])

    ind2 = ind.copy()
    ind2["indicator"] = ind2["indicator"].astype(str)
    ind2["par"] = ind2["par"].astype(str)
    ind2[score_col] = pd.to_numeric(ind2[score_col], errors="coerce")
    ind2 = ind2.dropna(subset=[score_col])
    ind2["group"] = ind2["indicator"].str.replace(r"_dap\d{2,3}$", "_dap", regex=True)

    rows = []
    for group, g in ind2.groupby("group", sort=False):
        agg = (
            g.groupby("par", as_index=False)[score_col]
            .mean()
            .sort_values(score_col, ascending=False, kind="stable")
            .head(int(indicator_top))
        )
        cells = []
        for _, r in agg.iterrows():
            cells.append(f"{r['par']} ({_fmt_score(r[score_col])})")
        while len(cells) < int(indicator_top):
            cells.append("")
        group_total = float(g[score_col].sum())
        rows.append([group, group_total] + cells)

    if rows:
        cols = ["indicator_group", "_total", *[f"top{i}" for i in range(1, int(indicator_top) + 1)]]
        per_ind = pd.DataFrame(rows, columns=cols).sort_values("_total", ascending=False, kind="stable")
        per_ind = per_ind.drop(columns=["_total"])
        per_ind_md = _df_to_markdown_table(per_ind)
    else:
        per_ind = pd.DataFrame(columns=["indicator_group", *[f"top{i}" for i in range(1, int(indicator_top) + 1)]])
        per_ind_md = ""

    md_path = os.path.join(out_dir, "sobol_onepage_summary.md")
    tsv_path = os.path.join(out_dir, "sobol_onepage_summary.tsv")

    md = []
    md.append("# Sobol 敏感性一页式汇总")
    md.append("")
    md.append(f"## 总体参数敏感性排名 Top{int(top_n)}")
    md.append("")
    md.append(overall_md)
    md.append("")
    md.append(f"## 各指标（时间序列 *_dapXXX 自动聚合为 *_dap）Top{int(indicator_top)}")
    md.append("")
    md.append(per_ind_md)
    md.append("")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md).strip() + "\n")

    with open(tsv_path, "w", encoding="utf-8") as f:
        f.write(f"OverallTop{int(top_n)}\n")
        f.write("rank\tpar\t" + score_col + "\n")
        for _, r in overall_top[["rank", "par", score_col]].iterrows():
            f.write(f"{r['rank']}\t{r['par']}\t{r[score_col]}\n")
        f.write("\n")
        f.write(f"PerIndicatorGroupTop{int(indicator_top)}\n")
        f.write("indicator_group\t" + "\t".join([f"top{i}" for i in range(1, int(indicator_top) + 1)]) + "\n")
        for _, r in per_ind.iterrows():
            f.write("\t".join([str(r[c]) for c in per_ind.columns]) + "\n")


def postprocess_sobol(
    case_dir,
    out_dir,
    top_n=20,
    formats=None,
    dpi=600,
    base_font_size=10,
    heatmap_percentile=99.0,
    plot_mode="compact",
):
    si_path = _find_sobol_si_csv(case_dir)
    sti_path = _find_sobol_sti_csv(case_dir)
    if not si_path and not sti_path:
        raise FileNotFoundError("Sobol output not found in case dir")
    os.makedirs(out_dir, exist_ok=True)
    _apply_pub_style(base_font_size=base_font_size)

    plot_mode = str(plot_mode or "compact").strip().lower()
    if plot_mode not in {"compact", "full"}:
        raise ValueError(f"plot_mode must be compact or full, got: {plot_mode}")
    plot_per_group = plot_mode == "full"
    plot_param_to_indicator = plot_mode == "full"

    si_long = None
    sti_long = None
    if si_path and os.path.exists(si_path):
        si_wide = pd.read_csv(si_path)
        si_long = _sobol_wide_to_long(si_wide, "Si")
    if sti_path and os.path.exists(sti_path):
        sti_wide = pd.read_csv(sti_path)
        sti_long = _sobol_wide_to_long(sti_wide, "STi")

    if si_long is not None and sti_long is not None and (not si_long.empty) and (not sti_long.empty):
        out = pd.merge(si_long, sti_long, on=["obs", "par"], how="outer")
    elif sti_long is not None and (not sti_long.empty):
        out = sti_long
    elif si_long is not None and (not si_long.empty):
        out = si_long
    else:
        raise ValueError("Sobol CSVs are empty or unreadable")

    out["key"] = out["obs"].map(_indicator_key)
    out["key_norm"] = out["key"].map(_normalize_key)
    out["group_key"] = out["key_norm"].map(_time_group_key)
    out = out[out["obs"].astype(str).str.strip().str.lower() != "phi"].copy()
    out.to_csv(os.path.join(out_dir, "sobol_raw.csv"), index=False, encoding="utf-8-sig")

    if "STi" in out.columns:
        val_col = "STi"
    elif "Si" in out.columns:
        val_col = "Si"
    else:
        raise ValueError(f"No Si/STi columns found in: {list(out.columns)}")

    quality = {
        "n_rows": int(len(out)),
        "n_obs": int(out["obs"].nunique()),
        "n_par": int(out["par"].nunique()),
    }
    for c in ["Si", "STi"]:
        if c in out.columns:
            s = pd.to_numeric(out[c], errors="coerce")
            quality[f"{c}_non_nan"] = int(s.notna().sum())
            quality[f"{c}_nan"] = int(s.isna().sum())
            quality[f"{c}_nan_frac"] = float(s.isna().mean()) if len(s) else 1.0
    pd.DataFrame([{"metric": k, "value": v} for k, v in quality.items()]).to_csv(
        os.path.join(out_dir, "sobol_quality_report.csv"), index=False, encoding="utf-8-sig"
    )

    if pd.to_numeric(out[val_col], errors="coerce").notna().sum() == 0:
        print(f"No finite Sobol indices found for {val_col}; wrote: {out_dir}")
        return

    summary_rows = []
    for gkey, g in out.groupby("group_key", sort=False):
        g2 = g.dropna(subset=[val_col]).copy()
        if g2.empty:
            continue
        agg = (
            g2.groupby("par", as_index=False)[val_col]
            .mean()
            .sort_values(val_col, ascending=False, kind="stable")
            .head(int(top_n))
        )
        agg.to_csv(os.path.join(out_dir, f"sobol_top{int(top_n)}_{gkey}.csv"), index=False, encoding="utf-8-sig")

        if plot_per_group:
            safe = re.sub(r"[^A-Za-z0-9_\-]", "_", gkey)
            _barh_topn(
                agg,
                value_col=val_col,
                label_col="par",
                title=f"Sobol {val_col} Top {int(top_n)}: {gkey}",
                xlabel=val_col,
                out_base=os.path.join(out_dir, f"sobol_top{int(top_n)}_{safe}"),
                formats=formats,
                dpi=dpi,
            )

        for _, r in agg.iterrows():
            summary_rows.append({"indicator": gkey, "par": r["par"], val_col: r[val_col]})

    if summary_rows:
        top_all = pd.DataFrame(summary_rows)
        top_all.to_csv(
            os.path.join(out_dir, f"sobol_top{int(top_n)}_all_indicators_{val_col}.csv"), index=False, encoding="utf-8-sig"
        )
        top_all.to_csv(os.path.join(out_dir, "sobol_top20_all_indicators.csv"), index=False, encoding="utf-8-sig")

    overall = (
        out.dropna(subset=[val_col])
        .groupby("par", as_index=False)[val_col]
        .mean()
        .sort_values(val_col, ascending=False, kind="stable")
    )
    if not overall.empty:
        overall.to_csv(os.path.join(out_dir, f"sobol_overall_parameter_ranking_{val_col}.csv"), index=False, encoding="utf-8-sig")
        overall.to_csv(os.path.join(out_dir, "sobol_overall_parameter_ranking.csv"), index=False, encoding="utf-8-sig")

        top_params = overall.head(int(top_n))["par"].tolist()
        p2i = (
            out.dropna(subset=[val_col])
            .copy()
            .assign(indicator=lambda d: d["group_key"])
            .groupby(["par", "indicator"], as_index=False)[val_col]
            .mean()
        )
        p2i.to_csv(os.path.join(out_dir, f"sobol_param_to_indicator_scores_{val_col}.csv"), index=False, encoding="utf-8-sig")
        p2i.to_csv(os.path.join(out_dir, "sobol_param_to_indicator_scores.csv"), index=False, encoding="utf-8-sig")

        ind_totals = p2i.groupby("indicator", as_index=False)[val_col].sum().sort_values(val_col, ascending=False, kind="stable")
        top_indicators = ind_totals.head(min(30, len(ind_totals)))["indicator"].tolist()
        heat = (
            p2i[p2i["par"].isin(top_params) & p2i["indicator"].isin(top_indicators)]
            .pivot_table(index="par", columns="indicator", values=val_col, aggfunc="mean")
            .reindex(index=top_params)
        )
        if not heat.empty:
            heat.to_csv(os.path.join(out_dir, f"sobol_heatmap_param_x_indicator_{val_col}.csv"), encoding="utf-8-sig")
            z = heat.fillna(0.0).values
            fig, ax = plt.subplots(figsize=(max(7.2, 0.24 * len(heat.columns)), max(4.0, 0.22 * len(heat.index))))
            im = ax.imshow(z, aspect="auto", interpolation="nearest", cmap="viridis")
            ax.set_yticks(range(len(heat.index)))
            ax.set_yticklabels(heat.index)
            ax.set_xticks(range(len(heat.columns)))
            ax.set_xticklabels(heat.columns, rotation=45, ha="right")
            ax.set_title(f"Sobol heatmap: top parameters × indicator groups ({val_col})")
            ax.set_xlabel("Indicator group")
            ax.set_ylabel("Parameter")
            cbar = fig.colorbar(im, ax=ax)
            cbar.set_label(val_col)
            _save_multi(fig, os.path.join(out_dir, f"sobol_heatmap_param_x_indicator_{val_col}"), formats=formats, dpi=dpi)
            plt.close(fig)

        if plot_param_to_indicator:
            for par in top_params:
                sub = p2i[p2i["par"] == par].sort_values(val_col, ascending=False, kind="stable").head(int(top_n))
                if sub.empty:
                    continue
                safe_par = re.sub(r"[^A-Za-z0-9_\-]", "_", str(par))
                _barh_topn(
                    sub,
                    value_col=val_col,
                    label_col="indicator",
                    title=f"Parameter → Indicators Top {int(top_n)}: {par}",
                    xlabel=val_col,
                    out_base=os.path.join(out_dir, f"sobol_param_top{int(top_n)}_indicators_{safe_par}"),
                    formats=formats,
                    dpi=dpi,
                )

    _write_onepage_tables(out_dir, top_n=int(top_n), indicator_top=3)

    metrics = out["key_norm"].map(_extract_dap)
    out["metric"] = [m[0] for m in metrics]
    out["dap"] = [m[1] for m in metrics]
    time_like = out.dropna(subset=["metric", "dap"]).copy()
    if not time_like.empty:
        metric_rank = (
            time_like.dropna(subset=[val_col]).groupby(["metric"], as_index=False)[val_col].sum().sort_values(val_col, ascending=False, kind="stable")
        )
        metric_order = metric_rank["metric"].tolist()

        top_params = (
            out.dropna(subset=[val_col]).groupby("par", as_index=False)[val_col].mean().sort_values(val_col, ascending=False, kind="stable").head(int(top_n))["par"].tolist()
        )

        for metric in metric_order[: min(8, len(metric_order))]:
            g = time_like[time_like["metric"] == metric].copy()
            pivot = g.pivot_table(index="par", columns="dap", values=val_col, aggfunc="mean")
            pivot = pivot.sort_index(axis=0).sort_index(axis=1)
            if top_params:
                pivot = pivot.reindex(index=top_params)
            pivot.to_csv(os.path.join(out_dir, f"sobol_heatmap_{metric}_{val_col}.csv"), encoding="utf-8-sig")

            z = pivot.fillna(0.0).values
            cap = None
            try:
                cap = float(pd.Series(z.ravel()).quantile(float(heatmap_percentile) / 100.0))
            except Exception:
                cap = None
            if cap is not None and cap > 0:
                z_plot = z.copy()
                z_plot[z_plot > cap] = cap
                norm = Normalize(vmin=0.0, vmax=cap)
            else:
                z_plot = z
                norm = None

            fig, ax = plt.subplots(figsize=(7.2, max(4.0, 0.18 * len(pivot.index))))
            im = ax.imshow(z_plot, aspect="auto", interpolation="nearest", cmap="viridis", norm=norm)
            ax.set_yticks(range(len(pivot.index)))
            ax.set_yticklabels(pivot.index)
            ax.set_xticks(range(len(pivot.columns)))
            ax.set_xticklabels([int(x) for x in pivot.columns], rotation=45, ha="right")
            ax.set_title(f"Sobol {val_col} heatmap: {metric}")
            ax.set_xlabel("DAP")
            ax.set_ylabel("Parameter")
            cbar = fig.colorbar(im, ax=ax)
            cbar.set_label(val_col)
            safe_metric = re.sub(r"[^A-Za-z0-9_\-]", "_", str(metric))
            _save_multi(fig, os.path.join(out_dir, f"sobol_heatmap_{safe_metric}_{val_col}"), formats=formats, dpi=dpi)
            plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--formats", default="png,svg")
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument("--base-font-size", type=int, default=10)
    parser.add_argument("--heatmap-percentile", type=float, default=99.0)
    parser.add_argument("--plot-mode", default="compact", choices=["compact", "full"])
    args = parser.parse_args()

    case_dir = os.path.normpath(args.case_dir) if args.case_dir else _default_case_dir()
    out_dir = (
        os.path.normpath(args.out_dir)
        if args.out_dir
        else os.path.join(os.path.dirname(case_dir), "sobol_results")
    )
    formats = [s.strip() for s in str(args.formats).split(",") if s.strip()]
    postprocess_sobol(
        case_dir=case_dir,
        out_dir=out_dir,
        top_n=args.top_n,
        formats=formats,
        dpi=args.dpi,
        base_font_size=args.base_font_size,
        heatmap_percentile=args.heatmap_percentile,
        plot_mode=args.plot_mode,
    )
    print(f"Wrote: {out_dir}")


if __name__ == "__main__":
    main()
