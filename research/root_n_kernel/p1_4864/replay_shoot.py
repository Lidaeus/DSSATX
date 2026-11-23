"""Replay and audit the steady-root TM deficiency ablations on the 26SP fixture."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

from verify_p1 import audit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from portable_dssat import FIXTURE, prepare_case, run

TEMPLATE = HERE.parent / "source/TMDeficiency.nml.template"
STAGES = {
    "B1": dict(lai_cn_mode=0, lai_cn_shape=-1, leaf_coupling=0, n_sen_rate=0,
               c4_photo=0, photo_reference_mode=0, photo_sln_ref=-1, photo_legacy=1,
               remob_mode=0, remob_rate_mode=0, remob_rate_max=-1, functional_rate_max=-1),
    "B2": dict(lai_cn_mode=0, lai_cn_shape=-1, leaf_coupling=0, n_sen_rate=0,
               c4_photo=0, photo_reference_mode=0, photo_sln_ref=-1, photo_legacy=1),
    "B3": dict(lai_cn_mode=0, lai_cn_shape=-1, leaf_coupling=0, n_sen_rate=0),
    "B4a": dict(lai_cn_mode=0, lai_cn_shape=-1),
    "B4": {},
}
ALL_LEDGERS = dict(luxury_priority=1, reserve_mode=1, v4_diagnostics=1,
                   reserve_capacity=0.004, reserve_fill_tau=3, reserve_protect=0.02)
GROUPS = {"W1": [12, 10, 6, 3], "W2": [11, 8, 5, 2], "W3": [9, 7, 4, 1]}
DAYS = {(r, d) for r in range(1, 13) for d in range(2026073, 2026199)}
FROZEN_SLN_REF = 0.18
STOP_DOY = 152
DONORS = ("leaf", "stem", "root", "shell")


def stage_config(stage, options, template=TEMPLATE):
    config = template.read_text(encoding="ascii")
    settings = {"photo_sln_ref": FROZEN_SLN_REF} | STAGES[stage] | options
    for name, value in settings.items():
        pattern = rf"\b{name}\s*=\s*[-.\d]+"
        config, count = re.subn(pattern, f"{name}={value}", config)
        if count == 0:
            config = config.replace("&NINTEGRATION", f"&NINTEGRATION\n {name}={value},", 1)
        elif count != 1:
            raise ValueError(f"Expected at most one setting for {name}")
    return config

def prepare_experiment(file_x, scenario):
    """Change only SA/IC levels, or omit N-only additions after the cutoff."""
    section = ""
    output = []
    edits = 0
    references = {t: group[2] for group in GROUPS.values() for t in group}
    for line in file_x.read_text(encoding="ascii").splitlines(keepends=True):
        if line.startswith("*"):
            section = line
        fields = list(re.finditer(r"\S+", line))
        if fields and fields[0].group().isdigit():
            if scenario == "matched" and section.startswith("*TREATMENTS"):
                treatment = int(fields[0].group())
                level = references[treatment]
                start, end = fields[7].end() - 3, fields[8].end()
                line = line[:start] + f"{level:3d}{level:3d}" + line[end:]
                edits += 1
            if scenario == "stop" and section.startswith("*FERTILIZERS (INORGANIC)"):
                _, day, _, _, _, n, *other = (f.group() for f in fields)
                if int(day) % 1000 >= STOP_DOY and float(n) > 0:
                    if any(float(amount) != 0 for amount in other[:4]):
                        raise ValueError("Cannot remove N without altering other fertilizer inputs")
                    edits += 1
                    continue
        output.append(line)
    if not edits:
        raise ValueError(f"No input changes prepared for {scenario}")
    file_x.write_text("".join(output), encoding="ascii")


def csv_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        yield from csv.DictReader(stream)


def daily_csv(path):
    rows = {}
    for row in csv_rows(path):
        key = (int(row.pop("run")), int(row.pop("yrdoy")))
        assert key not in rows, (path, key)
        rows[key] = {name: float(value) for name, value in row.items()}
        assert all(map(math.isfinite, rows[key].values())), (path, key)
    assert rows.keys() == DAYS, path
    return rows


def native_crop(path):
    records = {}
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if line.startswith("*RUN"):
            treatment = None
        elif line.lstrip().startswith("TREATMENT "):
            treatment = int(line.split()[1])
        elif line.startswith("@YEAR"):
            columns = line[1:].split()
        elif re.match(r"^\s+20\d{2} \d{3}\s", line):
            values = list(map(float, line.split()))
            key = (treatment, int(values[0]) * 1000 + int(values[1]))
            assert treatment is not None and key not in records and len(values) == len(columns), (path, key)
            records[key] = dict(zip(columns, values))
    assert {key[0] for key in records} == set(range(1, 13)), path
    return records


def trace_shoot(case):
    keys = {
        "veg_n_partition": {"FRRT", "FRRT_neutral", "leaf_allocated_dm", "leaf_neutral_dm"},
        "cg_mobil": {"NMINEA", "RPRO"},
        "c4_grow_flux": {"SLDOT", "SSDOT", "ALFDOT", *(f"Nmobile_{i}" for i in DONORS)},
        "grow_losses": {"NLOFF"},
        "grow_residue": {"surface_N"},
        "century_residue_input": {"surface_N"},
    }
    trace = defaultdict(dict)
    photos = defaultdict(list)
    with (case / "P0Trace.csv").open(newline="", encoding="ascii") as stream:
        reader = csv.reader(stream)
        assert next(reader) == "seq,run,yrdoy,das,dynamic,event,layer,key,value,text".split(",")
        for _, run_id, day, _, _, event, _, field, value, _ in reader:
            if event == "leaf_capacity" and field == "AGEMXL":
                photos[int(run_id), int(day)].append(float(value))
            elif field in keys.get(event, ()):
                trace[int(run_id), int(day)][event, field] = float(value)
    return trace, photos


def audit_shoot(case, stage, trace, photos, plant, cash, verify_partition=False):
    summary = {}
    if stage != "B1":
        mob = daily_csv(case / "PlantNRemob.csv")
        max_error = 0.0
        for day, row in mob.items():
            assert row["rate_mode"] == 1, day
            for organ in DONORS:
                settled = row[f"plan_{organ}"] - row[f"returned_{organ}"]
                actual = trace[day]["c4_grow_flux", f"Nmobile_{organ}"]
                assert -1e-9 <= settled and abs(actual - settled) < 1e-6, (day, organ, actual, settled)
                assert 0 <= row[f"safe_{organ}"] <= row[f"capR_{organ}"] + 1e-9, (day, organ)
                assert 0 <= row[f"function_{organ}"] <= row[f"capF_{organ}"] + 1e-9, (day, organ)
            returned = sum(row[f"returned_{organ}"] for organ in DONORS)
            actual = sum(trace[day]["c4_grow_flux", f"Nmobile_{organ}"] for organ in DONORS)
            initial = trace[day]["cg_mobil", "NMINEA"]
            assert abs(initial - returned - actual) < 1e-6, (day, initial, returned, actual)
            cost = trace[day]["cg_mobil", "RPRO"] / 0.16
            residual = max(abs(cash[day]["N_resynthesis"] - row["C_remob_actual"]),
                           abs(cash[day]["N_resynthesis"] + returned * cost - initial * cost))
            assert residual < 1e-6, (day, residual)
            max_error = max(max_error, residual)
        summary["max_remob_cash_difference"] = max_error
    if stage in ("B3", "B4a", "B4"):
        factors = [value for day, values in photos.items() if (day[0], day[1] - 1) in DAYS for value in values]
        assert factors and all(0.05 - 1e-7 <= f <= 1 for f in factors), (min(factors), max(factors))
        summary["photo_factor_range"] = [min(factors), max(factors)]
        summary["photo_calls_below_one"] = sum(f < 1 for f in factors)
        summary["photo_calls_sampled"] = len(factors)
    if stage in ("B4a", "B4"):
        lai = daily_csv(case / "PlantNLAI.csv")
        leaf = daily_csv(case / "PlantNLeaf.csv")
        budget = daily_csv(case / "PlantABudget.csv")
        area_error = 0.0
        residue_error = 0.0
        max_root_shift = 0.0
        for day, row in lai.items():
            assert row["area_calls"] == row["accept_calls"] == 1, day
            if stage == "B4":
                assert row["dm_leaf_actual"] <= row["dm_leaf_request"] + 2e-6, day
                assert row["N_leaf_actual"] >= row["dm_leaf_actual"] * row["build_N_leaf"] - 1e-7, day
                assert budget[day]["leaf_expansion_factor"] == 1, day
                if verify_partition:
                    root, neutral_root, allocated, neutral_leaf = (
                        trace[day]["veg_n_partition", key]
                        for key in ("FRRT", "FRRT_neutral", "leaf_allocated_dm", "leaf_neutral_dm")
                    )
                    assert -1e-6 <= root - neutral_root, day
                    requested = max(0, min(allocated, neutral_leaf * row["state_response"]))
                    assert abs(requested - row["dm_leaf_request"]) < 2e-6, (day, requested)
                    max_root_shift = max(max_root_shift, root - neutral_root)
            assert min(trace[day]["c4_grow_flux", f"{organ}DOT"] for organ in ("SL", "SS")) >= 0, day
            delta = row["new_leaf_area"] - row["old_leaf_area_lost"]
            assert abs(row["new_leaf_area"] - row["dm_leaf_actual"] * row["SLA_new"]) < 0.001, day
            assert abs(trace[day]["c4_grow_flux", "ALFDOT"] - delta) < 0.001, day
            if (day[0], day[1] - 1) in lai:
                prev = lai[day[0], day[1] - 1]
                error = abs(row["LAI_end"] - prev["LAI_end"] - delta / 10000)
                assert error < 2e-6, (day, error)
                area_error = max(area_error, error)
            remob = sum(mob[day][f"{source}_leaf"] for source in ("safe", "function"))
            healthy_mass = row["W_leaf_begin"] * (1 - leaf[day]["cell_loss_leaf"])
            healthy_n = row["N_nonreserve_begin"] * (1 - leaf[day]["cell_loss_leaf"])
            assert remob <= max(0, healthy_n - row["N_min_begin"] * healthy_mass) + 1e-7, day
            assert abs(leaf[day]["litter_N_leaf"] - trace[day]["grow_losses", "NLOFF"]) < 1e-6, day
            if (day[0], day[1] + 1) in plant:
                soil = trace[day[0], day[1] + 1]["century_residue_input", "surface_N"]
                error = abs(soil - trace[day]["grow_residue", "surface_N"]) / 10
                assert error < 1e-6, (day, error)
                residue_error = max(residue_error, error)
        summary.update(lai_rows=len(lai), max_area_difference=area_error, max_residue_difference=residue_error)
        if verify_partition:
            assert max_root_shift > 1e-5, "26SP did not exercise nitrogen-driven root partition"
            summary["max_root_partition_shift"] = max_root_shift
    return summary


def run_case(engine, folder, stage, scenario="field", traced=True, **options):
    case = prepare_case(argparse.Namespace(config=TEMPLATE, out=folder))
    config = stage_config(stage, options)
    (case / "NIntegration.nml").write_text(config, encoding="ascii")
    if scenario != "field":
        prepare_experiment(case / "XXQL2601.TMX", scenario)
    env = dict(os.environ, DSSAT_HOME=f".{os.sep}", DSSAT_P0_TRACE=str(int(traced)))
    env.pop("DSSAT_N_CONFIG", None)
    command = [str(engine), "CRGRO048", "B", "DSSBatch.v48"]
    start = perf_counter()
    run(command, case, "dssat", env)
    seconds = perf_counter() - start
    plant = daily_csv(case / "PlantNIntegration.csv")
    cash = daily_csv(case / "PlantCCash.csv")
    receipt = {"seconds": seconds, "config_sha256": hashlib.sha256(config.encode("ascii")).hexdigest(),
               "file_x_sha256": digest(case / "XXQL2601.TMX")}
    if traced:
        trace, photos = trace_shoot(case)
        receipt.update(audit(case, 12))
        receipt.update(audit_shoot(case, stage, trace, photos, plant, cash, verify_partition=stage == "B4"))
    return case, receipt


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compare_rerun(engine, case, traced):
    hashes = {p.name: digest(p) for p in sorted(case.glob("*.csv"))}
    env = dict(os.environ, DSSAT_HOME=f".{os.sep}", DSSAT_P0_TRACE=str(int(traced)))
    env.pop("DSSAT_N_CONFIG", None)
    run([str(engine), "CRGRO048", "B", "DSSBatch.v48"], case, "dssat-repeat", env)
    for name, expected in hashes.items():
        assert digest(case / name) == expected, name
    return list(hashes)

def observations(case, growth, fresh):
    sources = {
        "LAID": (growth, "LAID"), "LWAD": (growth, "LWAD"), "SWAD": (growth, "SWAD"),
        "LEAF_N_PCT": (native_crop(case / "PlantN.OUT"), "LN%D"), "CHFPW": (fresh, "CHFPW"),
    }
    residuals = defaultdict(list)
    for row in csv_rows(FIXTURE / "comparison.csv"):
        name = row["variable"]
        if name not in sources or row["status"] != "approved_all12_direct_target":
            continue
        when = date.fromisoformat(row["date"])
        key = (int(row["trno"]), when.year * 1000 + when.timetuple().tm_yday)
        table, field = sources[name]
        residuals[name].append(table[key][field] - float(row["observed"]))
    return {name: {"n": len(errors), "rmse": math.sqrt(sum(e * e for e in errors) / len(errors))}
            for name, errors in residuals.items()}


def field_metrics(case):
    plant = daily_csv(case / "PlantNIntegration.csv")
    cash = daily_csv(case / "PlantCCash.csv")
    growth = native_crop(case / "PlantGro.OUT")
    fresh = native_crop(case / "FreshWt.OUT")
    metrics = {}
    for r in range(1, 13):
        crop = [v for k, v in sorted(growth.items()) if k[0] == r and k in DAYS]
        fruit = [v["CHFPW"] for k, v in sorted(fresh.items()) if k[0] == r]
        metrics[r] = {
            "peak_lai": max(row["LAID"] for row in crop),
            "end_lai": crop[-1]["LAID"],
            "gross_photo": sum(v["PG"] for k, v in cash.items() if k[0] == r),
            "photo_less_plant_maintenance": sum(v["PG"] - v["maintenance"] for k, v in cash.items() if k[0] == r),
            "end_shoot_dm_kg_ha": crop[-1]["CWAD"],
            "fresh_yield_kg_ha": fruit[-1],
            "uptake_kg_ha": 10 * sum(v["U_NO3"] + v["U_NH4"] for k, v in plant.items() if k[0] == r),
            "mean_qno3": sum(v["QNO3"] for k, v in plant.items() if k[0] == r) / len(crop),
        }
    gradients = {}
    for water, treatment in GROUPS.items():
        gradients[water] = {}
        for field in metrics[1]:
            values = [metrics[r][field] for r in treatment]
            steps = [b - a for a, b in zip(values, values[1:])]
            gradients[water][field] = {
                "N0_to_N3": values, "increments": steps, "passes": steps[0] > steps[1] > steps[2] >= 0,
            }
    return {"gradients": gradients, "observation_rmse": observations(case, growth, fresh)}


def stop_metrics(control, stop):
    a = daily_csv(control / "PlantNIntegration.csv")
    b = daily_csv(stop / "PlantNIntegration.csv")
    a_leaf = daily_csv(control / "PlantNLAI.csv")
    b_leaf = daily_csv(stop / "PlantNLAI.csv")
    a_cash = daily_csv(control / "PlantCCash.csv")
    b_cash = daily_csv(stop / "PlantCCash.csv")
    signals = {"QNO3": (a, b, "QNO3"), "SLN": (a, b, "functional_leaf_N_per_area"),
               "new_area": (a_leaf, b_leaf, "new_leaf_area"), "photo": (a_cash, b_cash, "PG"),
               "old_area": (a_leaf, b_leaf, "old_leaf_area_lost")}
    paired = {}
    for r in (4, 5):  # W3 and W2 at N2
        paired[r] = {}
        for label, (control_rows, stop_rows, column) in signals.items():
            times = []
            for day in range(STOP_DOY, 199):
                original = control_rows[r, 2026000 + day][column]
                change = stop_rows[r, 2026000 + day][column] - original
                if label != "old_area":
                    change = -change
                if change > max(0.05 * abs(original), 1e-8):
                    times.append(day)
            paired[r][label] = times[0] if times else None
    return {"first_over_5_percent_relative_to_field_doy": paired}


def replay(engine, folder, full):
    jobs = [(s, s, "field", True, {}) for s in STAGES] if full else [("B4", "B4", "field", True, {})]
    if full:
        jobs += [("B4-matched", "B4", "matched", False, {}),
                 ("B4-stop", "B4", "stop", False, {}),
                 ("B4-SLN070", "B4", "field", True, {"photo_sln_ref": 0.70})]

    def worker(job):
        name, stage, scenario, traced, options = job
        case, receipt = run_case(engine, folder / name, stage, scenario, traced, **options)
        if full and scenario != "stop":
            receipt.update(field_metrics(case))
        return name, receipt

    with ThreadPoolExecutor(max_workers=3 if full else 1) as pool:
        cases = dict(pool.map(worker, jobs))
    cases["B4"]["same_directory_identical_csv"] = compare_rerun(engine, folder / "B4", traced=True)
    if full:
        cases["B4-stop"].update(stop_metrics(folder / "B4", folder / "B4-stop"))
        assert cases["B4-SLN070"]["photo_calls_below_one"] > 0, "Fixed SLN curve was never exercised"
        _, cases["B4-timing"] = run_case(engine, folder / "B4-timing", "B4", traced=False)
    case, diagnostics = run_case(engine, folder / "B4-all-ledgers", "B4", traced=False, **ALL_LEDGERS)
    diagnostics["same_directory_identical_csv"] = compare_rerun(engine, case, traced=False)
    assert len(diagnostics["same_directory_identical_csv"]) == 12
    cases["B4-all-ledgers"] = diagnostics
    result = {"engine_sha256": digest(engine), "cases": cases}
    (folder / "shoot_audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(f"TM deficiency engineering audit passed for {', '.join(cases)}")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="Keep the full ablation and paired 26SP outputs here")
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    if args.out is not None:
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=False)
        replay(engine, out, full=True)
    else:
        with TemporaryDirectory(prefix="dssat-tm-deficiency-") as out:
            replay(engine, Path(out), full=False)


if __name__ == "__main__":
    main()
