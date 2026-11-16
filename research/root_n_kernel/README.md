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

## Paired rhizosphere transport comparison

Use the same DSSATX executable and one case for both transport methods:

```sh
python research/root_n_kernel/p1_4864/replay_local.py \
  --engine build/bin/dscsm048 --t3-engine /path/to/t3/dscsm048 \
  --radial-cells 16 --out build/paired-transport-26sp
```

The runner stages identical input files and changes only `rnk_mode` between
the two active runs. Both use the equilibrium pore-water concentration at
the pre-extraction water content, the same exchangeable ammonium
partition, and the same species-specific dual-affinity membrane kinetics
and daily extractable stock. Both use the existing plant N feedback without
the legacy triangular wetness factor on membrane capacity. The model
holds the Millington–Quirk effective diffusion coefficient fixed at the
same extraction midpoint for the day in both methods. DSSAT `SAT` supplies
porosity for diffusion. The concentration calculation uses the actual
liquid water content. The fixed diffusion and membrane parameters are
engineering inputs.

Mode 1 uses a steady equivalent radial diffusion conductance with an
explicit bulk mass-flow term. Mode 2 integrates radial advection and
diffusion inside the same geometry, updating local liquid concentration
during the day. These are experimental alternatives in one model. The
comparison keeps the DSSAT plant acceptance and soil debit schedule intact.

Append the production template to the file containing `&NINTEGRATION`.
Mode 1 is the production default for this 26SP decision. Mode 2 is a research
comparison using 24 nominal substeps and either 8 cells (default for mode 2)
or 16 cells (comparison tier). Use `rnk_radial_cells=16` for the latter.
The 26SP wall-time and CPU measurements used three interleaved complete runs
per configuration with P0 tracing disabled. The new engine always uses the
common inputs in both active modes. Historical P1 input switches belong to
the historical P1 checkout. Mode 0 still bypasses the common kernel. The
ledger retains its mode and shared-input columns and the bulk diffusion value. In the paired comparison,
`c_bulk_mgN_L` is the initial equilibrium concentration in both methods.
Mode 1 reports the steady surface solution and equivalent diffusion
flux. Mode 2 reports the end-of-day concentration of its innermost cell
and the integrated diffusion across the first internal face.

The transient solver still initializes each day from the layer inventory.
With zero uptake of water and zero diffusion, the initially accessible
mass in the innermost cell can contribute a small, mesh-dependent uptake.
This is a documented limitation. Hydraulic lift is a separate water and
solute redistribution process for future investigation. The compiled
kernel lives in `Plant/CROPGRO/RootNUptake.f90`; the copy under
`research/root_n_kernel/source` preserves the T3 delivery.

### Resolution and porosity probes

`run_native_tests.sh` also writes `transport_resolution.csv` and
`transport_porosity.csv` to its new output directory. The transient probe
crosses 8, 16 and 32 radial cells with 24, 48 and 96 nominal substeps,
using the existing logarithmically spaced faces. It covers a normal layer,
a dry layer, and an extremely dry day followed by rewetting. The rewet
case starts with the inventory left on the dry day and adds only water.
The radial profile is homogenized at the day boundary as in the engine.

Both production formulations still use DSSAT `SAT` for porosity. The
single-layer sensitivity probe uses the 26SP 80–100 cm layer's bulk density
and `SAT` as inputs. Its density-derived `POROS` is about 0.445, compared
with `SAT=0.498`. The alternate value is used only in the probe. No runtime
porosity selector is needed.

### Paired ledger diagnostics

For the steady formulation with positive diffusion,
`steady_residual_gN_m2` is the sum of the bulk mass-flow and equivalent
diffusive supply minus the stock-limited root boundary uptake.
`zero_diffusion=1` identifies an evaluated zero-diffusion case.
Unavailable residuals and concentrations use `-99`.

For transient transport, pair `c_bulk_end_mgN_L` with the existing
`c_root_mgN_L` for the same end-of-day time. The transient layer mean
comes from total remaining radial mass divided by the layer's end-of-day
water-plus-sorption capacity. `c_bulk_mean_mgN_L` and
`c_root_mean_mgN_L` are duration-weighted concentrations over accepted
substeps. The steady means equal the constant concentrations used in its
daily balance. The transient concentrations refer to the transport solve
before the plant's acceptance and settlement stages.

`hats_candidate_gN_m2` and `lats_candidate_gN_m2` partition the transport
candidate. At an active stock limit, the allowed uptake is split using
each term's share of the membrane rate at the solved concentration.
The sum can differ from the engine's single-precision candidate by
rounding. These are modeled contributions to candidate uptake.

Both initial aqueous partitioning and transient cell storage use
`theta + bulk_density * Kd`. Using that storage term already represents
equilibrium sorption retardation. Dividing the bulk diffusion coefficient
by the same term again would apply it twice. The steady formulation
uses the same partition for its initial bulk concentration. Its
conductance is an equilibrium flux law without a transient storage term.

### 26SP selection

Use `compare_transport.py` with the steady case, the 8-cell transient case
and the 16-cell transient case. It joins by run, day, layer and N species.
Moisture uses the 16-cell transient midpoint relative to DSSAT LL. A half-LL
cutoff labels extreme dryness for reporting only. Early means DAP 0–30.
An irrigation or N application window includes the event day and the next
two days. Low RLV is the bottom quartile of positive RLV in the transient
16-cell layer/day records. The reported absolute percentage divides the sum of absolute
layer/day differences by the sum of the corresponding method means.
The grid comparison is an engineering sensitivity, and includes feedback
from separate whole-crop runs at the two resolutions.

For estimated radial relaxation, the outer cylinder radius uses RLV and
the configured root radius. Bulk density is recovered from the reserved
mass on rows above the store floor. The resulting times are descriptive
time scales. Mean versus end-of-day ratios compare contemporaneous
concentration definitions, and HATS shares describe modeled partitioning.

The production choice is based on the 26SP nitrate-dominated case and
near-equivalent whole-crop trajectories. The two modes differ materially
for ammonium supply, so this test gives no general equivalence result
for ammonium-dominated environments.
