"""CLI script for comparing Scheme B vs. Native CROPGRO dynamics across N levels.

Executes side-by-side simulations for:
- N0: Severe nitrogen deficiency
- N1: Moderate nitrogen deficiency
- N2: Optimal standard supply
- N3: Luxury nitrogen excess

Outputs quantitative performance metrics, avalanche prevention statistics,
mass conservation residuals, and optional trajectory CSVs.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from subprojects.critical_n.scheme_b.adapter import (
    SchemeBAdapter,
    DEFAULT_TREATMENT_N_LEVELS,
)
from subprojects.critical_n.scheme_b.acclimation import AcclimationType


def run_comparison(
    days: int = 100,
    acclimation_type: str = "sigmoid",
    out_dir: Path | None = None,
) -> int:
    """Run full comparative simulation suite."""
    print("=" * 78)
    print(" CROPGRO SCHEME B DYNAMIC ACCLIMATION & SENESCENCE GOVERNOR EVALUATION")
    print("=" * 78)
    print(f"Simulation duration: {days} days")
    print(f"Acclimation model  : {acclimation_type}")
    print(f"Treatments evaluated: {len(DEFAULT_TREATMENT_N_LEVELS)} (N0, N1, N2, N3)")
    print("-" * 78)

    acc_type = AcclimationType(acclimation_type.lower())
    adapter = SchemeBAdapter(acclimation_type=acc_type)
    all_results = adapter.run_all_treatments(duration_days=days)

    print("\n[1] TREATMENT SUMMARY TABLE (Native CROPGRO vs. Scheme B Coupled):")
    print("-" * 86)
    print(
        f"{'Treatment':<22} | {'LAI (Nat / B)':<15} | {'Avalanche Days':<16} | "
        f"{'Defol Saved (g)':<15} | {'Max N Res (g)':<12}"
    )
    print("-" * 86)

    all_conserved = True
    for trt_id, (metrics, _, _) in all_results.items():
        lai_str = f"{metrics.native_final_lai:.2f} / {metrics.scheme_b_final_lai:.2f}"
        avalanche_str = f"{metrics.native_avalanche_days:2d} -> {metrics.scheme_b_avalanche_days:2d}"
        saved_str = f"{metrics.total_suppressed_defoliation:6.1f}"
        res_str = f"{metrics.scheme_b_max_n_residual:.2e}"

        if not metrics.mass_balance_verified:
            all_conserved = False

        print(
            f"{trt_id:<22} | {lai_str:<15} | {avalanche_str:<16} | "
            f"{saved_str:<15} | {res_str:<12}"
        )

    print("-" * 86)

    # Key physiological conclusions
    n0_m = all_results["N0_severe_deficit"][0]
    n3_m = all_results["N3_luxury_excess"][0]

    print("\n[2] PHYSIOLOGICAL VERIFICATION METRICS:")
    print(f"  * N0 Defoliation Prevention: LAI retained at {n0_m.scheme_b_final_lai:.2f} "
          f"vs Native crash {n0_m.native_final_lai:.2f} "
          f"(Retention Ratio: {n0_m.lai_retention_ratio:.1f}x)")
    print(f"  * N0 Avalanche Elimination: Native had {n0_m.native_avalanche_days} avalanche days "
          f"-> Scheme B has {n0_m.scheme_b_avalanche_days} days")
    print(f"  * N3 Luxury Dampening     : Peak LAI regulated from {n3_m.native_peak_lai:.2f} "
          f"to {n3_m.scheme_b_peak_lai:.2f}")
    print(f"  * Global N Mass Balance    : {'PASSED (residuals < 1e-5 g N/m^2)' if all_conserved else 'FAILED'}")

    # Export tidy DataFrame if requested
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        df = adapter.build_comparison_dataframe(all_results)
        csv_path = out_dir / "scheme_b_comparison_trajectories.csv"
        df.to_csv(csv_path, index=False)
        print(f"\n[3] Exported comparison trajectory dataset: {csv_path} ({len(df)} rows)")

    print("=" * 78)
    return 0 if all_conserved else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Scheme B vs Native CROPGRO Dynamics across Nitrogen Levels"
    )
    parser.add_argument(
        "--days", type=int, default=100, help="Simulation duration in days (default: 100)"
    )
    parser.add_argument(
        "--acclimation-type",
        choices=["sigmoid", "hill", "michaelis_menten"],
        default="sigmoid",
        help="Photosynthetic acclimation function (default: sigmoid)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Optional directory to save comparison trajectory CSV",
    )
    args = parser.parse_args()
    sys.exit(run_comparison(days=args.days, acclimation_type=args.acclimation_type, out_dir=args.out_dir))


if __name__ == "__main__":
    main()
