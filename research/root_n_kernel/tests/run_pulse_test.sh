#!/usr/bin/env bash
# Reproduce the two-day pulse contract from the original T3 engine.
set -euo pipefail

if [[ $# != 2 ]]; then
    printf 'Usage: %s T3_SOURCE_TREE NEW_OUTPUT_DIRECTORY\n' "$0" >&2
    exit 2
fi

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$1" && pwd)"
build="$repo/build"
if [[ "$(git -C "$repo" rev-parse --short=8 HEAD)" != 8056a8df ]]; then
    printf 'The pulse contract uses the T3 engine at commit 8056a8df.\n' >&2
    exit 2
fi
fc="$(sed -n 's/^CMAKE_Fortran_COMPILER:[^=]*=//p' "$build/CMakeCache.txt")"
mkdir "$2"
out="$(cd "$2" && pwd)"
mkdir "$out/mod" "$out/run"
flags=(-ffree-line-length-none -fcheck=all -finit-real=snan -ffpe-trap=invalid,zero,overflow)
cd "$out/run"
"$fc" "${flags[@]}" -J"$out/mod" -I"$build/mod" -c "$repo/Plant/CROPGRO/RootNUptake.f90" -o "$out/mod/RootNUptake.o"
"$fc" "${flags[@]}" -J"$out/mod" -I"$build/mod" -I"$out/mod" -c "$repo/Plant/CROPGRO/CG_Nitrogen.f90" -o "$out/mod/CG_Nitrogen.o"
"$fc" "${flags[@]}" -I"$build/mod" -I"$out/mod" "$here/rnk_pulse_test.f90" \
    "$out/mod/CG_Nitrogen.o" "$out/mod/RootNUptake.o" -o "$out/mod/rnk_pulse_test"
cat > NIntegration.nml <<'EOF'
&NINTEGRATION
 ni_stage=5, root_mode=2,
 q_no3_max=.003, q_nh4_max=.0001,
 assim_no3_v=.003, assim_nh4_v=.006, assim_no3_k=.001, assim_nh4_k=.00005,
 root_v=.0002, root_k=10., diffusion_k=.005, pool_beta=1.,
 leaf_a=.042, leaf_b=.30, stem_a=.025, stem_b=.35,
 min_ratio=.40, max_ratio=1.25, photo_floor=.05, photo_gamma=1., growth_tau=2.,
 state_timing=1, pods_n_state=1, budget_revision=1, c4_budget=1, leaf_coupling=1, c4_photo=1,
 remob_mode=1, luxury_priority=1, remob_tau=8., protect_beta=0.5, slow_ratio=3.
/
&ROOTNUPTAKE
 rnk_mode=1,
 rnk_km_high=0.28, 0.5,
 rnk_km_low=35.0, 50.0,
 rnk_vmax_high=0.0003, 0.0004,
 rnk_vmax_low=0.0015, 0.0020,
 rnk_kd=0.0, 1.0,
 rnk_residual=0.25, 0.50,
 rnk_nh4_diff=0.005
/
EOF
unset DSSAT_N_CONFIG
"$out/mod/rnk_pulse_test"
