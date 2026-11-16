# DSSATX research workspace

Create the suite's own environment from the DSSATX checkout:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r research/requirements.txt
source .venv/bin/activate
```

Install `pestpp-ies` as a system tool or give `ies.py` its executable path.
On macOS the Fortran build uses CMake, Ninja and gfortran.

Build the 4.8.6.4 engine from this checkout. This branch's native and
whole-crop validation entry points are documented in the
[root nitrogen guide](research/root_n_kernel/README.md).

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_Fortran_COMPILER=gfortran -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build build --target dscsm048
bash research/root_n_kernel/p1_4864/run_native_tests.sh build/native-p1
```

- `main` follows the 4.8.6.4 engine through the macOS and V7 work.
- `base-4.8.6.4` identifies the upstream comparison baseline.
- `research/root-n-4864` preserves the A/B root nitrogen development and P1 integration. It has its own tests and receipts.
- `legacy/v15-s4` preserves the frozen 4.8.2.0 source with the V15 S3/S4 overlays.
- `compat/4.8.5-macos` holds the two gfortran-format repairs used by spring58. Its historical macOS runtime also uses the 4.8.5.62 CO₂ table.

[Mechanism diagnostics](research/n_diagnostics/README.md) and the
[PEST++ IES runner](research/calibration/README.md) consume explicit case
inputs. Use `python research/package_engine.py --help` to stage an engine
and standard data for other projects. The generated `engine.json` records
the declared source commit and the staged runtime checksums.

[Historical workflows and original run provenance](research/HISTORICAL_WORKFLOWS.md).
