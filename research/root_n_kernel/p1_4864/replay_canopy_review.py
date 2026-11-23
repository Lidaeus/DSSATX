"""Isolate canopy size, assimilation and input-card effects in 26SP."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import json
import os
from pathlib import Path
import re
import shutil
from statistics import mean

from replay_shoot import DAYS, FIXTURE, GROUPS, TEMPLATE, audit, daily_csv, digest, native_crop
from replay_shoot import prepare_case, prepare_experiment, run, stage_config
from replay_signal_chain import EXPERIMENT_INPUTS, probe_trace

CAPACITY = {"assim_no3_v": 0.006, "assim_no3_k": 0.00038, "q_no3_max": 0.004}
UPPER = {"assim_no3_v": 0.010, "assim_no3_k": 0.00030, "q_no3_max": 0.006}
C4_MAGNITUDE = {"assim_no3_v": 0.005598479402692075, "assim_no3_k": 0.00038010677801968889,
                "q_no3_max": 0.0040079321431243983}
STAGES = ("official", "B1", "B2", "B3", "B4a", "B4")


def edit_cultivar(path, changes):
    """Keep DSSAT's fixed-width cultivar fields and the other cultivar cards."""
    lines = path.read_text(encoding="ascii").splitlines(keepends=True)
    header = next(line for line in lines if line.startswith("@VAR#"))
    for index, line in enumerate(lines):
        if not line.startswith("TM0008 "):
            continue
        for field, value in changes.items():
            end = re.search(rf"(?<!\S){re.escape(field)}(?!\S)", header).end()
            token = f"{value:.5g}"
            if len(token) > 6:
                raise ValueError(f"{field}={value} does not fit the six-character cultivar field")
            line = line[:end - 6] + token.rjust(6) + line[end:]
        lines[index] = line
        path.write_text("".join(lines), encoding="ascii")
        return
    raise ValueError("Missing cultivar TM0008")


def season(case, integrated, traced):
    growth, fruit, native_n = (native_crop(case / name) for name in ("PlantGro.OUT", "FreshWt.OUT", "PlantN.OUT"))
    plant = daily_csv(case / "PlantNIntegration.csv") if integrated else None
    cash = daily_csv(case / "PlantCCash.csv") if integrated else None
    lai = daily_csv(case / "PlantNLAI.csv") if (case / "PlantNLAI.csv").exists() else None
    trace = probe_trace(case / "P0Trace.csv") if traced else None
    results = {}
    for water, runs in GROUPS.items():
        results[water] = {}
        for level, r in enumerate(runs):
            days = sorted(day for day in DAYS if day[0] == r)
            last = growth[days[-1]]
            y = fruit[max(day for day in fruit if day[0] == r)]
            row = {
                "peak_lai": max(growth[day]["LAID"] for day in days), "end_shoot": last["CWAD"],
                "end_leaf": last["LWAD"], "end_stem": last["SWAD"], "fresh": y["CHFPW"],
                "uptake": native_n[days[-1]]["NUPC"], "harvested_fruit_dm": y["CHPDT"],
                "fresh_at_first_pick": fruit.get((r, 2026146), {}).get("CHFPW"),
                "end_pods_per_m2": last["P#AD"],
            }
            if integrated:
                row |= {
                    "uptake": 10 * sum(plant[day]["U_NO3"] + plant[day]["U_NH4"] for day in days),
                    "no3_assim": 10 * sum(plant[day]["A_NO3"] for day in days),
                    "pg": sum(cash[day]["PG"] for day in days),
                    "fruit_c": sum(cash[day]["fruit_growth"] for day in days),
                    "veg_c": sum(cash[day]["veg_growth"] for day in days),
                    "rsp": sum(cash[day]["N_assim"] for day in days),
                    "early_lai_dap49": growth[r, 2026122]["LAID"],
                }
            if lai:
                denom = sum(lai[day]["dm_leaf_potential"] for day in days)
                row["leaf_requested_to_potential"] = sum(lai[day]["dm_leaf_request"] for day in days) / denom if denom else None
            if trace and integrated:
                photo = [v for day in days for v in trace[day].get(("sln_photo", "factor"), ())]
                sln = [v for day in days for v in trace[day].get(("sln_photo", "functional_SLN"), ())]
                surplus = [max(0, trace[day]["rnk_psi_feedback", "psi"][0]) for day in days]
                if photo:
                    late = [v for day in days if day[1] >= 2026181 for v in trace[day].get(("sln_photo", "factor"), ())]
                    row |= {"sln": mean(sln), "photo_factor": mean(photo), "unsaturated": mean(f < 1 for f in photo),
                            "late_photo_factor": mean(late)}
                for period, photo_days in (("season", days), ("late", [day for day in days if day[1] >= 2026181])):
                    fields = ("uncapped_SLN", "critical_SLN", "whole_LMA", "cmin", "ccrit")
                    basis = {field: [v for day in photo_days for v in trace[day].get(("sln_photo_basis", field), ())]
                             for field in fields}
                    if basis["uncapped_SLN"]:
                        assert all(len(values) == len(basis["uncapped_SLN"]) for values in basis.values())
                        row[f"{period}_sln_basis"] = {
                            **{field: mean(values) for field, values in basis.items()},
                            "critical_cap_share": mean(u > c for u, c in zip(basis["uncapped_SLN"], basis["critical_SLN"])),
                        }
                row |= {"positive_psi_days": sum(p > 0 for p in surplus), "mean_positive_component_psi": mean(surplus)}
            results[water][f"N{level}"] = row
    return results


def trial(engine, source, out, traced, spec):
    label, data, background, stage, options, changes = spec
    print(f"Running {label}", flush=True)
    case = prepare_case(argparse.Namespace(config=TEMPLATE, out=out / label))
    if data.startswith("sasc70"):
        for name in EXPERIMENT_INPUTS:
            shutil.copyfile(source / name, case / name)
    elif data == "fixture-sasc70-cultivar":
        shutil.copyfile(source / "TMGRO048.CUL", case / "TMGRO048.CUL")
    swaps = {
        "sasc70-fixture-cul": ("TMGRO048.CUL",),
        "sasc70-fixture-eco": ("TMGRO048.ECO",),
        "sasc70-fixture-spe": ("TMGRO048.SPE",),
        "sasc70-fixture-crop": ("TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE"),
    }
    for name in swaps.get(data, ()):
        shutil.copyfile(FIXTURE / name, case / name)
    if changes:
        edit_cultivar(case / "TMGRO048.CUL", changes)
    if background != "field":
        prepare_experiment(case / "XXQL2601.TMX", background)
    integrated = stage != "official"
    if integrated:
        config = stage_config(stage, ({"photo_sln_ref": 1.05} if stage not in ("B1", "B2") else {}) | options)
    else:
        config = "&NINTEGRATION\n ni_stage=0\n/\n"
    (case / "NIntegration.nml").write_text(config, encoding="ascii")
    env = dict(os.environ, DSSAT_HOME=f".{os.sep}", DSSAT_P0_TRACE=str(int(traced and integrated)), DSSAT_SLN_PROBE_CUT="0")
    for key in ("DSSAT_N_CONFIG", "DSSAT_ROOT_UPTAKE_NML", "DSSAT_NSTATE_NML"):
        env.pop(key, None)
    run([str(engine), "CRGRO048", "B", "DSSBatch.v48"], case, "dssat", env)
    files = ("NIntegration.nml", "XXQL2601.TMX", "TMGRO048.CUL", "TMGRO048.SPE", "TMGRO048.ECO", "XXTW2403.WTH", "SOIL.SOL")
    return label, {
        "data": data, "background": background, "stage": stage, "overrides": options,
        "cultivar_overrides": changes, "inputs": {name: digest(case / name) for name in files},
        "audit": audit(case, 12) if traced and integrated else None,
        "water": season(case, integrated, traced),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case", action="append", help="Select one named scenario. Repeat to select several.")
    parser.add_argument("--card-contrasts", action="store_true", help="Run only the follow-up cultivar and card contrasts")
    parser.add_argument("--traced", action="store_true", help="Run selected cases on the instrumented probe engine")
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    source = args.experiment.resolve(strict=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    specs = [(f"fixture-{stage}", "fixture", "common-soil", stage, {}, {}) for stage in STAGES]
    specs.extend((f"sasc70-{stage}", "sasc70", "common-soil", stage, {}, {}) for stage in STAGES)
    specs.extend((f"sasc70-field-{stage}", "sasc70", "field", stage, {}, {}) for stage in ("official", "B4"))
    specs += [
        ("fixture-field-official", "fixture", "field", "official", {}, {}),
        ("fixture-sasc70-cultivar", "fixture-sasc70-cultivar", "common-soil", "B4", {}, {}),
        ("fixture-v", "fixture", "common-soil", "B4", {"assim_no3_v": CAPACITY["assim_no3_v"]}, {}),
        ("fixture-k", "fixture", "common-soil", "B4", {"assim_no3_k": CAPACITY["assim_no3_k"]}, {}),
        ("fixture-q", "fixture", "common-soil", "B4", {"q_no3_max": CAPACITY["q_no3_max"]}, {}),
        ("fixture-c4-priors", "fixture", "common-soil", "B4", C4_MAGNITUDE, {}),
        ("fixture-joint-moderate", "fixture", "common-soil", "B4", CAPACITY, {}),
        ("fixture-joint-upper", "fixture", "common-soil", "B4", UPPER, {}),
        ("fixture-xfrt", "fixture", "common-soil", "B4", {}, {"XFRT": 0.78}),
        ("fixture-lfmax", "fixture", "common-soil", "B4", {}, {"LFMAX": 2.2}),
        ("fixture-lai1", "fixture", "common-soil", "B4", {"lai_cn_shape": 1}, {}),
        ("fixture-sln095", "fixture", "common-soil", "B4", {"photo_sln_ref": 0.95}, {}),
        ("fixture-sln085", "fixture", "common-soil", "B4", {"photo_sln_ref": 0.85}, {}),
        ("fixture-leafa035", "fixture", "common-soil", "B4", {"leaf_a": 0.035}, {}),
        ("fixture-minratio045", "fixture", "common-soil", "B4", {"min_ratio": 0.45}, {}),
        ("sasc70-joint-moderate", "sasc70", "common-soil", "B4", CAPACITY, {}),
        ("sasc70-joint-upper", "sasc70", "common-soil", "B4", UPPER, {}),
        ("sasc70-field-moderate", "sasc70", "field", "B4", CAPACITY, {}),
    ]
    specs.extend((f"fixture-moderate-{stage}", "fixture", "common-soil", stage, CAPACITY, {})
                 for stage in ("B1", "B2", "B3", "B4a"))
    if args.card_contrasts:
        specs = [(f"{data}-{stage}", data, "common-soil", stage, options, {})
                 for data in ("sasc70-fixture-cul", "sasc70-fixture-eco", "sasc70-fixture-spe", "sasc70-fixture-crop")
                 for stage, options in (("official", {}), ("B4", CAPACITY))]
        specs += [(f"sasc70-cul-{label}", "sasc70", "common-soil", "B4", CAPACITY, fields)
                  for label, fields in (
                      ("podur", {"PODUR": 8.207}), ("sfdur", {"SFDUR": 45.44}),
                      ("fl-lf", {"FL-LF": 207.4}), ("fl-sd", {"FL-SD": 24.57}),
                      ("xfrt", {"XFRT": 0.9234}), ("slar", {"SLAVR": 208}),
                      ("lfmax", {"LFMAX": 1.962}),
                      ("fruit-duration", {"PODUR": 8.207, "SFDUR": 45.44}),
                  )]
        specs += [(f"fixture-moderate-{label}", "fixture", "common-soil", "B4", CAPACITY | settings, changes)
                  for label, settings, changes in (
                      ("sln095", {"photo_sln_ref": 0.95}, {}), ("sln085", {"photo_sln_ref": 0.85}, {}),
                      ("lai1", {"lai_cn_shape": 1}, {}), ("xfrt", {}, {"XFRT": 0.78}),
                      ("lfmax", {}, {"LFMAX": 2.2}),
                  )]
        specs += [(f"canopy-recovery-{label}", "sasc70-fixture-crop", "common-soil", "B4", CAPACITY | settings, {})
                  for label, settings in (
                      ("sln095", {"photo_sln_ref": 0.95}), ("sln085", {"photo_sln_ref": 0.85}),
                      ("lai1", {"lai_cn_shape": 1}), ("leafa035", {"leaf_a": 0.035}),
                      ("minratio045", {"min_ratio": 0.45}),
                  )]
    elif args.traced and not args.case:
        selected = {"fixture-B4", "fixture-lai1", "fixture-leafa035", "fixture-minratio045", "fixture-sln095",
                    "fixture-joint-moderate", "fixture-joint-upper", "sasc70-B4", "sasc70-joint-moderate",
                    "sasc70-joint-upper"}
        specs = [spec for spec in specs if spec[0] in selected]
    if args.case:
        names = set(args.case)
        specs = [spec for spec in specs if spec[0] in names]
        if {spec[0] for spec in specs} != names:
            parser.error("Unknown case for this set")
    worker = partial(trial, engine, source, out, args.traced)
    with ProcessPoolExecutor(max_workers=min(6, len(specs))) as pool:
        trials = dict(pool.map(worker, specs))
    receipt = {"engine_sha256": digest(engine), "cases": trials}
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")
    print(out / "receipt.json")


if __name__ == "__main__":
    main()
