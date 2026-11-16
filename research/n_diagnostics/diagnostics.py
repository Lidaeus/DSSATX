"""Portable DSSAT diagnostics from explicitly selected outputs and treatment metadata."""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

from data import KEY, NORDER, dump, native_table, sha


COLORS = {"N0": "#707070", "N1": "#2980B9", "N2": "#E67E22", "N3": "#C0392B"}
SHAPES = {"W3": "o", "W2": "s", "W1": "^", "CK": "D"}
FRESH_UNITS = {"kg fresh/ha", "kg fresh ha-1"}
JOIN = ["season_id", "treatment"]


def read_metadata(path, season):
    meta = pd.read_csv(path)
    if "season_id" not in meta and season:
        meta["season_id"] = season
    required = JOIN + ["water_level", "nitrogen_level"]
    if not set(required).issubset(meta) or meta[required].isna().any().any():
        raise ValueError("Metadata needs treatment, water_level, nitrogen_level and season_id (or --season)")
    if season:
        meta = meta.loc[meta.season_id.eq(season)].copy()
    if meta.empty or meta.duplicated(JOIN).any():
        raise ValueError("Selected metadata must have unique season/treatment keys")
    if meta.duplicated(["season_id", "water_level", "nitrogen_level"]).any():
        raise ValueError("Multiple treatments in a water × nitrogen cell need explicit aggregation upstream")
    if not set(meta.water_level) <= SHAPES.keys() or not set(meta.nitrogen_level) <= set(NORDER):
        raise ValueError("Supported water levels are W1/W2/W3/CK and nitrogen levels are N0–N3")
    return meta


def select_season(data, season):
    if "season_id" not in data and season:
        data["season_id"] = season
    if "season_id" not in data or data.season_id.isna().any():
        raise ValueError("Supply season_id in the data or set --season explicitly")
    return data.loc[data.season_id.eq(season)].copy() if season else data


def normalize_keys(data, aliases):
    for old, new in aliases.items():
        if old not in data:
            continue
        if new in data:
            if not data[old].eq(data[new]).all():
                raise ValueError(f"Conflicting keys: {old} and {new}")
            data = data.drop(columns=old)
        else:
            data = data.rename(columns={old: new})
    return data


def final_comparison(path, season):
    data = normalize_keys(pd.read_csv(path), {"trno": "treatment", "season": "season_id"})
    data = select_season(data, season)
    required = JOIN + ["date", "variable", "unit", "observed"]
    if not set(required).issubset(data):
        raise ValueError(f"Comparison needs {required}")
    is_final = data.get("family", pd.Series("", index=data.index)).eq("FINAL_FRESH_YIELD")
    selected = data.loc[data.variable.eq("CHFPW") | is_final].copy()
    selected["explicit_final"] = is_final.loc[selected.index]
    if selected.empty or not set(selected.unit) <= FRESH_UNITS:
        raise ValueError("Comparison needs cumulative fresh yield (CHFPW) in kg fresh/ha")
    selected["date"] = pd.to_datetime(selected.date, format="%Y-%m-%d").dt.strftime("%Y-%m-%d")
    selected = selected.loc[
        selected.explicit_final.eq(selected.groupby(JOIN).explicit_final.transform("max"))
    ]
    selected = selected.loc[selected.date.eq(selected.groupby(JOIN).date.transform("max"))]
    if selected.duplicated(JOIN).any():
        raise ValueError("Duplicate final fresh-yield rows for a treatment")
    return selected


def pair_with_metadata(data, meta):
    columns = JOIN + [c for c in ["water_level", "nitrogen_level", "dataset_role"] if c in meta]
    paired = data.merge(meta[columns], on=JOIN, how="outer", validate="one_to_one", indicator=True)
    if not paired["_merge"].eq("both").all():
        bad = paired.loc[paired["_merge"].ne("both"), JOIN + ["_merge"]].to_dict("records")
        raise ValueError(f"Yield and metadata coverage differ: {bad}")
    return paired.drop(columns="_merge").sort_values(["season_id", "water_level", "nitrogen_level"])


def yield_data(args, meta):
    if args.terminal:
        frame = normalize_keys(pd.read_csv(args.terminal), {"season": "season_id", "tn": "treatment"})
        frame = select_season(frame, args.season)
        if "variable" in frame and not frame.variable.eq("CHFPW").all():
            raise ValueError("Terminal file must contain cumulative fresh yield only")
        if "unit" in frame and not set(frame.unit) <= FRESH_UNITS | {"t/ha", "t fresh/ha"}:
            raise ValueError("Terminal file has an unsupported source unit")
        if "comparison_status" in frame and not frame.comparison_status.eq("matched").all():
            raise ValueError("Terminal file contains unmatched rows")
        source = [args.terminal]
        return pair_with_metadata(frame[JOIN + ["date", "obs_t_ha", "sim_t_ha"]], meta), source

    observed = final_comparison(args.comparison, args.season) if args.comparison else None
    if not args.case_dir:
        if observed is None or "simulated" not in observed:
            raise ValueError("Comparison-only mode needs current paired simulated values")
        if "comparison_status" in observed and not observed.comparison_status.eq("matched").all():
            raise ValueError("Final comparison contains unmatched rows")
        frame = observed[JOIN + ["date"]].assign(
            obs_t_ha=observed.observed / 1000, sim_t_ha=observed.simulated / 1000)
        return pair_with_metadata(frame, meta), [args.comparison]

    native_path = args.case_dir / "FreshWt.OUT"
    fresh = native_table(native_path)
    if set(fresh.treatment) != set(meta.treatment):
        raise ValueError("FreshWt.OUT treatment coverage differs from metadata")
    expected_labels = meta.set_index("treatment").get("treatment_label")
    if expected_labels is not None and not fresh.treatment.map(expected_labels).eq(fresh.treatment_label_native).all():
        raise ValueError("FreshWt.OUT treatment labels differ from metadata")
    fresh = fresh.sort_values("yrdoy")
    if fresh[["treatment", "yrdoy"]].duplicated().any() or not fresh.groupby("treatment").run.nunique().eq(1).all():
        raise ValueError("Expected one simulated run per treatment and date")
    if not np.isfinite(fresh.CHFPW).all() or fresh.CHFPW.lt(0).any() or fresh.groupby("treatment").CHFPW.diff().lt(-.11).any():
        raise ValueError("Invalid native cumulative fresh yield")
    fresh["date"] = pd.to_datetime(fresh.yrdoy.astype(str), format="%Y%j").dt.strftime("%Y-%m-%d")
    fresh["season_id"] = args.season
    endpoint = fresh.groupby("treatment").tail(1)
    if observed is None:
        frame = endpoint[JOIN + ["date"]].assign(obs_t_ha=np.nan, sim_t_ha=endpoint.CHFPW / 1000)
        return pair_with_metadata(frame, meta), [native_path]
    same_day = observed[JOIN + ["date", "observed"]].merge(
        fresh[JOIN + ["date", "CHFPW"]], on=JOIN + ["date"], how="left", validate="one_to_one")
    end_yield = same_day.treatment.map(endpoint.set_index("treatment").CHFPW)
    if same_day.CHFPW.isna().any() or not np.allclose(same_day.CHFPW, end_yield, atol=.11, rtol=0):
        raise ValueError("Final observation date is missing from FreshWt.OUT or differs from its terminal cumulative yield")
    frame = same_day[JOIN + ["date"]].assign(
        obs_t_ha=same_day.observed / 1000, sim_t_ha=same_day.CHFPW / 1000)
    return pair_with_metadata(frame, meta), [native_path, args.comparison]


def contrasts(frame):
    records = []
    for (season, water), group in frame.groupby(["season_id", "water_level"]):
        by_n = group.set_index("nitrogen_level")
        for low in ("N0", "N2"):
            if {"N3", low} <= set(by_n.index):
                obs, sim = (1000 * (by_n.at["N3", field] - by_n.at[low, field])
                            for field in ["obs_t_ha", "sim_t_ha"])
                records.append(dict(season_id=season, water_level=water, contrast=f"N3-{low}",
                                    observed_kg_ha=obs, simulated_kg_ha=sim, error_kg_ha=sim-obs))
    return pd.DataFrame(records, columns=["season_id", "water_level", "contrast",
                                          "observed_kg_ha", "simulated_kg_ha", "error_kg_ha"])


def render_yield(frame, delta, out, label):
    seasons = sorted(frame.season_id.unique())
    fig, axes = plt.subplots(1, len(seasons), figsize=(6.0 * len(seasons), 5.25),
                             squeeze=False, sharey=True)
    fig.subplots_adjust(left=.09 if len(seasons) > 1 else .14, right=.975, bottom=.23, top=.77, wspace=.16)
    fig.suptitle("Final fresh yield across nitrogen levels", fontsize=16, fontweight="bold", y=.97)
    fig.text(.5, .90, label, ha="center", fontsize=9, color="#475569")
    for ax, season in zip(axes[0], seasons):
        selected = frame.loc[frame.season_id.eq(season)]
        for water in SHAPES:
            q = selected.loc[selected.water_level.eq(water)].set_index("nitrogen_level").reindex(NORDER)
            if q.sim_t_ha.isna().all():
                continue
            x = np.arange(len(NORDER))
            ax.plot(x, q.sim_t_ha, color="#53565A", lw=1.5)
            ax.scatter(x, q.sim_t_ha, marker=SHAPES[water], s=57, facecolor="white",
                       edgecolors=list(COLORS.values()), linewidths=1.4, zorder=4)
            ax.scatter(x, q.obs_t_ha, marker=SHAPES[water], s=55, c=list(COLORS.values()),
                       edgecolors="#222222", linewidths=1, zorder=5)
        role = selected.dataset_role.dropna().unique() if "dataset_role" in selected else []
        ax.set_title(f"{season}  ({role[0]})" if len(role) == 1 else season, fontweight="bold")
        ax.set_xticks(range(4), NORDER)
        ax.set_xlim(-.22, 3.22)
        ax.grid(axis="y", color="#E1E5E9", lw=.8)
        ax.spines[["top", "right"]].set_visible(False)
        q = delta.loc[delta.season_id.eq(season) & delta.contrast.eq("N3-N2")]
        if len(q):
            items = []
            for row in q.itertuples():
                obs = f"{row.observed_kg_ha:+.0f}" if np.isfinite(row.observed_kg_ha) else "—"
                items.append(f"{row.water_level}  {row.simulated_kg_ha:+.0f} / {obs}")
            ax.text(.5, -.15, "N3 − N2 (kg/ha) · model / observed\n" + "     ".join(items),
                    ha="center", va="top", transform=ax.transAxes, fontsize=9, color="#334155")
    axes[0, 0].set_ylabel("Final fresh fruit yield (t/ha)")
    handles = [
        Line2D([], [], color="#53565A", marker="o", mfc="white", label="Model"),
        Line2D([], [], color="#222222", marker="o", ls="", label="Observed"),
    ]
    if frame.obs_t_ha.isna().all():
        handles.pop()
    handles += [Line2D([], [], color="#53565A", marker=marker, ls="", label=water)
                for water, marker in SHAPES.items() if water in set(frame.water_level)]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .865),
               frameon=False, ncol=len(handles), fontsize=9)
    fig.savefig(out / "diagnostic_nitrogen_yield_response.png", dpi=200, facecolor="white")
    plt.close(fig)


def yield_command(args):
    if args.case_dir and not args.season:
        raise ValueError("--case-dir requires --season")
    if args.terminal and (args.case_dir or args.comparison):
        raise ValueError("--terminal is an independent input mode")
    meta = read_metadata(args.metadata, args.season)
    frame, sources = yield_data(args, meta)
    if frame.date.isna().any() or not np.isfinite(frame.sim_t_ha).all() or frame.sim_t_ha.lt(0).any():
        raise ValueError("Every treatment needs a date and a finite, nonnegative simulated final yield")
    if (args.comparison or args.terminal) and (
        not np.isfinite(frame.obs_t_ha).all() or frame.obs_t_ha.lt(0).any()
    ):
        raise ValueError("Every paired treatment needs a finite, nonnegative observed final yield")
    delta = contrasts(frame)
    args.out.mkdir(parents=True, exist_ok=False)
    frame.assign(error_t_ha=frame.sim_t_ha-frame.obs_t_ha).to_csv(
        args.out / "diagnostic_nitrogen_yield_response.source.csv", index=False)
    delta.to_csv(args.out / "diagnostic_nitrogen_yield_response.contrasts.csv", index=False)
    matched = frame.dropna(subset=["obs_t_ha"])
    if len(matched):
        scores = []
        for season, group in matched.groupby("season_id"):
            residual = group.sim_t_ha - group.obs_t_ha
            scores.append({"season_id": season, "n_treatments": len(group),
                           "rmse_t_ha": np.sqrt((residual ** 2).mean()),
                           "mean_bias_t_ha": residual.mean()})
        pd.DataFrame(scores).to_csv(args.out / "diagnostic_final_yield_fit.csv", index=False)
    render_yield(frame, delta, args.out, args.label)
    dump(args.out / "diagnostic_manifest.json", {
        "source_sha256": {str(p.resolve()): sha(p) for p in [*sources, args.metadata]},
        "renderer_sha256": sha(__file__),
        "diagnostic_only": True,
        "fresh_yield": "cumulative harvested fresh fruit",
    })
    print(args.out / "diagnostic_nitrogen_yield_response.png")


def daily_command(args):
    meta = read_metadata(args.metadata, args.season)
    path = args.case_dir / args.file
    base_path = args.case_dir / "PlantGro.OUT"
    base = native_table(base_path)
    labels = meta.set_index("treatment").get("treatment_label")
    if labels is not None and not base.treatment.map(labels).eq(base.treatment_label_native).all():
        raise ValueError("PlantGro.OUT treatment labels differ from metadata")
    if (set(base.treatment) != set(meta.treatment)
        or not base.groupby("treatment").run.nunique().eq(1).all()
        or not base.groupby("run").treatment.nunique().eq(1).all()):
        raise ValueError("Expected one simulated run per mapped treatment")
    data = pd.read_csv(path) if path.suffix.lower() == ".csv" else native_table(path)
    if args.layer is not None:
        data = data.loc[data.layer.eq(args.layer)].copy()
    if data.duplicated(KEY).any():
        raise ValueError("Expected unique run/day rows. Choose --layer for a layer-wise trace.")
    run_map = base[["run", "treatment"]].drop_duplicates().set_index("run").treatment
    for identity in ("treatment", "trt"):
        if identity in data and not data[identity].eq(data.run.map(run_map)).all():
            raise ValueError(f"{args.file} has a different run-to-treatment mapping from PlantGro.OUT")
    fields = dict((item.split(":", 1) + [""])[:2] for item in args.field)
    data = data[KEY + list(fields)]
    daily = base[KEY + ["treatment", "DAP"]].merge(data, on=KEY, how="left", validate="one_to_one")
    daily = daily.merge(meta, on="treatment", validate="many_to_one").sort_values(["treatment", "DAP"])
    for field in fields:
        daily[field] = pd.to_numeric(daily[field], errors="raise")
        if np.isinf(daily[field]).any() or not np.isfinite(daily[field]).any():
            raise ValueError(f"No finite values for {field}")
    waters = [w for w in SHAPES if w in set(daily.water_level)]
    fig, axes = plt.subplots(len(fields), len(waters), figsize=(4.0 * len(waters), 2.15 * len(fields) + 1.15),
                             squeeze=False, sharex=True, sharey="row", layout="constrained")
    fig.suptitle(f"{args.label}  |  {args.season}  |  {args.file}", fontsize=13, fontweight="bold")
    for i, (field, unit) in enumerate(fields.items()):
        for j, water in enumerate(waters):
            ax = axes[i, j]
            for n in NORDER:
                q = daily.loc[daily.water_level.eq(water) & daily.nitrogen_level.eq(n)]
                ax.plot(q.DAP, q[field], color=COLORS[n], label=n, lw=1.25)
            if i == 0:
                ax.set_title(water)
            if i == len(fields)-1:
                ax.set_xlabel("Days after planting (DAP)")
            if j == 0:
                ax.set_ylabel(f"{field}\n{unit}" if unit else field)
            ax.grid(axis="y", color="#E1E5E9", lw=.7)
    axes[0, -1].legend(frameon=False, fontsize=8)
    args.out.mkdir(parents=True, exist_ok=False)
    daily.to_csv(args.out / "diagnostic_daily_variables.source.csv", index=False)
    fig.savefig(args.out / "diagnostic_daily_variables.png", dpi=180)
    plt.close(fig)
    dump(args.out / "diagnostic_manifest.json", {
        "source_sha256": {str(p.resolve()): sha(p) for p in {path, base_path, args.metadata}},
        "fields": fields, "layer": args.layer, "diagnostic_only": True,
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    y = commands.add_parser("yield", help="Draw final fresh yield and N3−N2")
    y.add_argument("--terminal", type=Path, help="Existing terminal_fresh_yield_for_plot.csv")
    y.add_argument("--comparison", type=Path, help="Comparison table with CHFPW observations")
    y.add_argument("--case-dir", type=Path, help="Use this case's FreshWt.OUT for simulated values")
    d = commands.add_parser("daily", help="Draw selected columns from a native OUT or trace CSV")
    d.add_argument("--case-dir", type=Path, required=True)
    d.add_argument("--file", required=True)
    d.add_argument("--field", action="append", required=True, help="Column or Column:unit")
    d.add_argument("--layer", type=int)
    for command in (y, d):
        command.add_argument("--metadata", type=Path, required=True)
        command.add_argument("--season", required=command is d)
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--label", default="DSSAT run diagnostic")
    args = parser.parse_args()
    (yield_command if args.command == "yield" else daily_command)(args)


if __name__ == "__main__":
    main()
