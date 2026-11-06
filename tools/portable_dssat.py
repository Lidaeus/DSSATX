"""Build-toolchain checks and an isolated 26SP DSSAT smoke run."""

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "subprojects/critical_n/dssat_csm_os_4864"
FIXTURE = ROOT / "fixtures/v7-26sp"
SUFFIX = ".exe" if os.name == "nt" else ""
INPUT_SUFFIXES = {".cde", ".err", ".tmx", ".tma", ".tmt", ".cul", ".eco", ".spe", ".sol", ".wth", ".wda", ".sda"}


def run(command, cwd, name, env=None):
    log = cwd / f"{name}.log"
    with log.open("wb") as output:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=output,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=300)
    if result.returncode:
        raise RuntimeError(f"{name} exited with {result.returncode}. See {log}")
    return log.read_text(encoding="utf-8", errors="replace")


def local_profile(path):
    template = (ENGINE / "Data/DSSATPRO.L48.in").read_text(encoding="ascii")
    records = []
    for line in template.splitlines():
        match = re.fullmatch(r"([A-Z0-9]{3}) // \S+(.*)", line)
        if match:
            code, tail = match.groups()
            line = f"{code}    .{tail}"
        records.append(line)
    path.write_text("\n".join(records) + "\n", encoding="ascii")


def new_directory(path):
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def read_daily(path):
    with path.open(newline="", encoding="ascii") as stream:
        records = list(csv.DictReader(stream))
    return {(int(row["run"]), int(row["yrdoy"])): row for row in records}, len(records)


def smoke(args):
    executable = args.exe.resolve(strict=True)
    config = args.config.resolve(strict=True)
    work = new_directory(args.out)
    for path in sorted(FIXTURE.iterdir()):
        if path.suffix.lower() in INPUT_SUFFIXES or path.name == "DSSBatch.v48":
            shutil.copyfile(path, work / path.name)
    shutil.copyfile(config, work / "NIntegration.nml")
    shutil.copyfile(ENGINE / "Data/Pest/TMGRO048.PST", work / "TMGRO048.PST")
    local_profile(work / ("DSSATPRO.v48" if os.name == "nt" else "DSSATPRO.L48"))
    env = dict(os.environ, DSSAT_HOME=f".{os.sep}")
    env.pop("DSSAT_N_CONFIG", None)
    env.pop("DSSAT_P0_TRACE", None)
    if args.trace:
        env["DSSAT_P0_TRACE"] = "1"
    run([str(executable), "CRGRO048", "B", "DSSBatch.v48"], work, "dssat", env)

    expected = {(run_id, yrdoy) for run_id in range(1, 13) for yrdoy in range(2026073, 2026199)}
    budgets = {}
    for name, field, tolerance in [
        ("PlantNIntegration.csv", "Q_residual", 1e-9),
        ("PlantABudget.csv", "organic_residual", 1e-5),
        ("PlantCCash.csv", "CH2O_residual", 1e-4),
    ]:
        rows, count = read_daily(work / name)
        if count != len(expected) or set(rows) != expected:
            raise RuntimeError(f"{name} has incomplete or duplicate run/day keys")
        values = [float(row[field]) for row in rows.values()]
        if not all(math.isfinite(value) and abs(value) <= tolerance for value in values):
            raise RuntimeError(f"{name} exceeds smoke tolerance for {field}")
        budgets[field] = max(map(abs, values))
        if name == "PlantNIntegration.csv" and any(int(row["stage"]) != 5 for row in rows.values()):
            raise RuntimeError("The integrated nitrogen stage did not run for all days")
    layers = work / "LayerNIntegration.csv"
    with layers.open(newline="", encoding="ascii") as stream:
        uptake_rows = list(csv.DictReader(stream))
    if not uptake_rows or not any(float(row["NO3_final_gN_m2"]) > 0 for row in uptake_rows):
        raise RuntimeError("The root trace has no positive realized nitrate uptake")
    receipt = {
        "success": True,
        "purpose": "26SP smoke and conservation, not cross-platform numerical parity",
        "binary_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "treatments": 12,
        "daily_rows": len(expected),
        "layer_rows": len(uptake_rows),
        "max_abs_budget_residuals": budgets,
    }
    (work / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


def native_tests(args):
    build = args.build.resolve(strict=True)
    cache = (build / "CMakeCache.txt").read_text(encoding="utf-8")
    match = re.search(r"^CMAKE_Fortran_COMPILER:[^=]+=(.+)$", cache, flags=re.M)
    if not match:
        raise RuntimeError("Compiler path is missing from CMakeCache.txt")
    compiler = Path(match.group(1).strip()).resolve(strict=True)
    work = new_directory(args.out)
    shutil.copyfile(ENGINE / "research/n_integration_v2/stage5_engineering.nml", work / "NIntegration.nml")
    mods = work / "mod"
    mods.mkdir()
    flags = ["-ffree-line-length-none", "-fcheck=all", "-finit-real=snan",
             "-ffpe-trap=invalid,zero,overflow", "-I", str(build / "mod"), "-I", str(mods)]
    core = ENGINE / "Plant/CROPGRO/CG_Nitrogen.f90"
    obj = work / "nitrogen.o"
    env = os.environ.copy()
    env.pop("DSSAT_N_CONFIG", None)
    run([str(compiler), *flags, "-J", str(mods), "-c", str(core), "-o", str(obj)], work, "compile", env)
    suites = {
        "native_n": ("n_integration_v2/native_n_tests.f90", "NATIVE_N_CHECKS_PASSED="),
        "native_ra": ("n_v6/native_ra_tests.f90", "NATIVE_RA_CHECKS_PASSED="),
    }
    for name, (source, marker) in suites.items():
        executable = work / f"{name}{SUFFIX}"
        link_flags = ["-static"] if os.name == "nt" else []
        run([str(compiler), *flags, str(ENGINE / "research" / source), str(obj),
             *link_flags, "-o", str(executable)], work, f"link_{name}", env)
        output = run([str(executable)], work, name, env)
        if not re.search(rf"{marker}[1-9]\d*", output):
            raise RuntimeError(f"Missing success marker in {name}.log")
        print(output.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    case = actions.add_parser("smoke", help="Run the isolated 12-treatment fixture")
    case.add_argument("--exe", type=Path, required=True)
    case.add_argument("--out", type=Path, required=True)
    case.add_argument("--config", type=Path, default=FIXTURE / "NIntegration.nml")
    case.add_argument("--trace", action="store_true", help="Enable the large daily P0 trace")
    case.set_defaults(handler=smoke)
    native = actions.add_parser("native-tests", help="Compile and run the engine's Fortran unit tests")
    native.add_argument("--build", type=Path, required=True)
    native.add_argument("--out", type=Path, required=True)
    native.set_defaults(handler=native_tests)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
