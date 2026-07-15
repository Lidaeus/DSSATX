import sys
import os

sys.path.insert(0, 'd:/Tomato_Cal')
os.chdir('d:/Tomato_Cal/workspace')

print("="*70)
print("Generating PestHarvest.OUT")
print("="*70)

from src.dssat.run_dssat import (
    _write_pest_harvest_from_tmt_and_freshwt,
    PEST_HARVEST_FILE,
    _parse_batch_entries
)

workspace_dir = "d:/Tomato_Cal/workspace"
batch_file = "d:/Tomato_Cal/workspace/DSSBatch.v48"
freshwt_out = os.path.join(workspace_dir, "FreshWt.OUT")
tmt_path = os.path.join(workspace_dir, "XXQL2501.TMT")

print(f"FreshWt OUT: {freshwt_out} exists={os.path.exists(freshwt_out)}")
print(f"TMT path: {tmt_path} exists={os.path.exists(tmt_path)}")

if os.path.exists(freshwt_out) and os.path.exists(tmt_path):
    pest_harvest_path = os.path.join(workspace_dir, PEST_HARVEST_FILE)
    _write_pest_harvest_from_tmt_and_freshwt(batch_file, freshwt_out, pest_harvest_path, tmt_path=tmt_path, harvest_var="CHPDT")
    print(f"Generated: {pest_harvest_path} ({os.path.getsize(pest_harvest_path)} bytes)")
else:
    print(f"ERROR: Cannot generate PestHarvest.OUT")

print("\n" + "="*70)
print("Generating PST File")
print("="*70)

from src.calibration.build_pest import (
    parse_cul_params, parse_extra_params, apply_tighten_params_csv,
    apply_bounds_review_csv, _read_eco_init_values, _read_spe_temp_init_values,
    _read_spe_direct_init_values, _infer_ecotype_from_cul_base,
    _parse_batch_entries as bp_parse_batch, _first_batch_filex_path as bp_first_filex,
    _resolve_filex_path, _infer_excode_from_filex as bp_infer_excode,
    _infer_cultivar_from_filex,
    ECO_BOUNDS_EGGPLANT, SPE_TEMP_BOUNDS_EGGPLANT, SPE_DIRECT_BOUNDS_EGGPLANT,
    create_ins_and_pst_multi, _evaluate_out_path_from_batch,
    PEST_EVAL_FILE, PEST_JOINT_FILE, PEST_HARVEST_FILE, PEST_TMTGROW_FILE
)
import pandas as pd

prefix = "eggplant_stage2_v14_full"
noptmax = 6
ies_num_reals = 80
tighten_csv = "d:/Tomato_Cal/workspace/_v14_excl_tighten.csv"
tighten_frac = 0.10
bounds_csv = "d:/Tomato_Cal/data/parameter_registry/bounds_frozen/eggplant/eggplant_v14_20260405.csv"

workspace_dir = "d:/Tomato_Cal/workspace"

filex = bp_first_filex(batch_file)
filex_path = _resolve_filex_path(filex) or filex
print(f"First filex: {filex_path}")

cultivar = _infer_cultivar_from_filex(filex_path) or "TM0008"
ecotype = _infer_ecotype_from_cul_base(cultivar) or "TM0001"
print(f"Cultivar: {cultivar}, Ecotype: {ecotype}")

allowed = {
    "CSDL", "PPSEN", "EM-FL", "FL-SH", "FL-SD", "SD-PM", "FL-LF",
    "SLAVR", "SIZLF", "LFMAX", "XFRT", "WTPSD", "SFDUR", "SDPDV", "PODUR", "THRSH"
}
params = parse_cul_params(cultivar, allowed_params=allowed)

extra_allowed = {
    "XMAGE", "TRIFL", "RWDTH", "RHGHT", "KC_SLOPE", "VSSINK", "RTNO3", "RTNH4",
    "RTEXF", "NSTFAC", "NMOBMX", "NVSMOB", "NRCVR", "XFPHT", "XFINT",
    "PL-EM", "EM-V1", "V1-JU", "JU-R0",
    "TB1", "TO11", "TO21", "TM1", "TB2", "TO12", "TO22", "TM2", "TB3", "TO13", "TO23", "TM3",
}

eco_init = _read_eco_init_values(ecotype)
spe_init = _read_spe_temp_init_values()
spe_init.update(_read_spe_direct_init_values())

params.extend(parse_extra_params(eco_init, ECO_BOUNDS_EGGPLANT, extra_allowed, "ecotype"))
params.extend(parse_extra_params(spe_init, SPE_TEMP_BOUNDS_EGGPLANT, extra_allowed, "species"))
params.extend(parse_extra_params(spe_init, SPE_DIRECT_BOUNDS_EGGPLANT, extra_allowed, "species"))

params = apply_tighten_params_csv(params, [tighten_csv], tighten_frac)

if os.path.exists(bounds_csv):
    params, brm_report = apply_bounds_review_csv(params, bounds_csv, cultivar=cultivar, ecotype=ecotype, mode="eggplant_stage2")
    print(f"Bounds applied: {brm_report['applied']} applied, {brm_report['missing']} missing")

entries = bp_parse_batch(batch_file)
print(f"Batch entries: {len(entries)}")

excode = bp_infer_excode(filex_path)
print(f"Excode: {excode}")

from src.dssat.run_dssat import _read_tmt_harvest_events, _read_tmt_process_points

tmt_path = os.path.join(workspace_dir, f"{excode}.TMT") if excode else None
print(f"TMT path: {tmt_path}")

events_by_tn = {}
points_by_tn = {}
if tmt_path and os.path.exists(tmt_path):
    events_by_tn = _read_tmt_harvest_events(tmt_path)
    points_by_tn = _read_tmt_process_points(tmt_path)
    print(f"Harvest events: {len(events_by_tn)} treatments")

harvest_rows = []
process_rows = []
harvest_var = "CHPDT"

for e in entries:
    run_no = int(e["run"])
    tn = int(e.get("tn", -99))
    for ev in events_by_tn.get(tn, []):
        obs_cum = ev.get("dry_cum", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_cum", -99.0)
        obs_inc = ev.get("dry_inc", -99.0) if harvest_var == "CHPDT" else ev.get("fresh_inc", -99.0)
        harvest_rows.append({
            "@RUN": run_no, "TN": tn, "HNO": int(ev["hno"]), "DATE": int(ev["date"]),
            "PWADM": float(obs_cum), "PWAIM": float(obs_inc),
            "PWADS": -99.0, "PWAIS": -99.0,
        })
    for p in points_by_tn.get(tn, []):
        process_rows.append({
            "@RUN": run_no, "TN": tn, "DATE": int(p["date"]),
            "LAIDM": float(p["laid"]), "LWADM": float(p["lwad"]), "SWADM": float(p["swad"]),
            "LAIDS": -99.0, "LWADS": -99.0, "SWADS": -99.0,
        })

df_harvest = pd.DataFrame(harvest_rows)
df_process = pd.DataFrame(process_rows)
print(f"Harvest rows: {len(df_harvest)}, Process rows: {len(df_process)}")

harvest_sigmas = {"PWADM": 1.0, "PWAIM": 1.0}
process_sigmas = {"LAIDM": 2.0, "LWADM": 150.0, "SWADM": 200.0}

stage2_outputs = [
    {
        "model_out_path": PEST_EVAL_FILE,
        "obs_bases": {"ADAP"},
        "critical_obs": {"ADAPM"},
        "group_sigmas": {"ADAPM": 25.0},
    },
    {
        "model_out_path": PEST_JOINT_FILE,
        "obs_bases": {"HWAM", "LAIX", "CNAM", "CHTA", "CNAA", "PWAM", "H#AM", "HIAM"},
        "critical_obs": set(),
        "group_sigmas": {
            "HWAMM": 50.0, "PWAMM": 20.0, "LAIXM": 0.8, "CNAMM": 25.0,
            "CHTAM": 15.0, "CNAAM": 20.0, "H#AMM": 50.0, "HIAMM": 0.10,
        },
    },
    {
        "model_out_path": PEST_HARVEST_FILE,
        "obs_bases": {"PWAD", "PWAI"},
        "critical_obs": set(),
        "group_sigmas": harvest_sigmas,
        "df": df_harvest,
    },
    {
        "model_out_path": PEST_TMTGROW_FILE,
        "obs_bases": {"LAID", "LWAD", "SWAD"},
        "critical_obs": set(),
        "group_sigmas": process_sigmas,
        "df": df_process,
    },
]

evaluate_out_path = _evaluate_out_path_from_batch(batch_file)
model_cmd_extra = f"--batch DSSBatch.v48 --harvest-var CHPDT"

print(f"\nEvaluate out path: {evaluate_out_path}")
print(f"Model cmd extra: {model_cmd_extra}")

print(f"\nGenerating PST in: {workspace_dir}")

create_ins_and_pst_multi(
    params,
    prefix=prefix,
    noptmax=noptmax,
    ies_num_reals=ies_num_reals,
    outputs=stage2_outputs,
    evaluate_out_path=evaluate_out_path,
    model_cmd_extra=model_cmd_extra,
    out_dir=workspace_dir,
)

print("\n" + "="*70)
print("PST Generation Completed!")
print("="*70)

print("\nListing generated files:")
for f in sorted(os.listdir(workspace_dir)):
    fpath = os.path.join(workspace_dir, f)
    if os.path.isfile(fpath) and (f.endswith('.pst') or f.endswith('.ins') or f.endswith('.csv')):
        print(f"  {f} ({os.path.getsize(fpath)} bytes)")