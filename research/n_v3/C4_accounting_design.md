# C4 preparation: remaining area, dry-mass and elemental-C contract

This is a design deliverable, not an implemented physiology switch. C0-C3
retain native GROW/SENES area and senescence behavior to isolate their effects.

Before changing that behavior, explicitly reconcile these existing paths:

| Path | Current implementation | C4 requirement |
|---|---|---|
| Leaf protein-equivalent removal | GROW subtracts NRUSLF/0.16 from leaf DM | Keep organic N/DM/C skeleton transfer accounted; never simply delete this DM term |
| Direct area removal | ALFDOT subtracts NRUSLF/0.16 times SLA | Separate safe balance export from confirmed functional tissue damage; this is an area convention, not N conservation itself |
| Extra N senescence | SENES adds SENRTE*NRUSLF/0.16 to SLDOT | Replace rather than add another N-dependent death term |
| Existing-tissue repair | NAD adds protein-equivalent DM and may restore area below critical | Protein replacement must not automatically manufacture new leaf area |
| Returned C | Assimilation/reservation refund is stored as carbohydrate | Check that return to leaf C cannot bypass the intended expansion/allocation logic; soft concentration remains free to deviate |
| Native root/shell sources | Preserved by C2, shell removal already integrated in PODS | Keep cohort/bulk N, DM and harvest synchronized; no post-harvest rollback |
| Surface/root litter | A uses actual organ N losses and excludes harvested fruit | Preserve these upstream/A repairs when changing senescence composition |
| GRWRES | C3 switches the reduction diagnostic to actual assimilation | It is not an extra financial debit and is not a complete elemental-C account |

Required new ledger: initial/final organ DM and component C; N-bound
protein-equivalent DM/C transferred internally; real carbohydrate pools;
growth input; assimilation/re-synthesis/maintenance C paid once; harvest,
litter, other removal and unconsumed carbon. Use g C/m2 for elemental C and
retain g CH2O/m2 separately for the process budget. Component fractions must
come from actual native composition rules; do not infer chemical identity
from the diagnostic safe/functional N partition.

Proposed first replacement: safe organic export has no automatic green-area
death; functional damage reduces functional area N and future Pmax. Keep
age/shade/water losses. Initially add no new N-death coefficient, then test
sustained deficit/recovery before introducing one. No singular
N_export/(SLN-SLNmin) formula, hard projection to Nmin, new leaf cohorts,
fruit N dilution or calendar-specific growth guardrail.

Scientific unresolved point: at tau=10 d, protection beta=0.7, slow/fast=3,
the shared smooth-state gate plus donor protection may allow almost no extra
functional export. Improved W2 yield ordering alone cannot validate this
combination. Compare the same model with remob_severity=0 and protection/rate
perturbations before fitting all new controls together. Likewise, the current
one-pass C/N acceptance predictor can be conservative after reservations are
canceled; do not describe it as a converged coupled source-sink solution.
