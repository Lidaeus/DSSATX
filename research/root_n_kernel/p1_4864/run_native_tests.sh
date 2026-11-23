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
