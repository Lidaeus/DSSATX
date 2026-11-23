"""Run the 26SP luxury-N allocation ablation with fixed B4 inputs."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import json
from pathlib import Path
import re
import os

from replay_shoot import (
    DAYS, GROUPS, TEMPLATE, audit, audit_shoot, daily_csv, digest, native_crop,
    prepare_case, prepare_experiment, run, stage_config, trace_shoot,
)

MODES = ({}, {"lux_veg_mode": 1, "lux_xfrt_drop": 0.25})
SCENARIOS = ("matched", "double-N3", "low-mineral-N", "deficient")
POSITIVES = ("uptake_kg_ha", "peak_lai", "end_lai", "leaf_dm", "stem_dm", "maintenance")
NEGATIVES = ("harvest_index", "fresh_yield")
EVENTS = {"rnk_psi_feedback", "rnk_psi_end", "lux_shoot_state", "lux_demand", "lux_pods", "pods_set_budget"}


def set_n_supply(path, scenario):
    """Change the N input only, using the fixed-width FileX columns."""
    if scenario == "matched":
        return
    low_n = scenario in ("low-mineral-N", "deficient")
    section = ""
    rows = []
    edits = 0
    for line in path.read_text(encoding="ascii").splitlines(keepends=True):
        if line.startswith("*"):
            section = line.strip()
        fields = list(re.finditer(r"\S+", line))
        if fields and fields[0].group().isdigit():
            if section == "*FERTILIZERS (INORGANIC)":
                amount = float(fields[5].group())
                if amount > 0 and (low_n or fields[0].group() == "1"):
                    end = fields[5].end()
                    amount = 2 * amount if scenario == "double-N3" else 0
                    line = line[:end - 6] + f"{amount:6.1f}" + line[end:]
                    edits += 1
            if low_n and section == "*INITIAL CONDITIONS" and len(fields) == 5:
                end = fields[4].end()
                line = line[:end-12] + "  0.50  0.25" + line[end:]
                edits += 1
        rows.append(line)
    assert edits, scenario
    path.write_text("".join(rows), encoding="ascii")


def diagnostics(path):
    events = defaultdict(lambda: defaultdict(dict))
    shade = defaultdict(lambda: [0.0, 0.0])
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.reader(stream)
        assert next(reader) == "seq,run,yrdoy,das,dynamic,event,layer,key,value,text".split(",")
        for _, r, d, _, _, event, _, key, value, _ in reader:
            if event in EVENTS:
                events[int(r), int(d)][event][key] = float(value)
            elif event == "c4_canopy_n" and key in ("LAISL", "LAISH"):
                shade[int(r), int(d)][key == "LAISH"] += float(value)
    return events, shade


def check_state(trace, options):
    counts = defaultdict(int)
    responses = defaultdict(int)
    mode = options.get("lux_veg_mode", 0)
    threshold = options.get("lux_psi_threshold", 0)
    for day in sorted(DAYS):
        record = trace[day]
        root = record["rnk_psi_feedback"]
        psi = root["psi"]
        active = mode > 0 and root["valid"] and psi > 0
        assert ("lux_shoot_state" in record) == bool(active), day
        if not active:
            assert "lux_demand" not in record and "lux_pods" not in record, day
            continue
        source = int(root["source_day"])
        assert source < day[1], day
        assert trace[day[0], source]["rnk_psi_end"]["psi"] == psi, day
        counts[day[0]] += 1
        state = record["lux_shoot_state"]
        assert state["psi"] == psi, day
        surplus = max(0, (min(1, psi) - threshold) / (1 - threshold))
        xf = 1 - options["lux_xfrt_drop"] * surplus ** 2
        responses[day[0]] += state["xfrt_factor"] < 1.0
        if xf == 1:
            assert "lux_demand" not in record and "lux_pods" not in record, day
        assert abs(state["xfrt_factor"] - xf) < 1e-7 and state["pod_lux_factor"] == 1, day
        for event in ("lux_demand", "lux_pods"):
            if event in record:
                budget = record[event]
                assert abs(budget["XFRT_eff"] - budget["XFRT_base"] * xf) < 1e-7, (day, event)
        if "lux_pods" in record:
            assert record["lux_demand"]["XFRT_eff"] == record["lux_pods"]["XFRT_eff"], day
        if "pods_set_budget" in record:
            set_budget = record["pods_set_budget"]
            assert abs(set_budget["RNITPD"] - state["pod_def_factor"]) < 1e-7, day
    return {str(r): {"active_days": counts[r], "xfrt_response_days": responses[r]}
            for r in range(1, 13)}


def seasonal(case, plant, cash, state, shade):
    crop = native_crop(case / "PlantGro.OUT")
    fruit = native_crop(case / "FreshWt.OUT")
    results = {}
    for r in range(1, 13):
        days = sorted(day for day in DAYS if day[0] == r)
        end = crop[days[-1]]
        harvest = fruit[max(key for key in fruit if key[0] == r)]
        dry = harvest["CHPDT"]
        shade_totals = [sum(shade[day][i] for day in days) for i in (0, 1)]
        psi = [state[day]["rnk_psi_feedback"]["psi"] for day in days]
        results[str(r)] = {
            "uptake_kg_ha": 10 * sum(plant[day]["U_NO3"] + plant[day]["U_NH4"] for day in days),
            "peak_lai": max(crop[day]["LAID"] for day in days), "end_lai": end["LAID"],
            "leaf_dm": end["LWAD"], "stem_dm": end["SWAD"],
            "maintenance": sum(cash[day]["maintenance"] for day in days),
            "vegetative_C": sum(cash[day]["veg_growth"] for day in days),
            "fruit_C": sum(cash[day]["fruit_growth"] for day in days),
            "gross_photo": sum(cash[day]["PG"] for day in days),
            "shade_share": shade_totals[1] / sum(shade_totals),
            "harvest_index": dry / (end["CWAD"] + dry),
            "fresh_yield": harvest["CHFPW"],
            "positive_psi_days": sum(x > 0 for x in psi),
            "positive_psi_squared_sum": sum(max(0, x) ** 2 for x in psi),
            "max_nni": max(state[day]["rnk_psi_end"]["N_func"] / state[day]["rnk_psi_end"]["N_crit"] for day in days),
        }
    return results


def gradients(rows):
    result = {}
    for water, (_, _, intermediate, high) in GROUPS.items():
        higher, lower = rows[str(high)], rows[str(intermediate)]
        delta = {name: higher[name] - lower[name] for name in higher}
        passed = all(delta[name] > 0 for name in POSITIVES) and all(delta[name] < 0 for name in NEGATIVES)
        result[water] = {"high_minus_N2": delta, "passes": passed}
    return result


def run_case(engine, out, scenario, mode, legacy=False, *, overrides=None, label=None, vmax_scale=1, background="matched"):
    name = f"{scenario}-mode{mode}" + ("-reference" if legacy else "")
    if label:
        name += f"-{label}"
    case = prepare_case(argparse.Namespace(config=TEMPLATE, out=out / name))
    config = case / "NIntegration.nml"
    options = {"photo_sln_ref": 1.05} | MODES[mode] | (overrides or {})
    if mode == 0 and not legacy:
        options["lux_veg_mode"] = 0
    settings = stage_config("B4", options)
    if vmax_scale != 1:
        for field in ("rnk_vmax_high", "rnk_vmax_low"):
            pattern = rf"(\b{field}\s*=\s*)([.\deE+-]+)\s*,\s*([.\deE+-]+)"
            def scaled(match):
                values = [float(match.group(i)) * vmax_scale for i in (2, 3)]
                return match.group(1) + ", ".join(f"{value:.12g}" for value in values)
            settings, count = re.subn(pattern, scaled, settings)
            if count != 1:
                raise ValueError(f"Expected one two-species assignment for {field}")
    if scenario == "deficient":
        # Exercise the neutral branch for a whole season even with soil mineralization.
        regular = "rnk_vmax_high=0.0003,0.0004, rnk_vmax_low=0.0015,0.002,"
        limited = "rnk_vmax_high=0.000003,0.000004, rnk_vmax_low=0.000015,0.000020,"
        assert settings.count(regular) == 1
        settings = settings.replace(regular, limited)
    config.write_text(settings, encoding="ascii")
    file_x = case / "XXQL2601.TMX"
    prepare_experiment(file_x, background)
    set_n_supply(file_x, scenario)
    env = dict(os.environ, DSSAT_HOME=f".{os.sep}", DSSAT_P0_TRACE="1")
    env.pop("DSSAT_N_CONFIG", None)
    print(f"Running {name}", flush=True)
    run([str(engine), "CRGRO048", "B", "DSSBatch.v48"], case, "dssat", env)
    return case, analyze_case(engine, case, options)


def analyze_case(engine, case, options):
    plant = daily_csv(case / "PlantNIntegration.csv")
    cash = daily_csv(case / "PlantCCash.csv")
    trace, photo = trace_shoot(case)
    state, shade = diagnostics(case / "P0Trace.csv")
    metrics = seasonal(case, plant, cash, state, shade)
    receipt = {"engine_sha256": digest(engine), "config_sha256": digest(case / "NIntegration.nml"),
               "file_x_sha256": digest(case / "XXQL2601.TMX")}
    receipt.update(audit(case, 12))
    receipt.update(audit_shoot(case, "B4", trace, photo, plant, cash, verify_partition=True))
    return receipt | {"runs": metrics, "signals": check_state(state, options), "gradient": gradients(metrics)}


def identical_csv(control, other):
    reference = sorted(p.name for p in control.glob("*.csv"))
    assert reference and reference == sorted(p.name for p in other.glob("*.csv"))
    for name in reference:
        assert digest(control / name) == digest(other / name), (other, name)
    # The native output headers contain wall-clock timestamps.
    for name in ("PlantGro.OUT", "FreshWt.OUT", "PlantN.OUT", "PlantC.OUT"):
        assert native_crop(control / name) == native_crop(other / name), (other, name)
    return reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--reference-engine", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    old = args.reference_engine.resolve(strict=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cases, receipts = {}, {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for mode in range(len(MODES)):
            def trial(scenario):
                return run_case(engine, out, scenario, mode)
            for scenario, (case, receipt) in zip(SCENARIOS, pool.map(trial, SCENARIOS)):
                cases[scenario, mode] = case
                receipts[scenario, mode] = receipt
    ref, _ = run_case(old, out, "matched", 0, legacy=True)
    write_receipt(out, cases, receipts, ref)


def write_receipt(out, cases, receipts, ref):
    baseline = identical_csv(ref, cases["matched", 0])
    low = [e for e in receipts["deficient", 0]["runs"].values()]
    assert all(row["positive_psi_days"] == 0 and row["max_nni"] <= 1 for row in low), "Low-N control crossed NNI=1"
    equality = {mode: identical_csv(cases["deficient", 0], cases["deficient", mode]) for mode in (1,)}
    result = {
        "cases": {f"{scenario}-mode{mode}": receipt for (scenario, mode), receipt in receipts.items()},
        "baseline_identical_csv": baseline, "all_season_low_N_identical_csv": equality,
    }
    (out / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print("Luxury-N engineering audit complete", flush=True)


if __name__ == "__main__":
    main()
