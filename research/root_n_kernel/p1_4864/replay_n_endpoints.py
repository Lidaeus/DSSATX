"""Audit previous-day N state and reproductive budgets on the 26SP B4 route."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import math
from pathlib import Path

from replay_shoot import DAYS, daily_csv, run_case

FIELDS = {
    "rnk_psi_feedback": {"psi", "valid", "source_day", "membrane_factor"},
    "rnk_psi_end": {"psi", "valid"},
    "lux_shoot_state": {"pod_lux_factor"},
    "n_mobilization_input": {"NSTRES", "NMOBR", "N_acceleration", "after_NR5"},
    "repro_n_memory": {"NSTRES", "CNSTRES", "flower_N_scale", "shell_N_fraction"},
    "new_flower_gate": {"water_limit", "potential_count", "accepted_count"},
    "new_pod_gate": {"accepted_count"},
    "pods_set_budget": {"selected", "RNITPD"},
    "cg_repro": {"NGRSH"},
    "c4_grow_flux": {"Wnew_shell"},
}


def read_trace(path):
    trace = defaultdict(lambda: defaultdict(dict))
    with path.open(newline="", encoding="ascii") as stream:
        rows = csv.reader(stream)
        assert next(rows) == "seq,run,yrdoy,das,dynamic,event,layer,key,value,text".split(",")
        for _, r, d, _, _, event, _, key, value, _ in rows:
            if key in FIELDS.get(event, ()):
                day = (int(r), int(d))
                if day in DAYS:
                    assert key not in trace[day][event], (day, event, key)
                    trace[day][event][key] = float(value)
    assert trace.keys() == DAYS
    return trace


def audit_endpoint_routes(case, mode):
    trace = read_trace(case / "P0Trace.csv")
    states = daily_csv(case / "PlantNV3.csv")
    memory = defaultdict(lambda: 1.0)
    counts = defaultdict(int)
    max_shell_error = 0.0
    for (run, day), state in sorted(states.items()):
        identity = run, day
        events = trace[identity]
        root = events["rnk_psi_feedback"]
        donor = events["n_mobilization_input"]
        assert donor["N_acceleration"] == 1, identity
        if donor["after_NR5"]:
            counts["late_donor_days"] += 1
            counts["late_donor_stressed_days"] += donor["NSTRES"] < 1
        assert -1 <= root["psi"] <= 1, identity
        if root["psi"] <= 0:
            assert root["membrane_factor"] == 1, identity
        if state["valid"]:
            source = int(state["source_yrdoy"])
            end = trace[run, source]["rnk_psi_end"]
            assert source == root["source_day"] < day, identity
            assert root["valid"] == end["valid"] and root["psi"] == end["psi"], identity
            assert abs(donor["NSTRES"] - state["growth_day"]) < 1e-7, identity
            if root["psi"] > 0 and state["growth_day"] < 1:
                counts["shoot_surplus_with_smoothed_leaf_deficit_days"] += 1
            if root["psi"] > 0 and state["z_leaf_day"] < 1:
                counts["shoot_surplus_with_raw_leaf_deficit_days"] += 1
        if "repro_n_memory" not in events:
            continue
        reproduced = events["repro_n_memory"]
        assert abs(reproduced["NSTRES"] - donor["NSTRES"]) < 1e-7, identity
        expected = 0.875 * memory[run] + 0.125 * reproduced["NSTRES"]
        assert abs(expected - reproduced["CNSTRES"]) < 1e-7, identity
        memory[run] = reproduced["CNSTRES"]
        assert abs(reproduced["flower_N_scale"] - math.sqrt(memory[run])) < 1e-7, identity
        counts["reproductive_days"] += 1
        if root["psi"] > 0 and memory[run] < 1:
            counts["shoot_surplus_with_reproductive_memory_days"] += 1

        flower = events["new_flower_gate"]
        if flower["potential_count"] > 0 and reproduced["flower_N_scale"] < flower["water_limit"]:
            counts["flower_N_potential_limited_days"] += 1
        assert 0 <= flower["accepted_count"] <= flower["potential_count"] + 1e-7, identity
        shell = events["c4_grow_flux"]["Wnew_shell"]
        error = abs(events["cg_repro"]["NGRSH"] - shell * reproduced["shell_N_fraction"])
        assert error < 1e-6, (identity, error)
        max_shell_error = max(max_shell_error, error)
        if "new_pod_gate" in events:
            candidate = events["pods_set_budget"]
            accepted = events["new_pod_gate"]["accepted_count"]
            expected_pod = state["pod_n_factor"] * events.get("lux_shoot_state", {}).get("pod_lux_factor", 1)
            assert abs(candidate["RNITPD"] - expected_pod) < 1e-7, (identity, mode)
            assert 0 <= accepted <= candidate["selected"] + 1e-7, identity
            counts["pod_days"] += 1
            counts["new_pod_positive_days"] += accepted > 0
    assert counts["reproductive_days"] and counts["pod_days"], case
    return dict(counts) | {"max_shell_n_difference_gN_m2": max_shell_error}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    engine = args.engine.resolve(strict=True)

    def trial(mode):
        settings = {"photo_sln_ref": 1.05, "v4_diagnostics": 1, "lux_veg_mode": mode}
        if mode == 1:
            settings.update(lux_xfrt_drop=0.25)
        case, receipt = run_case(engine, out / f"mode{mode}", "B4", "matched", **settings)
        return str(mode), receipt | {"endpoints": audit_endpoint_routes(case, mode)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(pool.map(trial, (0, 1)))
    (out / "endpoint_audit.json").write_text(json.dumps(results, indent=2) + "\n", encoding="ascii")
    print("26SP endpoint and conservation audits passed")


if __name__ == "__main__":
    main()
