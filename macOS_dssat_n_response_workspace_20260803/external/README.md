# External dependencies

Place the macOS build of the DSSAT/CRGRO048 executable under `external/dssat/` and the corresponding DSSAT source under `external/dssat_source/`.

The project runner accepts the executable through:

```bash
export DSSAT_EXE_PATH="$PWD/external/dssat/DSCSM048"
```

Windows `.exe` files from the original project are intentionally not copied here because they cannot run natively on macOS.
