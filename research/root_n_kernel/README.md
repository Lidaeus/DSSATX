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
and daily extractable stock. Both regulate membrane capacity with the
same shoot N status and apply no additional triangular wetness factor. The model
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

### Shoot N status and root feedback

At day close, sum actual functional organic N in leaves and stems. The
sum excludes inorganic Q and subtracts the explicit organic reserve when
that reserve mode is enabled. Each reference stock is the sum of the
respective organ dry mass times its minimum, critical, or upper reference
concentration. The signed index `psi` is zero at the critical stock.
Divide the signed difference from critical by the minimum-to-critical
span for a deficiency and the critical-to-upper span for a surplus.
Clamp the index to [-1, 1]. These references do not alter organ inventory.

The common root kernel opens the day with the last committed shoot state
from the same treatment. It multiplies both affinity capacities for both
N species by `exp(-pool_beta * max(0, psi)**2)`. Deficiency, critical
status, and missing references give a neutral factor of one. The
unavailable state covers initialization before the first committed
state and runs that do not enable organ curves. This reuses the
`pool_beta` coefficient. The legacy root path continues to use that
coefficient with inorganic pool occupancy.

For both radial transport modes, the candidate is the layer supply
computed before admission into the plant inorganic pool. For each ion,
let P be the total candidate over the day, K its pool capacity, and Q
the stock at admission (after any early assimilation). The effective
inflow rate decreases with the unoccupied fraction: dQ/dt = P(t)(1-Q/K),
where P(t) is the candidate rate. With fixed capacity and no concurrent
withdrawals within this split, the accepted total is
(K-Q)(1-exp(-P/K)), distributed in proportion to layer candidates.
It tends to the available space for very large supply, retains a
supply response before saturation, and cannot exceed either the
candidate or the space. It uses the existing pool capacities and
leaves actual soil debit in the existing settlement path.

Use `luxury_priority=0` in the shared NIntegration configuration for
the paired study. This uses the existing demand budget that includes
old-tissue refill and allows growth surplus to refill leaves and
stems toward the upper reference. Assimilation remains limited by
substrate, kinetics and available carbon. With `luxury_priority=1`,
core refill targets the critical reference and additional assimilation
uses the later discretionary carbon budget. Keep the same setting in
both arms.

With the shared revised growth and refill path, new leaf and stem
tissue can use additional nitrogen above the critical reference.
Freeze the inorganic stock fraction at day open:
`fill=(QNO3+QNH4)/[(q_no3_max+q_nh4_max)*sum(carrier)]`.
Use the same bounded fraction in the forecast and allocation of new
growth: `target=critical+fill*(upper-critical)`.
The upper band is an optional receiver for organic N during new
growth, not a concentration assigned to existing tissue. Native
minimum construction uses the critical composition as its reference.
Actual incorporation still requires finite assimilation, carbon, and
accepted new tissue. The reference curves and the definition of `psi`
are independent of this target. Explicit separate reserve, joint
acceptance, or independent leaf C/N modes retain their own rules.
With P0 tracing, `rnk_tissue_target` records the frozen fraction,
organ references and the two new-tissue targets.

With `DSSAT_P0_TRACE=1`, `rnk_psi_end` reports the day-close stock,
reference stocks and signed state, and `rnk_psi_feedback` reports the
state, its source date and the multiplier used by the root kernel.
The layer ledger retains the same schema.

### S1-inspired organic buffer and NSTFAC

Run `p1_4864/replay_local.py --organic-buffer` to select the paired
organic buffer study. The active recipe sets `reserve_mode=2`,
`common_acceptance=1`, and `luxury_priority=1`. The recipe writes
NSTFAC=0.60 into the prepared TMGRO048.SPE for each case. Use
`--nstfac` to vary it in a separate replay. Frozen source inputs
and the default replay stay available for earlier studies.

Each leaf and stem organ has functional organic N and a remobilizable
reserve. The reserve is part of organ organic N. The forecast requests
N for new tissue, a fraction of the functional deficit, and a fraction
of the reserve vacancy. The existing joint allocation shares actual
carbon and N among reproductive growth, new vegetative tissue, and
functional repair. Remaining assimilation capacity and discretionary
carbon can fill bounded leaf and stem reserves after those uses.
When N is short, the existing donor ledger uses remobilizable reserve
before drawing more slowly from functional tissue. Fruit composition
and the stateful call count of PODS are preserved.

The root transport models still provide species- and layer-specific
candidates. The candidates fund today's finite assimilation with
carbon cost. The host can reject provisional assimilation; the
substrate then becomes available to eligible reserves on the same
day. Only N committed to organic receivers is charged to the soil.
There is no standing inorganic stock, no day-to-day mineral buffer
capacity, and no concentration surcharge on new tissue based on that
stock. The root `psi` in this mode reads total leaf/stem organic N
including reserves, with the upper reference equal to the critical
stock plus nominal reserve capacity. The organ growth, photosynthesis
and senescence signals use functional N according to their existing
rules. `rnk_psi_organic` identifies the quantities used for root
feedback. Modes 0 and 1 retain the inorganic buffer.

NSTFAC only controls the native fallback in VEGGR, through
`SUPPN/(NDMNEW*NSTFAC)`. The active daily feedback already calls
`NI_GROWTH()`, and common acceptance uses that state for its growth
budget. To retire NSTFAC for the research path, first audit its
remaining calls during initialization and on treatment reset. Then
use neutral nitrogen partitioning before a valid state is committed,
and the existing bounded functional-N signal from the previous day
after initialization. Retain separate water and phosphorus stress
and the actual C/N limits on biomass. Verify the replacement with
low-N and resupply runs and repeat the NSTFAC sensitivity check before
dropping it from any research input specification.

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
