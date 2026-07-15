import sys
import os

sys.path.insert(0, 'd:/Tomato_Cal')
os.chdir('d:/Tomato_Cal/workspace')

print("="*70)
print("Generating PEST Output Files")
print("="*70)

from src.dssat.run_dssat import (
    _write_pest_eval_from_evaluate,
    _write_pest_joint_from_evaluate,
    _write_pest_harvest_from_tmt_and_freshwt,
    _write_pest_tmtgrow_from_tmt_and_plantgro,
    PEST_EVAL_FILE, PEST_JOINT_FILE, PEST_HARVEST_FILE, PEST_TMTGROW_FILE,
    _parse_batch_entries, _first_batch_filex_path, _resolve_filex_from_batch,
    _infer_excode_from_filex, _read_tmt_harvest_events, _read_tmt_process_points
)

workspace_dir = "d:/Tomato_Cal/workspace"
batch_file = "d:/Tomato_Cal/workspace/DSSBatch.v48"

evaluate_out = os.path.join(workspace_dir, "Evaluate.OUT")
plantgro_out = os.path.join(workspace_dir, "PlantGro.OUT")
freshwt_out = os.path.join(workspace_dir, "FreshWt.OUT")

filex_path = _resolve_filex_from_batch(batch_file, workspace_dir) or _first_batch_filex_path(batch_file)
excode = _infer_excode_from_filex(filex_path)
tmt_path = os.path.join(os.path.dirname(os.path.abspath(filex_path)), f"{excode}.TMT") if excode else None

print(f"Evaluate OUT: {evaluate_out} exists={os.path.exists(evaluate_out)}")
print(f"PlantGro OUT: {plantgro_out} exists={os.path.exists(plantgro_out)}")
print(f"FreshWt OUT: {freshwt_out} exists={os.path.exists(freshwt_out)}")
print(f"TMT path: {tmt_path} exists={os.path.exists(tmt_path) if tmt_path else 'N/A'}")

if os.path.exists(evaluate_out):
    pest_eval_path = os.path.join(workspace_dir, PEST_EVAL_FILE)
    _write_pest_eval_from_evaluate(evaluate_out, pest_eval_path)
    print(f"Generated: {pest_eval_path} ({os.path.getsize(pest_eval_path)} bytes)")

    pest_joint_path = os.path.join(workspace_dir, PEST_JOINT_FILE)
    _write_pest_joint_from_evaluate(evaluate_out, pest_joint_path)
    print(f"Generated: {pest_joint_path} ({os.path.getsize(pest_joint_path)} bytes)")
else:
    print("ERROR: Evaluate.OUT not found!")

if os.path.exists(freshwt_out) and os.path.exists(tmt_path):
    pest_harvest_path = os.path.join(workspace_dir, PEST_HARVEST_FILE)
    _write_pest_harvest_from_tmt_and_freshwt(batch_file, freshwt_out, pest_harvest_path, tmt_path=tmt_path, harvest_var="CHPDT")
    print(f"Generated: {pest_harvest_path} ({os.path.getsize(pest_harvest_path)} bytes)")
else:
    print(f"WARNING: freshwt_out={os.path.exists(freshwt_out)}, tmt_path={os.path.exists(tmt_path) if tmt_path else False}")

if os.path.exists(plantgro_out):
    pest_tmtgrow_path = os.path.join(workspace_dir, PEST_TMTGROW_FILE)
    _write_pest_tmtgrow_from_tmt_and_plantgro(batch_file, plantgro_out, pest_tmtgrow_path, tmt_path=tmt_path)
    print(f"Generated: {pest_tmtgrow_path} ({os.path.getsize(pest_tmtgrow_path)} bytes)")
else:
    print(f"WARNING: PlantGro.OUT not found")

print("\n" + "="*70)
print("All PEST Output Files Generated!")
print("="*70)