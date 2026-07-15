import sys
import os

sys.path.insert(0, 'd:/Tomato_Cal')
os.chdir('d:/Tomato_Cal/workspace')

from src.dssat.run_dssat import (
    _parse_batch_entries, _resolve_filex_from_batch, _infer_excode_from_filex,
    _read_tmt_process_points, _read_plantgro_vars_by_run, PEST_TMTGROW_FILE
)

batch_file = "d:/Tomato_Cal/workspace/DSSBatch.v48"
plantgro_out = "d:/Tomato_Cal/workspace/PlantGro.OUT"
tmt_path = "d:/Tomato_Cal/workspace/XXQL2501.TMT"

print("="*70)
print("Debugging _write_pest_tmtgrow_from_tmt_and_plantgro")
print("="*70)

entries = _parse_batch_entries(batch_file)
print(f"\n[1] Batch entries: {len(entries)}")
for e in entries:
    print(f"  run={e['run']}, tn={e['tn']}, filex={e['filex']}")

print(f"\n[2] TMT path: {tmt_path}")
print(f"    TMT exists: {os.path.exists(tmt_path)}")

points_by_tn = _read_tmt_process_points(tmt_path)
print(f"\n[3] Points by TN: {len(points_by_tn)} treatments")
for tn, pts in list(points_by_tn.items())[:3]:
    print(f"  TN {tn}: {len(pts)} points")
    if pts:
        print(f"    First point: date={pts[0]['date']}")

print(f"\n[4] PlantGro path: {plantgro_out}")
print(f"    PlantGro exists: {os.path.exists(plantgro_out)}")

vars_by_run = _read_plantgro_vars_by_run(plantgro_out, ["L#SD", "LAID", "LWAD", "SWAD"])
print(f"\n[5] Vars by run: {len(vars_by_run)} runs")
for run_no, data in list(vars_by_run.items())[:3]:
    dates = list(data.keys())
    print(f"  Run {run_no}: {len(data)} dates, first date={dates[0] if dates else 'N/A'}")

print(f"\n[6] Expected output:")
total_lines = 0
for e in entries:
    tn = int(e.get("tn", -99))
    pts = points_by_tn.get(tn, [])
    print(f"  Entry run={e['run']}, TN={tn}: {len(pts)} points")
    total_lines += len(pts)
print(f"  Total expected lines: {total_lines}")