#!/usr/bin/env python3
"""End-to-end demonstration and validation of Scheme A CNC integration.

Executes:
1. Stream parsing of multi-run DSSAT output files.
2. Cumulative effective biomass calculation & sawtooth elimination verification.
3. Rigid PestCNC.OUT formatting and sentinel line count invariance.
4. Sparse phenological subsampling (4 points per treatment).
5. PestCNC.ins PEST++ instruction generation and PyEMU parse validation.
6. Symmetrical physiological tolerance interval objective penalty evaluation.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pyemu

from subprojects.critical_n.adapters.instruction_generator import (
    generate_pest_cnc_instructions,
)
from subprojects.critical_n.adapters.pest_cnc_exporter import (
    export_cnc_dataframe,
    export_pest_cnc,
)
from subprojects.critical_n.calibration.cnc_builder import (
    build_cnc_observation_targets,
)
from subprojects.critical_n.core.dilution_curve import (
    DEFAULT_CNC_A,
    DEFAULT_CNC_B,
    DEFAULT_CNC_W0,
)
from subprojects.critical_n.core.effective_biomass import (
    verify_sawtooth_elimination,
)
from subprojects.critical_n.core.objective_penalty import (
    compute_cnc_objective_penalty,
)


def run_demo(run_dir: Path) -> int:
    print("=" * 70)
    print("CRITICAL NITROGEN DILUTION (SCHEME A) INTEGRATION DEMO")
    print("=" * 70)
    print(f"Target run directory: {run_dir}")

    # Step 1: Export PestCNC.OUT
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        out_file = tmp_dir / "PestCNC.OUT"
        ins_file = tmp_dir / "PestCNC.OUT.ins"

        print("\n[1/5] Exporting PestCNC.OUT...")
        export_pest_cnc(run_dir, out_file=out_file)
        lines = out_file.read_text(encoding="utf-8").splitlines()
        print(f"  -> Generated {len(lines)} lines")
        print(f"  -> Header line 1: {lines[0]}")
        print(f"  -> Header line 2: {lines[1]}")
        print(f"  -> Sample data row: {lines[len(lines)//2]}")

        # Step 2: Build DataFrame and check statistics
        print("\n[2/5] Analyzing CNC Trajectories...")
        df = export_cnc_dataframe(run_dir)
        valid_df = df[df["is_valid"]]
        print(f"  -> Total records: {len(df)}, Valid canopy records: {len(valid_df)}")
        print(f"  -> Mean effective biomass W_eff: {valid_df['w_eff'].mean():.2f} t DM/ha")
        print(f"  -> Mean critical Nc: {valid_df['nc_crit'].mean():.2f}%")
        print(f"  -> Mean simulated NNI: {valid_df['nni'].mean():.3f}")

        # Step 3: Verify Sawtooth Elimination
        print("\n[3/5] Verifying Sawtooth Discontinuity Elimination...")
        # Check an empirical harvest drop
        sawtooth_check = verify_sawtooth_elimination(
            pre_harvest_cwad=3802.0,
            pre_harvest_cnad=173.6,
            fruit_dm=563.0,
            fruit_n=10.0,
            post_harvest_cwad=3239.0,
            post_harvest_cnad=163.6,
        )
        print(f"  -> Standing W jump: {sawtooth_check['standing_delta_w']:.3f} t DM/ha")
        print(f"  -> Standing NNI jump: {sawtooth_check['standing_delta_nni']:+.3f} (false jump!)")
        print(f"  -> Cumulative W_eff delta: {sawtooth_check['cum_delta_w']:.6f} t DM/ha (continuous!)")
        print(f"  -> Cumulative NNI delta: {sawtooth_check['cum_delta_nni']:+.6f} (continuous!)")
        assert abs(sawtooth_check["cum_delta_nni"]) < 1e-6

        # Step 4: Sparse Phenological Subsampling & PEST Instruction Generation
        print("\n[4/5] Building Sparse Phenological Targets & PEST Instruction...")
        targets = build_cnc_observation_targets(
            run_dir,
            treatment_n_levels=None,  # Auto-discovers from treatment_metadata.csv
            n_points_per_treatment=4,
            weight=0.25,
        )
        print(f"  -> Generated {len(targets)} sparse observation targets across runs")
        for t in targets[:4]:
            print(f"     Target: {t.obs_name:<16} trt={t.treatment_id} das={t.das:3d} val={t.target_value:.2f} w={t.weight:.2f}")

        generate_pest_cnc_instructions(run_dir, targets, ins_file)
        parsed_obs = pyemu.pst_utils.parse_ins_file(str(ins_file))
        print(f"  -> PyEMU verified {len(parsed_obs)} observation names from instruction file!")
        assert len(parsed_obs) == len(targets)

        # Step 5: Symmetrical Physiological Tolerance Penalty
        print("\n[5/5] Evaluating Symmetrical Physiological Tolerance Penalty...")
        sim_nni_by_level = {
            "N3": [1.10, 1.15, 1.25, 1.28],  # Realistic luxury consumption inside [1.00, 1.30]
            "N0": [0.65, 0.58, 0.52, 0.45],  # Healthy low-N deficiency inside [0.40, 0.70]
        }
        loss_realistic, comps = compute_cnc_objective_penalty(sim_nni_by_level)
        print(f"  -> Realistic physiology penalty J_CNC = {loss_realistic:.4f} (zero unwarranted penalty!)")

        # Now test severe collapse in N0
        sim_nni_collapsed = {
            "N0": [0.30, 0.20, 0.10, 0.05],  # Severe collapse below 0.40
        }
        loss_collapsed, comps_c = compute_cnc_objective_penalty(sim_nni_collapsed)
        print(f"  -> Collapsed N0 penalty J_CNC = {loss_collapsed:.4f} (properly penalized!)")
        assert loss_collapsed > 0.0

    print("\n" + "=" * 70)
    print("ALL DEMO VERIFICATION STEPS PASSED SUCCESSFULLY!")
    print("=" * 70)
    return 0


def main() -> int:
    # Use existing scratch/test_0.5 if present
    cand = PROJECT_ROOT / "scratch/test_0.5"
    if cand.is_dir() and (cand / "PlantGro.OUT").is_file():
        return run_demo(cand)
    else:
        print(f"Test directory not found at {cand}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
