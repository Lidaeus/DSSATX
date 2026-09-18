"""Report raw-scale metrics for the mixed increment/terminal E02 run."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.reporting.metrics import compute_metrics


def variable(group: str) -> str:
    root = str(group).upper().split("_", 1)[-1]
    root = re.sub(r"_[HD]\d+$", "", root)
    mapping = {
        "CHPDTM": "CHPDT_TERMINAL", "HPODWM": "HPODW_INCREMENT",
        "LAIDDM": "LAID_INCREMENT", "LAIETM": "LAID_TERMINAL",
        "LWADDM": "LWAD_INCREMENT", "LWETM": "LWAD_TERMINAL",
        "SWADDM": "SWAD_INCREMENT", "SWETM": "SWAD_TERMINAL",
        "LAIXM": "LAIX", "LAIDM": "LAID_STATE_DIAGNOSTIC",
        "LWADM": "LWAD_STATE_DIAGNOSTIC", "SWADM": "SWAD_STATE_DIAGNOSTIC",
        "SNAMM": "SNAM", "LNAMM": "LNAM", "NRESPM": "NRESP",
    }
    if root in mapping:
        return mapping[root]
    if root.startswith("SW"):
        return "SOIL_WATER"
    return root


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    run = args.run_dir.resolve()
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    case = next(run.glob("*.pst")).stem
    phi = pd.read_csv(run / f"{case}.phi.actual.csv")
    members = [c for c in phi.columns if str(c).isdigit()]
    best = int(phi.iloc[-1][members].astype(float).idxmin())
    best_phi = float(phi.iloc[-1][str(best)])
    obs_files = sorted(run.glob(f"{case}.*.obs.csv"), key=lambda p: int(p.name[len(case) + 1:].split(".", 1)[0]))
    obs = pd.read_csv(obs_files[-1])
    row = obs.loc[obs["real_name"].astype(str).eq(str(best))].iloc[0]
    reg = pd.read_csv(run / f"{case}_observation_registry.csv", encoding="utf-8-sig")
    reg["variable"] = reg["obgnme"].map(variable)
    reg["weight_num"] = pd.to_numeric(reg["weight"], errors="coerce").fillna(0.0)
    reg = reg[(reg["weight_num"] > 0) & ~reg["variable"].str.endswith("_DIAGNOSTIC")].copy()
    sim_t = pd.to_numeric(reg["obsnme"].str.lower().map(row), errors="coerce")
    transform = reg["transform"].astype(str).str.lower()
    offset = pd.to_numeric(reg["transform_offset"], errors="coerce").fillna(0.0)
    reg["simulated"] = np.where(transform.eq("log"), np.exp(sim_t) - offset, sim_t)
    reg["observed"] = pd.to_numeric(reg["raw_obsval"], errors="coerce")
    reg = reg[np.isfinite(reg["observed"]) & np.isfinite(reg["simulated"])].copy()
    pairs = reg[["season_id", "treatment", "variable", "obsnme", "observed", "simulated", "sigma"]]
    pairs.to_csv(out / "best_member_observation_pairs_rawscale.csv", index=False)
    rows = []
    for v, sub in reg.groupby("variable", sort=True):
        rows.append({"scope": "overall", "season_id": "ALL", "variable": v, **compute_metrics(sub.observed, sub.simulated)})
    for (s, v), sub in reg.groupby(["season_id", "variable"], sort=True):
        rows.append({"scope": "season", "season_id": s, "variable": v, **compute_metrics(sub.observed, sub.simulated)})
    metrics = pd.DataFrame(rows)
    metrics.to_csv(out / "best_member_metrics_rawscale.csv", index=False)
    final_iter = int(obs_files[-1].name[len(case) + 1:].split(".", 1)[0])
    par = pd.read_csv(run / f"{case}.{final_iter}.par.csv")
    par.loc[par["real_name"].astype(str).eq(str(best))].to_csv(out / "best_member_parameters.csv", index=False)
    (out / "summary.txt").write_text(f"best_member={best}\nactual_phi={best_phi:.10g}\nfinal_iteration={final_iter}\n", encoding="utf-8")
    print(f"best_member={best} actual_phi={best_phi:.10g}")
    print(metrics[metrics.scope.eq("overall")].to_string(index=False))


if __name__ == "__main__":
    main()
