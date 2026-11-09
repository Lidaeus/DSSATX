"""Re-evaluate the approved paired Morris design on the final spring split."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import shutil

import pandas as pd

import resume_dual_spring_morris_20261105 as paired
import run_dual_spring_morris_20261105 as model
from src.common.input_manifest import verify_calibrated_input_bundle, verify_manifest_integrity

ROOT = model.ROOT
RUN = ROOT / "workspace/runs/morris_dual_spring126_r40_final_bundles_sasc_default_20261107"
PRIOR = ROOT / "workspace/runs/morris_dual_spring126_r40_20261105_paired_feasible"
REFERENCE = ROOT / "workspace/runs/eggplant_26sp_final_cal25sp_old_val_c31pst_gradient_80x4_20261106"
SEASONS = ("25SP", "26SP")
SLPF = {"25SP": .92, "26SP": .89}
READ = paired.read
STATUS = model.status
WRITE = model.write


def default_sasc(content):
    """Normalize just the last soil-analysis field, preserving file layout."""
    lines = content.splitlines(keepends=True)
    in_soil, columns, count, changed = False, [], 0, 0
    for i,line in enumerate(lines):
        if line.startswith(b"*"):
            in_soil = line.startswith(b"*SOIL ANALYSIS")
            columns = []
        if not in_soil:
            continue
        fields = line.split()
        if not fields or fields[0].startswith((b"!", b"*")):
            continue
        if fields[0].startswith(b"@"):
            columns = fields
        elif b"SABL" in columns:
            assert columns[-1] == b"SASC" and len(fields) == len(columns)
            count += 1
            if float(fields[-1]) != -99:
                last = list(re.finditer(rb"\S+", line))[-1]
                assert last.end()-last.start() >= 3
                lines[i] = line[:last.start()] + b"-99".rjust(last.end()-last.start()) + line[last.end():]
                changed += 1
    return b"".join(lines), count, changed


def prepare():
    old = READ(PRIOR / "run_manifest.json")
    ref_path = REFERENCE / "design.json"
    ref = READ(ref_path)
    assert model.sha(ref_path) == READ(REFERENCE / "sealed_design.json")["sha256"]
    assert ref["SLPF"] == SLPF and ref["SASC"] == -99 and ref["ICNS"] == 1
    assert (old["seed"], old["p"], old["delta"], old["r"]) == (model.SEED, 6, .6, model.TRAJECTORIES)
    bounds = RUN / "approved_bounds.csv"
    stream = RUN / "candidate_stream_serialized.csv"
    exe = RUN / "DSCSM048.EXE"
    plan = RUN / "approved_plan.md"
    old_plan = ROOT / "workspace/runs" / model.RUN_ID / "approved_plan.md"
    for source, target, digest in (
        (PRIOR/"approved_bounds.csv", bounds, old["bounds_sha256"]),
        (PRIOR/"candidate_stream_serialized.csv", stream, old["candidate_stream_sha256"]),
        (Path("C:/DSSAT48/DSCSM048.EXE"), exe, model.EXE_HASH),
        (old_plan, plan, old["plan_sha256"]),
    ):
        assert model.sha(source) == digest, source
        if not target.exists():
            shutil.copy2(source, target)
        assert model.sha(target) == digest, target
    b = pd.read_csv(bounds, float_precision="round_trip")
    matrix = pd.read_csv(stream, index_col=0, float_precision="round_trip")
    assert len(b) == 126 and len(matrix) == paired.POOL_SIZE * (len(b)+1)
    assert list(matrix) == b.name.tolist()
    assert (b.loc[b.name.eq("RWUMX"), ["lower","upper"]].to_numpy() == [.02,.06]).all()

    contexts, fixed_hashes, input_bundles = {}, {}, {}
    audit = []
    for season in SEASONS:
        entry = ref["datasets"][season]
        bundle = Path(entry["path"])
        verified = verify_calibrated_input_bundle(bundle) if season == "26SP" else verify_manifest_integrity(bundle)
        assert verified.manifest_sha256 == entry["manifest_sha256"]
        payload = RUN / f"{season}_fixed_inputs"
        if not payload.exists():
            model.model_payload(bundle, payload, SLPF[season])
        reference = REFERENCE / f"{season}_inputs"
        filex = next(reference.glob("*.TMX"))
        expected_hashes = {f.name: ref["source_hashes"][str(f)] for f in reference.iterdir()}
        assert model.sha(filex) == expected_hashes[filex.name]
        original = filex.read_bytes()
        target, count, changed = default_sasc(original)
        staged = payload / filex.name
        if staged.read_bytes() == original and changed:
            staged.write_bytes(target)
        assert staged.read_bytes() == target
        assert default_sasc(staged.read_bytes()) == (target,count,0)
        fixed_hashes[season] = {f.name: model.sha(f) for f in sorted(payload.iterdir())}
        assert fixed_hashes[season] == (expected_hashes | {filex.name:model.sha(staged)})
        ctx = model.context(bundle, payload, season, b)
        assert set(ctx.mapping.values()) == set(entry["treatments"])
        assert count == len(ctx.mapping)*10
        contexts[season] = ctx
        input_bundles[season] = entry
        audit.append(dict(season=season,bundle=entry["bundle_id"],role=entry["role"],SLPF=SLPF[season],
                          SASC=-99,rows_verified=count,rows_changed=changed,initial_mineral_n_scale=1))
    assert contexts["25SP"].fields == contexts["26SP"].fields
    assert contexts["25SP"].templates == contexts["26SP"].templates
    pd.DataFrame(audit).to_csv(RUN/"fixed_input_audit.csv", index=False)
    manifest = dict(run_id=RUN.name, official_dssat_sha256=model.sha(exe), slpf=SLPF,
        sasc="native default marker -99 in both TMX files", sasc_marker=-99, seed=model.SEED, r=model.TRAJECTORIES,
        p=model.LEVELS, delta=model.STEP/(model.LEVELS-1), input_bundles=input_bundles,
        plan_sha256=model.sha(plan), runner_sha256=model.sha(Path(model.__file__)),
        campaign_runner_sha256=model.sha(Path(__file__)), bounds_sha256=model.sha(bounds),
        candidate_stream_sha256=model.sha(stream), prior_design_run=PRIOR.name, historical_evaluations_reused=False,
        calibration_reference_design_sha256=model.sha(ref_path), fixed_payload_sha256=fixed_hashes,
        treatment_mapping={s:{f"{w}_{n}":t for (w,n),t in c.mapping.items()} for s,c in contexts.items()},
        actual_n_doses={s:{str(t):v for t,v in c.doses.items()} for s,c in contexts.items()},
        approved_by_user=True, maximum_concurrent_model_processes=model.WORKERS)
    prepared = RUN/"prepared_inputs.json"
    if prepared.exists():
        assert READ(prepared) == manifest, "Prepared sources changed since previous start"
    else:
        WRITE(prepared,manifest)
    return manifest, exe, b, matrix, contexts


def run_preflight(exe, b, contexts, pool):
    preflight = RUN/"preflight"
    (preflight/"scratch").mkdir(parents=True,exist_ok=True)
    center = b.set_index("name").center.to_dict()
    STATUS(RUN,"baseline_preflight")
    for season,ctx in contexts.items():
        (preflight/"records"/season).mkdir(parents=True,exist_ok=True)
        cases = [("source_raw",{},False),("source_clean",{},True),("center_1",center,True),("center_2",center,True)]
        results = []
        for label,vector,cleanup in cases:
            record = preflight/"records"/season/f"{label}.json"
            result = READ(record) if record.exists() else model.forward(
                preflight,exe,ctx,label,vector,cleanup=cleanup,keep=True)
            if result["status"] != "ok":
                raise RuntimeError(f"{season} {label}: {result['error']}")
            results.append(result)
        for field in ("responses","diagnostics"):
            assert results[0][field] == results[1][field] and results[2][field] == results[3][field]
        info = (preflight/"native_evidence"/season/"source_clean"/"INFO.OUT").read_text(errors="replace")
        native_slpf = re.findall(r"^\s*0\.13\s+0\.65\s+75\.0\s+1\.00\s+(\d\.\d+)\s+SA001",info,re.M)
        assert len(native_slpf) == len(ctx.mapping) and all(float(x) == SLPF[season] for x in native_slpf)

    def check(task):
        ctx,label,vector = task
        record = preflight/"records"/ctx.season/f"{label}.json"
        result = READ(record) if record.exists() else model.forward(preflight,exe,ctx,label,vector)
        if result["status"] != "ok" and result["failure_kind"] not in {"native_output","native_run"}:
            raise RuntimeError(f"{ctx.season} {label}: {result['error']}")
        return dict(season=ctx.season,point=label,status=result["status"],error=result.get("error",""))

    tasks = [(ctx,f"boundary_{i:03d}_{edge}",center | {row.name:float(getattr(row,edge))})
             for ctx in contexts.values() for i,row in enumerate(b.itertuples()) for edge in ("lower","upper")]
    rows = []
    for start in range(0,len(tasks),model.WORKERS):
        rows.extend(pool.map(check,tasks[start:start+model.WORKERS]))
        STATUS(RUN,"boundary_preflight",finished=len(rows),planned=len(tasks),
               native_failures=sum(x["status"]!="ok" for x in rows))
    pd.DataFrame(rows).to_csv(RUN/"boundary_preflight.csv",index=False)


def execute(resume):
    RUN.mkdir(exist_ok=True)
    if not resume and (RUN/"prepared_inputs.json").exists():
        raise FileExistsError(f"Existing campaign {RUN}; use --resume")
    lock = RUN/"running.lock"
    with lock.open("x",encoding="ascii") as f:
        f.write(str(os.getpid()))
    try:
        STATUS(RUN,"preparing")
        manifest,exe,b,matrix,contexts = prepare()
        width = len(b)+1
        vectors = matrix.to_dict("records")
        eval_root = RUN/"evaluations"
        (eval_root/"scratch").mkdir(parents=True,exist_ok=True)
        for s in SEASONS:
            (eval_root/"records"/s).mkdir(parents=True,exist_ok=True)
        ledger_dir = RUN/"trajectory_decisions"
        ledger_dir.mkdir(exist_ok=True)
        fixed = {s:{n:manifest["fixed_payload_sha256"][s][n] for n in (c.filex,"SOIL.SOL","DSSBatch.v48")}
                 for s,c in contexts.items()}
        accepted,ledgers = [],[]
        with ThreadPoolExecutor(max_workers=model.WORKERS) as pool:
            run_preflight(exe,b,contexts,pool)
            for i in range(1,paired.POOL_SIZE+1):
                STATUS(RUN,"paired_morris_running",accepted=len(accepted),rejected=len(ledgers)-len(accepted),
                       attempted=len(ledgers),current_candidate=i)
                path = ledger_dir/f"trajectory_{i:04d}.json"
                result = READ(path) if path.exists() else paired.trajectory(
                    RUN,contexts,pool,exe,i,width,vectors,{},fixed)
                if not path.exists():
                    WRITE(path,result)
                assert result["trajectory_id"] == i
                ledgers.append(result)
                if result["status"] == "accepted":
                    accepted.append(i)
                print(f"candidate {i}: {result['status']}; {len(accepted)}/{model.TRAJECTORIES} accepted",flush=True)
                if len(accepted)==model.TRAJECTORIES:
                    break
        counts = dict(accepted=len(accepted),attempted=len(ledgers),rejected=len(ledgers)-len(accepted))
        if len(accepted)!=model.TRAJECTORIES:
            STATUS(RUN,"insufficient_feasible_trajectories",**counts)
            return
        coverage = paired.seal_retained(RUN,manifest,b,matrix,accepted,ledgers)
        STATUS(RUN,"checking_retained_replays",coverage=coverage,**counts)
        retained = pd.read_csv(RUN/"retained_point_map.csv")
        checks = []
        for season,ctx in contexts.items():
            for i in (0,len(retained)//2,len(retained)-1):
                point = int(retained.iloc[i].candidate_point_id)
                label = f"replay_retained_{i:04d}"
                original = READ(RUN/"records"/season/f"point_{i:04d}.json")
                cache = eval_root/"records"/season/f"{label}.json"
                if not cache.exists():
                    model.forward(eval_root,exe,ctx,label,vectors[point],keep=True)
                replay = READ(cache)
                assert replay["status"]=="ok" and replay["actual"]==vectors[point]
                assert all(replay[k]==original[k] for k in ("input_sha256","responses","diagnostics"))
                checks.append(dict(season=season,point_id=i,candidate_point_id=point,status="exact_match"))
        WRITE(RUN/"retained_replay_audit.json",checks)
        STATUS(RUN,"simulation_complete",conditional=True,coverage=coverage,**counts)
        paired.review(RUN)
        state = READ(RUN/"campaign_status.json")
        WRITE(RUN/"campaign_status.json",state | {"pilot_reused":False,"historical_evaluations_reused":False})
    except Exception as exc:
        prior = READ(RUN/"campaign_status.json")
        STATUS(RUN,"stopped",phase=prior["status"],error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume",action="store_true")
    execute(parser.parse_args().resume)
