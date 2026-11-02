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
