"""Audit organic refill and root supply at the frozen 26SP IES point."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

from replay_shoot import GROUPS, digest, prepare_experiment
from verify_p1 import audit

RESEARCH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH / "calibration"))
from prepare_26sp_signal import replace_assignment
sys.path.insert(0, str(RESEARCH / "n_diagnostics"))
from data import native_table

ARCHIVE = RESEARCH / "calibration/results/26sp_80x4"
CONTROLS = {"org_reserve_cap": "0.,0.", "refill_tau": "0."}
CAPACITY = {"org_reserve_cap": "0.015,0.010"}
RATE = {"refill_tau": "4."}
ROOT = {"rnk_vmax_scale": "0.75", "q_no3_max": "0.008"}
TRIALS = {
    "field-zero": CONTROLS,
    "common-zero": CONTROLS,
    "capacity": CAPACITY,
    "rate": RATE,
    "capacity-rate": CAPACITY | RATE,
    "vmax-060": {"rnk_vmax_scale": "0.6"},
    "vmax-090": {"rnk_vmax_scale": "0.9"},
    "pool-006": {"q_no3_max": "0.006"},
    "pool-008": {"q_no3_max": "0.008"},
    "root-paired": ROOT,
    "combined": CAPACITY | RATE | ROOT,
    "field-capacity-rate": CAPACITY | RATE,
}
DEFAULT_TRIALS = tuple(name for name in TRIALS if name != "field-capacity-rate")
FIELD_TRIALS = {"field-zero", "field-capacity-rate"}
TRACE = {"rnk_pool_capacity": ["QNO3_max"], "rnk_psi_feedback": ["psi", "membrane_factor"],
         "refill_partition": ["repair_leaf", "repair_stem", "repair_root", "luxury_leaf", "luxury_stem",
                              "limit_leaf", "limit_stem"]}
IDENTITY = {
    "PlantGro.OUT", "PlantN.OUT", "FreshWt.OUT", "PlantCCash.csv",
    "PlantNIntegration.csv", "PlantNLAI.csv", "PlantNLeaf.csv", "PlantNV3.csv",
    "PlantABudget.csv", "LayerRootNUptake.csv",
}


def trace_daily(path):
    parts = []
    for block in pd.read_csv(path, usecols=["run", "yrdoy", "event", "key", "value"], chunksize=200_000):
        parts.append(block.loc[block.event.isin(TRACE)])
    frame = pd.concat(parts, ignore_index=True)
    allowed = [(event, name) for event, names in TRACE.items() for name in names]
    frame = frame.loc[pd.MultiIndex.from_frame(frame[["event", "key"]]).isin(allowed)]
    return frame.pivot(index=["run", "yrdoy"], columns="key", values="value")


def summarize(case):
    plant = pd.read_csv(case / "PlantNIntegration.csv").set_index(["run", "yrdoy"])
    traces = trace_daily(case / "P0Trace.csv")
    fruit = native_table(case / "FreshWt.OUT", allow_numeric_overflow=True)
    growth = native_table(case / "PlantGro.OUT", allow_numeric_overflow=True)
    summary = (case / "Summary.OUT").read_text().splitlines()
    column = next(line for line in summary if line.startswith("@")).split().index("ADAT") - 1
    first_flower = {int(parts[0]): int(parts[column])
                    for line in summary if (parts := line.split()) and parts[0].isdigit()}
    layer = pd.read_csv(case / "LayerRootNUptake.csv")
    candidate = (layer.loc[layer.species.eq(1)].groupby(["run", "source_day"])
                 .candidate_gN_m2.sum().rename("NO3_candidate"))
    candidate.index.names = plant.index.names
    daily = plant.join(traces).join(candidate)
    # End-of-day capacity is a proxy for the capacity at root acceptance.
    daily["exposure_proxy"] = daily.NO3_candidate / daily.QNO3_max.where(daily.QNO3_max.gt(0))
    if "luxury_leaf" in daily:
        luxury = daily[["luxury_leaf", "luxury_stem"]].to_numpy()
        limits = daily[["limit_leaf", "limit_stem"]].to_numpy()
        assert np.isfinite(luxury).all() and (luxury >= 0).all() and (luxury <= limits + 1e-8).all()
    selection = {}
    for water, runs in GROUPS.items():
        selection[water] = {}
        for level, run in enumerate(runs):
            d = daily.loc[run].sort_index()
            last = d.iloc[-1]
            active = d.exposure_proxy.dropna()
            observed_fruit = fruit[fruit.run.eq(run)].sort_values("yrdoy")
            canopy = growth[growth.run.eq(run)]
            first_harvest = observed_fruit.loc[observed_fruit.CHFPW.gt(0), "yrdoy"].min()
            if pd.isna(first_harvest):
                first_harvest = observed_fruit.yrdoy.max()
            selection[water][f"N{level}"] = {
                "psi_at_one_before_flowering": int(d.loc[d.index < first_flower[run], "psi"].ge(1 - 1e-7).sum()),
                "uptake_kgN_ha": 10 * (d.U_NO3 + d.U_NH4).sum(),
                "no3_candidate_kgN_ha": 10 * d.NO3_candidate.sum(),
                "no3_assim_kgN_ha": 10 * d.A_NO3.sum(),
                "mean_q3_kgN_ha": 10 * d.QNO3.mean(),
                "q3_fill_mean": (d.QNO3 / d.QNO3_max.where(d.QNO3_max.gt(0))).mean(),
                "leaf_organic_mean_pct": 100 * d.Corg_leaf.mean(),
                "stem_organic_mean_pct": 100 * d.Corg_stem.mean(),
                "leaf_organic_end_pct": 100 * last.Corg_leaf,
                "stem_organic_end_pct": 100 * last.Corg_stem,
                "leaf_total_end_pct": 100 * last.Ctotal_leaf,
                "stem_total_end_pct": 100 * last.Ctotal_stem,
                "mean_leaf_nni": d.NNI_raw_leaf.mean(),
                "mean_day_psi": d.psi.mean(),
                "day_psi_at_one": int(d.psi.ge(1 - 1e-7).sum()),
                "psi_at_one_before_first_harvest": int(d.loc[d.index < first_harvest, "psi"].ge(1 - 1e-7).sum()),
                "mean_membrane_factor": d.membrane_factor.mean(),
                "exposure_median": active.median(),
                "exposure_ge_3_fraction": active.ge(3).mean(),
                "peak_lai": canopy.LAID.max(),
                "fresh_kg_ha": observed_fruit.CHFPW.iloc[-1],
                "luxury_refill_kgN_ha": 10 * d[["luxury_leaf", "luxury_stem"]].sum().sum()
                if "luxury_leaf" in d else None,
            }
    return selection, plant


def observation_envelope(plant, out):
    # Carrier allocations are simulated components, with 0 and 1 recoveries
    # providing bounds on the mineral contribution for each organ.
    components = {}
    for organ in ("leaf", "stem"):
        mass = plant[f"W_{organ}"].where(plant[f"W_{organ}"].gt(0))
        components[f"{organ}_organic_pct"] = 100 * plant[f"Norg_{organ}"] / mass
        components[f"{organ}_no3_n_pct"] = 100 * plant[f"QNO3_{organ}"] / mass
        components[f"{organ}_nh4_n_pct"] = 100 * plant[f"QNH4_{organ}"] / mass
        components[f"{organ}_total_pct"] = sum(components[f"{organ}_{form}_pct"]
                                               for form in ("organic", "no3_n", "nh4_n"))
    pd.DataFrame(components).to_csv(out / "organ_n_diagnostics.csv")
    pairs = pd.read_csv(ARCHIVE / "matched_observations.csv")
    pairs = pairs.loc[pairs.column.eq("LN%D")].copy()
    index = pd.MultiIndex.from_frame(pairs[["treatment", "yrdoy"]])
    leaf = plant.loc[index]
    if not leaf.W_leaf.gt(0).all():
        raise ValueError("Matched leaf N requires positive living leaf mass")
    for name, concentrations in components.items():
        if name.startswith("leaf_"):
            pairs[name] = concentrations.loc[index].to_numpy()
    np.testing.assert_allclose(pairs.leaf_total_pct, 100 * leaf.Ctotal_leaf.to_numpy(), atol=1e-11, rtol=0)
    pairs.to_csv(out / "leaf_n_observation_envelope.csv", index=False)
    return {role: {
        "count": len(g), "median_mineral_pct_points": float((g.leaf_total_pct - g.leaf_organic_pct).median()),
        "max_mineral_pct_points": float((g.leaf_total_pct - g.leaf_organic_pct).max()),
        "rmse_organic": float(np.sqrt(np.mean((g.leaf_organic_pct - g.observed)**2))),
        "rmse_full_mineral_recovery_scenario": float(np.sqrt(np.mean((g.leaf_total_pct - g.observed)**2))),
    } for role, g in pairs.groupby("role")}


def run_trial(engine, inputs, out, name):
    case = out / name
    shutil.copytree(inputs, case)
    for file in (ARCHIVE / "configs").iterdir():
        shutil.copyfile(file, case / file.name)
    config = case / "NIntegration.nml"
    settings = config.read_text(encoding="ascii")
    for key, value in TRIALS[name].items():
        if key in CONTROLS:
            settings = settings.replace("&NINTEGRATION", f"&NINTEGRATION\n {key}={value},", 1)
        else:
            settings, changed = replace_assignment(settings, key, value)
            if changed != 1:
                raise ValueError(f"Expected one setting for {key}")
    config.write_text(settings, encoding="ascii")
    if name not in FIELD_TRIALS:
        prepare_experiment(case / "XXQL2601.TMX", "common-soil")
    env = dict(os.environ, DSSAT_HOME="./", DSSAT_P0_TRACE="1", DSSAT_SLN_PROBE_CUT="0")
    for name_in_env in ("DSSAT_N_CONFIG", "DSSAT_ROOT_UPTAKE_NML", "DSSAT_NSTATE_NML"):
        env.pop(name_in_env, None)
    with (case / "dssat.log").open("wb") as log:
        subprocess.run([str(engine), "CRGRO048", "B", "DSSBatch.v48"], cwd=case, env=env,
                       stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=True, timeout=300)
    groups, plant = summarize(case)
    result = {"overrides": TRIALS[name], "NIntegration_sha256": digest(config),
              "TMX_sha256": digest(case / "XXQL2601.TMX"), "audit": audit(case, 12), "groups": groups}
    if name == "field-zero":
        result["observation_envelope"] = observation_envelope(plant, out)
    return name, result


def model_output(path):
    content = path.read_bytes()
    if path.suffix == ".OUT":
        # Native headers include the evaluation wall time. Retain model
        # version, treatment headers, all data rows, and line endings.
        content = re.sub(rb"(?m)^(\*DSSAT Cropping System Model [^\r\n]*?) +[A-Z]{3} +[0-9]{1,2}, +[0-9]{4} +[0-9:]{8}(?=\r?$)",
                         rb"\1", content)
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for opt in ("engine", "inputs", "out"):
        parser.add_argument(f"--{opt}", type=Path, required=True)
    parser.add_argument("--reference", type=Path, help="Archived field replay directory for byte checks")
    parser.add_argument("--trial", action="append", choices=TRIALS, help="Repeat to select individual contrasts")
    args = parser.parse_args()
    if args.reference and args.trial and "field-zero" not in args.trial:
        parser.error("--reference requires the field-zero trial")
    engine, inputs, out = (args.engine.resolve(strict=True), args.inputs.resolve(strict=True), args.out.resolve())
    if any(not p.is_file() or p.suffix.lower() in (".out", ".log") for p in inputs.iterdir()):
        raise ValueError("Expected the flat, frozen IES input directory")
    archived_hashes = json.loads((ARCHIVE / "input_receipt.json").read_text())["input_source_sha256"]
    for file in ("DSSBatch.v48", "XXQL2601.TMX", "SOIL.SOL", "XXTW2403.WTH"):
        if digest(inputs / file) != archived_hashes[file]:
            raise ValueError(f"Input differs from the frozen SASC70 experiment: {file}")
    out.mkdir(parents=True)
    trials = args.trial or DEFAULT_TRIALS
    with ThreadPoolExecutor(max_workers=min(4, len(trials))) as pool:
        pending = {name: pool.submit(run_trial, engine, inputs, out, name) for name in trials}
        results = dict(job.result() for job in pending.values())
    receipt = {"engine_sha256": digest(engine), "trials": results}
    if args.reference:
        byte_equal = {name: model_output(out / "field-zero" / name) == model_output(args.reference / name)
                      for name in sorted(IDENTITY)}
        receipt["disabled_byte_equal_excluding_native_run_timestamp"] = byte_equal
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    if args.reference and not all(byte_equal.values()):
        raise ValueError(f"Disabled refill changed outputs: {byte_equal}")


if __name__ == "__main__":
    main()
