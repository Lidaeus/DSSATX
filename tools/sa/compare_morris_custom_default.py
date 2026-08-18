"""Compare the custom nitrogen-response DSSAT Morris run with the default run.

This is a diagnostic renderer/data exporter, not a paper-figure renderer.  It
keeps the project's two Morris ranking domains separate and reports two
custom-version scales:

* ``score_full81``: the official within-observation share using all 81 custom
  parameters;
* ``score_common_default``: the same share re-normalised over the active
  parameters shared with the default candidate set, for a less confounded common-set
  comparison.

The default baseline is the existing three-seed consensus group-score table.
The custom result is restricted to quality-passing seed cases only.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SEASON_LABELS = {"XXQL2501": "25SP", "XXQL2601": "26SP"}
DOMAIN_ORDER = ["general_genetic", "water_nitrogen_response"]
GROUP_ORDER = [
    "phenology", "canopy", "biomass", "organ_n",
    "yield_harvest", "water_response", "nitrogen_response",
    "water_nitrogen_interaction",
]
GROUP_LABELS = {
    "phenology": "Phenology",
    "canopy": "Canopy",
    "biomass": "Biomass",
    "organ_n": "Organ N",
    "yield_harvest": "Harvest",
    "water_response": "Water response",
    "nitrogen_response": "Nitrogen response",
    "water_nitrogen_interaction": "Water × nitrogen",
}
DOMAIN_LABELS = {
    "general_genetic": "General genetic effects",
    "water_nitrogen_response": "Water–nitrogen response",
}


def read_contract(path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    groups = data["response_groups"]
    feature_to_group: dict[str, str] = {}
    for group, features in groups.items():
        for feature in features:
            feature_to_group[str(feature).upper()] = str(group)
    return feature_to_group, {str(k): [str(x) for x in v] for k, v in groups.items()}


def response_group(observation: str, feature_to_group: dict[str, str]) -> tuple[str, str] | None:
    obs = str(observation).strip().upper()
    if obs.startswith("WN_WATER_"):
        return "water_response", "water_nitrogen_response"
    if obs.startswith("WN_NSLOPE_"):
        return "nitrogen_response", "water_nitrogen_response"
    if obs.startswith("WN_INTERACTION_"):
        return "water_nitrogen_interaction", "water_nitrogen_response"
    match = re.match(r"^TN\d+_(.+)$", obs)
    if not match:
        return None
    feature = match.group(1)
    feature = re.sub(r"_DAP\d{3}$", "_DAP", feature)
    group = feature_to_group.get(feature)
    if group is None:
        return None
    domain = "water_nitrogen_response" if group.startswith("water_") else "general_genetic"
    if group in {"nitrogen_response", "water_nitrogen_interaction"}:
        domain = "water_nitrogen_response"
    return group, domain


def custom_scores(case_dir: Path, season: str, feature_to_group: dict[str, str]) -> pd.DataFrame:
    quality_path = case_dir / "morris_audit" / "morris_run_quality.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    if not bool(quality.get("science_validated")):
        raise ValueError(f"Custom case is not quality-passing: {case_dir}")
    frame = pd.read_csv(case_dir / "sa_sen_morris.mio")
    frame["parameter"] = frame["parameter_name"].astype(str).str.upper()
    frame["observation"] = frame["observation_name"].astype(str)
    frame["mu_star"] = pd.to_numeric(frame["sen_mean_abs"], errors="coerce")
    mapped = frame["observation"].map(lambda x: response_group(x, feature_to_group))
    frame["group"] = [x[0] if x else None for x in mapped]
    frame["domain"] = [x[1] if x else None for x in mapped]
    frame = frame.dropna(subset=["group", "domain", "mu_star"])
    frame = frame[frame["mu_star"] >= 0].copy()
    all_parameters = sorted(frame["parameter"].unique())
    default_parameters = set(pd.read_csv(DEFAULT_GROUP_SCORES[season])["parameter"].astype(str).str.upper())
    common_parameters = sorted(set(all_parameters) & default_parameters)
    obs_total_full = frame.groupby("observation")["mu_star"].transform("sum")
    frame["share_full81"] = np.where(obs_total_full > 0, frame["mu_star"] / obs_total_full, np.nan)
    common = frame[frame["parameter"].isin(common_parameters)].copy()
    obs_total_common = common.groupby("observation")["mu_star"].transform("sum")
    common["share_common_default"] = np.where(obs_total_common > 0, common["mu_star"] / obs_total_common, np.nan)
    frame = frame.merge(
        common[["observation", "parameter", "share_common_default"]],
        on=["observation", "parameter"], how="left",
    )
    # The official rank score is the mean of normalized effects across the
    # contracted response features within each response group.
    out = (frame.groupby(["group", "domain", "parameter"], as_index=False)
           .agg(score_full81=("share_full81", "mean"), score_common_default=("share_common_default", "mean"),
                observation_count=("observation", "nunique")))
    out["season"] = season
    out["parameter_count_full"] = len(all_parameters)
    out["parameter_count_common"] = len(common_parameters)
    out["source_case"] = str(case_dir)
    return out


def default_scores(default_root: Path) -> pd.DataFrame:
    rows = []
    for season in SEASON_LABELS:
        path = default_root / season / "r10" / "morris_seed_group_scores.csv"
        frame = pd.read_csv(path)
        frame["season"] = season
        frame["parameter"] = frame["parameter"].astype(str).str.upper()
        # r10 contains the three default seeds; averaging their group scores
        # reproduces the season-level consensus scale used by the project.
        rows.append(frame.groupby(["season", "response_group", "ranking_domain", "parameter"], as_index=False)
                    .agg(score_default=("group_score", "mean"), default_seed_count=("seed", "nunique")))
    out = pd.concat(rows, ignore_index=True).rename(columns={"response_group": "group", "ranking_domain": "domain"})
    return out


def rank(frame: pd.DataFrame, score_col: str, rank_col: str) -> pd.DataFrame:
    frame = frame.copy()
    frame[rank_col] = frame.groupby(["season", "domain"])[score_col].rank(method="min", ascending=False)
    return frame


def save_plot(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path, dpi=420, bbox_inches="tight")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def plot_top_comparison(comp: pd.DataFrame, out: Path) -> None:
    rows = []
    for domain in DOMAIN_ORDER:
        part = comp[comp["domain"].eq(domain)].copy()
        top = (part.groupby("parameter")["score_default"].mean().nlargest(12).index
               .union(part.groupby("parameter")["score_common_default"].mean().nlargest(12).index))
        part = part[part["parameter"].isin(top)]
        summary = part.groupby("parameter", as_index=False).agg(default=("score_default", "mean"), custom=("score_common_default", "mean"))
        summary["domain"] = domain
        rows.append(summary)
    plot = pd.concat(rows, ignore_index=True)
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 7.6), sharex=False)
    colors = {"default": "#536D8A", "custom": "#C44E52"}
    for ax, domain in zip(axes, DOMAIN_ORDER):
        p = plot[plot["domain"].eq(domain)].copy()
        p["order"] = p[["default", "custom"]].max(axis=1)
        p = p.sort_values("order")
        y = np.arange(len(p))
        ax.hlines(y, p["default"], p["custom"], color="#B9BFC7", lw=1.3, zorder=1)
        ax.scatter(p["default"], y, s=42, color=colors["default"], label="Default DSSAT", zorder=2)
        ax.scatter(p["custom"], y, s=42, color=colors["custom"], label="Custom N-response DSSAT", zorder=3)
        ax.set_yticks(y, p["parameter"])
        ax.set_title(DOMAIN_LABELS[domain])
        ax.set_xlabel("Mean normalized Morris effect\n(common active-parameter denominator)")
        ax.grid(axis="x", color="#E6E8EB", lw=.8)
        ax.spines[["top", "right", "left"]].set_visible(False)
    axes[1].legend(frameon=False, loc="lower right")
    fig.suptitle("Custom versus default Morris sensitivity", y=.995, fontsize=15, weight="bold")
    fig.tight_layout()
    save_plot(fig, out / "diagnostic_morris_custom_vs_default_top_parameters.png")


def plot_delta(comp: pd.DataFrame, out: Path) -> None:
    p = comp.groupby(["domain", "parameter"], as_index=False).agg(default=("score_default", "mean"), custom=("score_common_default", "mean"))
    p["delta"] = p["custom"] - p["default"]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 8.2), sharey=False)
    for ax, domain in zip(axes, DOMAIN_ORDER):
        q = p[p["domain"].eq(domain)].sort_values("delta")
        colors = np.where(q["delta"] >= 0, "#C44E52", "#4C78A8")
        y = np.arange(len(q))
        ax.axvline(0, color="#333333", lw=.8)
        ax.barh(y, q["delta"], color=colors, alpha=.86)
        ax.set_yticks(y, q["parameter"])
        ax.set_xlabel("Custom − default effect")
        ax.set_title(DOMAIN_LABELS[domain])
        ax.grid(axis="x", color="#E6E8EB", lw=.8)
        ax.spines[["top", "right", "left"]].set_visible(False)
    fig.suptitle("Change in Morris effect for common parameters", y=.995, fontsize=15, weight="bold")
    fig.tight_layout()
    save_plot(fig, out / "diagnostic_morris_custom_minus_default_delta.png")


def plot_new_parameters(custom: pd.DataFrame, out: Path) -> None:
    p = (custom[custom["parameter"].isin(["NREXP", "NRMIN"])]
         .groupby(["season", "domain", "parameter"], as_index=False)
         .agg(score=("score_full81", "mean")))
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 5.6), sharey=True)
    colors = {"NREXP": "#D95F02", "NRMIN": "#7570B3"}
    season_order = ["XXQL2501", "XXQL2601"]
    x = np.arange(len(season_order))
    width = .34
    for ax, domain in zip(axes, DOMAIN_ORDER):
        q = p[p["domain"].eq(domain)]
        for i, parameter in enumerate(["NREXP", "NRMIN"]):
            values = [float(q[(q["season"] == season) & (q["parameter"] == parameter)]["score"].iloc[0]) for season in season_order]
            ax.bar(x + (i - .5) * width, values, width=width, color=colors[parameter], label=parameter)
        ax.set_xticks(x, ["25SP", "26SP"])
        ax.set_title(DOMAIN_LABELS[domain])
        ax.grid(axis="y", color="#E6E8EB", lw=.8)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Normalized Morris effect (full 81-parameter domain)")
    axes[1].legend(frameon=False, title="Custom parameter")
    fig.suptitle("Sensitivity of the custom nitrogen-response parameters", y=.995, fontsize=14, weight="bold")
    fig.tight_layout()
    save_plot(fig, out / "diagnostic_morris_custom_parameters_nrexp_nrmin.png")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--custom-root", type=Path, required=True)
    parser.add_argument("--default-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--profile-25sp", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    global DEFAULT_GROUP_SCORES
    DEFAULT_GROUP_SCORES = {season: args.default_root / season / "r10" / "morris_seed_group_scores.csv" for season in SEASON_LABELS}
    custom_parts = []
    for season, seed in [("XXQL2501", "seed_20260804"), ("XXQL2601", "seed_20260803")]:
        case = args.custom_root / season / seed
        feature_to_group, _ = read_contract(args.profile_25sp if season == "XXQL2501" else args.profile_25sp.parent / "eggplant_formal_xxql2601_outputs_20260720.json")
        custom_parts.append(custom_scores(case, season, feature_to_group))
    custom = pd.concat(custom_parts, ignore_index=True)
    default = default_scores(args.default_root)
    common_params = set(custom["parameter"]) & set(default["parameter"])
    # The custom executable also emits an organ-N response family.  The
    # default baseline has no corresponding organ-N outputs, so the common
    # executable comparison excludes that family while the full custom rank
    # retains it as a genuine model-output difference.
    custom_common = custom[~custom["group"].eq("organ_n")].copy()
    custom_param = (custom.groupby(["season", "domain", "parameter"], as_index=False)
                    .agg(score_full81=("score_full81", "mean"), score_common_default=("score_common_default", "mean")))
    custom_common_param = (custom_common.groupby(["season", "domain", "parameter"], as_index=False)
                           .agg(score_full81=("score_full81", "mean"), score_common_default=("score_common_default", "mean")))
    default_param = (default.groupby(["season", "domain", "parameter"], as_index=False)
                     .agg(score_default=("score_default", "mean")))
    comp = custom_common_param[custom_common_param["parameter"].isin(common_params)].merge(
        default_param[default_param["parameter"].isin(common_params)], on=["season", "domain", "parameter"], how="inner"
    )
    comp = rank(comp, "score_default", "rank_default")
    comp = rank(comp, "score_common_default", "rank_custom")
    custom_param["rank_full81"] = custom_param.groupby(["season", "domain"])["score_full81"].rank(method="min", ascending=False)
    custom_param["rank_common_default"] = custom_param.groupby(["season", "domain"])["score_common_default"].rank(method="min", ascending=False)
    custom.to_csv(args.out_dir / "custom_morris_effects.csv", index=False)
    default.to_csv(args.out_dir / "default_morris_effects.csv", index=False)
    comp.to_csv(args.out_dir / "morris_common_parameter_comparison.csv", index=False)
    custom_new = custom_param[custom_param["parameter"].isin(["NREXP", "NRMIN"])].copy()
    nresp_group = (custom[custom["parameter"].isin(["NREXP", "NRMIN"]) & custom["group"].eq("nitrogen_response")]
                   .groupby(["season", "domain", "parameter"], as_index=False)
                   .agg(nitrogen_response_score_full81=("score_full81", "mean")))
    custom_new = custom_new.merge(nresp_group, on=["season", "domain", "parameter"], how="left")
    custom_new.to_csv(args.out_dir / "custom_nresp_parameter_effects.csv", index=False)
    custom_group = custom_common[custom_common["parameter"].isin(common_params)]
    default_group = default[default["parameter"].isin(common_params)]
    group_comp = custom_group.merge(default_group, on=["season", "group", "domain", "parameter"], how="inner")
    group_summary = (group_comp.groupby(["season", "domain", "group"], as_index=False)
                     .agg(default_group_score=("score_default", "mean"), custom_group_score_common_default=("score_common_default", "mean")))
    group_summary.to_csv(args.out_dir / "morris_group_comparison.csv", index=False)
    plot_top_comparison(comp, args.out_dir)
    plot_delta(comp, args.out_dir)
    plot_new_parameters(custom, args.out_dir)
    summary = {
        "custom_cases_used": [str(args.custom_root / "XXQL2501" / "seed_20260804"), str(args.custom_root / "XXQL2601" / "seed_20260803")],
        "custom_cases_excluded": ["XXQL2501/seed_20260803 (quality failed)", "XXQL2601/seed_20260804 (quality failed)"],
        "custom_parameter_count": int(custom["parameter"].nunique()),
        "default_parameter_count": int(default["parameter"].nunique()),
        "common_active_parameter_count": int(len(common_params)),
        "custom_parameter_names": sorted(set(custom["parameter"]) - set(default["parameter"])),
        "custom_full_domain_note": "Full-domain score uses all custom parameters and includes the custom organ-N response family; score_common_default is re-normalized over the shared active default parameter set and excludes organ-N outputs from the cross-version comparison.",
        "default_seed_count": int(default["default_seed_count"].max()),
    }
    (args.out_dir / "comparison_manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
