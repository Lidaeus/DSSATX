import argparse
import os

import numpy as np
import pandas as pd


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _as_num(s):
    try:
        return pd.to_numeric(s, errors="coerce")
    except Exception:
        return pd.Series([np.nan] * len(s))


def _filter_pairs(df, obs_col, sim_col):
    o = _as_num(df.get(obs_col))
    s = _as_num(df.get(sim_col))
    ok = np.isfinite(o) & np.isfinite(s)
    ok = ok & (o != -99) & (s != -99)
    return df.loc[ok].copy(), o.loc[ok].astype(float), s.loc[ok].astype(float)


def _rmse_nrmse_d(obs, sim):
    from analyze_results import _rmse_nrmse_d as _impl

    return _impl(obs, sim)


def _scatter_1to1(df, obs_col, sim_col, title, out_png):
    import matplotlib.pyplot as plt

    dff, o, s = _filter_pairs(df, obs_col, sim_col)
    if dff.empty:
        return None

    n, rmse, nrmse, d = _rmse_nrmse_d(o, s)
    fig, ax = plt.subplots(figsize=(6.2, 5.4), dpi=150)
    ax.scatter(o, s, s=18, alpha=0.85)
    vmin = float(np.nanmin([o.min(), s.min()]))
    vmax = float(np.nanmax([o.max(), s.max()]))
    pad = 0.05 * (vmax - vmin) if vmax > vmin else 1.0
    ax.plot([vmin - pad, vmax + pad], [vmin - pad, vmax + pad], color="black", linewidth=1)
    ax.set_xlim(vmin - pad, vmax + pad)
    ax.set_ylim(vmin - pad, vmax + pad)
    ax.set_xlabel(f"OBS ({obs_col})")
    ax.set_ylabel(f"SIM ({sim_col})")
    ax.set_title(title)
    ax.text(
        0.02,
        0.98,
        f"n={n}\nRMSE={rmse:.3g}\nNRMSE={nrmse:.3g}\nd-index={d:.3g}",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor="0.8", alpha=0.9),
    )
    fig.tight_layout()
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
    return out_png


def _facet_timeseries(df, tn_col, date_col, pairs, title, out_png, ncols=5):
    import matplotlib.pyplot as plt

    if tn_col not in df.columns or date_col not in df.columns:
        return None
    tns = sorted([t for t in pd.unique(df[tn_col]) if pd.notna(t)])
    if not tns:
        return None

    n = len(tns)
    ncols = int(max(1, ncols))
    nrows = int((n + ncols - 1) // ncols)
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(3.6 * ncols, 2.6 * nrows), dpi=150, sharex=False)
    axes = np.array(axes).reshape(-1)

    for i, tn in enumerate(tns):
        ax = axes[i]
        d = df[df[tn_col] == tn].copy()
        d[date_col] = _as_num(d[date_col])
        d = d.sort_values(by=[date_col])

        for obs_col, sim_col, lab in pairs:
            dff, o, s = _filter_pairs(d, obs_col, sim_col)
            if dff.empty:
                continue
            x = _as_num(dff[date_col]).astype(float)
            ax.plot(x, o.values, marker="o", markersize=3.0, linewidth=1.0, label=f"OBS {lab}")
            ax.plot(x, s.values, marker=None, linewidth=1.5, label=f"SIM {lab}")

        ax.set_title(f"TN={tn}")
        ax.grid(True, alpha=0.25)

    for j in range(len(tns), len(axes)):
        axes[j].axis("off")

    handles, labels = [], []
    for ax in axes[: len(tns)]:
        h, lab_list = ax.get_legend_handles_labels()
        for hh, ll in zip(h, lab_list):
            if ll not in labels:
                labels.append(ll)
                handles.append(hh)
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=min(len(labels), 6), frameon=True)

    fig.suptitle(title, y=0.995)
    fig.tight_layout(rect=[0, 0.06, 1, 0.97])
    fig.savefig(out_png, bbox_inches="tight")
    plt.close(fig)
    return out_png


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prefix", required=True)
    p.add_argument("--results-dir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "workspace", "runs"))
    p.add_argument("--out-dir", default="")
    p.add_argument("--no-timeseries", action="store_true")
    args = p.parse_args()

    results_dir = os.path.abspath(args.results_dir)
    out_dir = args.out_dir.strip() or os.path.join(results_dir, "plots", args.prefix)
    _ensure_dir(out_dir)

    process_csv = os.path.join(results_dir, f"{args.prefix}_deterministic_process_compare.csv")
    harvest_csv = os.path.join(results_dir, f"{args.prefix}_deterministic_harvest_compare.csv")
    joint_csv = os.path.join(results_dir, f"{args.prefix}_deterministic_joint_compare.csv")

    if os.path.exists(process_csv):
        dfp = pd.read_csv(process_csv)
        _scatter_1to1(dfp, "OBS_LAID", "SIM_LAID", f"{args.prefix}: LAID", os.path.join(out_dir, "scatter_LAID.png"))
        _scatter_1to1(dfp, "OBS_LWAD", "SIM_LWAD", f"{args.prefix}: LWAD", os.path.join(out_dir, "scatter_LWAD.png"))
        _scatter_1to1(dfp, "OBS_SWAD", "SIM_SWAD", f"{args.prefix}: SWAD", os.path.join(out_dir, "scatter_SWAD.png"))
        if not args.no_timeseries:
            _facet_timeseries(
                dfp,
                tn_col="TN",
                date_col="DATE",
                pairs=[("OBS_LAID", "SIM_LAID", "LAID")],
                title=f"{args.prefix}: LAID time series by TN",
                out_png=os.path.join(out_dir, "timeseries_LAID_by_TN.png"),
            )

    if os.path.exists(harvest_csv):
        dfh = pd.read_csv(harvest_csv)
        _scatter_1to1(
            dfh,
            "OBS_FRESH_CUM",
            "SIM_FRESH_CUM",
            f"{args.prefix}: Fresh yield cumulative",
            os.path.join(out_dir, "scatter_fresh_cum.png"),
        )
        _scatter_1to1(
            dfh,
            "OBS_DRY_CUM",
            "SIM_DRY_CUM",
            f"{args.prefix}: Dry yield cumulative",
            os.path.join(out_dir, "scatter_dry_cum.png"),
        )
        if not args.no_timeseries:
            _facet_timeseries(
                dfh,
                tn_col="TN",
                date_col="DATE",
                pairs=[("OBS_FRESH_CUM", "SIM_FRESH_CUM", "FreshCum")],
                title=f"{args.prefix}: cumulative fresh yield by TN",
                out_png=os.path.join(out_dir, "timeseries_fresh_cum_by_TN.png"),
            )
            _facet_timeseries(
                dfh,
                tn_col="TN",
                date_col="DATE",
                pairs=[("OBS_DRY_CUM", "SIM_DRY_CUM", "DryCum")],
                title=f"{args.prefix}: cumulative dry yield by TN",
                out_png=os.path.join(out_dir, "timeseries_dry_cum_by_TN.png"),
            )

    if os.path.exists(joint_csv):
        dfj = pd.read_csv(joint_csv)
        _scatter_1to1(dfj, "OBS_HWAM", "SIM_HWAM", f"{args.prefix}: HWAM", os.path.join(out_dir, "scatter_HWAM.png"))
        _scatter_1to1(dfj, "OBS_LAIX", "SIM_LAIX", f"{args.prefix}: LAIX", os.path.join(out_dir, "scatter_LAIX.png"))
        _scatter_1to1(dfj, "OBS_CNAM", "SIM_CNAM", f"{args.prefix}: CNAM", os.path.join(out_dir, "scatter_CNAM.png"))

    print(out_dir)


if __name__ == "__main__":
    main()
