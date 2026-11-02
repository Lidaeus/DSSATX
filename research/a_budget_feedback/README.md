# A: actual acceptance, budgets and soft leaf feedback

Based on official v4.8.6.4 plus the frozen five-stage integration at
`a1bfa80678c3e9ca87d4991f373af36038539688`. New mechanism changes require
`budget_revision=1` with stage >= 4. Mode 0 and revision 0 retain the old
physiology. No V15 physiological code is adopted.

Changes:

- VEGGR reconciles actual organ composition, leaf growth acceptance and its
  carbon payment before committing growth. Leaf DM and area respond together;
  the second N multiplier on SLA is removed. Forecast concentration can inhibit
  expansion immediately while the common growth state retains its recovery lag.
- Existing tissue accepts N according to its own stock deficit, independently
  of new-organ partition fractions. Receiver space includes added protein DM.
  Refills are allocated to surviving tissue; they are not reduced again by the
  native old-tissue survival fraction. Luxury refill above critical does not
  automatically create proportional new area.
- N-limited leaf carbohydrate acceptance transfers unused carbohydrate to the
  native stem C reserve at the same PCH2O payment. This is a process allocation,
  not a projection of actual concentration onto a prescribed range.
- Leaf/stem remobilizable N uses the current lower-reference reserve. Actual
  N can remain outside the references; root and fruit composition are native.
- Harvested shell N is excluded from soil surface residue. Actual fruit N
  export is bounded by available stock before the native negative-stock guard
  can conceal excess export. Seed harvest accumulation uses seed N concentration.
  Root litter receives the same actual N removed from roots, not a second
  estimate using post-update concentration. Fruit demand physiology is unchanged.
- `photo_slw_ref` explicitly controls the functional area-N reference; surplus
  organic concentration above critical does not proportionally increase Pmax.
  No inorganic reserve N is counted as functional protein.
- `curve_w0` controls the low-biomass plateau of
  `Nc = a * max(W, W0)**(-b)`, with W = standing leaf+stem DM in t/ha and
  a in gN/gDM. For W >= 1, the 0.7 and 1.0 curves coincide. This isolates the
  breakpoint without silently redefining a. New curves are not equivalent to
  the old V15 asymptotic canopy curve.
- Competing desired shoot fractions are normalized when their sum exceeds
  0.98, and the stress root fraction stays within [0,0.98]. Parameter inputs
  themselves are not clipped or repaired during candidate evaluation.

Verification: 29 original native core checks and 9 additional A checks;
same-input eight-output regression at revision zero and mode zero; all-12
deterministic replay; 2 breakpoints x 3 lower ratios x 2 upper ratios;
independent Q, committed organic N and vegetative growth C ledgers.
`PlantABudget.csv` exposes actual acceptance and revision/configuration values.
The C assertion is for vegetative growth payment, not a complete elemental
whole-system carbon audit. No seasonal or date growth guardrail is introduced.

Calibration uses the user's 76-parameter reference only for compatible native
activations/ranges. Four obsolete CNC fields, nine NB fields, RTNO3 and three
old photo fields are not silently renamed into new mechanisms. SLPF_25SP is
outside 26SP scope. The 58 native candidates and 17 NI activities pass native
perturbation checks; TCMP requires an ICMP interaction context. The failed PM06
endpoint lacking mature fruit at the exact N sampling date remains recorded;
no objective is imputed or shifted in time. New NI domains are engineering
working domains, not validated biological confidence ranges.

`joint_A.py` builds the isolated frozen 80 x 4, six-worker real PEST-IES run.
Its initial ensemble is local uniform within +/-12% of each full working
domain width around the verified start, intersected with the full bounds.
Full bounds remain available to IES. All 612 existing objective operators and
weights remain unchanged. Nitrogen assay recovery remains an explicit limit.

Historical `critical_n/tests` stops at a pre-existing stored cross-season
report assertion (early 4.56% vs late 4.59%), after 25 passing tests. That test
does not execute this new engine. Its historical evidence is not edited to
force a pass, and no 25FA applicability test is added to the current scope.
