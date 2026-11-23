"""Test luxury onset and isolate the W3 nitrogen supply bottleneck in 26SP."""

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import json
from pathlib import Path
from statistics import median

from replay_luxury import identical_csv, run_case
from replay_shoot import DAYS, GROUPS, csv_rows, daily_csv

W3 = GROUPS["W3"][-2:]
SUPPLY = {
    "B4": {},
    "beta0": {"pool_beta": 0},
    "maxratio150": {"max_ratio": 1.50},
    "double-qno3": {"q_no3_max": 0.006},
    "double-vno3": {"assim_no3_v": 0.006},
}
ONSETS = (0, 0.15, 0.20, 0.25)
TRACE_FIELDS = {
    "rnk_psi_feedback": {"psi", "membrane_factor"},
    "rnk_pool_capacity": {"QNO3_max"},
    "rnk_psi_end": {"N_func", "N_max"},
}


def summarize_supply(case, treatment):
    plant = daily_csv(case / "PlantNIntegration.csv")
    trace = defaultdict(dict)
    layers = defaultdict(lambda: defaultdict(float))
    for row in csv_rows(case / "P0Trace.csv"):
        if int(row["run"]) == treatment and row["key"] in TRACE_FIELDS.get(row["event"], ()):
            trace[int(row["yrdoy"])][row["key"]] = float(row["value"])
    for row in csv_rows(case / "LayerRootNUptake.csv"):
        if int(row["run"]) != treatment:
            continue
        for field in ("candidate_gN_m2", "accepted_gN_m2", "settled_gN_m2"):
            layers[row["species"]][field] += float(row[field])
    days = sorted(day for r, day in DAYS if r == treatment)
    pool_fill = [plant[treatment, d]["QNO3"] / trace[d]["QNO3_max"]
                 for d in days if trace[d]["QNO3_max"] > 0]
    return {
        "root_flux_gN_m2": {species: dict(totals) for species, totals in layers.items()},
        "assim_no3_gN_m2": sum(plant[treatment, d]["A_NO3"] for d in days),
        "median_end_qno3_fill": median(pool_fill),
        "end_qno3_fill_ge_95_days": sum(fill >= 0.95 for fill in pool_fill),
        "days_psi_at_ceiling": sum(trace[d]["psi"] == 1 for d in days),
        "min_membrane_factor": min(trace[d]["membrane_factor"] for d in days),
        "end_shoot_n_above_reference_days": sum(trace[d]["N_func"] > trace[d]["N_max"] for d in days),
    }


def trial(engine, out, spec):
    label, scenario, mode, options = spec
    case, receipt = run_case(engine, out, scenario, mode, overrides=options, label=label)
    receipt["overrides"] = options
    if label in SUPPLY:
        receipt["W3_supply"] = {str(run): summarize_supply(case, run) for run in W3}
    return (label, scenario), (case, receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--reference-engine", type=Path, required=True, help="Frozen c076cac4 build")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    reference = args.reference_engine.resolve(strict=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)

    scenarios = ("matched", "double-N3")
    specs = [(name, scenario, 0, config) for name, config in SUPPLY.items() for scenario in scenarios]
    specs += [(f"onset-{onset:.2f}", scenario, 1, {"lux_psi_threshold": onset})
              for onset in ONSETS for scenario in scenarios]
    specs += [("deficit-control", "deficient", 0, {}),
              ("deficit-onset", "deficient", 1, {"lux_psi_threshold": 0.20})]
    with ProcessPoolExecutor(max_workers=6) as pool:
        results = dict(pool.map(partial(trial, engine, out), specs))

    old_0, _ = run_case(reference, out, "matched", 0, legacy=True)
    old_1, _ = run_case(reference, out, "double-N3", 1, legacy=True)
    assert all(run["max_nni"] <= 1 for run in results["deficit-control", "deficient"][1]["runs"].values())
    comparisons = {
        "mode_off_vs_frozen": (old_0, results["B4", "matched"][0]),
        "zero_onset_vs_frozen": (old_1, results["onset-0.00", "double-N3"][0]),
        "deficit_off_vs_positive_onset": (results["deficit-control", "deficient"][0],
                                         results["deficit-onset", "deficient"][0]),
    }
    receipt = {"byte_identical_csv": {label: identical_csv(*cases) for label, cases in comparisons.items()},
               "cases": {f"{label}/{scenario}": result for (label, scenario), (_, result) in results.items()}}
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")
    print("Luxury onset and nitrogen supply audit complete", flush=True)


if __name__ == "__main__":
    main()
