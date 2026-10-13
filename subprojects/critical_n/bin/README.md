# Subproject critical_n Binaries Directory

This directory hosts compiled standalone DSSAT executables for sandboxed verification:
- `dscsm048_vanilla.exe`: Baseline compiled DSSAT v4.8 without Scheme B modifications.
- `dscsm048_cnc.exe`: Customized DSSAT v4.8 compiled with Scheme B Critical Nitrogen Dilution & Senescence Limiter Fortran patches.

## Compilation Instructions
To build or re-verify these executables, run:
```bash
python subprojects/critical_n/scripts/build_and_verify_dssat.py
```
This script dynamically detects the local toolchain (gfortran, cmake, ninja), patches DSSAT sources in a sandbox, compiles both executables, and runs regression tests.
