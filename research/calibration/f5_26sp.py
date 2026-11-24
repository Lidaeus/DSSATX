"""Prepare and assess the controlled 26SP F5/F6 experiments."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

from prepare_26sp_signal import FILES, replace_assignment

RESEARCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH / "root_n_kernel/p1_4864"))
from replay_organic_refill import ARCHIVE, IDENTITY, digest, model_output, summarize
from verify_p1 import audit
sys.path.insert(0, str(RESEARCH / "n_diagnostics"))
from data import native_table

N2_LEAF_DAYS = (2026122, 2026153, 2026180)
JUNE_29 = 2026180
F5 = {
    "q_no3_max": "0.0072", "leaf_a": "0.040", "leaf_b": "0.30", "max_ratio": "1.24",
    "rnk_vmax_scale": "0.68", "rnk_vmax_high": ("0.00012", "0.00018"),
    "rnk_km_low": ("110.", "110."),
}
F6 = F5 | {
    "rnk_vmax_scale": "0.65", "rnk_km_low": ("115.", "115."), "q_no3_max": "0.0075",
}
BOUNDS = (
    ("rnk_vmax_scale", 0.68, 0.50, 0.78),
    ("rnk_vmax_high_no3", 0.00012, 0.00008, 0.00018),
    ("rnk_km_low_no3", 110.0, 75.0, 160.0),
    ("q_no3_max", 0.0072, 0.0060, 0.0085),
    ("refill_substrate_km", 0.05, 0.025, 0.12),
    ("assim_no3_v", 0.006700886921448985, 0.0055, 0.0095),
    ("assim_no3_k", 0.00035284325887431216, 0.0002, 0.0009),
    ("pool_beta", 0.20753800491343818, 0.05, 0.60),
    ("leaf_a", 0.040, 0.037, 0.045),
    ("leaf_b", 0.30, 0.22, 0.36),
    ("max_ratio", 1.24, 1.18, 1.30),
)
F6_PRIORS = {
    "rnk_vmax_scale": (0.65, 0.50, 0.78),
    "rnk_km_low_no3": (115.0, 80.0, 160.0),
    "q_no3_max": (0.0075, 0.0062, 0.0088),
    "assim_no3_v": (0.0067, 0.0055, 0.0095),
    "assim_no3_k": (0.00035, 0.00020, 0.00090),
    "pool_beta": (0.21, 0.05, 0.60),
}
HILL_SETTINGS = " lux_veg_mode=2, lux_psi_threshold=.76, lux_hill_k=.04, lux_xfrt_drop=.50,"
NO3_ARRAY = {"rnk_vmax_high_no3": "rnk_vmax_high", "rnk_km_low_no3": "rnk_km_low"}
SPLITS = {
    "observations.csv": ("fit", "diagnostic"),
    "holdout.csv": ("holdout",),
    "stage2b_observations.csv": ("n3",),
}
TOLERANCES = {
    "legacy_organic_N_residual": 1e-5, "legacy_growth_C_overrun": 1e-5, "Q_residual": 1e-12,
}


def config_text(base, settings, enabled):
    km = ".05" if enabled else "0."
    new_assignments = (
        f" org_reserve_cap=0.,0., refill_tau=0., refill_substrate_target={int(enabled)},\n"
        f" refill_substrate_km={km},"
    )
    text = base.replace("&NINTEGRATION", "&NINTEGRATION\n" + new_assignments, 1)
    for key, value in settings.items():
        if isinstance(value, tuple):
            pat = rf"(?im)(^[^!\r\n]*?\b{key}\s*=\s*)[^!,\r\n]+,[^!,\r\n]+"
            text, count = re.subn(pat, lambda match: match[1] + ",".join(value), text)
        else:
            text, count = replace_assignment(text, key, value)
        if count != 1:
            raise ValueError(f"Expected one configuration assignment for {key}")
    return text


def prepare(experiment, inputs, out, profile="f5"):
    source = json.loads((ARCHIVE / "input_receipt.json").read_text())["input_source_sha256"]
    for name, expected in source.items():
        if digest(experiment / name) != expected or (name in FILES and digest(inputs / name) != expected):
            raise ValueError(f"Mismatch against the archived private input: {name}")
    out.mkdir(parents=True)
    dest = out / "inputs"
    shutil.copytree(inputs, dest)
    reproduced = json.loads((ARCHIVE / "replay_receipt.json").read_text())["rendered_config_sha256"]
    for name, expected in reproduced.items():
        path = ARCHIVE / "configs" / name
        if digest(path) != expected:
            raise ValueError(f"80x4 selected card changed: {name}")
        shutil.copyfile(path, dest / name)
    base = (dest / "NIntegration.nml").read_text(encoding="ascii")
    for name, options, enabled in (("control", {}, False), ("f5", F5, True), ("f6", F6, True)):
        (out / f"{name}.nml").write_text(config_text(base, options, enabled), encoding="ascii")
    priors = BOUNDS
    if profile == "f6":
        priors = [(name, *F6_PRIORS.get(name, tuple(values))) for name, *values in BOUNDS]
        for name in ("f5", "f6"):
            text = (out / f"{name}.nml").read_text(encoding="ascii")
            text = text.replace("&NINTEGRATION", "&NINTEGRATION\n" + HILL_SETTINGS, 1)
            (out / f"{name}_hill.nml").write_text(text, encoding="ascii")
    parameters = pd.DataFrame(priors, columns=["name", "init", "lower", "upper"])
    text = (out / f"{profile}.nml").read_text(encoding="ascii")
    for alias in parameters.name:
        text, count = replace_assignment(text, NO3_ARRAY.get(alias, alias), f"~ {alias:26s} ~")
        if count != 1:
            raise ValueError(f"Expected one template field for {alias}")
    (out / "NIntegration.nml.tpl").write_text("ptf ~\n" + text, encoding="ascii")
    parameters.to_csv(out / "bounds.csv", index=False)
    observations = pd.read_csv(ARCHIVE / "matched_observations.csv", float_precision="round_trip")
    new_leaf = (observations.role.eq("diagnostic") & observations.nitrogen_level.eq("N2")
                & observations.column.eq("LN%D") & observations.yrdoy.isin(N2_LEAF_DAYS))
    if new_leaf.sum() != 9:
        raise ValueError("Expected nine new N2 leaf-N observations")
    observations.loc[new_leaf, "role"] = "fit"
    observations.loc[new_leaf, "sample_sd_or_scale"] = .40
    fit_leaf = observations.role.eq("fit") & observations.column.eq("LN%D")
    observations.loc[fit_leaf, "weight"] = 1 / (
        observations.loc[fit_leaf, "sample_sd_or_scale"] * math.sqrt(fit_leaf.sum())
    )
    target_columns = ["name", "file", "column", "treatment", "yrdoy", "observed", "weight",
                      "group", "sample_sd_or_scale", "preflight_only"]
    for filename, roles in SPLITS.items():
        subset = observations.loc[observations.role.isin(roles), target_columns].copy()
        subset["preflight_only"] = int(filename != "observations.csv")
        subset.to_csv(out / filename, index=False)
    metadata = pd.read_csv(experiment / "treatment_metadata.csv")
    metadata.to_csv(out / "treatment_metadata.csv", index=False)
    frozen_count = len(pd.read_csv(ARCHIVE / "best_parameters.csv")) - len(
        set(parameters.name) & set(pd.read_csv(ARCHIVE / "bounds.csv").name)
    )
    receipt = {
        "profile": profile, "frozen_80x4_parameters": frozen_count, "active_parameters": len(parameters),
        "positive_observations": int(observations.weight.gt(0).sum()),
        "positive_leaf_N": int(fit_leaf.sum()), "added_N2_leaf_N": observations.loc[new_leaf, "name"].tolist(),
        "source_sha256": source, "frozen_config_sha256": reproduced,
        "stage_files_sha256": {p.name: digest(p) for p in out.iterdir() if p.is_file()},
    }
    (out / "input_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def run_case(engine, stage, case, config):
    shutil.copytree(stage / "inputs", case)
    shutil.copyfile(config, case / "NIntegration.nml")
    env = dict(os.environ, DSSAT_HOME="./", DSSAT_P0_TRACE="1", DSSAT_SLN_PROBE_CUT="0")
    for key in ("DSSAT_N_CONFIG", "DSSAT_ROOT_UPTAKE_NML", "DSSAT_NSTATE_NML"):
        env.pop(key, None)
    with (case / "dssat.log").open("wb") as log:
        subprocess.run([str(engine), "CRGRO048", "B", "DSSBatch.v48"], cwd=case, env=env,
                       stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, check=True, timeout=300)


def compare_case(engine, stage, case, config):
    run_case(engine, stage, case, config)
    return assess_case(stage, case)


def assess_case(stage, case):
    groups, plant = summarize(case)
    residuals = {key: float(plant[key].abs().max()) for key in TOLERANCES}
    if not all(math.isfinite(value) and value < TOLERANCES[key] for key, value in residuals.items()):
        raise ValueError(f"{case.name} failed native residual thresholds: {residuals}")
    tables = {name: native_table(case / name, allow_numeric_overflow=True).set_index(["treatment", "yrdoy"])
              for name in ("PlantGro.OUT", "FreshWt.OUT", "PlantN.OUT")}
    metadata = pd.read_csv(stage / "treatment_metadata.csv")
    root = pd.read_csv(case / "LayerRootNUptake.csv",
                       usecols=["run", "species", "hats_candidate_gN_m2"])
    nitrate_hats = root.loc[root.species.eq(1)].groupby("run").hats_candidate_gN_m2.sum()
    for row in metadata.itertuples(index=False):
        values = tables["PlantN.OUT"].loc[(row.treatment, JUNE_29)]
        receiver = groups[row.water_level][row.nitrogen_level]
        receiver["leaf_n_june29_pct"] = float(values["LN%D"])
        receiver["stem_n_june29_pct"] = float(values["SN%D"])
        receiver["no3_hats_candidate_kgN_ha"] = 10 * float(nitrate_hats.loc[row.treatment])
    for filename in SPLITS:
        targets = pd.read_csv(stage / filename)
        targets["simulated"] = [tables[t.file].loc[(t.treatment, t.yrdoy), t.column] for t in targets.itertuples()]
        if not np.isfinite(targets.simulated).all() or targets.simulated.le(-99).any():
            raise ValueError(f"Invalid daily predictions in {filename}")
        targets["phi_contribution"] = np.square((targets.simulated - targets.observed) * targets.weight)
        targets.to_csv(case / f"paired_{filename}", index=False)
        if filename == "observations.csv":
            fit = targets.loc[targets.weight.gt(0)]
            phi_by_group = fit.groupby("group").phi_contribution.sum().to_dict()
    return {
        "groups": groups, "residuals": residuals, "audit": audit(case, 12),
        "phi": sum(phi_by_group.values()), "phi_by_group": phi_by_group,
        "config_sha256": digest(case / "NIntegration.nml"),
    }


def gate(candidate, control):
    # The roadmap gives qualitative LAI and Phi thresholds. Record their
    # numerical interpretation so future runs can compare like for like.
    phi_limit = control["phi"] * 1.10
    details = {"phi": {"actual": candidate["phi"], "limit": phi_limit, "pass": candidate["phi"] <= phi_limit}}
    for water in ("W2", "W3"):
        low, medium, high = (candidate["groups"][water][key] for key in ("N0", "N1", "N2"))
        yield_gain = (high["fresh_kg_ha"] - medium["fresh_kg_ha"]) / 1000
        leaf_n_gain = high["leaf_n_june29_pct"] - medium["leaf_n_june29_pct"]
        lai_steps = [medium["peak_lai"] - low["peak_lai"], high["peak_lai"] - medium["peak_lai"]]
        yield_monotone = bool(low["fresh_kg_ha"] < medium["fresh_kg_ha"] < high["fresh_kg_ha"])
        details[water] = {
            "yield_monotone": yield_monotone,
            "N2_minus_N1_fresh_t_ha": yield_gain, "N2_minus_N1_leaf_n_pct_points": leaf_n_gain,
            "peak_LAI_steps": lai_steps,
            "pass": bool(yield_monotone and 3 <= yield_gain <= 6
                         and .25 <= leaf_n_gain <= .35 and min(lai_steps) >= .05),
        }
    return {"pass": all(item["pass"] for item in details.values()), "details": details}


def compare(engine, stage, out, reference, posterior):
    out.mkdir(parents=True)
    cases = {name: stage / f"{name}.nml" for name in ("control", "f5", "f6")}
    if posterior:
        cases["posterior"] = posterior
    with ThreadPoolExecutor(max_workers=len(cases)) as pool:
        jobs = {name: pool.submit(compare_case, engine, stage, out / name, config) for name, config in cases.items()}
        results = {name: job.result() for name, job in jobs.items()}
    write_receipt(engine, out, reference, results)


def write_receipt(engine, out, reference, results):
    same = {name: model_output(out / "control" / name) == model_output(reference / name)
            for name in sorted(IDENTITY | {"P0Trace.csv"})}
    receipt = {
        "engine_sha256": digest(engine), "control_refills_disabled": same, "cases": results,
        "stage_2a_gates": {name: gate(value, results["control"]) for name, value in results.items() if name != "control"},
    }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n")
    rows = [
        dict(case=name, water=water, nitrogen=nitrogen, **values)
        for name, case in results.items() for water, group in case["groups"].items()
        for nitrogen, values in group.items()
    ]
    pd.DataFrame(rows).to_csv(out / "treatment_summary.csv", index=False)
    if not all(same.values()):
        raise ValueError(f"Disabled branch differs from the archived reference: {same}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    subs = ap.add_subparsers(dest="action", required=True)
    staging = subs.add_parser("prepare")
    for key in ("experiment", "inputs", "out"):
        staging.add_argument(f"--{key}", type=Path, required=True)
    staging.add_argument("--profile", choices=("f5", "f6"), default="f5")
    replay = subs.add_parser("compare")
    for key in ("engine", "stage", "out", "reference"):
        replay.add_argument(f"--{key}", type=Path, required=True)
    replay.add_argument("--posterior",type=Path)
    args = ap.parse_args()
    if args.action == "prepare":
        prepare(args.experiment.resolve(), args.inputs.resolve(), args.out.resolve(), args.profile)
    else:
        compare(args.engine.resolve(),args.stage.resolve(),args.out.resolve(),args.reference.resolve(),args.posterior)


if __name__ == "__main__":
    main()
