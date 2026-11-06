from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def run_cmd(args: list[str]):
    print(f"Running: {' '.join(args)}")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    result = subprocess.run([sys.executable] + args, cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"FAILED!\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
        sys.exit(result.returncode)
    print("SUCCESS")


def main():
    raise SystemExit(
        "Retired: these legacy v2 bundles set SYMBI=Y. "
        "The approved formal-SA policy is SYMBI=N and POTAS=N."
    )
    # 1. Clean up output directories if they exist
    dest_dir = PROJECT_ROOT / "data" / "user" / "experiments"
    for b in [
        "xxql2501_sa_source_crgro_y_v2",
        "xxql2502_sa_source_crgro_y_v2",
        "xxql2601_sa_source_crgro_y_v2",
        "xxql2501_sa_controlled_crgro_y_v2",
        "xxql2502_sa_controlled_crgro_y_v2",
        "xxql2601_sa_controlled_crgro_y_v2",
    ]:
        p = dest_dir / b
        if p.exists():
            shutil.rmtree(p)

    # 2. Generate source bundles
    # XXQL2501
    run_cmd([
        "tools/import_experiment_bundle.py",
        "--source-dir", "data/user/experiments/XXQL2501",
        "--soil", "data/user/experiments/xxql2501_symbi_n_candidate_20260719/SOIL.SOL",
        "--weather", "data/user/experiments/XXQL2501/XXLI2502.WTH",
        "--batch", "data/user/experiments/XXQL2501/DSSBatch.v48",
        "--experiment", "XXQL2501",
        "--bundle-id", "xxql2501_sa_source_crgro_y_v2",
        "--purpose", "sensitivity",
        "--symbi", "Y",
        "--correction-note", "Set non-legume eggplant SYMBI=Y as a CRGRO compatibility requirement, with FRCNOD fixed and excluded"
    ])

    # XXQL2502
    run_cmd([
        "tools/import_experiment_bundle.py",
        "--source-dir", "data/user/experiments/XXQL2502",
        "--soil", "data/user/experiments/xxql2501_symbi_n_candidate_20260719/SOIL.SOL",
        "--weather", "data/user/experiments/XXQL2502/XXLI2502.WTH",
        "--batch", "data/user/experiments/XXQL2502/DSSBatch.v48",
        "--experiment", "XXQL2502",
        "--bundle-id", "xxql2502_sa_source_crgro_y_v2",
        "--purpose", "sensitivity",
        "--symbi", "Y",
        "--experiment-title", "XXQL2502TM 2025 AUTUMN,SOLARSET,N-RATE,DRIP-IRR",
        "--correction-note", "Set non-legume eggplant SYMBI=Y as a CRGRO compatibility requirement, with FRCNOD fixed and excluded and correct season title to 2025 AUTUMN"
    ])

    # XXQL2601
    run_cmd([
        "tools/import_experiment_bundle.py",
        "--source-dir", "data/user/experiments/XXQL2601",
        "--soil", "data/user/experiments/xxql2501_symbi_n_candidate_20260719/SOIL.SOL",
        "--weather", "data/user/experiments/XXQL2601/XXQL2601.WTH",
        "--batch", "data/user/experiments/XXQL2601/DSSBatch.v48",
        "--experiment", "XXQL2601",
        "--bundle-id", "xxql2601_sa_source_crgro_y_v2",
        "--purpose", "sensitivity",
        "--symbi", "Y",
        "--normalize-fertilizer-level", "2",
        "--correction-note", "Set non-legume eggplant SYMBI=Y as a CRGRO compatibility requirement, with FRCNOD fixed and excluded and normalize MF2 fertilizer row order without changing values"
    ])

    # 3. Generate controlled counterfactual bundles
    # XXQL2501
    run_cmd([
        "src/sensitivity/counterfactual_inputs.py",
        "--source-dir", "data/user/experiments/xxql2501_sa_source_crgro_y_v2",
        "--out-dir", "data/user/experiments/xxql2501_sa_controlled_crgro_y_v2",
        "--common-ic", "2",
        "--treatments", "2,3,4,5,10,11,12,13"
    ])

    # XXQL2502
    run_cmd([
        "src/sensitivity/counterfactual_inputs.py",
        "--source-dir", "data/user/experiments/xxql2502_sa_source_crgro_y_v2",
        "--out-dir", "data/user/experiments/xxql2502_sa_controlled_crgro_y_v2",
        "--common-ic", "2",
        "--treatments", "1,3,4,6,7,9,10,12"
    ])

    # XXQL2601: Treatments 1,3,4,6,7,9,10 (deleting TN12)
    run_cmd([
        "src/sensitivity/counterfactual_inputs.py",
        "--source-dir", "data/user/experiments/xxql2601_sa_source_crgro_y_v2",
        "--out-dir", "data/user/experiments/xxql2601_sa_controlled_crgro_y_v2",
        "--common-ic", "2",
        "--treatments", "1,3,4,6,7,9,10"
    ])

    # 4. Modify manifests to record DSSAT version, SYMBI=Y compatibility reason, A/B evidence, and FRCNOD exclusion.
    for b in [
        "xxql2501_sa_source_crgro_y_v2",
        "xxql2502_sa_source_crgro_y_v2",
        "xxql2601_sa_source_crgro_y_v2",
        "xxql2501_sa_controlled_crgro_y_v2",
        "xxql2502_sa_controlled_crgro_y_v2",
        "xxql2601_sa_controlled_crgro_y_v2",
    ]:
        manifest_path = dest_dir / b / "input_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["dssat_version"] = "DSSAT v4.8.5.0"
        manifest["symbi_y_compatibility_reason"] = (
            "DSSAT CRGRO (tomato) model aborts at startup with IPSIM 'Potassium model has not been enabled "
            "for CRGRO' whenever SYMBI=N. For eggplant-on-tomato-model runs, SYMBI must therefore be Y."
        )
        manifest["ab_evidence"] = (
            "Confirmed by A/B testing the same FileX with SYMBI=N vs SYMBI=Y in CWD=TMD with explicit CRGRO048 "
            "(SYMBI=N -> exit 99, 0 rows; SYMBI=Y -> exit 0, 8 rows), documented in docs/reports/三季SA_T1_T3代码审查与下一轮交接_20260720.md"
        )
        manifest["frcnod_note"] = (
            "FRCNOD species parameter is fixed at 0.05 and excluded from genetic calibration/SA. "
            "Biological N fixation is not proven to be disabled by 0.05, but we require model-source or "
            "output evidence before describing it as an off switch."
        )
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"Updated manifest for {b}")

    print("\nAll V2 bundles generated and manifests updated successfully!")


if __name__ == "__main__":
    main()
