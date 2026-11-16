from concurrent.futures import ThreadPoolExecutor
import csv
import json
from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CASE_NAMES = {
    "off": "n4864_off_regression",
    "A": "n4864_rnkA_smoke",
    "B": "n4864_rnkB_smoke",
}
SPECIES = {"1": "UNO3", "2": "UNH4"}


def audit(run_dir, arm, expected_runs):
    trace_rates = {}
    season_end = {}
    soil_totals = {}
    pre_extract = {}
    with (run_dir / "P0Trace.csv").open(newline="") as stream:
        for row in csv.DictReader(stream):
            run, day, layer, key = (row[k] for k in ("run", "yrdoy", "layer", "key"))
            event = row["event"]
            if event == "rnk_pre_extract":
                pre_extract[run, day, layer, key] = float(row["value"])
            elif event == "soil_debit_before" and key in SPECIES.values():
                trace_rates[run, day, layer, key] = float(row["value"]) / 10
            elif event == "soil_season_end" and key in SPECIES.values():
                season_end[run, layer, key] = float(row["value"]) / 10
            elif event == "soil_season_end" and key == "CNUPTAKE":
                soil_totals[run] = float(row["value"]) / 10

    with (run_dir / "LayerRootNUptake.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows and all(len(row) == 25 and None not in row for row in rows)
    matched = set()
    deducted_by_run = {}
    pending_by_run = {}
    pending_rows = 0
    dry_rows = 0
    max_mass_residual = 0.0
    seen = set()
    for row in rows:
        run, source, commit, layer, species, status = (
            row[key] for key in ("run", "source_day", "soil_commit_day", "layer", "species", "soil_status")
        )
        identity = (run, source, layer, species)
        assert identity not in seen, identity
        seen.add(identity)
        deducted, pending, settled, accepted, candidate, cap = (
            float(row[f"{key}_gN_m2"]) for key in ("deducted", "pending", "settled", "accepted", "candidate", "stock_cap")
        )
        assert abs(settled - deducted - pending) < 1e-10, identity
        assert 0 <= settled <= accepted + 1e-10 and accepted <= candidate + 1e-10, identity
        assert candidate <= cap + 2e-7, identity
        assert int(row["solver_status"]) < 100, identity
        max_mass_residual = max(max_mass_residual, abs(float(row["radial_mass_error_gN_m2"])))
        if status == "committed":
            assert int(commit) > int(source) and pending == 0, identity
            trace_key = (run, commit, layer, SPECIES[species])
            assert trace_key not in matched, identity
            assert abs(trace_rates[trace_key] - deducted) < 1e-10, identity
            matched.add(trace_key)
            deducted_by_run[run] = deducted_by_run.get(run, 0.0) + deducted
        else:
            assert status == "pending_season_end" and commit == "0" and deducted == 0, identity
            assert abs(season_end[run, layer, SPECIES[species]] - pending) < 1e-10, identity
            pending_by_run[run] = pending_by_run.get(run, 0.0) + pending
            pending_rows += 1
        theta0 = pre_extract[run, source, layer, "theta0"]
        lower_limit = pre_extract[run, source, layer, "LL"]
        depth = pre_extract[run, source, layer, "DLAYR"]
        water = float(row["rwu_cm_d"])
        assert abs(float(row["theta0"]) - theta0) < 1e-12, identity
        assert abs(float(row["theta_mid"]) - (theta0 - 0.5 * water / depth)) < 1e-12, identity
        if theta0 < lower_limit:
            assert water == 0, identity
            dry_rows += 1
    unmatched = [key for key, value in trace_rates.items() if value > 0 and key not in matched]
    assert not unmatched, unmatched[:5]
    assert len(deducted_by_run) == expected_runs and len(pending_by_run) == expected_runs and max_mass_residual < 1e-9
    soil_residual = max(abs(soil_totals[run] - value) for run, value in deducted_by_run.items())
    # SOILNI's cumulative total uses single precision. The row-by-row check above is tighter.
    assert soil_residual < 0.002, soil_residual
    return {
        "arm": arm,
        "rows": len(rows),
        "matched_soil_rows": len(matched),
        "pending_rows": pending_rows,
        "pending_positive_rows": sum(float(row["pending_gN_m2"]) > 0 for row in rows),
        "dry_rows_theta0_below_LL": dry_rows,
        "max_radial_mass_residual_gN_m2": max_mass_residual,
        "max_soil_cumulative_difference_gN_m2": soil_residual,
        "run_1_deducted_kgN_ha": 10 * deducted_by_run["1"],
        "run_1_pending_kgN_ha": 10 * pending_by_run["1"],
    }


def prepare_run(run, source, field_case):
    run.mkdir()
    inputs = {file.name: file for file in source.iterdir()
              if file.is_file() and file.suffix.lower() not in {".out", ".csv", ".log", ".lst", ".exe"}}
    if field_case is not None:
        inputs = {name: file for name, file in inputs.items() if file.suffix.lower() in {".cde", ".nml"}}
        inputs.update({file.name: file for file in field_case.iterdir() if file.is_file()
                       and file.suffix.lower() in {".inp", ".inh", ".v48", ".sol", ".cul", ".eco",
                                                   ".spe", ".tma", ".tmt", ".tmx", ".wth", ".cde"}})
    for name, file in inputs.items():
        shutil.copy2(file, run / name)


def execute(run, exe, trace_enabled):
    with (run / "stdout.log").open("wb") as stdout, (run / "stderr.log").open("wb") as stderr:
        subprocess.run([str(exe), "B", "DSSBatch.v48"], cwd=run, stdout=stdout, stderr=stderr, check=True,
                       env=dict(os.environ, DSSAT_P0_TRACE="1" if trace_enabled else "0"), timeout=120)


def replay(arm, exe, output, field_case=None, baseline_engine=None):
    source = ROOT / "runs" / CASE_NAMES[arm]
    run = output / arm
    prepare_run(run, source, field_case)
    execute(run, exe, arm != "off")
    if arm == "off":
        assert not (run / "LayerRootNUptake.csv").exists()
        if field_case is not None:
            reference = output / "off_reference"
            prepare_run(reference, source, field_case)
            execute(reference, baseline_engine, False)
        else:
            reference = source
        ledgers = sorted(file.name for file in reference.glob("*.csv"))
        assert ledgers
        for name in ledgers:
            assert (run / name).read_bytes() == (reference / name).read_bytes(), name
        return {"arm": arm, "byte_identical_reference_ledgers": ledgers}
    expected_runs = sum(".TMX" in line.upper() for line in (run / "DSSBatch.v48").read_text().splitlines())
    return audit(run, arm, expected_runs)


if __name__ == "__main__":
    engine, destination, *optional = map(lambda value: Path(value).resolve(), sys.argv[1:])
    if len(optional) not in (0, 2):
        raise SystemExit("usage: verify_p1.py ENGINE DESTINATION [FIELD_CASE_DIR BASELINE_ENGINE]")
    destination.mkdir()
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda arm: replay(arm, engine, destination, *optional), CASE_NAMES))
    report = json.dumps(results, indent=2)
    (destination / "audit.json").write_text(report + "\n", encoding="utf-8")
    print(report)
