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
# The transient comparator is pinned to the previous research implementation.
git -C "$root" show 929914ab:Plant/CROPGRO/RootNUptake.f90 |
    sed -E 's/(module )RootNUptake/\1HistoricalRootNUptake/' > "$out/HistoricalRootNUptake.f90"
cd "$out"
"$fc" -O2 -ffree-line-length-none -fcheck=all -ffpe-trap=invalid,zero,overflow \
    HistoricalRootNUptake.f90 "$root/Plant/CROPGRO/RootNUptake.f90" \
    "$here/nh4_penetration_probe.f90" -o nh4_penetration_probe
./nh4_penetration_probe > penetration.csv
