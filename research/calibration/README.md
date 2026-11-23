# Standalone DSSAT mechanism calibration

The IES entry maps bounded mechanism parameters into one or more DSSAT
namelists and extracts explicitly selected native output rows. It stages the
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
multi-response observations, provisional bounds, an input receipt and two
treatment holdouts. Use `--updates 0` for this bundle until the nitrogen
observation operator and the mechanistic admission criteria are verified.
The `preflight_only` marker blocks IES updates. The shared `rnk_vmax_scale`
controls both affinity ranges and nitrogen forms through one parameter.
