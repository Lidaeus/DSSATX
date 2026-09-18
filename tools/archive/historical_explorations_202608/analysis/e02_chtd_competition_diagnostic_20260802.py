"""Diagnose whether CHDT/height fitting can compete with canopy and W/N response.

Read-only audit for the three relevant E02 runs.  It deliberately separates:
1) observation-contract eligibility (does CHDT enter Phi?);
2) Phi-group contribution and posterior co-movement; and
3) height-related posterior pressure.

Outputs are compact CSV/JSON files intended for a report or handoff.  This is
not a calibration or model-editing script.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "workspace" / "diagnostics" / "e02_chtd_competition_diagnostic_20260802"

RUNS = {
    "A_wnstress_fourcorner_20260801": {
        "dir": ROOT / "workspace" / "runs" / "e02_wnstress_fourcorner_formal_200x5_20260801_080700",
        "prefix": "e02_wnstress_fourcorner_formal_200x5_20260801_080700",
        "best": 179,
        "role": "CHDT diagnostic_only",
    },
    "B_joint61_n012_no_nresponse_20260801": {
        "dir": ROOT / "workspace" / "runs" / "e02_joint61_25sp25fa_validic_n012_no_nresponse_formal_200x5_20260801",
        "prefix": "e02_joint61_25sp25fa_validic_n012_no_nresponse_formal_200x5_20260801",
        "best": 55,
        "role": "CHDT diagnostic_only; N response not targeted",
    },
    "C_joint62_softn_response_20260802": {
        "dir": ROOT / "workspace" / "runs" / "e02_joint62_softn_response_95pct_dmc5_formal_200x5_20260802",
        "prefix": "e02_joint62_softn_response_95pct_dmc5_formal_200x5_20260802",
        "best": 99,
        "role": "CHDT active within CANOPY budget",
    },
}


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def registry_audit(label: str, spec: dict) -> dict:
    path = spec["dir"] / f"{spec['prefix']}_observation_registry.csv"
    df = read_csv(path)
    sim = df.get("sim_token", pd.Series(index=df.index, dtype=object)).astype(str).str.upper()
    ch = df.loc[sim.isin(["CHTDS", "CHTD"])].copy()
    weight_col = "weight" if "weight" in ch else "wt"
    positive_col = "positive" if "positive" in ch else None
    weights = pd.to_numeric(ch.get(weight_col, 0), errors="coerce").fillna(0)
    positive = pd.to_numeric(ch.get(positive_col, (weights > 0).astype(int)), errors="coerce").fillna(0) if positive_col else (weights > 0).astype(int)
    canopy_tokens = {"CHTDS", "CHTD", "LAIDS", "LAID", "LAIXS", "LAIX", "LWADS", "LWAD", "SWADS", "SWAD"}
    canopy = df.loc[sim.isin(canopy_tokens)].copy()
    canopy_w = pd.to_numeric(canopy.get(weight_col, 0), errors="coerce").fillna(0)
    return {
        "run": label,
        "role": spec["role"],
        "n_all": int(len(df)),
        "n_positive_all": int((pd.to_numeric(df.get(positive_col, 0), errors="coerce").fillna(0) > 0).sum()) if positive_col else int((pd.to_numeric(df.get(weight_col, 0), errors="coerce").fillna(0) > 0).sum()),
        "n_chtd": int(len(ch)),
        "n_chtd_positive": int((positive > 0).sum()),
        "chtd_weight_sum": float(weights.sum()),
        "n_canopy": int(len(canopy)),
        "canopy_weight_sum": float(canopy_w.sum()),
        "chtd_weight_share_of_canopy_pct": float(100 * weights.sum() / canopy_w.sum()) if canopy_w.sum() else 0.0,
        "chtd_enters_phi": bool((weights > 0).any()),
    }


def group_values(phi: pd.DataFrame) -> pd.DataFrame:
    """Return per-row sums using stable token rules across run versions."""
    cols = [c for c in phi.columns if c not in {"iteration", "total_runs", "obs_realization", "par_realization"}]

    def s(match: str) -> pd.Series:
        hits = [c for c in cols if match in c]
        return phi[hits].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1) if hits else pd.Series(0.0, index=phi.index)

    height = s("chtdm")
    nonheight = s("laidm") + s("laixm") + s("lwadm") + s("swadm")
    harvest = s("chpdtm")
    nresp = s("nrespm")
    plant_n = s("snamm") + s("lnamm")
    biomass = s("hpodwm") + s("chfpwm")
    sw_cols = [c for c in cols if "_sw" in c and "_swadm" not in c]
    soil = phi[sw_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1) if sw_cols else pd.Series(0.0, index=phi.index)
    out = pd.DataFrame({
        "iteration": pd.to_numeric(phi.get("iteration", 0), errors="coerce").fillna(0),
        "height_phi": height,
        "nonheight_canopy_phi": nonheight,
        "dry_harvest_phi": harvest,
        "n_response_phi": nresp,
        "soil_water_phi": soil,
        "plant_n_phi": plant_n,
        "biomass_phi": biomass,
    })
    out["total_selected_phi"] = out.drop(columns="iteration").sum(axis=1)
    out["height_share_of_canopy_pct"] = 100 * out["height_phi"] / (out["height_phi"] + out["nonheight_canopy_phi"]).replace(0, np.nan)
    return out


def posterior_audit(label: str, spec: dict) -> pd.DataFrame:
    par_path = spec["dir"] / f"{spec['prefix']}.5.par.csv"
    sum_path = spec["dir"] / "posterior_response_analysis" / "posterior_summary.csv"
    par = read_csv(par_path)
    summ = read_csv(sum_path)
    if "name" not in summ:
        return pd.DataFrame()
    summ["name"] = summ["name"].astype(str).str.lower()
    keys = ["phtmax", "rhght", "trifl", "kcan", "kc_slope", "lfmax", "lngsh", "fl-sh", "fl-sd", "xfrt", "xfint", "rtno3", "nstfac", "cmobmx", "lnref", "rwumx"]
    rows = []
    for key in keys:
        hit = summ.loc[summ["name"].eq(key)]
        if hit.empty or key not in par.columns:
            continue
        h = hit.iloc[0]
        lo, hi = float(h["lower"]), float(h["upper"])
        vals = pd.to_numeric(par[key], errors="coerce").dropna()
        span = hi - lo
        rows.append({
            "run": label, "parameter": key.upper(), "lower": lo, "upper": hi,
            "median": float(h["median"]), "p05": float(h["p05"]), "p95": float(h["p95"]),
            "near_lower_2pct": float(h.get("near_lower_pct", np.nan)),
            "near_upper_2pct": float(h.get("near_upper_pct", np.nan)),
        })
    return pd.DataFrame(rows)


def best_metrics(label: str, spec: dict) -> pd.DataFrame:
    path = spec["dir"] / "best_member_metrics_rawscale" / "best_member_metrics_rawscale.csv"
    if not path.exists():
        return pd.DataFrame()
    df = read_csv(path)
    if "variable" not in df:
        return pd.DataFrame()
    wanted = {"chtd", "chtds", "laid", "laix", "lwad", "swad", "nresp", "soil_water"}
    var = df["variable"].astype(str).str.lower()
    out = df.loc[var.isin(wanted)].copy()
    out.insert(0, "run", label)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    audits = []
    phi_rows = []
    correlations = []
    posterior = []
    metrics = []

    for label, spec in RUNS.items():
        audits.append(registry_audit(label, spec))
        phi_path = spec["dir"] / f"{spec['prefix']}.phi.group.csv"
        phi = read_csv(phi_path)
        gv = group_values(phi)
        final = gv.loc[gv["iteration"].eq(gv["iteration"].max())].copy()
        mean_row = final.mean(numeric_only=True)
        best_index = (pd.to_numeric(phi.get("par_realization", np.nan), errors="coerce") == int(spec["best"])) & phi["iteration"].eq(phi["iteration"].max())
        best_g = gv.loc[best_index]
        row = {"run": label, "sample": "iteration_max_mean", **{k: float(mean_row[k]) for k in gv.columns if k != "iteration"}}
        phi_rows.append(row)
        if not best_g.empty:
            br = best_g.iloc[0]
            phi_rows.append({"run": label, "sample": f"best_par_{spec['best']}", **{k: float(br[k]) for k in gv.columns if k != "iteration"}})
        if label.startswith("C_"):
            for target in ["nonheight_canopy_phi", "dry_harvest_phi", "n_response_phi", "soil_water_phi", "plant_n_phi", "total_selected_phi"]:
                correlations.append({"run": label, "x": "height_phi", "y": target, "spearman_rho": float(gv.loc[gv["iteration"].eq(gv["iteration"].max()), ["height_phi", target]].corr(method="spearman").iloc[0, 1])})
        posterior.append(posterior_audit(label, spec))
        metrics.append(best_metrics(label, spec))

    pd.DataFrame(audits).to_csv(OUT / "height_observation_weight_audit.csv", index=False)
    pd.DataFrame(phi_rows).to_csv(OUT / "phi_group_contribution_audit.csv", index=False)
    pd.DataFrame(correlations).to_csv(OUT / "phi_group_correlation_audit.csv", index=False)
    pd.concat([x for x in posterior if not x.empty], ignore_index=True).to_csv(OUT / "posterior_canopy_audit.csv", index=False)
    pd.concat([x for x in metrics if not x.empty], ignore_index=True).to_csv(OUT / "best_member_metrics_selected.csv", index=False)
    notes = {
        "scope": "A/B/C E02 CHDT competition diagnostic",
        "interpretation": "CHTDS/CHTD is the project observation-contract token for height; exact target behavior is determined by registry weight.",
        "noncausal_warning": "Posterior Spearman correlations describe conditional co-movement among accepted ensemble members; they are not causal sensitivities.",
        "run_A": RUNS["A_wnstress_fourcorner_20260801"]["role"],
        "run_B": RUNS["B_joint61_n012_no_nresponse_20260801"]["role"],
        "run_C": RUNS["C_joint62_softn_response_20260802"]["role"],
    }
    (OUT / "analysis_notes.json").write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(OUT), "files": sorted(p.name for p in OUT.iterdir())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
