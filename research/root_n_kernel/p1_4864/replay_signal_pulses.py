"""Run paired 26SP weak-light and no-new-root-N pulses with the SLN probe engine."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from functools import partial
import json
import os
from pathlib import Path
from statistics import mean

from replay_shoot import GROUPS, TEMPLATE, audit, digest, prepare_case, prepare_experiment, run
from replay_signal_chain import enable_fixed_diagnostics, matrix
from replay_sln_pulse import CUT, REFILL, write_records

LIGHT_END = CUT + 5
LIGHT_FRACTION = 0.2
RESPONSE = {
    "q_no3": -1, "leaf_n_org_pct": -1, "photo_sln": -1, "photo_factor": -1,
    "gross_photo": -1, "new_leaf_area": -1, "sen_n_extra": 1,
}


def attenuate(path):
    lines = path.read_text(encoding="ascii").splitlines(keepends=True)
    changed = 0
    for i, line in enumerate(lines):
        day = line[:7]
        if day.isdigit() and CUT <= int(day) < LIGHT_END:
            lines[i] = line[:7] + f"{LIGHT_FRACTION * float(line[7:13]):6.1f}" + line[13:]
            changed += 1
    if changed != LIGHT_END - CUT:
        raise ValueError("Expected one weather row per pulse day")
    path.write_text("".join(lines), encoding="ascii")


def trial(engine, config, out, name):
    case = prepare_case(argparse.Namespace(config=config, out=out / name))
    settings = enable_fixed_diagnostics(config)
    (case / "NIntegration.nml").write_text(settings, encoding="ascii")
    prepare_experiment(case / "XXQL2601.TMX", "matched")
    weather = case / "XXTW2403.WTH"
    if name == "weak-light":
        attenuate(weather)
    env = dict(os.environ, DSSAT_HOME=f".{os.sep}", DSSAT_P0_TRACE="1",
               DSSAT_SLN_PROBE_CUT=str(int(name == "cutoff")))
    env.pop("DSSAT_N_CONFIG", None)
    run([str(engine), "CRGRO048", "B", "DSSBatch.v48"], case, "dssat", env)
    daily, _ = matrix(case)
    write_records(case / "signal_daily.csv", daily)
    return name, {(r["run"], r["yrdoy"]): r for r in daily}, {
        "config_sha256": digest(case / "NIntegration.nml"),
        "weather_sha256": digest(weather), "audit": audit(case, 12),
    }


def compare(reference, pulse, kind):
    assert all(row == pulse[key] for key, row in reference.items() if key[1] < CUT)
    result = {}
    end = LIGHT_END if kind == "weak-light" else REFILL
    for water, group in GROUPS.items():
        for index, run_id in enumerate(group):
            c = [reference[run_id, d] for d in range(CUT, end)]
            p = [pulse[run_id, d] for d in range(CUT, end)]
            uptake = sum(r["uptake"] for r in p)
            if kind == "cutoff":
                assert uptake == 0 and pulse[run_id, REFILL]["uptake"] > 0, run_id
            entry = {}
            for label, days in (("control", c), ("pulse", p)):
                soil_n = sum(r["uptake"] for r in days)
                entry[label] = {
                    "avg_q_no3": mean(r["q_no3"] for r in days),
                    "uptake": soil_n, "assim": sum(r["assim"] for r in days),
                    "assim_per_uptake": sum(r["assim"] for r in days) / soil_n if soil_n else None,
                    "tnleak_increment": days[-1]["tnleak"] - reference[run_id, CUT - 1]["tnleak"],
                    "min_pgavl_before_pods": min(r["pgavl_pre_pods"] for r in days),
                    "gross_photo": sum(r["gross_photo"] for r in days),
                }
            entry["first_5pct_DAP"] = {
                name: next((cut["dap"] for base, cut in zip(c, p)
                            if base[name] is not None and cut[name] is not None
                            and direction * (cut[name] - base[name]) > max(1e-8, 0.05 * abs(base[name]))), None)
                for name, direction in RESPONSE.items()
            }
            result[f"{water}_N{index}"] = entry
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=TEMPLATE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    engine = args.engine.resolve(strict=True)
    config = args.config.resolve(strict=True)
    with ProcessPoolExecutor(max_workers=3) as pool:
        trials = {name: (daily, receipt) for name, daily, receipt in pool.map(
            partial(trial, engine, config, out), ("control", "weak-light", "cutoff"))}
    control = trials["control"][0]
    receipt = {name: meta | {"paired": compare(control, daily, name)}
               for name, (daily, meta) in trials.items() if name != "control"}
    receipt.update(control=trials["control"][1], engine_sha256=digest(engine))
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="ascii")
    print(out / "receipt.json")


if __name__ == "__main__":
    main()
