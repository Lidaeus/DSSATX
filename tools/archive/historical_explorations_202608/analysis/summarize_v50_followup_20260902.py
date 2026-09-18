"""Audit deterministic follow-up; separate fresh N-N0 and raw nonN0 contrasts."""
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.experiments.run_v50_mechanism_followup_20260902 import OUT, plan, verify_seal, sha
from tools.analysis.audit_v46_best71_early_nstress_20260831 import parse_plantgro


def error(frame):
    return float(np.sqrt(np.mean(frame.residual**2)))


def main():
    verify_seal()
    control = OUT / "control_A47"
    cg = pd.read_csv(control / "26SP_nonN0_gradients.csv")
    cp = pd.read_csv(control / "parsed_observations.csv", index_col=0).iloc[:, 0]
    overview, fits, spread, dose, stress, shifts = [], [], [], [], [], []
    identity, daily_identity = [], []
    meta = pd.read_csv(ROOT / "configs/runs/e02_mapping_26sp_w2_w1_20260830.csv")
    meta = meta[meta.season_id.eq("26SP")][["treatment", "water_level", "nitrogen_level"]]
    for task in plan():
        label = task["label"]
        dest = OUT / label
        status = json.loads((dest / "completed.json").read_text())
        assert status["status"] == "completed"
        if task['kind'] == 'probe':
            for season, excode in [('25SP', 'XXQL2501'), ('26SP', 'XXQL2601')]:
                for filename in ['TMGRO048.CUL', 'TMGRO048.ECO', 'SOIL.SOL', excode+'.TMX']:
                    a = dest / '_seasons' / season / filename
                    b = control / '_seasons' / season / filename
                    assert sha(a) == sha(b), (label, season, filename)
                    identity.append(dict(candidate=label, season=season, filename=filename, matches_control=True, sha256=sha(a)))
                if label.startswith('nstfac_'):
                    for filename in ['PlantGro.OUT', 'PlantN.OUT']:
                        a = parse_plantgro(dest / '_seasons' / season / filename)
                        b = parse_plantgro(control / '_seasons' / season / filename)
                        pd.testing.assert_frame_equal(a, b, check_exact=True)
                        daily_identity.append(dict(candidate=label, season=season, filename=filename, identical_numeric_daily_output=True))
        f = pd.read_csv(dest / "fit_metrics.csv")
        fits.append(f.assign(candidate=label))
        ix = f.set_index(["season", "variable"])
        pred = pd.read_csv(dest / "parsed_observations.csv", index_col=0).iloc[:, 0]
        obj = pd.read_csv(dest / "objective_residuals.csv")
        gates = status["checks"]
        row = dict(candidate=label, kind=task["kind"], phi=obj.actual_phi.sum(),
                   max_output_change_vs_control=float((pred-cp).abs().max()),
                   scale_guard_both=all(g["scale_canopy_pass"] for g in gates.values()),
                   original_mechanism_gate_both=all(g["mechanism_target_pass"] for g in gates.values()),
                   replay_max_difference=status["replay_max_difference"])
        for season in ("25SP", "26SP"):
            for variable, metric in [("FRESH_CUM", "nse"), ("FRESH_TERMINAL", "rrmse_pct"),
                                     ("LAID", "nse"), ("LAID_late", "rmse"), ("LAID_early", "rmse")]:
                row[f"{season}_{variable}_{metric}"] = ix.loc[(season, variable), metric]
        for ref, g in gates.items():
            n26 = [r["rmse_improvement_fraction"] for r in g["response_changes"] if r["season"] == "26SP" and r["variable"].startswith("NRESPS_")]
            water = [r["rmse_improvement_fraction"] for r in g["response_changes"] if r["variable"].startswith("WRESPS_")]
            row[f"N26_mean_improvement_vs_{ref}"] = np.mean(n26)
            row[f"water_worst_improvement_vs_{ref}"] = min(water)
            row[f"late26_improvement_vs_{ref}"] = g["26SP_late_LAI_rmse_improvement_fraction"]
        gradients = pd.read_csv(dest / "26SP_nonN0_gradients.csv")
        for variable in ("FRESH_CUM", "LAID"):
            g = gradients[gradients.variable.eq(variable) & gradients.contrast.ne("N3-N1")]
            c = cg[cg.variable.eq(variable) & cg.contrast.ne("N3-N1")]
            row[f"nonN0_{variable}_adjacent_rmse"] = error(g)
            row[f"nonN0_{variable}_improvement_vs_A"] = 1-error(g)/error(c)
        g = pd.read_csv(dest / "26SP_nonN0_spread.csv")
        last = g[g.variable.eq("FRESH_CUM")].date.max()
        terminal = g[g.variable.eq("FRESH_CUM") & g.date.eq(last)]
        for r in terminal.itertuples():
            row[f"terminal_cv_{r.water}_pct"] = r.simulated_cv_pct
            row[f"terminal_monotone_{r.water}"] = r.simulated_monotone
        spread.append(g.assign(candidate=label))
        d = obj[obj.sim_token.isin(["NG12S", "NG23S", "NGCVS"])].groupby(["season_id", "sim_token"]).actual_phi.sum().reset_index()
        dose.append(d.assign(candidate=label))
        row["N_DOSE26_phi"] = d.loc[d.season_id.eq("26SP"), "actual_phi"].sum()
        daily = pd.read_csv(dest / "26SP_mechanism_daily.csv")
        process = pd.read_csv(dest / "_seasons/26SP/26SP_deterministic_process_compare.csv")
        runs = process[["RUN", "TN"]].drop_duplicates()
        daily = daily.merge(runs, left_on="global_run", right_on="RUN", validate="many_to_one").merge(meta, left_on="TN", right_on="treatment", validate="many_to_one")
        pn = parse_plantgro(dest / "_seasons/26SP/PlantN.OUT")
        daily = daily.merge(pn[["global_run", "YEAR", "DOY", "NUPC"]], on=["global_run", "YEAR", "DOY"], validate="one_to_one")
        for (water, nitrogen), group in daily.groupby(["water_level", "nitrogen_level"]):
            stress.append(dict(candidate=label, water=water, nitrogen=nitrogen,
                               nstd_max=group.NSTD.max(), nstd_positive_days=int((group.NSTD>0).sum()),
                               pcnl_platform_fraction=group.PCNL_ge_FNPGN2_lower_bound.mean(),
                               pcnl_min=group["LN%D"].min(), pcnl_median=group["LN%D"].median(),
                               final_NUPC=group.sort_values(["YEAR", "DOY"]).iloc[-1].NUPC))
        harvest = pd.read_csv(dest / "_seasons/26SP/26SP_deterministic_harvest_compare.csv")
        hc = pd.read_csv(control / "_seasons/26SP/26SP_deterministic_harvest_compare.csv")
        h = harvest.merge(hc[["TN", "DATE", "SIM_FRESH_CUM"]], on=["TN", "DATE"], validate="one_to_one", suffixes=("", "_control"))
        h = h.sort_values("DATE").groupby("TN").tail(1).merge(meta, left_on="TN", right_on="treatment", validate="one_to_one")
        h["change_vs_control"] = h.SIM_FRESH_CUM-h.SIM_FRESH_CUM_control
        shifts.append(h.assign(candidate=label))
        overview.append(row)
    for filename, frames in [("fit_metrics", fits), ("spread", spread), ("dose_phi", dose), ("terminal_shifts", shifts)]:
        pd.concat(frames, ignore_index=True).to_csv(OUT / f"{filename}.csv", index=False)
    pd.DataFrame(overview).to_csv(OUT / "overview.csv", index=False)
    pd.DataFrame(stress).to_csv(OUT / "nitrogen_daily_summary.csv", index=False)
    pd.DataFrame(identity).to_csv(OUT / 'input_identity_audit.csv', index=False)
    pd.DataFrame(daily_identity).to_csv(OUT / 'NSTFAC_output_identity.csv', index=False)
    # Raw observational uncertainty, independent-group approximation only.
    u = pd.read_csv(control / "_seasons/26SP/observation_uncertainty.csv")
    u = u[u.variable.eq("LAID")].set_index(["trno", "date"])
    obs = pd.read_csv(control / "_seasons/26SP/26SP_deterministic_process_compare.csv").merge(meta, left_on="TN", right_on="treatment", validate="many_to_one")
    rows = []
    for (water, date), group in obs.groupby(["water_level", "DATE"]):
        g = group.set_index("nitrogen_level")
        for high, low in [("N2", "N1"), ("N3", "N2"), ("N3", "N1")]:
            a, b = g.loc[high], g.loc[low]
            if a.OBS_LAID == -99 or b.OBS_LAID == -99:
                continue
            ua, ub = u.loc[(int(a.TN), date)], u.loc[(int(b.TN), date)]
            se = np.sqrt(ua.raw_sd**2/ua.n_rep + ub.raw_sd**2/ub.n_rep)
            rows.append(dict(water=water, date=date, contrast=f"{high}-{low}",
                             observed_delta=a.OBS_LAID-b.OBS_LAID, independent_se=se,
                             delta_over_se=(a.OBS_LAID-b.OBS_LAID)/se,
                             n_rep_high=ua.n_rep, n_rep_low=ub.n_rep))
    pd.DataFrame(rows).to_csv(OUT / "LAI_observed_gradient_uncertainty.csv", index=False)
    verify_seal()
    print(pd.DataFrame(overview)[["candidate", "phi", "scale_guard_both", "original_mechanism_gate_both", "N26_mean_improvement_vs_A47", "nonN0_FRESH_CUM_improvement_vs_A", "terminal_cv_W1_pct", "terminal_cv_W2_pct", "terminal_cv_W3_pct"]].to_string(index=False))


if __name__ == "__main__":
    main()
