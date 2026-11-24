#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 1 ]]; then
    printf 'Usage: %s NEW_OUTPUT_DIRECTORY\n' "$0" >&2
    exit 2
fi
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
fc="${FC:-gfortran}"
mkdir "$1"
out="$(cd "$1" && pwd)"
flags=(-ffree-line-length-none -fcheck=all -ffpe-trap=invalid,zero,overflow -J"$out" -I"$out")
"$fc" "${flags[@]}" -c "$root/Plant/CROPGRO/RootNUptake.f90" -o "$out/kernel.o"
"$fc" "${flags[@]}" "$here/../tests/test_root_n_uptake.f90" "$out/kernel.o" -o "$out/test_a"
"$out/test_a"

# The adapter uses control records as a compile-time interface.
for module in OSDefsLINUX CSMVersion ModuleDefs; do
    "$fc" "${flags[@]}" -ffixed-line-length-none -std=legacy -fsyntax-only "$root/Utilities/$module.for"
done
"$fc" "${flags[@]}" -c "$root/Plant/CROPGRO/CG_RootNUptakeAdapter.f90" -o "$out/adapter.o"
"$fc" "${flags[@]}" "$here/../tests/test_rnk_reload.f90" "$out/kernel.o" "$out/adapter.o" -o "$out/test_rnk_reload"
(cd "$out" && ./test_rnk_reload)

"$fc" "${flags[@]}" -c "$root/Utilities/CG_P0Trace.f90" -o "$out/trace.o"
"$fc" "${flags[@]}" -c "$root/Plant/CROPGRO/CG_Nitrogen.f90" -o "$out/nitrogen.o"
"$fc" "${flags[@]}" "$here/../tests/test_f5_refill.f90" \
    "$out/kernel.o" "$out/adapter.o" "$out/trace.o" "$out/nitrogen.o" -o "$out/test_f5"
"$out/test_f5"

base="$root/research/calibration/results/26sp_80x4/configs/NIntegration.nml"
check_f5_config() {
    local name="$1" settings="$2" expected="$3" root_mode="${4:-1}"
    awk -v settings="$settings" -v root_mode="$root_mode" '
        { sub(/rnk_mode=1,/, "rnk_mode=" root_mode ","); print }
        /^&NINTEGRATION/ { print " " settings }
    ' \
        "$base" > "$out/$name.nml"
    if (cd "$out" && DSSAT_N_CONFIG="$out/$name.nml" ./test_f5 load) > "$out/$name.log" 2>&1; then
        if [[ -n "$expected" ]]; then
            printf 'Invalid F5 settings accepted: %s\n' "$name" >&2
            return 1
        fi
    elif [[ -z "$expected" ]] || ! grep -Fq "$expected" "$out/$name.log"; then
        cat "$out/$name.log" >&2
        return 1
    fi
}
check_f5_config f5_valid 'refill_substrate_target=1, refill_substrate_km=.05,' ''
check_f5_config f5_linear 'refill_substrate_target=1, refill_substrate_km=0.,' ''
check_f5_config f5_conflict 'refill_substrate_target=1, org_reserve_cap=.015,.010,' 'cannot be combined with org_reserve_cap'
check_f5_config f5_disabled_km 'refill_substrate_target=0, refill_substrate_km=.05,' 'requires refill_substrate_target=1'
check_f5_config f5_negative_km 'refill_substrate_target=1, refill_substrate_km=-.05,' 'invalid refill_substrate_km'
check_f5_config f5_nonfinite_km 'refill_substrate_target=1, refill_substrate_km=NaN,' 'invalid refill_substrate_km'
check_f5_config f5_unknown_mode 'refill_substrate_target=2,' 'refill_substrate_target must be 0 or 1'
check_f5_config f5_wrong_route 'refill_substrate_target=1,' 'requires the B4 persistent inorganic route' 0
check_f5_config lux_legacy 'lux_veg_mode=1, lux_xfrt_drop=.50,' ''
check_f5_config lux_hill 'lux_veg_mode=2, lux_psi_threshold=.76, lux_hill_k=.04, lux_xfrt_drop=.50,' ''
check_f5_config lux_wrong_mode 'lux_veg_mode=3,' 'lux_veg_mode must be 0'
check_f5_config lux_zero_width 'lux_veg_mode=2, lux_hill_k=0.,' 'lux_hill_k must be finite and positive'
check_f5_config lux_negative_width 'lux_veg_mode=2, lux_hill_k=-.1,' 'lux_hill_k must be finite and positive'
check_f5_config lux_nonfinite_width 'lux_veg_mode=2, lux_hill_k=NaN,' 'lux_hill_k must be finite and positive'
check_f5_config lux_wrong_route 'lux_veg_mode=2,' 'substrate-fill luxury response requires' 0
printf 'F5 and luxury namelist validation: 15 cases passed\n'
