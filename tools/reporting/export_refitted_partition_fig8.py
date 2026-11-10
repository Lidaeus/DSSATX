"""Freeze the matched two-run comparison for R Fig8."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from export_dual_morris_fig3 import read_json, record
from export_spring_calibration_figures import ROOT, prepare_spring_tables, require

REMOVED = {"XFINT", "XFPHT"}
VARIABLES = {"TERMINAL_FRESH": "CHFPW", "FRESH_CUM": "CHFPW", "FRESH_INC": "HFPOW",
             "LAID": "LAID", "LWAD": "LWAD", "SWAD": "SWAD"}
GROWTH_VARIABLES = ("LAID", "LWAD", "SWAD")


def eco_coefficients(path):
    rows = path.read_text(encoding="ascii").splitlines()
    fields = next(line for line in rows if line.startswith("@ECO#")).split()
    actual = next(line for line in rows if line.startswith("TM0001")).split()
    if fields[-1] == "XMAGE":
        require(not any(name in line for name in REMOVED for line in rows),
                f"Unexpected dynamic partition fields: {path}")
        return {}
    require(fields[-3:] == ["XMAGE", "XFPHT", "XFINT"], f"Unexpected ecotype layout: {path}")
    return dict(zip(fields[-2:], map(float, actual[-2:])))


def export(full, reduced, out, allow_demo, season_end_growth=False, exclude_25sp_final_growth=False,
           validation_bundle=None):
    require(not (season_end_growth and exclude_25sp_final_growth), "Choose only one growth evaluation variant")
    sources = {}

    def track(path, expected=None):
        item = record(path)
        require(expected is None or item["sha256"] == expected, f"SHA-256 mismatch: {path}")
        sources[item["path"]] = item
        return path

    runs = {"full": full, "reduced": reduced}
    designs, bounds, metadata, pairs, references, coefficients = {}, {}, {}, {}, {}, {}
    for variant, run in runs.items():
        tables, meta = prepare_spring_tables(run, allow_demo, validation_bundle)
        metadata[variant] = {k: v for k, v in meta.items() if k not in {"sources", "treatment_order"}}
        sources.update({item["path"]: item for item in meta["sources"]})
        design = designs[variant] = read_json(run / "design.json")
        sealed = read_json(track(run / "sealed_design.json"))
        track(run / "design.json", sealed["sha256"])
        bounds_file = track(Path(design["frozen_bounds"]), design["source_hashes"][design["frozen_bounds"]])
        bounds[variant] = pd.read_csv(bounds_file).set_index("native_name").sort_index()
        executable, = [Path(p) for p in design["source_hashes"] if Path(p).name.upper() == "DSCSM048.EXE"]
        track(executable, design["source_hashes"][str(executable)])
        best = pd.read_csv(run / "best_calibration_parameters.csv").set_index("name").value
        for folder in ("selected_deterministic", "validation"):
            eco = eco_coefficients(track(run / folder / "TMGRO048.ECO"))
            require(set(eco) == (REMOVED if variant == "full" else set()) and
                    all(np.isclose(v, best[k], atol=1e-10, rtol=0) for k, v in eco.items()) and
                    (variant == "full" or REMOVED.isdisjoint(best.index)), f"Wrong ecotype: {run / folder}")
            require(folder == "selected_deterministic" or eco == coefficients[variant],
                    "Ecotype partition values changed between seasons")
            coefficients[variant] = eco
        pairs[variant] = tables["comparison.csv"].query("variable in @VARIABLES").copy()
        references[variant] = {name: pd.read_csv(track(run / "result_review" / name))
                               for name in ("terminal_yield_metrics.csv", "variable_metrics.csv")}

    a, b = designs["full"], designs["reduced"]
    for k in ("datasets", "members", "updates", "seed", "target_count", "objective_budget",
              "anthesis_dates", "SLPF", "SASC", "ICNS"):
        require(a[k] == b[k], f"Two calibration designs disagree: {k}")
    require(b["parent_trial"] == full.name and set(b["eco_columns_removed"]) == REMOVED and
            len(a["active_parameters"]) == 58 and len(b["active_parameters"]) == 56 and
            set(a["active_parameters"]) - REMOVED == set(b["active_parameters"]), "Wrong ablation design")
    pd.testing.assert_frame_equal(bounds["full"].drop(index=list(REMOVED)), bounds["reduced"])
    for name in ("calibration_observations.csv", "objective_policy.csv", "locked_validation_observations.csv",
                 "calibration_diagnostic_observations.csv", "fixed_input_audit.csv"):
        require(record(track(full / name))["sha256"] == record(track(reduced / name))["sha256"],
                f"Calibration or observation input differs: {name}")
    for season in ("26SP", "25SP"):
        lhs, rhs = full / f"{season}_inputs", reduced / f"{season}_inputs"
        names = {p.name for p in lhs.iterdir() if p.is_file()}
        require(names == {p.name for p in rhs.iterdir() if p.is_file()}, "Season inputs differ")
        for name in sorted(names):
            path_a = track(lhs / name, a["source_hashes"][str(lhs / name)])
            path_b = track(rhs / name, b["source_hashes"][str(rhs / name)])
            if name == "TMGRO048.ECO":
                rows_a = path_a.read_text(encoding="ascii").splitlines()
                rows_b = path_b.read_text(encoding="ascii").splitlines()
                require(len(rows_a) == len(rows_b) and all(
                    x == y or (x.startswith(("@ECO#", "!", "TM0001", "DFAULT")) and
                               x.rstrip()[:-12].rstrip() == y.rstrip())
                    for x, y in zip(rows_a, rows_b)), f"Other ECO fields differ in {season}")
            else:
                require(sources[str(path_a)]["sha256"] == sources[str(path_b)]["sha256"],
                        f"Season inputs differ: {season}/{name}")

    keys = ["season_id", "dataset_role", "treatment", "date", "variable"]
    keep = ["observed", "management", "dap", "unit", "simulated"]
    paired = {v: p.set_index(keys)[keep].sort_index() for v, p in pairs.items()}
    pd.testing.assert_frame_equal(paired["full"].drop(columns="simulated"),
                                  paired["reduced"].drop(columns="simulated"))
    obs = paired["full"].rename(columns={"simulated": "simulated_full"}).join(
        paired["reduced"].simulated.rename("simulated_reduced"), validate="one_to_one").reset_index()
    growth_dates = {}
    excluded_growth_dates = {}
    if season_end_growth:
        is_growth = obs.variable.isin(GROWTH_VARIABLES)
        growth = obs[is_growth]
        growth_dates = growth.groupby("season_id").date.max().to_dict()
        endpoint = growth[growth.date.eq(growth.season_id.map(growth_dates))]
        for season, group in endpoint.groupby("season_id"):
            expected = set(a["datasets"][season]["treatments"])
            require(set(group.variable) == set(GROWTH_VARIABLES) and all(
                set(rows.treatment) == expected and len(rows) == len(expected)
                for _, rows in group.groupby("variable")), f"Incomplete last growth sampling in {season}")
        obs = obs[~is_growth | obs.date.eq(obs.season_id.map(growth_dates))]
    if exclude_25sp_final_growth:
        excluded_date = "2025-07-13"
        growth_25sp = obs.season_id.eq("25SP") & obs.variable.isin(GROWTH_VARIABLES)
        excluded = growth_25sp & obs.date.eq(excluded_date)
        expected = set(a["datasets"]["25SP"]["treatments"])
        removed = obs[excluded]
        require(obs.loc[growth_25sp, "date"].max() == excluded_date and
                set(removed.variable) == set(GROWTH_VARIABLES) and
                all(set(group.treatment) == expected and len(group) == len(expected)
                    for _, group in removed.groupby("variable")),
                "Expected one 2025-07-13 observation per treatment and growth variable")
        obs = obs[~excluded]
        excluded_growth_dates["25SP"] = excluded_date
    metrics = []
    for (season, role, variable), rows in obs.groupby(["season_id", "dataset_role", "variable"]):
        observed = rows.observed.to_numpy()
        for variant in runs:
            simulated = rows[f"simulated_{variant}"].to_numpy()
            center = observed.mean()
            sse = np.square(simulated - observed).sum()
            nrmse = np.sqrt(sse / len(rows)) / center * 100
            d = 1 - sse / np.square(abs(simulated - center) + abs(observed - center)).sum()
            r2 = np.corrcoef(observed, simulated)[0, 1] ** 2
            growth_subset = variable in GROWTH_VARIABLES and (
                season_end_growth or season in excluded_growth_dates)
            refreshed_leaf = validation_bundle is not None and season == "25SP" and variable == "LWAD"
            if not growth_subset and not refreshed_leaf:
                table_name = "terminal_yield_metrics.csv" if variable == "TERMINAL_FRESH" else "variable_metrics.csv"
                native_variable = VARIABLES[variable]
                ref = references[variant][table_name].query(
                    "season_id == @season and role == @role and variable == @native_variable").iloc[0]
                require(len(rows) == ref.n and ref.n_unmatched == 0, f"Review count mismatch: {season}/{variable}")
                np.testing.assert_allclose([nrmse, d, r2], [ref.RRMSE, ref.d, ref.R2], rtol=0, atol=1e-9)
            metrics.append(dict(season_id=season, dataset_role=role, variable=variable, variant=variant,
                                n=len(rows), nrmse_pct=nrmse, willmott_d=d, r2=r2))

    xfint, xfpht = (coefficients["full"][k] for k in ("XFINT", "XFPHT"))
    require(0 < xfint < 1 and xfpht > 0, "Full model has no active ramp")
    # The CROPGRO branch scales each configuration's own cultivar baseline.
    track(ROOT / "subprojects/critical_n/dssat_csm_os_4864/Plant/CROPGRO/DEMAND.for")
    ages = [0.0, xfpht, float(np.ceil(xfpht / 10 + 1) * 10)]
    curve = pd.DataFrame(dict(photothermal_age=ages * 2, variant=["full"] * 3 + ["reduced"] * 3,
                              relative_potential_fraction=[xfint, 1., 1., 1., 1., 1.]))
    out.mkdir(parents=True, exist_ok=False)
    tables = {"partition_function.csv": curve, "ablation_metrics.csv": pd.DataFrame(metrics),
              "matched_comparison.csv": obs}
    for name, table in tables.items():
        table.to_csv(out / name, index=False)
    states = [m["data_status"] for m in metadata.values()]
    status = "science_validated" if all(s == "science_validated" for s in states) else "science_pending_trial"
    manifest = dict(schema_version=1, bundle_type="refitted_partition_ablation", run_id=full.name,
                    data_status=status, runs=metadata, retained_coefficients=coefficients["full"],
                    growth_scope=("season_end" if season_end_growth else
                                  "process_excluding_final_25sp" if excluded_growth_dates else "process"),
                    growth_sampling_dates=growth_dates,
                    excluded_growth_dates=excluded_growth_dates,
                    matching=dict(treatments="same season/treatment/date/variable and observation",
                                  common_bounds=True, common_objective=True, validation_used_for_selection=False),
                    sources=list(sources.values()),
                    artifacts=[{**record(out / name), "path": name} for name in tables])
    path = out / "paper_data_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("full-run", "reduced-run", "out-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    parser.add_argument("--validation-bundle", type=Path)
    growth_options = parser.add_mutually_exclusive_group()
    growth_options.add_argument("--season-end-growth", action="store_true",
                                help="Evaluate growth at each season's last observed sampling date.")
    growth_options.add_argument("--exclude-25sp-final-growth", action="store_true",
                                help="Exclude 2025-07-13 LAI, leaf and stem dry-weight pairs only.")
    args = parser.parse_args()
    print(export(args.full_run.resolve(), args.reduced_run.resolve(), args.out_dir.resolve(),
                 args.allow_unvalidated_demo, args.season_end_growth, args.exclude_25sp_final_growth,
                 args.validation_bundle.resolve() if args.validation_bundle else None))
