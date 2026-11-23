# 26SP 61-parameter joint IES result

This archive records the 80-member, four-update 26SP eggplant calibration
using CROPGRO TM. The selected final member is 4, with recorded Φ 23.5973
and independent replay Φ 23.597281962049188. The reported treatment
gradients and boundary contacts qualify this result as a research parameter
set.

- [Fit and diagnostic report](report.zh.md)
- [Diagnostic atlas](../../../../output/pdf/diagnostic_atlas.pdf)
- [Final selected parameters](best_parameters.csv)
- [Target-family and variable metrics](fit_metrics.csv)
- [Matched observations and simulations](matched_observations.csv)
- [Final ensemble](ies_final_parameters.csv) and [objective history](ies_phi_history.csv)
- [Frozen rendered crop and mechanism inputs](configs/)
- [Replay receipt](replay_receipt.json) and [C/N audit](balance_audit.json)

## Reproduce the plots

Install the diagnostic dependencies from
[requirements.txt](../../../n_diagnostics/requirements.txt) and provide a CJK
font when it is unavailable at a detected system location.

```sh
python research/calibration/results/26sp_80x4/render_atlas.py \
  --out build/26sp-80x4-atlas-reproduced.pdf
```

The atlas reads the archived native daily fields, seasonal root-layer
settlement totals, and the matched observation table. The root-layer totals
include season-end pending N per the reconciled ledger. The plot inputs
and submitted PDF are identified by [SHA-256](archive_manifest.json).

## Reproduce the simulation or IES batch

The original experiment package is `xxql2601_final_sasc70_20261106`.
Check the package against [input hashes](input_receipt.json) and use the
DSSATX build identified in [the run manifest](run_manifest.json).
The archive contains the exact rendered namelist and crop cards used in
the replay. To run the selected point, copy `configs/` over a private
prepared SASC70 case, set `DSSAT_HOME=./` and `DSSAT_P0_TRACE=1`, then
invoke the verified executable with `CRGRO048 B DSSBatch.v48`.

To repeat IES, use the [joint-run setup](../../README.md) with 80 members,
four updates, eight workers, and seed 20261123. Use the archive's
[parameter design](parameter_design.csv) and [bounds](bounds.csv) if the
working prior has changed. The training objective uses 131 positive
weights. W1–N1, W3–N1 and N3 remain held out, and the archive preserves
the subset roles in the matched table.
