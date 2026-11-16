# C3/C4 diagnostics and latest-C4 research calibration

> Historical workflow. Its original scripts are preserved at `archive/pre-standalone-root-n`. Use the [current suite](../../RESEARCH.md) for new runs.

User requested both frozen-version diagnostics and a new latest-C4 calibration
on 2026-11-03. Output and working directories stay separate from existing runs.
No production/official executable, previous delivery or input is replaced.

`diagnostics.py` renders only diagnostic_* PNG/CSV artifacts from exact frozen
C3/C4 native output. It uses the standing leaf+stem biomass in CG_Nitrogen,
organic and total N separately, and actual PlantGro DAP. Fitting means/dates
come from the frozen 612-target comparison; raw July17 leaf/stem means are
added only as crosses for diagnosis. They never enter the objective. Raw source
and the frozen catalog have some historical date/value differences; this work
does not silently remap the calibration observations to the raw table.

New calibration uses the C4 accounting fixes in 7a3d14aa/3c40f815, preserving
small unspent CH2O and deriving aggregate weights from real organ components.
The two originally failed native perturbations are reproduced before launch;
core/Fortran, fallback and independent daily journals must pass. The frozen
4.8.6.4/C3/C4 deliveries remain unchanged. No elemental-C closure or management
validation is claimed; this is an explicitly requested research calibration.

`joint_c4.py --out RUN --prepare-only` creates independent candidate bounds,
validates each active parameter through native perturbation and freezes the
bounds under RUN/data/parameter_registry/bounds_frozen/eggplant/. Native and
NI ranges inherit the last A batch, whose native ranges derive from the user
76-parameter reference. Only remob_tau [5,20] days and protect_beta [0.5,0.9]
are added from the prior C4 sensitivity plan, as engineering domains. Slow/fast
ratio stays 3 and extra N senescence stays 0. Inert native terms (e.g. old
SENRTE under new leaf coupling) are fixed only after real perturbation checks.
All CSV parameter reads must use round_trip; otherwise tiny unrelated NI
changes can create false native-wiring effects.

`--launch-prepared` runs real PEST++ IES 80 members x 4 updates with six
isolated workers; it does not guarantee retention of all 80 members. Existing
612 direct targets/weights, same-day independently picked mature fruit and
failure semantics remain unchanged. Runtime forward_c4.py explicitly emits
all C1-C4 switches plus R2 for every call and checks the actual N/C journals.
It never fills or shifts a missing mature-fruit objective. Final selection is
from actual successful PEST evaluations, followed by exact deterministic replay.
