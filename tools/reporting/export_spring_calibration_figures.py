"""Freeze audited deterministic dual-spring results for the R Fig4–6 figures."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from export_dual_morris_fig3 import read_json, record

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.single_season_n import read_native
from src.common.input_manifest import verify_manifest_integrity


GROWTH = ("LAID", "LWAD", "SWAD")
HARVEST = {"CHFPW": "FRESH_CUM", "CHPDT": "DRY_CUM", "HFPOW": "FRESH_INC"}
TREATMENTS = ("W3N3", "W1N1", "W1N0")
KEYS = ["trno", "date", "variable"]
LABELS = {"LAID": "LAI", "LWAD": "Leaf dry mass", "SWAD": "Stem dry mass",
          "FRESH_CUM": "Cumulative fresh harvest", "DRY_CUM": "Cumulative dry harvest",
          "FRESH_INC": "Event fresh harvest", "TERMINAL_FRESH": "Season-end fresh yield"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def equivalent(left, right, context):
    np.testing.assert_allclose(left, right, rtol=0, atol=1e-9, equal_nan=True, err_msg=context)


def prepare_spring_tables(run, allow_demo, validation_bundle=None):
    sources = {}

    def track(path, expected=None):
        item = record(path)
        require(expected is None or item["sha256"] == expected, f"SHA-256 mismatch: {path}")
        sources[str(path)] = item
        return path

    review = read_json(track(run / "result_review/review_summary.json"))
    state = read_json(track(run / "pipeline_status.json"))
    selection = read_json(track(run / "selection.json"))
    require(review["selection"] == selection and review["status"] == state and
            state["status"] == "completed" and not selection["validation_used"],
            "Representative selection and review do not match")
    require((state["selected_iteration"], state["selected_member"], state["selected_phi"]) ==
            (selection["iteration"], selection["member"], selection["phi"]) and
            review["phi_relative_error"] <= 1e-8, "Deterministic selection failed replay audit")
    status = state["scientific_status"]
    if status != "science_validated" or not state["all_rounds_passed"]:
        require(allow_demo, "This run requires --allow-unvalidated-demo for review figures")
        require(status != "science_validated", "Engineering and scientific statuses conflict")
    track(run / "best_calibration_parameters.csv", selection["parameters_sha256"])
    review_hashes = {(ROOT / path).resolve(): value for path, value in review["source_sha256"].items()}

    def reviewed(path):
        return track(path, review_hashes[path.resolve()])

    design = read_json(reviewed(run / "design.json"))
    require(design["run_id"] == run.name, "Run directory and design disagree")
    compared = pd.read_csv(track(run / "result_review/all_observed_simulated_pairs.csv"))
    terminal = pd.read_csv(track(run / "result_review/terminal_yield_pairs.csv"))
    metadata = pd.read_csv(track(run / "result_review/treatment_metadata.csv"))
    require(not metadata.duplicated(["season_id", "treatment"]).any(), "Duplicate treatment mapping")
    cases = {"26SP": ("calibration", "selected_deterministic"),
             "25SP": ("validation", "validation")}
    pairs, trajectories, chosen = [], [], []
    refresh = None
    for season, (role, directory) in cases.items():
        dataset = design["datasets"][season]
        folder = Path(dataset["path"])
        manifest = read_json(track(folder / "input_manifest.json", dataset["manifest_sha256"]))
        files = {item["name"]: item["sha256"] for item in manifest["files"]}
        evidence = pd.read_csv(track(folder / "observation_uncertainty.csv", files["observation_uncertainty.csv"]))
        schedule = pd.read_csv(track(folder / "harvest_schedule_audit.csv", files["harvest_schedule_audit.csv"]))
        original_meta = pd.read_csv(track(folder / "treatment_metadata.csv", files["treatment_metadata.csv"]))
        meta = metadata.loc[metadata.season_id.eq(season)].copy()
        ids = set(dataset["treatments"])
        require(dataset["role"] == role and meta.dataset_role.eq(role).all() and set(meta.treatment) == ids,
                f"Season/role or treatment mismatch for {season}")
        for col in ("water_level", "nitrogen_level", "treatment_label"):
            require(meta.set_index("treatment")[col].equals(original_meta.set_index("treatment")[col].reindex(meta.treatment)),
                    f"Management metadata do not match the frozen input for {season}/{col}")
        meta["management"] = meta.water_level + meta.nitrogen_level
        display = meta[meta.management.isin(TREATMENTS)].copy()
        require(len(display) == len(TREATMENTS), f"Incomplete representative treatments in {season}")
        chosen.append(display)
        plant = read_native(reviewed(run / directory / "PlantGro.OUT")).reset_index()
        fresh = read_native(reviewed(run / directory / "FreshWt.OUT")).reset_index()
        q = compared[compared.season_id.eq(season) & compared.variable.isin((*GROWTH, *HARVEST))].copy()
        ref = evidence[evidence.trno.isin(ids) & evidence.variable.isin((*GROWTH, *HARVEST))].copy()
        q = q.set_index(KEYS).sort_index()
        ref = ref.set_index(KEYS).sort_index()
        require(q.index.is_unique and q.index.equals(ref.index) and q.role.eq(role).all() and
                q.dataset_role.eq(role).all() and q.comparison_status.eq("matched").all() and
                np.isfinite(q[["observed", "simulated", "dap"]]).all().all(),
                f"Incomplete or unpaired observation evidence for {season}")
        equivalent(q.observed, ref.unrounded_source_mean, f"{season} observed values")
        equivalent(q.raw_sd, ref.raw_sd, f"{season} replicate SD")
        equivalent(q.n_rep, ref.n_rep, f"{season} replicate counts")
        q["observed_se"] = (ref.raw_sd / np.sqrt(ref.n_rep)).where(ref.sd_method.eq("sample_sd") &
                           ref.quality_flag.eq("ok") & ref.n_rep.ge(2) & ref.raw_sd.ge(0))
        q = q.reset_index()
        for native, variables in ((plant, GROWTH), (fresh, HARVEST)):
            n = native.melt(id_vars=["trno", "date", "DAP"], value_vars=list(variables), var_name="variable")
            verified = q[q.variable.isin(variables)].merge(n, on=KEYS, how="left", validate="one_to_one")
            equivalent(verified.simulated, verified.value, f"{season} DSSAT simulation")
            equivalent(verified.dap, verified.DAP, f"{season} exact-date DAP")
        events = schedule.loc[schedule.role.str.startswith("measured_harvest")].copy()
        dates = sorted(events.observed_harvest_date)
        require(events.observed_harvest_date.is_unique and
                events.observed_harvest_date.eq(events.model_output_date).all(),
                f"Unresolved measured harvest date alignment in {season}")
        h = q[q.variable.isin(HARVEST)]
        require(h.groupby(["trno", "variable"]).date.apply(lambda values: sorted(values) == dates).all(),
                f"Harvest pairs include non-event dates or lack measured dates in {season}")
        end = h[h.variable.eq("CHFPW") & h.date.eq(dates[-1])]
        last = terminal[terminal.season_id.eq(season) & terminal.variable.eq("CHFPW")]
        require(set(last.trno) == ids and last.date.eq(dates[-1]).all(), f"Invalid terminal yield rows: {season}")
        for col in ("observed", "simulated"):
            equivalent(end.set_index("trno")[col].reindex(last.trno), last[col], f"{season} terminal yield")
        if season == "25SP" and validation_bundle is not None:
            new_manifest_path = track(validation_bundle / "input_manifest.json",
                                      verify_manifest_integrity(validation_bundle).manifest_sha256)
            new_manifest = read_json(new_manifest_path)
            new_files = {item["name"]: item["sha256"] for item in new_manifest["files"]}
            provenance = read_json(track(validation_bundle / "source_provenance.json",
                                         new_files["source_provenance.json"]))
            require(provenance["baseline_manifest_sha256"] == dataset["manifest_sha256"],
                    "Validation refresh does not descend from the run's frozen validation bundle")
            model_suffixes = {".TMX", ".SOL", ".WTH", ".CUL", ".ECO", ".SPE"}
            same_inputs = {name for name in files if Path(name).suffix.upper() in model_suffixes}
            require(same_inputs == {name for name in new_files if Path(name).suffix.upper() in model_suffixes},
                    "Validation refresh changed the model input file set")
            for name in sorted(same_inputs | {"DSSBatch.v48", "treatment_metadata.csv", "harvest_schedule_audit.csv"}):
                track(validation_bundle / name, files[name])
            current = pd.read_csv(track(validation_bundle / "observation_uncertainty.csv",
                                        new_files["observation_uncertainty.csv"]))
            current = current[current.trno.isin(ids) & current.variable.isin((*GROWTH, *HARVEST))]
            current = current.set_index(KEYS).sort_index()
            require(current.index.is_unique and current.index.equals(ref.index),
                    "Validation refresh changed the evaluation keys")
            other = ref.index.get_level_values("variable") != "LWAD"
            pd.testing.assert_frame_equal(current.loc[other], ref.loc[other])
            equivalent(current.n_rep, ref.n_rep, "Refreshed validation replicate counts")
            leaf = current.loc[~other]
            require(leaf.sd_method.eq("sample_sd").all() and leaf.quality_flag.eq("ok").all() and
                    leaf.n_rep.ge(2).all() and np.isfinite(leaf[["unrounded_source_mean", "raw_sd"]]).all().all()
                    and leaf.raw_sd.ge(0).all() and leaf.unrounded_source_mean.ge(0).all(),
                    "Unusable refreshed leaf dry mass observations")
            q = q.set_index(KEYS)
            q.loc[leaf.index, "observed"] = leaf.unrounded_source_mean
            q.loc[leaf.index, "observed_se"] = leaf.raw_sd / np.sqrt(leaf.n_rep)
            q = q.reset_index()
            refresh = dict(bundle_id=new_manifest["bundle_id"], manifest=record(new_manifest_path),
                           refreshed_variable="LWAD", pairs=len(leaf),
                           deterministic_simulation="archived outputs; identical model input bundle")
        q["variable"] = q.variable.replace(HARVEST)
        q["harvest_number"] = q.date.map(dict(zip(dates, range(1, len(dates) + 1)))).where(q.variable.isin(HARVEST.values()))
        q = pd.concat([q, q[q.variable.eq("FRESH_CUM") & q.date.eq(dates[-1])].assign(variable="TERMINAL_FRESH")])
        q = q.drop(columns=["treatment_label", "water_level", "nitrogen_level"]).merge(
            meta, on=["season_id", "treatment", "dataset_role"], validate="many_to_one")
        to_tonnes = q.variable.isin((*HARVEST.values(), "TERMINAL_FRESH"))
        q.loc[to_tonnes, ["observed", "simulated", "observed_se"]] /= 1000
        q.loc[to_tonnes, "unit"] = "t ha-1"
        q["time"] = q.dap
        q["time_label"] = q.date
        q["variable_label"] = q.variable.map(LABELS)
        q["source_file"] = "result_review/all_observed_simulated_pairs.csv"
        if season == "25SP" and refresh is not None:
            q.loc[q.variable.eq("LWAD"), "source_file"] = str(validation_bundle / "observation_uncertainty.csv")
        pairs.append(q[["season_id", "dataset_role", "treatment", "management", "water_level", "nitrogen_level",
                        "variable", "variable_label", "unit", "dap", "date", "time", "time_label",
                        "harvest_number", "observed", "simulated", "observed_se", "n_rep", "source_file"]])
        tr = plant.loc[plant.trno.isin(ids) & plant.DAP.ge(0),
                       ["trno", "date", "DAP", *GROWTH]].rename(columns={"trno": "treatment", "DAP": "dap"})
        require(tr.groupby("treatment").dap.apply(lambda x: x.sort_values().diff().dropna().eq(1).all()).all()
                and np.isfinite(tr[list(GROWTH)]).all().all() and tr[list(GROWTH)].ge(0).all().all(),
                f"Invalid daily plant series: {season}")
        tr = tr.melt(id_vars=["treatment", "date", "dap"], var_name="variable", value_name="simulated")
        tr["time"] = tr.dap
        tr["time_label"] = tr.date
        dates = pd.to_datetime(tr.date)
        tr["year"], tr["doy"] = dates.dt.year, dates.dt.dayofyear
        tr["date_code"] = dates.dt.strftime("%y%j").astype(int)
        tr["variable_label"] = tr.variable.map(LABELS)
        tr["unit"] = np.where(tr.variable.eq("LAID"), "m2/m2", "kg DM/ha")
        trajectories.append(tr.merge(meta, on="treatment", validate="many_to_one").assign(
            statistic="deterministic", source_file=f"{directory}/PlantGro.OUT"))

    tables = {
        "comparison.csv": pd.concat(pairs, ignore_index=True).assign(run_id=run.name, data_status=status),
        "simulation_trajectory.csv": pd.concat(trajectories, ignore_index=True).assign(run_id=run.name, data_status=status),
        "representative_treatments.csv": pd.concat(chosen, ignore_index=True),
        "treatment_metadata.csv": metadata,
    }
    payload = dict(schema_version=1, bundle_type="spring_deterministic_figures", run_id=run.name,
                   data_status=status, engineering_status=state["engineering_status"],
                   retained=state["retained"], members=state["members"], selection=selection,
                   treatment_order=TREATMENTS, sources=list(sources.values()))
    if refresh is not None:
        payload["validation_refresh"] = refresh
    return tables, payload


def export(run, out, allow_demo, validation_bundle=None):
    tables, payload = prepare_spring_tables(run, allow_demo, validation_bundle)
    out.mkdir(parents=True, exist_ok=False)
    artifacts = []
    for name, table in tables.items():
        path = out / name
        table.to_csv(path, index=False)
        artifacts.append({**record(path), "path": name})
    payload["artifacts"] = artifacts
    manifest_path = out / "paper_data_manifest.json"
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--validation-bundle", type=Path)
    parser.add_argument("--allow-unvalidated-demo", action="store_true")
    args = parser.parse_args()
    print(export(args.run_dir.resolve(), args.out_dir.resolve(), args.allow_unvalidated_demo,
                 args.validation_bundle.resolve() if args.validation_bundle else None))
