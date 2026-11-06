"""Continue the approved Morris random stream, keeping complete paired trajectories."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from run_dual_spring_morris_20261105 import (
    ROOT, RUN_ID, TRAJECTORIES, LEVELS, STEP, WORKERS,
    context, design, forward, sha, status, write,
)
from review_dual_spring_morris_20261105 import main as review
from src.common.input_manifest import verify_calibrated_input_bundle

RECOVERY_ID = RUN_ID + "_paired_feasible"
POOL_SIZE = 160


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def prepared(original, out):
    manifest = read(original/"run_manifest.json")
    exe = original/"DSCSM048.EXE"
    source = original/"approved_bounds.csv"
    frozen_matrix = original/"morris_X_serialized.csv"
    assert sha(exe)==manifest["official_dssat_sha256"]
    assert sha(source)==manifest["bounds_sha256"]
    assert sha(frozen_matrix)==manifest["design_sha256"]
    b = pd.read_csv(source,float_precision="round_trip")
    matrix_path = out/"candidate_stream_serialized.csv"
    if not matrix_path.exists():
        _, matrix = design(b,trajectories=POOL_SIZE)
        matrix.to_csv(matrix_path,index_label="candidate_point_id")
    matrix = pd.read_csv(matrix_path,index_col=0,float_precision="round_trip")
    prefix = pd.read_csv(frozen_matrix,index_col=0,float_precision="round_trip")
    assert len(matrix)==POOL_SIZE*(len(b)+1)
    pd.testing.assert_frame_equal(matrix.iloc[:len(prefix)],prefix,check_names=False,check_exact=True)
    shutil.copy2(source,out/source.name)
    contexts = {}
    for season,entry in manifest["input_bundles"].items():
        bundle = ROOT/"data/user/experiments"/entry["bundle_id"]
        assert verify_calibrated_input_bundle(bundle).manifest_sha256==entry["manifest_sha256"]
        fixed = original/f"{season}_fixed_inputs"
        assert {p.name:sha(p) for p in fixed.iterdir()}==manifest["fixed_payload_sha256"][season]
        contexts[season] = context(bundle,fixed,season,b)
    return manifest, exe, b, matrix, contexts


def check_record(record, season, vector, fixed):
    assert record["season"]==season
    if record["status"]=="ok":
        assert record["actual"]==vector
        for name,digest in fixed.items():
            assert record["input_sha256"][name]==digest
        assert record["responses"] and np.isfinite(list(record["responses"].values())).all()
    else:
        assert record["status"]=="failed" and record["vector"]==vector


def trajectory(out, contexts, pool, exe, trajectory_id, width, vectors, pilot, fixed):
    """Retain every evaluated point, but skip the rest of a failed trajectory."""
    eval_root = out/"evaluations"
    records, tasks = {}, []
    points = range((trajectory_id-1)*width,trajectory_id*width)
    for i in points:
        for season,ctx in contexts.items():
            path = pilot.get((season,i),eval_root/"records"/season/f"point_{i:05d}.json")
            if path.is_file():
                result=read(path)
                check_record(result,season,vectors[i],fixed[season])
                records[season,i] = (result,path)
            else:
                tasks.append((season,i,ctx,path))

    def evaluate(task):
        season,i,ctx,path = task
        result=forward(eval_root,exe,ctx,path.stem,vectors[i])
        check_record(result,season,vectors[i],fixed[season])
        return (season,i),(result,path)

    for offset in range(0,len(tasks),WORKERS):
        if any(result["status"]!="ok" for result,_ in records.values()):
            break
        records.update(pool.map(evaluate,tasks[offset:offset+WORKERS]))
    failed = [dict(season=s,point_id=i,error=result["error"],
                   failure_kind=result.get("failure_kind","native_output"),record=str(path))
              for (s,i),(result,path) in records.items() if result["status"]!="ok"]
    # Native failures and an individually failed executable are candidate outcomes.
    # Keep infrastructure or input-writing exceptions distinct from physical infeasibility.
    for item in failed:
        if item["failure_kind"] not in {"native_output","native_run"}:
            raise RuntimeError(f"Execution/contract check failed: {item['record']}: {item['error']}")
    valid = not failed and len(records)==width*len(contexts)
    return dict(trajectory_id=trajectory_id,status="accepted" if valid else "rejected",
                evaluated=len(records),unexecuted=width*len(contexts)-len(records),failures=failed,
                evaluated_points=[dict(season=s,point_id=i,status=r["status"],record=str(p))
                                  for (s,i),(r,p) in sorted(records.items())])


def endpoint_counts(x, selected, b):
    k = len(b)
    values = x.to_numpy().reshape(-1,k+1,k)[np.asarray(selected)-1]
    coordinates=(values-b.lower.to_numpy())/(b.upper-b.lower).to_numpy()
    levels=np.rint(coordinates*(LEVELS-1)).astype(int)
    assert (np.abs(coordinates-levels/(LEVELS-1))<.002).all()
    counts=np.zeros((k,LEVELS),dtype=int)
    for i,z in enumerate(levels):
        delta=np.diff(z,axis=0)
        assert ((delta!=0).sum(axis=0)==1).all() and ((delta!=0).sum(axis=1)==1).all()
        order=np.argmax(delta!=0,axis=1)
        before=z[np.arange(k),order]
        after=z[np.arange(1,k+1),order]
        assert (np.abs(after-before)==STEP).all(),i
        counts[order,before]+=1
        counts[order,after]+=1
    return counts


def coverage_audit(out,matrix,b,accepted,attempted):
    n=len(accepted)
    good=endpoint_counts(matrix,accepted,b)
    offered=endpoint_counts(matrix,attempted,b)
    tv=.5*np.abs(good/(2*n)-offered/(2*len(attempted))).sum(axis=1)
    pd.DataFrame([dict(parameter=name,level=i,relative_level=i/(LEVELS-1),
                       accepted_endpoint_count=good[j,i],attempted_endpoint_count=offered[j,i],
                       total_variation=tv[j])
                  for j,name in enumerate(b.name) for i in range(LEVELS)]).to_csv(
                      out/"parameter_grid_coverage.csv",index=False)
    return dict(all_parameters_all_levels_present=bool((good>0).all()),
                parameters_missing_levels=b.name[(good==0).any(axis=1)].tolist(),
                min_accepted_endpoint_count=int(good.min()),
                maximum_total_variation=float(tv.max()))


def seal_retained(out, manifest, b, matrix, accepted, ledgers):
    width=len(b)+1
    retained=np.concatenate([np.arange((i-1)*width,i*width) for i in accepted])
    selected=matrix.iloc[retained].reset_index(drop=True)
    selected.to_csv(out/"morris_X_serialized.csv",index_label="point_id")
    pd.DataFrame(dict(point_id=np.arange(len(retained)),candidate_point_id=retained,
                      candidate_trajectory_id=retained//width+1)).to_csv(out/"retained_point_map.csv",index=False)
    links={(r["season"],r["point_id"]):Path(r["record"]) for ledger in ledgers if ledger["status"]=="accepted"
           for r in ledger["evaluated_points"]}
    for season in manifest["input_bundles"]:
        target=out/"records"/season
        target.mkdir(parents=True,exist_ok=True)
        for i,point in enumerate(retained):
            source=links[season,point]
            dest=target/f"point_{i:04d}.json"
            if not dest.exists():
                os.link(source,dest)
            assert dest.samefile(source)
    audit=coverage_audit(out,matrix,b,accepted,[item["trajectory_id"] for item in ledgers])
    manifest.update(run_id=out.name,source_run=RUN_ID,
                    design_sha256=sha(out/"morris_X_serialized.csv"),
                    candidate_stream_sha256=sha(out/"candidate_stream_serialized.csv"),
                    recovery_runner_sha256=sha(Path(__file__)),
                    conditional_trajectory_selection=dict(
                        rule="first 40 complete trajectories valid in both seasons, in original single-seed stream order",
                        accepted_ids=accepted,attempted=len(ledgers),rejected=len(ledgers)-len(accepted),
                        inference="conditional on complete two-season model feasibility",coverage=audit))
    write(out/"run_manifest.json",manifest)
    return audit


def main(resume=False):
    original=ROOT/"workspace/runs"/RUN_ID
    out=ROOT/"workspace/runs"/RECOVERY_ID
    out.mkdir(exist_ok=resume)
    lock=out/"running.lock"
    with lock.open("x",encoding="utf-8") as file:
        file.write(str(os.getpid()))
    try:
        status(out,"preparing_recovery",accepted=0,rejected=0,attempted=0)
        manifest,exe,b,matrix,contexts=prepared(original,out)
        pilot_dir=original/"pilot_recovery_audit_20261105"
        pilot_status=read(pilot_dir/"campaign_status.json")
        assert pilot_status["status"]=="pilot_recovery_audit_complete"
        p=pd.read_csv(pilot_dir/"point_feasibility.csv")
        assert len(p)==4*(len(b)+1)*len(contexts)
        assert not p.duplicated(["season","point_id"]).any()
        pilot={(r.season,r.point_id):Path(r.record) for r in p.itertuples()}
        vectors=matrix.to_dict("records")
        eval_root=out/"evaluations"
        (eval_root/"scratch").mkdir(parents=True,exist_ok=True)
        for season in contexts:
            (eval_root/"records"/season).mkdir(parents=True,exist_ok=True)
        ledgers_dir=out/"trajectory_decisions"
        ledgers_dir.mkdir(exist_ok=True)
        fixed={s:{n:manifest["fixed_payload_sha256"][s][n] for n in (c.filex,"SOIL.SOL","DSSBatch.v48")}
               for s,c in contexts.items()}
        width=len(b)+1
        accepted, ledgers = [], []
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for i in range(1,POOL_SIZE+1):
                path=ledgers_dir/f"trajectory_{i:04d}.json"
                status(out,"paired_recovery_running",accepted=len(accepted),rejected=len(ledgers)-len(accepted),
                       attempted=len(ledgers),current_candidate=i,reused_pilot_valid=pilot_status["valid_paired_trajectories"])
                item=read(path) if path.exists() else trajectory(out,contexts,pool,exe,i,width,vectors,pilot,fixed)
                if not path.exists():
                    write(path,item)
                assert item["trajectory_id"]==i
                ledgers.append(item)
                if item["status"]=="accepted":
                    accepted.append(i)
                print(f"candidate {i}: {item['status']}; {len(accepted)}/{TRAJECTORIES} accepted",flush=True)
                if len(accepted)==TRAJECTORIES:
                    break
        if len(accepted)!=TRAJECTORIES:
            status(out,"insufficient_feasible_trajectories",accepted=len(accepted),attempted=len(ledgers),
                   rejected=len(ledgers)-len(accepted))
            return
        coverage=seal_retained(out,manifest,b,matrix,accepted,ledgers)
        retained_points = pd.read_csv(out/"retained_point_map.csv")
        replay_checks = []
        status(out,"checking_retained_replays",accepted=len(accepted),attempted=len(ledgers),
               rejected=len(ledgers)-len(accepted))
        for season,ctx in contexts.items():
            for i in (0,TRAJECTORIES*width//2,TRAJECTORIES*width-1):
                match=retained_points.iloc[i]
                vector=vectors[int(match.candidate_point_id)]
                ref=read(out/"records"/season/f"point_{i:04d}.json")
                name=f"replay_retained_{i:04d}"
                cache=eval_root/"records"/season/f"{name}.json"
                if not cache.exists():
                    forward(eval_root,exe,ctx,name,vector,keep=True)
                # Read both records from disk so JSON treatment keys have the same type.
                result=read(cache)
                assert result["status"]=="ok" and result["actual"]==vector, (season,i)
                for field in ("input_sha256","responses","diagnostics"):
                    assert result[field]==ref[field], (season,i,field)
                replay_checks.append(dict(season=season,point_id=i,
                                          candidate_point_id=int(match.candidate_point_id),
                                          status="exact_match"))
        write(out/"retained_replay_audit.json",replay_checks)
        status(out,"simulation_complete",accepted=len(accepted),attempted=len(ledgers),
               rejected=len(ledgers)-len(accepted),conditional=True,coverage=coverage)
        review(out)
    except Exception as exc:
        prior=read(out/"campaign_status.json")
        status(out,"recovery_stopped",phase=prior["status"],error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        lock.unlink()


if __name__=="__main__":
    cli=argparse.ArgumentParser()
    cli.add_argument("--resume",action="store_true")
    main(cli.parse_args().resume)
