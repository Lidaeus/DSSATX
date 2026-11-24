# Standalone DSSAT mechanism calibration

The IES entry maps bounded parameters into DSSAT namelists and CROPGRO
crop cards and extracts explicitly selected native output rows. It stages the
case, saves checksums and runs each forward evaluation in a private directory.
Use the DSSATX virtual environment. When starting PEST directly in an
existing case, activate that environment so the staged launcher finds Python.

```sh
python -m pip install -r research/calibration/requirements.txt
python research/portable_dssat.py prepare --out build/c4-inputs
example=research/calibration/examples/c4
python research/calibration/ies.py \
  --engine build/bin/dscsm048 --inputs build/c4-inputs \
  --template "$example/NIntegration.nml.tpl" --bounds "$example/bounds.csv" \
  --observations "$example/observations.csv" --members 4 --updates 1 \
  --pestpp-ies pestpp-ies --out build/c4-ies
```

Use a flat, prepared case with its local DSSAT profile and batch. Repeat
`--template` for multiple namelists. State parameter names and finite ranges
in the bounds table. Each observation provides the DSSAT treatment ID,
native output file and column, an optional YYYYDDD date, the measured
value in the native unit and its weight. A blank date selects the final
reported value in that run. The CLI can also prepare inputs alone by
omitting `--pestpp-ies`.

For the TM deficiency model, keep `photo_sln_ref` as a numeric value in
`NIntegration.nml` and any PEST template used for the trial. The standalone
IES preparer checks this assignment for PEST placeholders. The 26SP working
anchor comes from the independent SLN reference scan.

Replay the final ensemble's lowest actual-Phi member and verify the objective
against the IES record:

```sh
python research/calibration/replay.py --case build/c4-ies --out build/c4-replay
```

The C4 example fits one root parameter to four terminal yield targets to
exercise the toolchain. The V15 branch has a separate S4 example. The full
historical C4 and S4 designs used additional parameter cards, targets, and
run selection rules. Keep those runs tied to their original files and
frozen objectives.

For the 26SP staged signal-chain study, `prepare_26sp_signal.py` accepts the
original SASC70 experiment package as an explicit local input. It writes
multi-response observations, prior bounds, an input receipt and two
treatment holdouts. The default bundle uses a `preflight_only` marker
that blocks IES updates. The explicit `--joint --calibrate` run profile
permits updates on its training rows. The shared `rnk_vmax_scale` controls
both affinity ranges and nitrogen forms through one parameter.

The 26SP preflight stages N0–N2 in `observations.csv`, reserves both complete
N1 holdouts, and writes N3 to `stage2b_observations.csv` for the separate
luxury response check. N0/N1 leaf N uses a provisional minimum scale of
0.5 dry-mass percentage points. The July 17 leaf data remain diagnostic.

## Joint 26SP crop-card and mechanism calibration

One IES control file activates the 61 parameters in
[`26sp_joint_parameters.csv`](26sp_joint_parameters.csv). The design includes
all 21 strong and all 20 weak water–nitrogen card parameters, plus 20
coefficients of the enabled nitrogen mechanisms. The fixed SLN reference is
1.05. IES adjustment status and actual sensitivity are distinct. Replaced
native pathways may be insensitive in this configuration.

```sh
python research/calibration/prepare_26sp_signal.py \
  --experiment /path/to/xxql2601_final_sasc70_20261106 \
  --joint --calibrate --out build/26sp-joint-input
case=build/26sp-joint-input
python research/calibration/ies.py \
  --engine build/bin/dscsm048 --inputs "$case/inputs" \
  --template "$case/NIntegration.nml.tpl" --crop-map "$case/crop_map.csv" \
  --bounds "$case/bounds.csv" --observations "$case/observations.csv" \
  --members 80 --updates 1 --workers 8 --seed 20261123 \
  --pestpp-ies pestpp-ies --out build/26sp-joint-ies
python research/calibration/replay.py \
  --case build/26sp-joint-ies --out build/26sp-joint-replay
```

Use `--updates 0` for baseline preflight. Parallel PEST workers use a
sibling directory and keep forward errors for diagnosis. Simulation targets
must be finite on selected treatment–dates. Fortran overflow symbols on
unused output fields may be retained as missing values.

A custom `--crop-map` can also run without `--template` when the namelists
remain fixed in the input case. The map uses the following columns.

```csv
name,file,record,field
lfmax,TMGRO048.CUL,TM0008,LFMAX
xfint,TMGRO048.ECO,TM0001,XFINT
vssink,TMGRO048.SPE,,VSSINK
xswbar3,TMGRO048.SPE,,XSWBAR(3)
```

Use one alias per field. The TM batch must reference the selected cultivar
and ecotype. The SPE record column is blank. Array indices start at one
and must be consumed by the model. The writer uses the column positions
in the Fortran read statements and checks six-column values, representable
bounds, physical ranges and selected ordered arrays. Use coupled bounds
that satisfy all applicable ordering constraints across their full ranges
when multiple nodes vary. The maximum tolerated relative rounding per
field is 0.1%. Original input bytes outside the edited spans are preserved.

PEST writes a wide numeric table. The forward runner renders each
member's private crop cards and checks the resulting bytes before launching
DSSAT. `baseline_crop_readback.json` and `crop_readback.json` in the case
record initial and latest forward values. Replay writes the selected
member's rendered cards in `configs/`, their checksums in `receipt.json`
and the requested and read-back values in `crop_readback.json`.

The two N1 holdouts and the N3 observations remain separate from the
fitting objective. Luxury mode remains disabled for this N0–N2 task.
Verify the replay and conservation ledgers before adopting any parameter set.

The [80×4 result archive](results/26sp_80x4/README.md) contains the selected
parameters and rendered cards, independent replay, fit metrics, conservation
audit, and data for the diagnostic atlas.

## F5 existing-tissue nitrogen refill

The private 26SP F5/F6 workflow checks archived input and card hashes, stages
11 active parameters, and compares the archived control and both variants.
See the [execution report](f5_execution.zh.md) for commands, stage 2A criteria
and treatment-level results.


The paired F6 and substrate-fill luxury protocol is documented in the
[stage 2A archive](results/26sp_stage2a_11p/README.md). Its fixed-parameter
mode-2 ablations are in the [stage 2B archive](results/26sp_stage2b_lux2/README.md).


The [26SP continuation report](results/26sp_stage2a_11p/continuation/execution.zh.md)
describes the expanded F6 ensemble and the bounded W2 screen. The screen uses
training data and W2 endpoints to select points for independent native
validation against both water levels and the complete-treatment holdouts.

When a native 2A replay passes, `prepare_stage2b_26sp.py` checks the engine
and frozen configuration against that replay and stages only the three Hill
parameters. Its training table combines N3 fresh fruit and shoot dry mass
with the corresponding N3−N2 contrasts. The optional `reference_treatment`
column in an IES observation subtracts that treatment's native value for the
same file, column and date.

```sh
python research/calibration/prepare_stage2b_26sp.py \
  --engine "$engine" --stage "$stage_2a" --assessment "$passed_2a/receipt.json" \
  --config "$passed_2a/posterior/NIntegration.nml" --out "$stage_2b"
python research/calibration/ies.py --engine "$engine" --inputs "$stage_2b/inputs" \
  --template "$stage_2b/NIntegration.nml.tpl" --bounds "$stage_2b/bounds.csv" \
  --observations "$stage_2b/observations.csv" --members 32 --updates 2 --workers 8 \
  --seed 20261127 --pestpp-ies pestpp-ies --out "$ies_2b"
python research/calibration/replay.py --case "$ies_2b" --out "$replay_2b"
python research/calibration/stage2_26sp.py luxury \
  --engine "$engine" --stage "$stage_2a" --reference "$passed_2a/receipt.json" \
  --baseline "$passed_2a/posterior" --config "$replay_2b/configs/NIntegration.nml" \
  --out "$native_2b"
```
