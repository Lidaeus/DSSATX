#!/bin/bash
# run_native_tests.sh -- compile and run the v15_s4_nstate fused plant-N
# state property tests against the REAL variant N_BUFFER_V2 module.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
FC="${FC:-gfortran}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/nstate-tests.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

cd "$WORK"
echo "[nstate-tests] work=$WORK"
"$FC" -c "$HERE/N_BUFFER_V2.f90" -o N_BUFFER_V2.o
"$FC" -c "$HERE/native_nstate_tests.f90" -o native_nstate_tests.o
"$FC" N_BUFFER_V2.o native_nstate_tests.o -o native_nstate_tests

./native_nstate_tests
