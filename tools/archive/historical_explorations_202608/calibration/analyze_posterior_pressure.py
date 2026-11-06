"""Audit posterior parameter pressure for a completed PEST-IES run.

The audit distinguishes ensemble-level mass at a bound from a single
best-member value at a bound.  It consumes only the frozen bounds and the
PEST++ parameter ensembles, and writes machine-readable tables plus a short
interpretive report.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _family(row: pd.Series) -> str:
    gp = str(row.get("pargp", ""))
    loc = str(row.get("location", ""))
    name = str(row.get("name", "")).lower()
    if name.startswith(("page_", "penv_")):
        return "seedling_PAGE_PENV"
    if gp.upper().startswith("SOIL") or name.startswith("soil_"):
        return "soil"
    if gp.upper().startswith("CUL") or loc.upper() == "CUL":
        return "cultivar_genetic"
    if gp.upper().startswith("ECO") or loc.upper() == "ECO":
        return "ecotype_genetic"
    if gp.upper().startswith("SPE") or loc.upper() == "SPE":
        return "species_genetic"
    return "other"


def audit(bounds_path: Path, posterior_path: Path, prior_path: Path, out_dir: Path) -> None:
    bounds = _read(bounds_path)
    bounds["name"] = bounds["name"].astype(str).str.lower()
    bounds = bounds.loc[bounds["status"].astype(str).str.lower().eq("active")].copy()
    post = _read(posterior_path)
    prior = _read(prior_path)
    # PEST++ appends a deterministic ``base`` row to each parameter ensemble;
    # it is not a posterior realization and must not enter fractions or
    # quantiles.  Keep the row separately only for traceability of the
    # selected best member.
    best_member = post.loc[post["real_name"].astype(str).eq("0")].iloc[0] if "real_name" in post.columns and (post["real_name"].astype(str) == "0").any() else None
    if "real_name" in post:
        post = post.loc[~post["real_name"].astype(str).str.lower().eq("base")].copy()
    if "real_name" in prior:
        prior = prior.loc[~prior["real_name"].astype(str).str.lower().eq("base")].copy()
    post.columns = [str(c).lower() for c in post.columns]
    prior.columns = [str(c).lower() for c in prior.columns]
    if "real_name" in post:
        post = post.drop(columns=["real_name"])
    if "real_name" in prior:
        prior = prior.drop(columns=["real_name"])

    rows: list[dict[str, object]] = []
    for _, b in bounds.iterrows():
        n = b["name"]
        if n not in post:
            continue
        lo, hi = float(b["lower"]), float(b["upper"])
        span = hi - lo
        vals = pd.to_numeric(post[n], errors="coerce").dropna().to_numpy(float)
        pvals = pd.to_numeric(prior[n], errors="coerce").dropna().to_numpy(float) if n in prior else np.array([])
        norm = (vals - lo) / span if span else np.full(vals.shape, np.nan)
        near_lo = norm <= 0.05
        near_hi = norm >= 0.95
        q05, q25, med, q75, q95 = np.quantile(vals, [0.05, 0.25, 0.50, 0.75, 0.95])
        pstd = float(np.std(pvals, ddof=1)) if len(pvals) > 1 else np.nan
        pmean = float(np.mean(pvals)) if len(pvals) else np.nan
        pstd_ratio = float(np.std(vals, ddof=1) / pstd) if pstd > 0 and len(vals) > 1 else np.nan
        rows.append(
            {
                "name": n,
                "pargp": b.get("pargp", ""),
                "family": _family(b),
                "location": b.get("location", ""),
                "file": b.get("file", ""),
                "init": float(b["init"]),
                "lower": lo,
                "upper": hi,
                "posterior_mean": float(np.mean(vals)),
                "posterior_median": float(med),
                "q05": float(q05),
                "q25": float(q25),
                "q75": float(q75),
                "q95": float(q95),
                "posterior_sd": float(np.std(vals, ddof=1)) if len(vals) > 1 else np.nan,
                "posterior_median_norm": float((med - lo) / span) if span else np.nan,
                "posterior_mean_norm": float((np.mean(vals) - lo) / span) if span else np.nan,
                "posterior_iqr_norm": float((q75 - q25) / span) if span else np.nan,
                "posterior_p90_width_norm": float((q95 - q05) / span) if span else np.nan,
                "near_lower_frac_5pct": float(np.mean(near_lo)),
                "near_upper_frac_5pct": float(np.mean(near_hi)),
                "boundary_pressure_5pct": float(max(np.mean(near_lo), np.mean(near_hi))),
                "dominant_boundary": "lower" if np.mean(near_lo) > np.mean(near_hi) else ("upper" if np.mean(near_hi) > np.mean(near_lo) else "none"),
                "prior_mean": pmean,
                "prior_sd": pstd,
                "posterior_to_prior_sd": pstd_ratio,
                "normalized_shift_from_prior_mean": float((np.mean(vals) - pmean) / span) if len(pvals) and span else np.nan,
                "best_value": float(best_member[n]) if best_member is not None and n in best_member else np.nan,
                "best_norm": float((float(best_member[n]) - lo) / span) if best_member is not None and n in best_member and span else np.nan,
                "best_near_boundary_5pct": bool((float(best_member[n]) - lo) / span <= 0.05 or (float(best_member[n]) - lo) / span >= 0.95) if best_member is not None and n in best_member and span else False,
            }
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df = df.sort_values(["boundary_pressure_5pct", "posterior_p90_width_norm"], ascending=[False, True])
    df.to_csv(out_dir / "posterior_parameter_pressure.csv", index=False, encoding="utf-8-sig")
    df.head(25).to_csv(out_dir / "posterior_parameter_pressure_top25.csv", index=False, encoding="utf-8-sig")

    group = (
        df.groupby("family", dropna=False)
        .agg(
            active_parameters=("name", "count"),
            mean_boundary_pressure_5pct=("boundary_pressure_5pct", "mean"),
            parameters_with_mass_ge_25pct=("boundary_pressure_5pct", lambda x: int((x >= 0.25).sum())),
            parameters_with_mass_ge_10pct=("boundary_pressure_5pct", lambda x: int((x >= 0.10).sum())),
            median_iqr_norm=("posterior_iqr_norm", "median"),
            median_sd_ratio=("posterior_to_prior_sd", "median"),
        )
        .reset_index()
        .sort_values(["parameters_with_mass_ge_25pct", "mean_boundary_pressure_5pct"], ascending=False)
    )
    group.to_csv(out_dir / "posterior_pressure_by_family.csv", index=False, encoding="utf-8-sig")

    mass = df.loc[df["boundary_pressure_5pct"] >= 0.25].copy()
    point_only = df.loc[(df["best_near_boundary_5pct"]) & (df["boundary_pressure_5pct"] < 0.10)].copy()
    diffuse = df.loc[df["posterior_p90_width_norm"] >= 0.75].sort_values("posterior_p90_width_norm", ascending=False).head(15)

    lines = [
        "# PEST-IES 后验参数压力审计",
        "",
        f"- 后验成员：{len(post)}；激活参数：{len(df)}；边界压力定义：成员值距任一边界不超过该参数范围的 5%。",
        f"- 这是集合层面的压力统计；最佳成员触界但集合压力低，归类为 point-only，不直接建议扩界。",
        "",
        "## 集合层面高压力（≥25%成员靠近边界）",
        "",
    ]
    if mass.empty:
        lines.append("无参数达到 ≥25% 成员边界压力。")
    else:
        lines.append("|参数|族|方向|边界压力|后验中位数|范围|90%区间|后验/先验SD|")
        lines.append("|---|---|---|---:|---:|---|---:|---:|")
        for _, r in mass.head(30).iterrows():
            lines.append(f"|{r['name']}|{r['family']}|{r['dominant_boundary']}|{r['boundary_pressure_5pct']:.0%}|{r['posterior_median']:.5g}|[{r['lower']:.5g},{r['upper']:.5g}]|[{r['q05']:.5g},{r['q95']:.5g}]|{r['posterior_to_prior_sd']:.3g}|")

    lines += ["", "## 仅最佳成员触界（集合压力 <10%）", ""]
    if point_only.empty:
        lines.append("无此类参数。")
    else:
        lines.append("|参数|族|最佳值|范围|最佳归一化位置|集合边界压力|")
        lines.append("|---|---|---:|---|---:|---:|")
        for _, r in point_only.sort_values("best_norm").iterrows():
            lines.append(f"|{r['name']}|{r['family']}|{r['best_value']:.5g}|[{r['lower']:.5g},{r['upper']:.5g}]|{r['best_norm']:.3f}|{r['boundary_pressure_5pct']:.0%}|")

    lines += ["", "## 后验最宽/弱识别参数（90%区间 ≥75%边界范围）", ""]
    if diffuse.empty:
        lines.append("无参数达到该阈值。")
    else:
        lines.append("|参数|族|90%区间归一化宽度|后验/先验SD|后验中位数|")
        lines.append("|---|---|---:|---:|---:|")
        for _, r in diffuse.iterrows():
            lines.append(f"|{r['name']}|{r['family']}|{r['posterior_p90_width_norm']:.0%}|{r['posterior_to_prior_sd']:.3g}|{r['posterior_median']:.5g}|")

    lines += [
        "",
        "## 解释与当前拟合的对应关系",
        "",
        "1. 只有集合中有较高比例成员贴边，才构成下一轮扩界的证据；单个最低 Phi 成员贴边不等于边界错误。",
        "2. 当前确定性复跑显示产量尺度尚可，但 N_RESPONSE 两季 NSE 仍显著为负，26SP W_RESPONSE 也为负。因此，若氮/水响应相关参数没有形成清晰的后验收缩，不能把总体 Phi 下降解释为响应结构已识别。",
        "3. PAGE/PENV 若出现上界压力，应与苗期株高/物候和产量同时复核；不能只按株高优选。",
        "4. soil 参数的边界压力若集中在多个相邻层，应先检查土壤剖面标量和初始氮/水输入的一致性，再决定是否放宽。",
        "",
        "## 可复现输入",
        "",
        f"- bounds: `{bounds_path}`",
        f"- posterior: `{posterior_path}`",
        f"- prior: `{prior_path}`",
        f"- 全量表：`{out_dir / 'posterior_parameter_pressure.csv'}`",
    ]
    (out_dir / "posterior_pressure_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounds", type=Path, required=True)
    ap.add_argument("--posterior", type=Path, required=True)
    ap.add_argument("--prior", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    audit(args.bounds, args.posterior, args.prior, args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
