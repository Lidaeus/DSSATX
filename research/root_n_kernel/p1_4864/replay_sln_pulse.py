"""Scan functional SLN and run a root N cutoff with build_sln_probe.py's engine."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
import json
from pathlib import Path
from statistics import mean, quantiles
from time import perf_counter
import os

from replay_shoot import (
    DAYS, FROZEN_SLN_REF, audit, audit_shoot, daily_csv, digest, native_crop,
    prepare_case, prepare_experiment, run, stage_config, trace_shoot,
)

REFERENCE_BAND = (0.95, 1.25)
REFERENCES = (FROZEN_SLN_REF, 0.90, 0.95, 1.05, 1.15, 1.20, 1.25, 1.35)
HISTORICAL_REFERENCES = (FROZEN_SLN_REF, 0.90, 1.10, 1.30, 1.50)
EARLY, CUT, REFILL, FOLLOWUP = 2026120, 2026123, 2026143, 2026148
W3 = (9, 7, 4, 1)
W2 = (11, 8, 5, 2)
PODS_KEYS = ("PG", "MAINR", "RSPNO3", "RSPNH4", "PGAVL", "NAVL", "NIV3CORE",
             "NDMTOT", "NDMNEW", "NDMREP", "NASSIMD", "pod_score", "XFRT")


def probe_trace(path):
    pods, sen, setting = {}, defaultdict(float), defaultdict(dict)
    photo = defaultdict(lambda: defaultdict(list))
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.reader(stream)
        assert next(reader) == "seq,run,yrdoy,das,dynamic,event,layer,key,value,text".split(",")
        for _, r, d, _, _, event, _, key, value, _ in reader:
            if event == "sln_before_pods":
                pods.setdefault((int(r), int(d)), {})[key] = float(value)
            elif event == "sln_photo":
                photo[int(r), int(d)][key].append(float(value))
            elif event == "sln_n_senescence":
                sen[int(r), int(d)] += float(value)
            elif event == "pods_set_budget":
                setting[int(r), int(d)][key] = float(value)
    assert pods.keys() == DAYS and all(set(row) == set(PODS_KEYS) for row in pods.values())
    assert photo and all(len(row["factor"]) == len(row["functional_SLN"]) for row in photo.values())
    for day, row in pods.items():
        row.update({f"pod_{key}": setting[day].get(key, 0.0)
                    for key in ("PODADD", "C_limit", "flower_limit", "N_limit", "selected", "RNITPD")})
        row["pod_set_called"] = int(bool(setting[day]))
    return pods, photo, sen


def test_case(engine, base, stage, reference, cutoff=False):
    label = f"{stage}-{reference:.2f}" + ("-cutoff" if cutoff else "")
    # Use the template from the revision compiled into the probe engine.
    template = engine.parents[2] / "source/research/root_n_kernel/source/TMDeficiency.nml.template"
    case = prepare_case(argparse.Namespace(config=template, out=base / label))
    config = case / "NIntegration.nml"
    config.write_text(stage_config(stage, {"photo_sln_ref": reference}, template=template), encoding="ascii")
    file_x = case / "XXQL2601.TMX"
    prepare_experiment(file_x, "matched")
    env = dict(os.environ, DSSAT_HOME=f".{os.sep}", DSSAT_P0_TRACE="1",
               DSSAT_SLN_PROBE_CUT=str(int(cutoff)))
    env.pop("DSSAT_N_CONFIG", None)
    start = perf_counter()
    run([str(engine), "CRGRO048", "B", "DSSBatch.v48"], case, "dssat", env)
    receipt = {"seconds": perf_counter() - start, "config_sha256": digest(config),
               "file_x_sha256": digest(file_x)}
    plant = daily_csv(case / "PlantNIntegration.csv")
    cash = daily_csv(case / "PlantCCash.csv")
    trace, old_photo = trace_shoot(case)
    receipt.update(audit(case, 12))
    receipt.update(audit_shoot(case, stage, trace, old_photo, plant, cash))
    pods, photo, extra = probe_trace(case / "P0Trace.csv")
    for day, row in pods.items():
        assert abs(row["PG"] - cash[day]["PG"]) < 1e-6, day
        assert abs(row["MAINR"] - cash[day]["maintenance"]) < 1e-6, day
    receipt["window_181_198"] = {}
    for r in W3:
        late = [row for (n, d), row in photo.items() if n == r and 2026181 <= d <= 2026198]
        receipt["window_181_198"][r] = {
            "photo": response([f for row in late for f in row["factor"]]),
            "functional_sln_gN_m2_leaf": sln_percentiles(late),
            **{key: sum(pods[r, day][key] for day in range(2026181, 2026199))
               for key in ("PG", "MAINR", "RSPNO3", "RSPNH4", "PGAVL")},
            "fruit_C": sum(cash[r, day]["fruit_growth"] for day in range(2026181, 2026199)),
        }
    receipt["all_photo"] = response([f for row in photo.values() for f in row["factor"]])
    receipt["all_functional_sln_gN_m2_leaf"] = sln_percentiles(photo.values())
    harvest = native_crop(case / "FreshWt.OUT")
    for water, group in (("W2", W2), ("W3", W3)):
        yields = [harvest[max(day for day in harvest if day[0] == r)]["CHFPW"] for r in group]
        receipt[water] = {"yield_N0_to_N3": yields, "N0_minus_N1": yields[0] - yields[1]}
    lai = daily_csv(case / "PlantNLAI.csv") if stage == "B4" else {}
    return case, receipt, plant, cash, pods, photo, lai, extra


def response(values):
    assert values
    return {"calls": len(values), "fraction_below_one": sum(f < 1 for f in values) / len(values),
            "mean": mean(values), "min": min(values)}


def sln_percentiles(rows):
    values = [sln for row in rows for sln in row["functional_SLN"]]
    cuts = quantiles(values, n=20, method="inclusive")
    return {"p05": cuts[0], "median": cuts[9], "p95": cuts[18]}


def write_records(path, rows):
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def carbon_rows(stage, reference, result):
    _, _, plant, cash, pods, photo, _, _ = result
    records = []
    for d in range(2026181, 2026199):
        row = {"stage": stage, "SLN_ref": reference, "yrdoy": d}
        for r, label in ((9, "N0"), (7, "N1")):
            key = r, d
            s = pods[key]
            values = s | {
                "RSP_sum": s["RSPNO3"] + s["RSPNH4"],
                "other_pre_PODS_C": s["PGAVL"] - (s["PG"] - s["MAINR"] - s["RSPNO3"] - s["RSPNH4"]),
                "RSP_settled": cash[key]["N_assim"],
                "assim_refund": plant[key]["C_refund"],
                "PODS_C": cash[key]["fruit_growth"],
                "veg_C": cash[key]["veg_growth"],
                "mean_leaf_photo_factor": mean(photo[key]["factor"]),
                "photo_fraction_below_one": response(photo[key]["factor"])["fraction_below_one"],
            }
            row.update({f"{name}_{label}": value for name, value in values.items()})
        row.update({f"{name}_N0_minus_N1": row[f"{name}_N0"] - row[f"{name}_N1"] for name in values})
        records.append(row)
    return records


def pulse_rows(comparison, cutoff):
    _, _, cp, cc, _, cs, cl, ce = comparison
    _, _, pp, pc, _, ps, pl, pe = cutoff
    assert all(cp[key] == pp[key] for key in DAYS if key[1] < CUT)
    assert all(pp[key]["U_NO3"] == pp[key]["U_NH4"] == 0 for key in DAYS if CUT <= key[1] < REFILL)
    crop = native_crop(cutoff[0] / "PlantGro.OUT")
    assert all(crop[r, CUT]["DAP"] == 50 for r, d in DAYS if d == CUT)
    assert any(pp[key]["U_NO3"] + pp[key]["U_NH4"] > 0 for key in DAYS if key[1] == REFILL)
    rows = []
    for r in (*W3, *W2):
        for d in range(EARLY, FOLLOWUP):
            key = r, d
            row = {"run": r, "DAP": int(crop[key]["DAP"]), "yrdoy": d}
            for label, p, c, s, l, e in (("control", cp, cc, cs, cl, ce), ("cutoff", pp, pc, ps, pl, pe)):
                metrics = {
                    "QNO3": p[key]["QNO3"], "QNH4": p[key]["QNH4"],
                    "U_NO3": p[key]["U_NO3"], "U_NH4": p[key]["U_NH4"],
                    "uptake": p[key]["U_NO3"] + p[key]["U_NH4"],
                    "A_total": p[key]["A_NO3"] + p[key]["A_NH4"],
                    "leaf_organic_N": p[key]["Norg_leaf"],
                    "leaf_functional_N": max(0.0, p[key]["Norg_leaf"] - p[key]["leaf_min"] * p[key]["W_leaf"]),
                    "SLN": p[key]["functional_leaf_N_per_area"],
                    "photo_SLN": mean(s[key]["functional_SLN"]),
                    "photo_factor": mean(s[key]["factor"]),
                    "PG": c[key]["PG"],
                    "lai_signal": l[key]["state_response"],
                    "new_area": l[key]["new_leaf_area"],
                    "sen_extra": e.get(key, 0.0),
                    "old_leaf_area_lost": l[key]["old_leaf_area_lost"],
                }
                row.update({f"{name}_{label}": value for name, value in metrics.items()})
            row.update({f"{name}_cutoff_minus_control": row[f"{name}_cutoff"] - row[f"{name}_control"] for name in metrics})
            rows.append(row)
    return rows


def pulse_onsets(rows):
    thresholds = {"QNO3": 1e-8, "leaf_functional_N": 1e-8, "SLN": 1e-8, "photo_SLN": 1e-8,
                  "photo_factor": 1e-8, "PG": 1e-8, "lai_signal": 1e-8, "new_area": 1e-8, "sen_extra": 1e-5}
    result = {}
    for r in (*W3, *W2):
        window = [row for row in rows if row["run"] == r and CUT <= row["yrdoy"] < REFILL]
        result[r] = {}
        for name, absolute in thresholds.items():
            direction = 1 if name == "sen_extra" else -1
            result[r][name] = next((
                row["DAP"] for row in window if direction * row[f"{name}_cutoff_minus_control"]
                > max(absolute, 0.05 * abs(row[f"{name}_control"]))
            ), None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--historical", action="store_true", help="Reproduce the original reference scan")
    parser.add_argument("--scan-only", action="store_true", help="Save the scan without running a new pulse")
    parser.add_argument("--pulse-ref", type=float, help="Use one positive reference from the selected scan")
    args = parser.parse_args()
    references = HISTORICAL_REFERENCES if args.historical else REFERENCES
    if args.pulse_ref is not None and args.pulse_ref not in references[1:]:
        parser.error("--pulse-ref must be a non-control value in the selected scan")
    engine = args.engine.resolve(strict=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    all_cases = [(stage, reference) for stage in ("B3", "B4") for reference in references]

    def execute(job):
        stage, reference = job
        print(f"Running {stage} at {reference:.2f}", flush=True)
        return test_case(engine, out, stage, reference)

    scan, failed = {}, {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {job: pool.submit(execute, job) for job in all_cases}
        for (stage, reference), future in futures.items():
            try:
                scan[stage, reference] = future.result()
            except RuntimeError as exc:
                if not args.scan_only:
                    raise
                failed[f"{stage}-{reference:.2f}"] = str(exc)
    if not scan:
        raise RuntimeError(f"No reference completed: {failed}")
    carbon = [row for job, result in scan.items() for row in carbon_rows(*job, result)]
    write_records(out / "late_carbon_paired.csv", carbon)
    passing_b4 = [ref for ref in references[1:]
                  if ("B4", ref) in scan and scan["B4", ref][1]["W3"]["N0_minus_N1"] <= 0]
    passing = [ref for ref in passing_b4
               if ("B3", ref) in scan and scan["B3", ref][1]["W3"]["N0_minus_N1"] <= 0]
    results = {
        "engine_sha256": digest(engine), "W3_passing_both": passing, "W3_passing_B4": passing_b4,
        "working_reference_band": REFERENCE_BAND, "failed_cases": failed,
        "scan": {f"{stage}-{ref:.2f}": v[1] for (stage, ref), v in scan.items()},
    }
    if not args.scan_only:
        refs = [args.pulse_ref]
        if args.pulse_ref is None:
            refs = sorted({1.10, *(passing or passing_b4)[:1]}) if args.historical else [1.05]
        pulse, pulse_receipts = [], {}
        for reference in refs:
            cutoff = test_case(engine, out, "B4", reference, cutoff=True)
            profile = pulse_rows(scan["B4", reference], cutoff)
            pulse.extend({"SLN_ref": reference, **row} for row in profile)
            pulse_receipts[str(reference)] = cutoff[1] | {"first_5pct_change_DAP": pulse_onsets(profile)}
        write_records(out / "pulse_paired.csv", pulse)
        results.update(pulse_runs=pulse_receipts, pulse_window_DAP=[50, 69])
    (out / "receipt.json").write_text(json.dumps(results, indent=2) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
