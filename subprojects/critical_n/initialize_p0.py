"""Initialize isolated development workspace n_buffer_v1 and generate P0 manifests."""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

CRITICAL_N = Path(r"D:\Tomato_Cal\subprojects\critical_n")
RELEASE = CRITICAL_N / "reviewfix_r1"
TARGET = CRITICAL_N / "n_buffer_v1"

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    print(f"Initializing n_buffer_v1 at {TARGET}...")
    TARGET.mkdir(parents=True, exist_ok=True)
    
    # Subdirectories
    for sub in ["vendor", "runtime", "bin", "tests", "experiments", "reports", "patches", "manifests", "failure_snapshot"]:
        (TARGET / sub).mkdir(parents=True, exist_ok=True)

    # Copy vendor if not already present
    vendor_target = TARGET / "vendor"
    if not (vendor_target / "CMakeLists.txt").exists():
        print("Copying vendor source tree...")
        shutil.copytree(RELEASE / "vendor", vendor_target, dirs_exist_ok=True)

    # Copy runtime if not already present
    runtime_target = TARGET / "runtime"
    if not (runtime_target / "src").exists():
        print("Copying runtime environment...")
        shutil.copytree(RELEASE / "runtime", runtime_target, dirs_exist_ok=True)

    # Verify protected originals
    protected = json.loads((RELEASE / "protected_originals.json").read_text(encoding="utf-8"))
    for p, h in protected.items():
        assert sha256_file(Path(p)) == h, f"Protected original mismatch: {p}"

    # B0 baseline info
    b0_dir = Path(r"D:\Tomato_Cal\workspace\runs\eggplant_26sp_all12_reviewfix_joint69_200x5_r1c")
    b0_bin = RELEASE / "bin/dscsm048_cnc_reviewfix_r1c.exe"
    b0_bin_hash = sha256_file(b0_bin)
    assert b0_bin_hash == "4e8cfa9de9a1077ac72c1a3d227b9e9aa88e0c7ad9a4e95b72a8f0b0bd4ec6e6"

    # Find toolchain
    sys.path.insert(0, str(CRITICAL_N.parents[1]))
    from subprojects.critical_n.scripts.build_and_verify_dssat import find_toolchain
    toolchain = find_toolchain()

    baseline_manifest = {
        "workspace": str(TARGET),
        "source_base": str(RELEASE / "vendor"),
        "runtime_base": str(RELEASE / "runtime"),
        "b0_run_id": "eggplant_26sp_all12_reviewfix_joint69_200x5_r1c",
        "b0_run_dir": str(b0_dir),
        "b0_executable": str(b0_bin),
        "b0_executable_sha256": b0_bin_hash,
        "protected_originals_count": len(protected),
        "toolchain": toolchain,
        "active_crop": "eggplant",
        "model": "TMGRO048 (CROPGRO)",
        "season": "2026 Spring (26SP)",
        "treatments": list(range(1, 13)),
        "baseline_metrics": {
            "LEAF_N_CONCENTRATION": {"n": 48, "rmse": 0.395432, "nrmse_pct": 9.2178, "nse": -0.4174},
            "STEM_N_CONCENTRATION": {"n": 48, "rmse": 0.519897, "nrmse_pct": 22.2302, "nse": -0.8775},
            "FRUIT_N_CONCENTRATION": {"n": 36, "rmse": 0.241246, "nrmse_pct": 13.9780, "nse": -0.6378},
            "FINAL_FRESH_YIELD": {"n": 12, "rmse_kgha": 4454.07, "nrmse_pct": 6.8570, "nse": 0.4135},
            "FINAL_DRY_YIELD": {"n": 12, "rmse_kgha": 306.44, "nrmse_pct": 7.9794, "nse": -0.0523},
            "N_ADJACENT_SIGNED_CONTRAST": {"n": 9, "rmse_kgha": 4474.19, "nrmse_pct": 128.4027, "nse": -0.2265},
            "LEAF_DRY_MASS": {"n": 48, "rmse_kgha": 173.99, "nrmse_pct": 18.9005, "nse": 0.8923},
            "STEM_DRY_MASS": {"n": 48, "rmse_kgha": 274.40, "nrmse_pct": 21.8957, "nse": 0.8908},
            "CANOPY_LAI": {"n": 48, "rmse": 0.433883, "nrmse_pct": 23.2005, "nse": 0.8452}
        }
    }
    (TARGET / "manifests/baseline_manifest.json").write_text(json.dumps(baseline_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Acceptance contract G00 - G11
    acceptance_contract = {
        "version": "1.0",
        "target_season": "2026 Spring (12 treatments: W1/W2/W3 x N0/N1/N2/N3)",
        "contracts": {
            "G00": {
                "name": "Isolation, Versioning & Baseline Reproduction",
                "rules": [
                    "Original protected 591 files and B0 binaries untouched",
                    "New executable path and binary hash strictly isolated",
                    "With new mechanism disabled, reproduces 12 treatments against B0 (PlantGro, PlantN, FreshWt, SoilNi, ETPhot)"
                ]
            },
            "G01": {
                "name": "Mass & Carbon Conservation, Non-negative Stocks",
                "rules": [
                    "Plant N balance: output = input with tolerance daily <= max(1e-4, 20*eps*S), season <= max(0.01, 100*eps*S)",
                    "Native print balance tolerance <= 0.25 kg N/ha (plant) and <= 0.05 kg N/ha (soil) maintained",
                    "No negative stocks or over-capacity in fast reserves",
                    "Carbon assimilation cost accounted for newly absorbed N"
                ]
            },
            "G02": {
                "name": "Observation Operators and Data Integrity",
                "rules": [
                    "Leaf 48 and Stem 48 matched pairs exact date and dry-basis",
                    "Fruit 36 pairs audited and explicit operator documented",
                    "No silent zero imputation, no interpolated observation dates"
                ]
            },
            "G03": {
                "name": "Controlled Mechanism Behaviors",
                "rules": [
                    "Smooth transition near NNI=1",
                    "Reserves form endogenously under adequate N, buffer during cutoff, recover on refill",
                    "Reserve N does not automatically increase leaf photosynthesis",
                    "Fruit is non-donor; root uptake remains active for new sink even if shoot NNI > 1"
                ]
            },
            "G04": {
                "name": "Compiled Fortran & Runtime Stress Tests",
                "rules": [
                    "True Fortran modules and full executable tests pass",
                    "10,000+ random state mass conservation checks pass",
                    "Official tomato & maize benchmark smoke tests pass"
                ]
            },
            "G05": {
                "name": "Organ N Fitting (Primary Scientific Threshold)",
                "rules": [
                    "Leaf N RMSE <= 0.3163 % DM (80% of B0) and overall NSE >= 0",
                    "Stem N RMSE <= 0.3639 % DM (70% of B0) and overall NSE >= 0",
                    "Fruit N RMSE <= 0.2533 % DM (105% of B0)",
                    "Subgroup check: at least 9 of 12 subgroups (4 dates x 3 water levels) RMSE not worse than B0"
                ]
            },
            "G06": {
                "name": "Guardrails on Yield, Biomass, LAI, Water & Phenology",
                "rules": [
                    "Final fresh yield NRMSE <= 7.0%, final dry yield NRMSE <= 8.0%",
                    "Leaf DM, Stem DM, LAI, event harvest dry yield RMSE <= 110% of B0",
                    "Soil water and interval water balance RMSE <= 110% of B0",
                    "Anthesis date MAE <= 2 days"
                ]
            },
            "G07": {
                "name": "N Rate Yield Response Smoothness",
                "rules": [
                    "Fixed non-N inputs sweep across 0 - 400 kg N/ha across W1, W2, W3",
                    "No non-physical jumps J(h) > 1%, no oscillating zig-zags"
                ]
            },
            "G08": {
                "name": "Nitrogen Response Magnitude & Direction",
                "rules": [
                    "9 adjacent N signed fresh yield contrasts RMSE <= 3579.35 kg/ha (80% of B0)",
                    "N2 - N1 positive and >= 25% of observed contrast across all 3 water levels",
                    "At least 7 of 9 adjacent contrasts match observed sign"
                ]
            },
            "G09": {
                "name": "Calibration Stability & Identifiability",
                "rules": [
                    "True PEST++ IES execution",
                    "Final member retention >= 98%, missing Phi slots <= 2%",
                    "Deterministic re-computation matches PEST Phi within numerical tolerance",
                    "Added active parameters <= 6"
                ]
            },
            "G10": {
                "name": "Root Limitation Diagnosis",
                "rules": [
                    "Decompose trajectory limitations: sink demand, root capacity, soil inventory, C limitation",
                    "Execute local concentration response & whole-crop counterfactuals"
                ]
            },
            "G11": {
                "name": "Reproducible Delivery Package",
                "rules": [
                    "Delivery files complete: README, mechanism_spec, manifests, tests, experiments, acceptance_results, final_review",
                    "All thresholds explicitly marked pass/fail/not_tested/blocked_by_data"
                ]
            }
        }
    }
    (TARGET / "manifests/acceptance_contract.json").write_text(json.dumps(acceptance_contract, indent=2, ensure_ascii=False), encoding="utf-8")
    print("P0 setup completed successfully.")

if __name__ == "__main__":
    main()
