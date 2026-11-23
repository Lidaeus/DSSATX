"""Audit the five 26SP water–N signal levels and scan the W3 uptake plateau."""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
from functools import partial
from itertools import product
import json
import os
from pathlib import Path
import re
import shutil
from statistics import mean

from replay_luxury import run_case, set_n_supply
from replay_shoot import (
    DAYS, GROUPS, audit, csv_rows, daily_csv, digest, native_crop, prepare_case,
    prepare_experiment, run,
)

EXPERIMENT_INPUTS = ("XXQL2601.TMX", "XXQL2601.TMA", "XXQL2601.TMT", "SOIL.SOL",
                     "XXTW2403.WTH", "TMGRO048.CUL", "TMGRO048.ECO", "TMGRO048.SPE", "DSSBatch.v48")
TRACE = {
    "rnk_psi_feedback": {"psi", "membrane_factor"},
    "rnk_pool_capacity": {"QNO3_max"},
    "rnk_plant_settled": {"NASSIMD", "RSPNO3", "PGAVL"},
    "sln_before_pods": {"NASSIMD", "RSPNO3", "PGAVL"},
    "cg_end": {"TNLEAK"},
    "veg_n_partition": {"FRRT"},
    "sln_n_senescence": {"extra_DM"},
    "c4_canopy_n": {"LAISL", "LAISH"},
    "sln_photo": {"functional_SLN", "factor"},
    "sln_photo_basis": {"uncapped_SLN", "critical_SLN", "whole_LMA", "cmin", "ccrit"},
    "pods_set_budget": {"PODADD", "C_limit", "flower_limit", "N_limit"},
    "new_pod_gate": {"accepted_count"},
}
GRADIENT_METRICS = ("cb_no3", "cr_no3", "uptake", "q_no3", "assim", "psi", "z_leaf",
                    "photo_sln", "photo_factor", "gross_photo", "peak_lai", "end_shoot",
                    "fruit_c", "fresh_yield")


def management(path):
    levels, doses = {}, defaultdict(float)
    section = ""
    for line in path.read_text(encoding="ascii").splitlines():
        if line.startswith("*"):
            section = line.strip()
        fields = line.split()
        if not fields or not fields[0].isdigit():
            continue
        if section.startswith("*TREATMENTS"):
            levels[int(fields[0])] = int(fields[11])
        elif section == "*FERTILIZERS (INORGANIC)":
            doses[int(fields[0])] += max(0, float(fields[5]))
    return {run: doses[level] for run, level in levels.items()}


def probe_trace(path):
    events = defaultdict(lambda: defaultdict(list))
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.reader(stream)
        assert next(reader) == "seq,run,yrdoy,das,dynamic,event,layer,key,value,text".split(",")
        for _, run, day, _, _, event, _, key, value, _ in reader:
            if key in TRACE.get(event, ()):
                events[int(run), int(day)][event, key].append(float(value))
    return events


def root_rows(case):
    daily = defaultdict(lambda: defaultdict(float))
    for row in csv_rows(case / "LayerRootNUptake.csv"):
        if row["species"] != "1":
            continue
        day = (int(row["run"]), int(row["yrdoy"]))
        r = daily[day]
        for name in ("candidate", "accepted", "settled"):
            r[name + "_no3"] += float(row[f"{name}_gN_m2"])
        # The root solver writes a placeholder zero for undefined concentration.
        if int(row["layer"]) <= 3 and int(row["solver_status"]) // 10 in (1, 2):
            r["cb_sum"] += float(row["c_bulk_mgN_L"])
            r["cr_sum"] += float(row["c_root_mgN_L"])
            r["c_samples"] += 1
    return daily


def matrix(case):
    trace = probe_trace(case / "P0Trace.csv")
    roots = root_rows(case)
    plant = daily_csv(case / "PlantNIntegration.csv")
    lai = daily_csv(case / "PlantNLAI.csv")
    cash = daily_csv(case / "PlantCCash.csv")
    crop = native_crop(case / "PlantGro.OUT")
    fresh = native_crop(case / "FreshWt.OUT")
    rows = []
    for run, day in sorted(DAYS):
        key = run, day
        t, p, r, c, l, g = trace[key], plant[key], roots[key], cash[key], lai[key], crop[key]
        def total(event, field):
            return sum(t.get((event, field), ()))
        def value(event, field):
            return t[event, field][0]
        fp = t["sln_photo", "factor"]
        assert len(fp) == len(t["sln_photo", "functional_SLN"]), key
        assert abs(r["settled_no3"] - p["U_NO3"]) < 1e-6, key
        assert abs(value("rnk_plant_settled", "NASSIMD") - p["A_NO3"] - p["A_NH4"]) < 1e-6, key
        has_pod_set = ("pods_set_budget", "PODADD") in t
        limiting = ""
        if has_pod_set:
            choices = ("PODADD", "C_limit", "flower_limit", "N_limit")
            caps = [value("pods_set_budget", label) for label in choices]
            # Keep ties separate. A zero from a closed gate does not establish control.
            if min(caps) > 0 and caps.count(min(caps)) == 1:
                limiting = choices[caps.index(min(caps))]
            else:
                limiting = "zero_or_tied"
        q_cap = value("rnk_pool_capacity", "QNO3_max")
        rows.append({
            "run": run, "yrdoy": day, "dap": int(g["DAP"]),
            "cb_no3_sum": r["cb_sum"], "cr_no3_sum": r["cr_sum"], "c_no3_samples": r["c_samples"],
            "candidate_no3": r["candidate_no3"], "accepted_no3": r["accepted_no3"],
            "settled_no3": r["settled_no3"], "uptake": p["U_NO3"] + p["U_NH4"],
            "q_no3": p["QNO3"], "q_no3_fill": p["QNO3"] / q_cap if q_cap else 0,
            "assim": p["A_NO3"] + p["A_NH4"], "assim_no3": p["A_NO3"],
            "rsp_no3_settled": value("rnk_plant_settled", "RSPNO3"),
            "rsp_no3_pre_pods": value("sln_before_pods", "RSPNO3"),
            "pgavl_pre_pods": value("sln_before_pods", "PGAVL"),
            "pgavl_n_settlement": value("rnk_plant_settled", "PGAVL"),
            "tnleak": value("cg_end", "TNLEAK"),
            "leaf_n_org_pct": 100 * p["Norg_leaf"] / p["W_leaf"],
            "leaf_n_total_pct": 100 * p["Ctotal_leaf"],
            "psi": value("rnk_psi_feedback", "psi"),
            "membrane_factor": value("rnk_psi_feedback", "membrane_factor"),
            "z_leaf": l["state_raw_leaf"],
            "photo_sln": mean(t["sln_photo", "functional_SLN"]) if fp else None,
            "photo_factor": mean(fp) if fp else None,
            "photo_calls": len(fp), "photo_unsat_calls": sum(f < 1 for f in fp),
            "gross_photo": c["PG"], "lai": l["LAI_end"], "new_leaf_area": l["new_leaf_area"],
            "sen_n_extra": total("sln_n_senescence", "extra_DM"),
            "frrt": value("veg_n_partition", "FRRT"),
            "sunlit_lai_sum": total("c4_canopy_n", "LAISL"),
            "shade_lai_sum": total("c4_canopy_n", "LAISH"),
            "maintenance": c["maintenance"], "fruit_c": c["fruit_growth"], "veg_c": c["veg_growth"],
            "pod_count_m2": g["P#AD"], "pod_gate": limiting,
            "new_pods": total("new_pod_gate", "accepted_count"),
            "leaf_dm": g["LWAD"], "stem_dm": g["SWAD"], "shoot_dm": g["CWAD"],
        })
    doses = management(case / "XXQL2601.TMX")
    seasons = {}
    for run in doses:
        days = [r for r in rows if r["run"] == run]
        last = days[-1]
        harvest = fresh[max(key for key in fresh if key[0] == run)]
        def summed(name):
            return sum(row[name] for row in days)
        def weighted_photo(name):
            return sum(row[name] * row["photo_calls"] for row in days if row["photo_calls"]) / summed("photo_calls")
        seasons[run] = {
            "fertilizer_kg_ha": doses[run],
            "cb_no3": summed("cb_no3_sum") / summed("c_no3_samples"),
            "cr_no3": summed("cr_no3_sum") / summed("c_no3_samples"),
            "c_no3_samples": summed("c_no3_samples"),
            **{name + "_kg_ha": 10 * summed(name) for name in ("candidate_no3", "accepted_no3", "settled_no3")},
            "uptake": 10 * summed("uptake"), "q_no3": mean(r["q_no3"] for r in days),
            "q_no3_fill_ge95_days": sum(r["q_no3_fill"] >= 0.95 for r in days),
            "assim": 10 * summed("assim"), "assim_to_uptake": summed("assim") / summed("uptake"),
            "rsp_no3": summed("rsp_no3_settled"), "min_pgavl_pre_pods": min(r["pgavl_pre_pods"] for r in days),
            "end_tnleak": last["tnleak"], "end_org_leaf_n_pct": last["leaf_n_org_pct"],
            "psi": mean(max(0, r["psi"]) for r in days),
            "positive_psi_days": sum(r["psi"] > 0 for r in days),
            "psi_cap_days": sum(r["psi"] == 1 for r in days),
            "z_leaf": mean(r["z_leaf"] for r in days), "photo_sln": weighted_photo("photo_sln"),
            "photo_factor": weighted_photo("photo_factor"),
            "late_photo_factor": mean(r["photo_factor"] for r in days if r["yrdoy"] >= 2026181 and r["photo_calls"]),
            "photo_unsat_fraction": summed("photo_unsat_calls") / summed("photo_calls"),
            "gross_photo": summed("gross_photo"), "peak_lai": max(r["lai"] for r in days),
            "end_lai": last["lai"], "new_leaf_area": summed("new_leaf_area"), "sen_n_extra": summed("sen_n_extra"),
            "frrt": mean(r["frrt"] for r in days),
            "maintenance": summed("maintenance"),
            "shade_fraction": summed("shade_lai_sum") / (summed("sunlit_lai_sum") + summed("shade_lai_sum")),
            "fruit_c": summed("fruit_c"), "veg_c": summed("veg_c"),
            "pod_gates": {gate: sum(r["pod_gate"] == gate for r in days)
                          for gate in ("PODADD", "C_limit", "flower_limit", "N_limit", "zero_or_tied")},
            "end_pod_count": last["pod_count_m2"], "new_pods": summed("new_pods"),
            "end_leaf": last["leaf_dm"], "end_stem": last["stem_dm"], "end_shoot": last["shoot_dm"],
            "hi": harvest["CHPDT"] / (last["shoot_dm"] + harvest["CHPDT"]), "fresh_yield": harvest["CHFPW"],
        }
    return rows, seasons


def gradient(treatments):
    dose = [row["fertilizer_kg_ha"] for row in treatments]
    dose_steps = [b - a for a, b in zip(dose, dose[1:])]
    assert min(dose_steps) > 0, dose
    result = {}
    for name in GRADIENT_METRICS:
        values = [row[name] for row in treatments]
        increments = [b - a for a, b in zip(values, values[1:])]
        slopes = [delta / step for delta, step in zip(increments, dose_steps)]
        result[name] = {"values": values, "delta": increments, "slope_per_kg_n": slopes,
                        "increasing": all(delta >= 0 for delta in increments),
                        "diminishing_0_to_2": slopes[0] > slopes[1] >= 0,
                        "diminishing_0_to_3": min(increments[:3]) >= 0 and slopes[0] > slopes[1] > slopes[2]}
    return result


def enable_fixed_diagnostics(config):
    settings = config.read_text(encoding="ascii")
    lines = [line.partition("!")[0] for line in settings.splitlines()]
    values = re.findall(r"\bphoto_sln_ref\s*=\s*([.\dDdEe+-]+)", "\n".join(lines), flags=re.I)
    if len(values) != 1 or float(values[0].lower().replace("d", "e")) != 1.05:
        raise ValueError("A fixed 26SP replay requires photo_sln_ref=1.05")
    settings, count = re.subn(
        r"(^[^!\n]*\bv4_diagnostics\s*=\s*)[01]\b", r"\g<1>1", settings, flags=re.I | re.M,
    )
    if count == 0:
        settings, count = re.subn(r"^(&NINTEGRATION)\b", r"\1\n v4_diagnostics=1,", settings, flags=re.I | re.M)
    if count != 1:
        raise ValueError("Expected one B4 diagnostic configuration")
    return settings


def stage_fixed_case(config, out, inputs=None):
    case = prepare_case(argparse.Namespace(config=config, out=out))
    if inputs is not None:
        for name in EXPERIMENT_INPUTS:
            shutil.copyfile(inputs / name, case / name)
    (case / "NIntegration.nml").write_text(enable_fixed_diagnostics(config), encoding="ascii")
    return case


def trial(engine, out, spec, *, background, config, inputs):
    label, scenario, overrides, scale = spec
    if config is None:
        case, audit_result = run_case(engine, out, scenario, 0, label=label, overrides=overrides,
                                      vmax_scale=scale, background=background)
    else:
        case = stage_fixed_case(config, out / scenario, inputs)
        nml = case / "NIntegration.nml"
        file_x = case / "XXQL2601.TMX"
        prepare_experiment(file_x, background)
        set_n_supply(file_x, scenario)
        env = dict(os.environ, DSSAT_HOME=f".{os.sep}", DSSAT_P0_TRACE="1", DSSAT_SLN_PROBE_CUT="0")
        env.pop("DSSAT_N_CONFIG", None)
        run([str(engine), "CRGRO048", "B", "DSSBatch.v48"], case, "dssat", env)
        audit_result = audit(case, 12) | {
            "config_sha256": digest(nml), "file_x_sha256": digest(file_x),
            "engine_sha256": digest(engine), "source_config_sha256": digest(config),
            "case_input_sha256": {name: digest(case / name) for name in EXPERIMENT_INPUTS},
        }
    daily, seasonal = matrix(case)
    with (case / "signal_daily.csv").open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(daily[0]))
        writer.writeheader()
        writer.writerows(daily)
    scales = {"vmax_scale": scale} if config is None else {}
    return label, scenario, {"audit": audit_result, "treatments": seasonal, "overrides": overrides} | scales


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True, help="build_sln_probe.py engine")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path,
                        help="Audit one rendered B4 parameter point on the matched and synthetic N4 cases")
    parser.add_argument("--inputs", type=Path, help="Use the experiment, weather, soil and crop cards from this case")
    parser.add_argument("--background", choices=("matched", "common-soil", "common-sa", "common-ic"), default="matched",
                        help="Scan matched W-specific backgrounds, or compare B4 with W2–N2 SA, IC or both")
    args = parser.parse_args()
    if args.inputs and not args.config:
        parser.error("--inputs requires a fixed --config")
    engine = args.engine.resolve(strict=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    baseline = "beta1-max1.25"
    knobs = [(f"beta{beta:g}-max{ratio:.2f}", {"pool_beta": beta, "max_ratio": ratio}, 1)
             for beta, ratio in product((0.3, 0.6, 1.0), (1.25, 1.40))]
    knobs += [(f"vmax{scale:g}", {}, scale) for scale in (0.5, 2)]
    config = args.config.resolve(strict=True) if args.config else None
    if config is not None or args.background != "matched":
        baseline = "fixed" if config is not None else baseline
        knobs = [(baseline, {}, 1)]
    specs = [(label, scenario, {"v4_diagnostics": 1} | settings, scale)
             for label, settings, scale in knobs for scenario in ("matched", "double-N3")]
    inputs = args.inputs.resolve(strict=True) if args.inputs else None
    worker = partial(trial, engine, out, background=args.background, config=config, inputs=inputs)
    with ProcessPoolExecutor(max_workers=min(6, len(specs))) as pool:
        runs = {(label, scenario): result for label, scenario, result in pool.map(worker, specs)}
    receipt = {}
    for label, _, _ in knobs:
        matched = runs[label, "matched"]
        double = runs[label, "double-N3"]
        gradients = {}
        for water, treatments in GROUPS.items():
            series = [matched["treatments"][r] for r in treatments]
            assert all(matched["treatments"][r] == double["treatments"][r] for r in treatments[:3])
            series.append(double["treatments"][treatments[-1]])
            gradients[water] = gradient(series)
        receipt[label] = {"matched": matched, "double_N3": double, "gradients": gradients}
    assert baseline in receipt
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")
    print(out / "receipt.json")


if __name__ == "__main__":
    main()
