# N v3: staged state, remobilization and assimilation budget

User approval 2026-11-03 authorizes the reviewed C0-C3 sequence, including
the individually reported V15 S1 principles V1-V3. This does not authorize
old 4.8.2.0 file replacement, fruit dilution or zero-cost assimilation.

Baseline is 0927ba62 (official 4.8.6.4 plus A fixes); protected binaries,
calibration inputs and observations remain unchanged. New executables and
native cases go to critical_n/reports/n_v3_execution_20261103. Source commits
and evidence are separate, so no unverified candidate is promoted.

Plan: critical_n/reports/n_v3_refined_plan_20261103/
氮机制改进精简方案_V15S1经验与v3评估_20261103.md.

Use workflow.py build LABEL, then workflow.py case NAME EXE --changes JSON.
Cases use exact already-injected A best native inputs, record actual NML and
binary hashes, retain unavailable mature-fruit objectives as errors, and
independently check Q/organic-N/vegetative-C budgets. No test forces yield
ordering, actual N concentration onto reference curves, or calendar growth.

Implemented opt-in settings (default zero preserves frozen A):

- `state_timing=1`: publish previous-end growth state before phenology;
  SPAM opens the same snapshot before its earlier photosynthesis call.
- `pods_n_state=1`: replace RNITPD's mixed concentration ratio at its existing
  site with 1-(1-Z_leaf)^2. Existing fruit N composition/CNSTRES stays native.
- `remob_mode=1`: safe above-critical organic balance first, protected
  functional balance second. `remob_tau`, `protect_beta`, `slow_ratio` are
  mandatory, finite, explicitly declared experimental settings. Functional
  export uses the SAME smoothed C1 leaf growth state; no extra severity clock.
  Native root/shell sources are retained and bounded. Unused leaf/stem/root
  reservations are canceled before GROW. Shell loss is already integrated
  inside PODS; it is NOT silently undone after harvest. An assertion requires
  that its full retained export has a real new-growth recipient.
- `luxury_priority=1`: core acceptance targets critical function, late
  assimilation uses only discretionary storage carbon after native CSAVEV.
  Its enzyme allowance is the UNUSED part of the original two-half-step
  potential envelope, not an extra full day of activity. Actual uptake remains
  separate, Q is the substrate, all costs use original species coefficients.

Both state settings must be 1 before enabling remobilization or priority;
all require stage5/A. Three incompatible/missing-config tests reject early.
The demonstration tau=10 d, beta=0.7, slow/fast=3 is an engineering scenario,
not a fitted parameter set or universal eggplant constant.

Ledgers: PlantNV3.csv, PlantNRemob.csv, PlantNLuxury.csv extend existing
PlantNIntegration/PlantABudget rather than introducing another true N pool.
verify_c1/2/3.py independently reconstruct published state, submitted source,
recipient, unused kinetic capacity, N cost and residual-C storage accounts.

C4 physiology (remobilization vs area/senescence) is NOT changed. Current
GROW/SENES double pathways remain a transparent comparison until complete
elemental-C/DM accounting and the detailed replacement diff are reviewed.
These checks prove incremental Q/organic-N/vegetative-payment closure, not
complete whole-system elemental C closure or field management validity.
