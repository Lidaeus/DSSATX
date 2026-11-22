#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 2 ]]; then
    printf 'Usage: %s CMAKE_BUILD_DIRECTORY NEW_OUTPUT_DIRECTORY\n' "$0" >&2
    exit 2
fi
here="$(cd "$(dirname "$0")" && pwd)"
build="$(cd "$1" && pwd)"
objects="$build/CMakeFiles/dscsm048.dir"
compiler="$(sed -n 's/^CMAKE_Fortran_COMPILER:[^=]*=//p' "$build/CMakeCache.txt")"
mkdir "$2"
cd "$2"
cat "$here/../p1_4864/p1_smoke.nml" "$here/../source/RootNUptake.nml.template" > NIntegration.nml
"$compiler" -ffree-line-length-none -fcheck=all -I"$build/mod" "$here/rnk_buffer_pulse.f90" \
    "$objects"/Plant/CROPGRO/{CG_Nitrogen,CG_RootNUptakeAdapter,RootNUptake}.f90.o \
    "$objects"/Utilities/CG_P0Trace.f90.o -o rnk_buffer_pulse
unset DSSAT_N_CONFIG DSSAT_P0_TRACE
./rnk_buffer_pulse > pulse.csv
