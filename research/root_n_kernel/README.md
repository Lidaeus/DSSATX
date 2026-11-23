# 4.8.6.4 steady root nitrogen

The P1 changes from Tomato_Cal `6431551c` were applied to `8056a8df`.
Tag `archive/root-n-t3` records that T3 baseline. The original verification
receipt describes its Windows tests and archived paths.

Build both engines with CMake and use the checked-in case and engineering
namelist for a local 26SP audit. The T3 reference can be built from the
`archive/root-n-t3` tag in a temporary Git worktree. Run the native steady-kernel tests
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

## Steady rhizosphere transport

Append `source/RootNUptake.nml.template` to the file containing
`&NINTEGRATION`. The active kernel uses `rnk_mode=1`. Use `rnk_mode=0`
or omit the group to use the historical integration route. For the
historical two-transport study, check out `929914ab` in a separate worktree.

The steady kernel computes the equilibrium pore-water concentration using
pre-extraction water and the exchangeable stock. Ammonium's water plus
sorption capacity is `theta + bulk_density * Kd`. DSSAT `SAT` supplies
porosity in Millington–Quirk diffusion, evaluated at the water extraction
midpoint, computed with the layer depth from the SPAM water snapshot.
Concentration and root geometry use the crop-side soil layer depth. Set both species' parameter provenance with `rnk_source_tag`.
Older steady configurations that omit the field use `unspecified`.

When mass flow can meet membrane uptake evaluated at bulk concentration,
root and bulk concentrations are equal and diffusion is zero. Otherwise,
the kernel bisects the concentration interval from zero to bulk to balance
membrane uptake against mass flow plus inward diffusive supply. The
extractable inventory caps the resulting uptake. At or below the residual
stock concentration, there is no uptake and the equilibrium is skipped.

The pure kernel lives in `Plant/CROPGRO/RootNUptake.f90`.
`CG_RootNUptakeAdapter` translates layer inputs and holds the source day's
diagnostics until the following soil debit. This keeps plant N allocation
and shoot feedback in `CG_Nitrogen`.

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

The candidate is the layer supply
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

Use `luxury_priority=0` to include optional refill above the critical
reference in the NIntegration demand budget. This uses the existing demand budget that includes
old-tissue refill and allows growth surplus to refill leaves and
stems toward the upper reference. Assimilation remains limited by
substrate, kinetics and available carbon. With `luxury_priority=1`,
core refill targets the critical reference and additional assimilation
uses the later discretionary carbon budget.

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

Run `p1_4864/replay_local.py --organic-buffer` to select the steady
organic buffer study. The active recipe sets `reserve_mode=2`,
`common_acceptance=1`, and `luxury_priority=1`. The recipe writes
NSTFAC=0.60 into the prepared TMGRO048.SPE for each case. Use
`--nstfac` to vary it in a separate replay. Frozen source inputs
and the default replay stay available for earlier studies.

Each leaf and stem organ has functional organic N and a remobilizable
reserve. The reserve is part of organ organic N. At organ allocation,
first estimate how much structural growth and functional repair the
available carbon and N can support. Then use those feasible demands
when deciding how much optional N can enter new tissue or organic
reserve. Both uses spend the same carbon and N budget. Low supply
reduces the optional N allocation before the minimum composition of
new tissue changes. The host executes PODS and growth once.

Today's root substrate is the sum of the candidates after root/soil
transport. The optional new leaf and stem composition uses the fraction
`substrate / (substrate + feasible structural N demand)` of the
critical-to-upper reference band. This is a bounded allocation rule,
not a measured transporter saturation curve. The critical concentrations
used for function and the minimum composition remain independent of it.
Live reserve replenishment is bounded by organ capacity and daily
fill rate. Only accepted supply after actual growth and repair can fill
reserve, and unused internal donor credit is reconciled separately.

The root candidates fund today's finite assimilation with carbon cost.
Only N committed to organic receivers is charged to the soil; there
is no standing inorganic stock. This mode uses two signed distances
from the respective reference bands. Root uptake reads total leaf/stem
organic N, including reserves. Growth uses the functional N stock
without reserve; the daily target is `1 + min(0, psi_functional)`,
using the existing smoothing time. Photosynthesis uses the leaf-local
functional deficit with the S1 response `1 - deficit**2.5`, keeping
DSSAT's sun/shade concentration gradient. Positive `psi` has no growth
penalty or bonus. `rnk_psi_organic` and `rnk_psi_growth` trace stocks
and growth state separately. Modes 0 and 1 retain the inorganic buffer.

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

### Layer ledger

`steady_residual_gN_m2` measures the bisection error of the potential
balance between mass flow plus diffusion and the membrane rate.
It retains that meaning on a stock-capped layer. Actual mass closure is
verified separately against plant settlement and soil debit. A residual
of `-99` marks a branch without a bisection balance, including
`RNK_BRANCH_MEMBRANE`. `zero_diffusion=1` identifies an evaluated zero-diffusion
case. The concentration mean columns reproduce the steady concentrations
when the kernel evaluates them. The three former transient-only fields
remain in the 35-column CSV for historical readers, with zeros in the
two radial flux/residual columns and `-99` in the end-of-day bulk column.

`hats_candidate_gN_m2` and `lats_candidate_gN_m2` partition candidate
uptake after the stock cap according to their shares of the membrane rate.
The candidate supplied to the engine is converted to single precision.
Actual soil debit is checked against the settled plant uptake with
a tolerance of `1e-6 * max(1, abs(settled))` in g N/m² per layer and ion.
Run identity, layer count and ordering are checked separately.

The first ledger write in a DSSAT process replaces the previous file.
At each season end the adapter records any pending final-day uptake and
closes the file. Subsequent treatments append to the same batch ledger.

### Optional ammonium penetration radius

Set `rnk_penetration_coeff=1.5` to run the offline candidate in the
steady kernel. The production template uses zero. The 1.5 setting is an explicit
research option for ammonium-dominated or strongly sorbing soils. Positive values
shorten the equivalent diffusion radius only for ammonium with positive
sorption and effective diffusion. The apparent diffusivity divides
`D_bulk` by `theta_mid + bulk_density * Kd` solely in the one-day
penetration length. The steady conductance itself uses `D_bulk`.
The stock cap, mass-flow term and membrane kinetics use the same inputs.

```sh
bash research/root_n_kernel/tests/run_penetration_benchmark.sh build/nh4-benchmark
bash research/root_n_kernel/tests/run_buffer_pulse.sh build build/steady-pulse
```

The offline benchmark builds the historical 32-cell and 96-substep
reference in a private output directory. Cases include four moisture
conditions, three root densities and three sorption coefficients.
Its nitrate check compares candidates bit for bit across the coefficient
sweep. Positive penetration coefficients improve the strong-sorption
and dry subsets near 1.5, with a larger positive signed bias across the
other cases. The correction increases diffusion conductance for a
shortened shell. A case that already overpredicts uptake can retain or
increase its bias.

The production steady run carries unassimilated nitrogen into the next day
within its nitrate and ammonium capacities. The organic-buffer control
(`--organic-buffer`, `reserve_mode=2`) refunds and
cancels any unsettled provisional uptake and closes both inorganic
pools at zero. The carbon-limitation pulse tests the persistent store.

The season audit separately checks published layer uptake, next-day
soil debit, pool capacity and N assimilation charges. For the combined
season N balance, initial seed N is included in opening plant stocks.
Cumulative harvest and other exported organic N enter through the
organic loss ledger. Inorganic litter and the final-day plant uptake
pending at the soil boundary are explicit terms. At nitrogen settlement,
the audit requires a finite, nonnegative `PGAVL`. It also requires one
actual carbon cash entry per plant nitrogen day, with an absolute
`CH2O_residual` below `1e-5` g CH₂O/m² each day. The minimum predicted
`PGAVL` after vegetative growth and carbohydrate storage is reported for
regression monitoring.

### TM deficiency response ablation

`source/TMDeficiency.nml.template` uses the 26SP working
`photo_sln_ref=1.05` g N/m² leaf for TM with `MEPHO='L'`. The candidate
band is 0.95–1.25 g N/m² leaf. Keep the anchor fixed during cultivar IES
and reassess it with independent leaf photosynthesis–SLN observations
when transferring it to another species. The shared root route uses the
kinetics in `&ROOTNUPTAKE` and the feedback setting `pool_beta`. The steady root
transport, persistent inorganic store, organ curves, day-state timing, pod
response, and revised C/N accounting are common to the ablation. B1 uses the
native leaf photosynthesis via the `photo_legacy=1` ablation switch. B2 adds
protected remobilization (rate limits 0.01 and 0.001 d⁻¹). B3 replaces the
light-response nitrogen factors with the existing fixed-reference functional
SLN curve. B4a adds leaf-turnover coupling, and B4 adds single-acceptance
C/N leaf expansion. B4 retains nitrogen-induced root allocation and caps
the leaf request by the smaller of its actual allocation and the N-state
ceiling evaluated at otherwise identical neutral-N partition. The replay
explicitly uses 0.18 g N/m² leaf for the historical engineering control.
The daily senescence coefficient (0.01) and expansion shape (2) are
engineering priors.

Run the numerical and same-directory regression by configuring CMake with
`-DDSSAT_TM_DEFICIENCY_TEST=ON`, building, and running CTest. To keep detailed
ledgers, 26SP observations, nutrient-gradient checks, and paired cessation
outputs, run the full replay from the repository root.

```sh
python3 research/root_n_kernel/p1_4864/replay_shoot.py \
  --engine build/bin/dscsm048 --out build/tm-deficiency-replay
```

The field and matched-soil checks report strict N0→N3 slope criteria
separately from conservation. The matched comparison uses each water
regime's N2 soil-analysis and initial-condition levels for all four doses.
The cessation input omits N-only fertilizer starting at DOY 152. Soil
mineral N and ongoing root uptake are still simulated. The audit compares
canopy gross photosynthesis and gross photosynthesis less whole-plant
maintenance, since the model's daily canopy output is gross photosynthesis.
The 26SP field replay saturates the SLN curve at 0.18, and the 0.70
sensitivity run exercises its unsaturated range. The candidate remains
under evaluation because the matched treatments still fail the strict
biomass and fresh-yield gradient criteria.

### Fixed SLN scan and 26SP root N interruption

Use the isolated diagnostic build to scan the B3 and B4 fixed functional SLN
reference and measure the carbon balance at entry to PODS. The build copies an
explicit Git revision, adds probes to that copy, and compiles a separate engine.
The 20-day pulse begins at 26SP DAP 50 and withholds both forms of new nitrogen
at crop acceptance. Soil pools, potential root transport, previously committed
soil debits, and assimilation from the standing inorganic pool are still
computed. The pulse is only available in this diagnostic build.

```sh
python3 research/root_n_kernel/p1_4864/build_sln_probe.py \
  --ref HEAD --out build/26sp-sln-probe
python3 research/root_n_kernel/p1_4864/replay_sln_pulse.py \
  --engine build/26sp-sln-probe/engine/bin/dscsm048 \
  --out build/26sp-sln-replay --scan-only
```

The matched-soil run writes `late_carbon_paired.csv` with daily W3 N0, N1,
and N0−N1 values for days 181–198. The RSP submitted before PODS and the
settled assimilation expenditure are both recorded. `pulse_paired.csv`
contains uninterrupted and interrupted daily trajectories. `receipt.json`
contains nitrogen and carbon audits, saturation counts and the first day
each paired signal exceeds a 5% difference. The updated scan tests
0.95, 1.05, 1.15, 1.20 and 1.25 within the candidate band, with 0.90
and 1.35 for sensitivity and 0.18 as the frozen control. Functional SLN
percentiles and saturation fractions summarize solver evaluations.
Omit `--scan-only` to run the pulse at 1.05 or set `--pulse-ref` to
another value in the scan. To reproduce the original experiment, build
`--ref 07f1be5f` and replay with `--historical`.

The reference curve uses standing leaf plus stem dry mass in t/ha.
Using the TM0008 standard `SLAVR=208` cm²/g as an illustrative conversion
gives a specific leaf mass of 48.1 g/m². At 1, 3 and 5 t/ha, the critical
functional SLN ceilings on that mass basis are about 1.21, 0.87 and
0.75 g N/m² leaf. At 1 t/ha and the species `SLWREF` basis of 28 g/m²,
the corresponding estimate is 0.706. The model uses the actual sunlit
and shaded leaf mass per area and carbohydrate fraction at each call.

With the 26SP root-partition fixes, the 0.18 control had a simulated
functional SLN 5th–95th percentile interval of 0.65–1.10 g N/m² leaf.
At 1.05, 81.3% of B4 calls were below saturation. The late W3 mean
factors were 0.958 for N0 and 0.935 for N3. The 1.05 working anchor
exercises the response with a smaller increase in field fresh-yield
RMSE than 1.15. The N0/N1 yield reversal and the late leaf-level factor
ordering remain open validation targets.

In the original matched W3 replay, 1.50 removed the final N0/N1 yield reversal in
B4 by 0.074 t/ha. B3 retained the reversal, and B4 still failed the strict
diminishing-increment criterion. Across the original field treatments,
the unweighted same-date cumulative fresh-yield RMSE increased from 18.55
to 28.21 t/ha. Keep both the existing engineering reference and the higher
references as research controls.

Both pulses reduced QNO3 on DAP 50 and reduced functional leaf N on DAP 51.
The direct nitrogen constraint on accepted new leaf area acted on DAP 50.
The canopy photo factor separated by more than 5% on DAP 52. Extra
nitrogen-driven senescence increased smoothly, with DAP 51–52 crossings
at the diagnostic tolerance. Audit the direct assimilation-to-assembly
response alongside the delayed tissue-state response.


### Luxury nitrogen response ablation

The persistent inorganic B4 route supports opt-in luxury-N carbon partition
and new pod-set responses. The default mode remains 0. See the
[26SP execution report](p1_4864/luxury_response.zh.md) for the mechanism
choices, neutral controls, and ablation results.


See the [nitrogen endpoint audit](p1_4864/n_endpoints.zh.md) for the previous-day
state mapping, protected donor-rate change and reproductive budget checks.

See the [26SP signal-chain execution report](p1_4864/signal_chain_execution.zh.md)
for the five-level diagnostics, root supply scans, pulse rehearsals and IES admission
checks. The current luxury shoot configuration accepts modes 0 and 1. Use the
archived `c076cac4` build for the original mode 2 ablation.

The [canopy and calibration review](p1_4864/canopy_review_execution.zh.md) tracks
the SASC70 crop-card contrast, assimilation and SLN ablations, and the N0–N2
admission and pulse checks at the recovered-size diagnostic point.
