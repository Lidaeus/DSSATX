# 4.8.6.4 root nitrogen A/B and P1

The P1 changes from Tomato_Cal `6431551c` were applied to `8056a8df`.
Tag `archive/root-n-t3` records that T3 baseline. The original verification
receipt describes its Windows tests and archived paths.

Build both engines with CMake and use the checked-in case and engineering
namelist for a local 26SP audit. The T3 reference can be built from the
`archive/root-n-t3` tag in a temporary Git worktree. Run the native A/B tests
from the P1 checkout before comparing whole-crop runs.

```sh
bash research/root_n_kernel/p1_4864/run_native_tests.sh build/native-p1
python research/root_n_kernel/p1_4864/replay_local.py \
  --engine build/bin/dscsm048 --t3-engine /path/to/t3/dscsm048 \
  --out build/p1-audit
```

The verifier audits candidate/accepted/actual deduction and checks the
off-mode CSV bytes against T3. This case checks integration and conservation.
The historical 25SP compatibility replay has a separate source receipt.

The two-day pulse check targets the original T3 timing. Build the
`archive/root-n-t3` worktree at `<t3>/build`, then run:

```sh
bash research/root_n_kernel/tests/run_pulse_test.sh /path/to/t3 build/t3-pulse
```

Use the P1 replay above for the later cross-day debit contract. The historical
Windows launchers and verification paths are retained at
`archive/pre-standalone-root-n`.
