#!/bin/bash
# run_native_tests.sh -- compile and run the v15_s3_v4root NUPTAK property
# tests against the REAL production objects (no mirrored kernel math
# beyond the bound formulas used in assertions).
#
# Usage: run_native_tests.sh [source_tree]   (default: vnext_v15_s1 frozen
# tree; NUPTAK.for is taken from THIS variant directory)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"            # subprojects/critical_n
SRC="${1:-$ROOT/vnext_v15_s1/source}"
FC="${FC:-gfortran}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/v4root-tests.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

cd "$WORK"
echo "[native-tests] work=$WORK"
FFLAGS="-ffixed-line-length-none -ffree-line-length-none"
"$FC" $FFLAGS -c "$SRC/Utilities/CSMVersion.for" -o CSMVersion.o
"$FC" $FFLAGS -c "$SRC/Utilities/OSDefsLINUX.for" -o OSDefsLINUX.o
"$FC" $FFLAGS -c "$SRC/Utilities/ModuleDefs.for" -o ModuleDefs.o
"$FC" $FFLAGS -c "$SRC/Plant/CROPGRO/N_BUFFER_V2.f90" -o N_BUFFER_V2.o
"$FC" $FFLAGS -c "$HERE/NUPTAK.for" -o NUPTAK.o
"$FC" $FFLAGS -c "$HERE/native_root_tests.f90" -o native_root_tests.o
"$FC" CSMVersion.o OSDefsLINUX.o ModuleDefs.o N_BUFFER_V2.o NUPTAK.o native_root_tests.o -o native_root_tests

./native_root_tests
./native_root_tests lux
