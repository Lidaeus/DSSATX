"""Resume the four approved pilot trajectories as a model-feasibility audit."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json

import pandas as pd

from run_dual_spring_morris_20261105 import (
    ROOT, RUN_ID, WORKERS, context, forward, sha, status, write,
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    original = ROOT/"workspace/runs"/RUN_ID
    manifest = read(original/"run_manifest.json")
    exe = original/"DSCSM048.EXE"
    matrix = original/"morris_X_serialized.csv"
    bounds_path = original/"approved_bounds.csv"
    assert sha(matrix)==manifest["design_sha256"] and sha(bounds_path)==manifest["bounds_sha256"]
    assert sha(exe)==manifest["official_dssat_sha256"]
    b = pd.read_csv(bounds_path)
    vectors = pd.read_csv(matrix,index_col=0,float_precision="round_trip").to_dict("records")
    contexts = {}
    from src.common.input_manifest import verify_calibrated_input_bundle
    for season,entry in manifest["input_bundles"].items():
        bundle = ROOT/"data/user/experiments"/entry["bundle_id"]
        assert verify_calibrated_input_bundle(bundle).manifest_sha256==entry["manifest_sha256"]
        fixed = original/f"{season}_fixed_inputs"
        assert {p.name:sha(p) for p in fixed.iterdir()}==manifest["fixed_payload_sha256"][season]
        contexts[season] = context(bundle,fixed,season,b)

    run = original/"pilot_recovery_audit_20261105"
    run.mkdir(exist_ok=True)
    lock = run/"running.lock"
    with lock.open("x",encoding="utf-8") as file:
        import os
        file.write(str(os.getpid()))
    try:
        (run/"scratch").mkdir(exist_ok=True)
        for season in contexts:
            (run/"records"/season).mkdir(parents=True,exist_ok=True)
        width = len(b)+1
        pilot_size = 4*width
        planned = pilot_size*len(contexts)
        completed, pending = {}, []
        for point in range(pilot_size):
            label = f"point_{point:04d}"
            for season, ctx in contexts.items():
                revised = run/"records"/season/f"{label}.json"
                old = original/"records"/season/f"{label}.json"
                if revised.is_file():
                    p = revised
                    record = read(p)
                elif old.is_file() and read(old)["status"]=="ok":
                    p = old
                    record = read(p)
                else:
                    pending.append((ctx,label,vectors[point]))
                    continue
                if record["status"]=="ok":
                    assert record["actual"]==vectors[point]
                elif record.get("failure_kind")!="native_output":
                    raise RuntimeError(f"Execution or contract error still unresolved: {p}")
                completed[season,label] = (record,p)
        reused = sum(p.is_relative_to(original/"records") for _,p in completed.values())
        native_failures = sum(r["status"]!="ok" for r,_ in completed.values())
        status(run,"pilot_recovery_audit_running",planned=planned,finished=len(completed),
               reused=reused,native_failures=native_failures,formal_campaign_started=False)
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(forward,run,exe,ctx,label,vector):(ctx.season,label)
                       for ctx,label,vector in pending}
            for future in as_completed(futures):
                season,label = futures[future]
                record = future.result()
                p = run/"records"/season/f"{label}.json"
                if record["status"]!="ok":
                    if record.get("failure_kind")!="native_output":
                        for waiting in futures:
                            waiting.cancel()
                        raise RuntimeError(record["error"])
                    native_failures += 1
                completed[season,label] = (record,p)
                if len(completed)%12==0 or len(completed)==planned:
                    status(run,"pilot_recovery_audit_running",planned=planned,finished=len(completed),
                           reused=reused,native_failures=native_failures,formal_campaign_started=False)
        rows = []
        for (season,label),(record,p) in sorted(completed.items()):
            point = int(label.removeprefix("point_"))
            rows.append(dict(season=season,point_id=point,trajectory_id=point//width+1,
                             step=point%width,status=record["status"],
                             error=record.get("error",""),record=str(p)))
        results = pd.DataFrame(rows)
        results.to_csv(run/"point_feasibility.csv",index=False)
        summary = (results.assign(passed=results.status.eq("ok"))
                   .groupby(["trajectory_id","season"]).passed.agg(["sum","count"]).reset_index())
        summary.to_csv(run/"trajectory_feasibility.csv",index=False)
        passing = summary.assign(passed=summary["sum"].eq(width)).groupby("trajectory_id").passed.all()
        status(run,"pilot_recovery_audit_complete",planned=planned,finished=len(completed),reused=reused,
               native_failures=native_failures,valid_paired_trajectories=passing[passing].index.tolist(),
               formal_campaign_started=False)
    except Exception as exc:
        status(run,"pilot_recovery_audit_stopped",error=f"{type(exc).__name__}: {exc}",
               formal_campaign_started=False)
        raise
    finally:
        lock.unlink()


if __name__ == "__main__":
    main()
