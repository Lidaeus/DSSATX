#!/usr/bin/env python3
"""port_spring58_macos.py -- port the Windows spring58 calibration line to
this macOS tree, switching the VALIDATION bundle to the user-directed
xxql2501_refreshed_lwad_20261108 (calibration set xxql2601_final_20261105
unchanged; the old 20261027 validation bundle is NOT imported).

Objective-function and weight design is preserved byte-for-byte: the 511
calibration observations (all from the 26SP bundle) and objective_policy
are untouched; only the validation-side assets are rebuilt with the
package's own builder functions, design.json paths are rewritten for
POSIX, the seal is recomputed and a fresh joint case is assembled.

Idempotent: re-running refreshes the ported artifacts in place.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

RUN_ID = "eggplant_final_springs_58_restored_bounds_40x3_8agents_20261107"
RUN = ROOT / "workspace/runs" / RUN_ID
PKG = ROOT / ".local/incoming/eggplant_spring58_calibration_portable_20261109"
PKG_TC = PKG / "Tomato_Cal"
LWAD_BUNDLE = ROOT / "data/user/experiments/xxql2501_refreshed_lwad_20261108"

WIN_TC = "D:\\Tomato_Cal\\"
WIN_CS_CAL = ("D:\\Tomato_Cal_Cold_Storage\\bundle_retirement_20261105"
              "\\calibration\\")
WIN_EXE = "C:\\DSSAT48\\DSCSM048.EXE"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def to_posix_key(value: str, engine_path: Path, engine_sha: str):
    """Rewrite one design.json path string / hash key to POSIX roots."""
    if value == WIN_EXE:
        return str(engine_path), engine_sha
    if value.startswith(WIN_CS_CAL):
        # 20261027 validation bundle is replaced by the LWAD bundle; the
        # mapping is recorded in port_macos.json (never silently).
        return str(LWAD_BUNDLE) + value[len(WIN_CS_CAL
                                            + "xxql2501_refreshed_20261027"):], None
    if value.startswith(WIN_TC):
        rel = value[len(WIN_TC):].replace("\\", "/")
        return str(ROOT / rel), None
    return value, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True,
                    help="native dscsm048 path (DSSAT_CUSTOM_EXE)")
    ap.add_argument("--engine-sha", required=True,
                    help="sha256 of the native engine")
    ap.add_argument("--std-data", default="",
                    help="DSSAT_STD_DATA_DIR used at runtime (recorded for "
                         "provenance; e.g. 4.8.5.0 code + 4.8.5.62 tables)")
    ap.add_argument("--std-data-note", default="",
                    help="provenance note for the standard-data mix")
    a = ap.parse_args()
    engine = Path(a.engine).resolve()
    assert engine.is_file(), engine

    # ---- 1. rebuild validation-side assets from the LWAD bundle -------
    from tools.calibration.run_dual_morris98_trial_20261105 import (
        observation_catalog)
    from tools.sa import run_dual_spring_morris_20261105 as native
    from src.common.input_manifest import verify_calibrated_input_bundle

    manifest_sha = verify_calibrated_input_bundle(LWAD_BUNDLE).manifest_sha256
    # The shipped locked_validation_observations.csv carries ADAP=37 dap
    # (existing_TMA_ADAT 2025-04-22) for the validation season -- both the
    # retired 20261027 bundle and the LWAD revision keep that FileA date.
    # The module's DATES assert enforces the confirmed-date policy for the
    # CALIBRATION season only; bypass it for the validation regeneration
    # exactly as the inherited locked table was constructed.
    import tools.calibration.run_dual_morris98_trial_20261105 as trial_mod
    saved = trial_mod.DATES["25SP"]
    trial_mod.DATES["25SP"] = "2025-04-22"
    try:
        lwad_catalog = observation_catalog(LWAD_BUNDLE, "25SP")
    finally:
        trial_mod.DATES["25SP"] = saved
    lwad_catalog.to_csv(RUN / "locked_validation_observations.csv",
                         index=False)
    print(f"locked_validation_observations.csv: {len(lwad_catalog)} rows "
          f"(LWAD 20261108, manifest {manifest_sha[:12]}…)")

    design = json.loads((RUN / "design.json").read_text(encoding="utf-8"))
    frozen_name = design["frozen_bounds"].replace("\\", "/").split("/")[-1]
    frozen = ROOT / "data/parameter_registry/bounds_frozen/eggplant" / frozen_name
    fields = __import__("pandas").read_csv(frozen).rename(
        columns={"name": "registry_name", "native_name": "name"})
    payload_dir = RUN / "25SP_inputs"
    if payload_dir.exists():
        shutil.rmtree(payload_dir)
    native.model_payload(LWAD_BUNDLE, payload_dir,
                         float(design["SLPF"]["25SP"]))
    native.context(LWAD_BUNDLE, payload_dir, "25SP", fields)
    kept = sorted(p.name for p in payload_dir.iterdir())
    print(f"25SP_inputs rebuilt from LWAD: {len(kept)} files")

    # ---- 2. rewrite design.json paths + hashes ------------------------
    replaced_cs, mapping = [], {}

    def walk(node, in_hashes=False):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if in_hashes:
                    # source_hashes: {win_path: sha}; 25SP payload entries
                    # will be recomputed after the rebuild below.
                    new_key, _ = to_posix_key(k, engine, a.engine_sha)
                    rel = k.replace("\\", "/").split("/")[-1]
                    rebuilt = payload_dir / rel
                    if k.startswith(WIN_TC) and "25SP_inputs" in k:
                        out[str(rebuilt)] = sha256(rebuilt)
                        mapping[k] = str(rebuilt)
                    elif new_key != k:
                        out[new_key] = sha256(Path(new_key)) \
                            if Path(new_key).is_file() else v
                        mapping[k] = new_key
                        if k.startswith(WIN_CS_CAL):
                            replaced_cs.append(k)
                    else:
                        out[k] = v
                elif isinstance(v, str):
                    new_v, _ = to_posix_key(v, engine, a.engine_sha)
                    if new_v != v:
                        mapping[v] = new_v
                        if v.startswith(WIN_CS_CAL):
                            replaced_cs.append(v)
                    out[k] = new_v
                elif k == "source_hashes":
                    out[k] = walk(v, True)
                else:
                    out[k] = walk(v, in_hashes)
            return out
        if isinstance(node, list):
            return [walk(x, in_hashes) for x in node]
        return node

    design = walk(design)
    # Force the engine entry to the CURRENT run's engine (idempotent rerun
    # with a different engine must not keep a stale fingerprint).
    for k in [k for k in design["source_hashes"]
              if k.endswith("/dscsm048") or k.endswith("DSCSM048.EXE")]:
        design["source_hashes"].pop(k)
    design["source_hashes"][str(engine)] = a.engine_sha
    design["datasets"]["25SP"]["path"] = str(LWAD_BUNDLE)
    design["datasets"]["25SP"]["manifest_sha256"] = manifest_sha
    design["port_macos"] = {
        "ported_from": str(PKG),
        "engine": str(engine), "engine_sha256": a.engine_sha,
        "windows_engine_sha256": "92173d5f63bc60d58839630b9a29f576"
                                 "32a19b373cab0faa8ad70362d98f5c7a",
        "std_data": a.std_data, "std_data_note": a.std_data_note,
        "co2_provenance": (
            "Windows installer C:\\DSSAT48\\StandardData\\CO2048.WDA was "
            "not shipped in the package; the repo v4.8.5.0 table ends at "
            "2023 and the engine then holds the last value for 2026. The "
            "v4.8.5.62 table (2026 ~429-431 ppm) is used instead; supply "
            "the Windows file to restore bit-exact parity (Windows ref "
            "Phi 84.7269878728234; macOS approx 86.44 with this mix)."),
        "validation_bundle": str(LWAD_BUNDLE),
        "validation_bundle_switch": ("xxql2501_refreshed_20261027 -> "
                                     "xxql2501_refreshed_lwad_20261108 "
                                     "(user decision 2026-11-09)"),
        "path_mapping": mapping,
        "replaced_cold_storage_refs": replaced_cs,
    }
    (RUN / "design.json").write_text(
        json.dumps(design, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    seal = {"sha256": sha256(RUN / "design.json")}
    (RUN / "sealed_design.json").write_text(
        json.dumps(seal, indent=2) + "\n", encoding="utf-8")
    print(f"design.json rewritten + resealed ({seal['sha256'][:12]}…); "
          f"{len(mapping)} paths remapped, {len(replaced_cs)} cold-storage "
          f"refs replaced")

    # ---- 3. fresh joint case ------------------------------------------
    from tools.calibration.port_spring58_joint import rebuild_joint
    rebuild_joint(RUN, engine)
    print("fresh joint/ rebuilt")

    # ---- 4. hash-gate dry run ------------------------------------------
    ok, bad = 0, []
    for key, digest in design["source_hashes"].items():
        p = Path(key)
        if not p.is_file():
            bad.append(f"MISSING {key}")
        elif sha256(p) != digest:
            bad.append(f"HASH {key}")
        else:
            ok += 1
    print(f"hash gate: {ok} pass, {len(bad)} fail")
    for b in bad[:10]:
        print(" ", b)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
