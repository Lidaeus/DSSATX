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
