"""Paired Morris experiment using two frozen rate-calibration inputs and native DSSAT."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.calibration.single_season_n import read_native
from src.common.experiment_inputs import parse_filex
from src.common.input_manifest import verify_calibrated_input_bundle
from tools.experiments.rebuild_current_bundles import read_summary

RUN_ID = "morris_dual_spring126_r40_20261105"
PLAN = "2025春新bundle_Morris敏感性分析待审方案_20261030.md"
EXE_HASH = "92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a"
SEED, LEVELS, STEP, TRAJECTORIES, WORKERS = 20261030, 6, 3, 40, 6
SLPF = {"25SP": .90, "26SP": .89}
GENOTYPE = tuple(f"TMGRO048.{x}" for x in ("CUL", "ECO", "SPE"))
SPE_FIELDS = {
    "PARMAX,PHTMAX": "PARMAX PHTMAX KCAN KC_SLOPE",
    "FNPGN(4),": "FNPGN(1) FNPGN(2) FNPGN(3) FNPGN(4)",
    "PGEFF SCV": "PGEFF SCV KDIF LFANGB",
    "SLWREF,SLWSLO": "SLWREF SLWSLO NSLOPE LNREF PGREF",
    "RNO3C,RNH4C": "RNO3C RNH4C RPRO RFIXN",
    "PROLFI,PROLFG": "PROLFI PROLFG PROLFF PROSTI PROSTG PROSTF",
    "PRORTI,PRORTG": "PRORTI PRORTG PRORTF PROSHI PROSHG PROSHF",
    "SDPROS,SDPROG": "SDPROS SDPROG PRONOD PROMIN PROMAX THETA",
    "PCARLF,PCARST": "PCARLF PCARST PCARRT PCARSH PCARSD PCARNO",
    "CMOBMX,CADSTF": "CMOBMX CADSTF CADPR1 NMOBMX NVSMOB NRCVR",
    "XPODF, NSTFAC": "XPODF NSTFAC",
    "ALPHL,ALPHS": "ALPHL ALPHS ALPHR ALPHSH",
    "YLEAF VALUES": "YLEAF(1) YLEAF(2) YLEAF(3) YLEAF(4)",
    "YSTEM VALUES": "YSTEM(1) YSTEM(2) YSTEM(3) YSTEM(4)",
    "WTFSD,PORPT": "WTFSD PORPT FRSTMF FRLFF ATOP FRCNOD",
    "FRLFMX": "FRLFMX",
    "FINREF,SLAREF": "FINREF SLAREF SIZREF VSSINK EVMODC",
    "SLAMAX,SLAMIN": "SLAMAX SLAMIN SLAPAR TURSLA NSLA",
    "SENRTE,SENRT2": "SENRTE SENRT2 SENDAY FREEZ1 FREEZ2",
    "ICMP,TCMP": "ICMP TCMP",
    "RTDEPI,RFAC1": "RTDEPI RFAC1 RTSEN RLDSM RTSDF RWUEP1 RWUMX",
    "XRTFAC,YRTFAC": "XRTFAC(1) YRTFAC(1) XRTFAC(2) YRTFAC(2)",
    "RTNO3,RTNH4": "RTNO3 RTNH4 PORMIN RTEXF",
    "SETMAX,SRMAX": "SETMAX SRMAX RFLWAB XMPAGE",
    "DSWBAR,XFRMAX": "DSWBAR XFRMAX SHLAG",
    "XSWFAC(1-4)": "XSWFAC(1) XSWFAC(2) XSWFAC(3) XSWFAC(4)",
    "YSWFAC(1-4)": "YSWFAC(1) YSWFAC(2) YSWFAC(3) YSWFAC(4)",
    "XSWBAR(1-5)": "XSWBAR(1) XSWBAR(2) XSWBAR(3) XSWBAR(4) XSWBAR(5)",
    "YSWBAR(1-5)": "YSWBAR(1) YSWBAR(2) YSWBAR(3) YSWBAR(4) YSWBAR(5)",
    "YTRFAC(1-4)": "YTRFAC(1) YTRFAC(2) YTRFAC(3) YTRFAC(4)",
    "KEP, EORATIO": "KEP EORATIO",
}
CORE = {
    "phenology": {"anthesis": ("ADAPS",), "first_seed": ("PDFPS",)},
    "canopy": {"lai_nodes": ("LAI45", "LAI67", "LAI95"), "lai_auc": ("LAI_AUC",)},
    "biomass": {"leaf": ("LWAD",), "stem": ("SWAD",), "aboveground": ("CWAD",)},
    "yield_harvest": {"fresh": ("CHFPW",), "dry": ("CHPDT",)},
}
CONTRAST = ("LAI_AUC", "SWAD", "CHPDT")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def status(run, state, **fields):
    write(run/"campaign_status.json", dict(status=state, updated_utc=datetime.now(timezone.utc).isoformat(),
                                          seed=SEED, trajectories=TRAJECTORIES, parameters=126, **fields))


def bounds(path):
    rows = re.findall(r"^\|([^|]+)\|(CUL|ECO|SPE)\|([.\d]+)\|([.\d]+)\|[^|]*\|$",
                      path.read_text(encoding="utf-8"), re.M)
    b = pd.DataFrame(rows, columns=["name","location","lower","upper"])
    b[["lower","upper"]] = b[["lower","upper"]].astype(float)
    if len(b) != 126 or not b.name.is_unique or not (b.upper > b.lower).all():
        raise ValueError("The approved 126-parameter table is invalid")
    return b


def single_line(lines, predicate):
    found = [i for i, line in enumerate(lines) if predicate(line)]
    if len(found) != 1:
        raise ValueError(f"Expected one native row, found {found}")
    return found[0]


def field_map(lines, ext):
    if ext in ("CUL","ECO"):
        identifier, header, skip, start = (
            ("TM0008 ", "@VAR#", 4, 36) if ext=="CUL" else ("TM0001 ", "@ECO#", 4, 30))
        i = single_line(lines, lambda l: l.startswith(identifier))
        cols = next(l for l in lines if l.startswith(header)).split()[skip:]
        return {name: (i,start+6*j) for j,name in enumerate(cols)}
    out = {}
    for marker, names in SPE_FIELDS.items():
        i = single_line(lines, lambda l: marker in l and not l.lstrip().startswith("!"))
        out.update({n:(i,j*6) for j,n in enumerate(names.split())})
    i = single_line(lines, lambda l: l.startswith("!") and "SENPOR........." in l)+1
    out.update({"SENPOR(4)":(i,18),"SENMAX(4)":(i,42)})
    for stage, label in enumerate(("VEGETATIVE DEVELOPMENT","EARLY REPRODUCTIVE DEVELOPMENT",
                                   "LATE REPRODUCTIVE DEVELOPMENT"),1):
        i = single_line(lines, lambda l: label in l)
        out.update({f"{n}{stage}":(i,6*j) for j,n in enumerate(("TB","TO1","TO2","TM"))})
    return out


def format_field(value):
    for places in range(9,-1,-1):
        raw = f"{value:.{places}f}"
        if "." in raw:
            raw = raw.rstrip("0")
        else:
            raw += "."
        if len(raw)>5 and raw.startswith("0."):
            raw = raw[1:]
        if len(raw)<=6:
            return raw.rjust(6)
    raise ValueError(f"Cannot represent {value} in six columns")


def read_field(line, offset):
    # Fortran fixed-width F fields ignore embedded blanks (BN).
    return float(line[offset:offset+6].replace(" ",""))


def design(b, trajectories=TRAJECTORIES):
    rng = np.random.default_rng(SEED)
    dimension = len(b)
    grid = np.empty((trajectories,dimension+1,dimension),dtype=np.int8)
    for tr in range(trajectories):
        directions = rng.choice([-1,1],dimension)
        start = rng.integers(0,LEVELS-STEP,dimension)+np.where(directions<0,STEP,0)
        grid[tr,0] = start
        for step, parameter in enumerate(rng.permutation(dimension),1):
            grid[tr,step] = grid[tr,step-1]
            grid[tr,step,parameter] += STEP*directions[parameter]
    assert grid.min()==0 and grid.max()==LEVELS-1
    levels = b.lower.to_numpy()+grid.reshape(-1,dimension)/(LEVELS-1)*(b.upper-b.lower).to_numpy()
    actual = np.array([[float(format_field(v)) for v in row] for row in levels])
    low, high = b.lower.to_numpy(), b.upper.to_numpy()
    assert np.all(actual>=low-1e-12) and np.all(actual<=high+1e-12)
    for trajectory in actual.reshape(trajectories,dimension+1,dimension):
        changed = np.abs(np.diff(trajectory,axis=0))>1e-12
        assert (changed.sum(axis=0)==1).all() and (changed.sum(axis=1)==1).all()
    return pd.DataFrame(levels,columns=b.name),pd.DataFrame(actual,columns=b.name)


def model_payload(bundle, destination, slpf):
    destination.mkdir()
    for f in bundle.iterdir():
        if f.suffix.upper() in {".TMX",".TMA",".TMT",".SOL",".WTH",".CUL",".ECO",".SPE"} or f.name=="DSSBatch.v48":
            shutil.copy2(f,destination/f.name)
    for name in ("DSSAT48.INH","DSSAT48.INP","DSSATPRO.v48"):
        shutil.copy2(ROOT/"data/templates"/name,destination/name)
    soil = destination/"SOIL.SOL"
    lines = soil.read_bytes().splitlines(keepends=True)
    i = single_line(lines, lambda l: l.startswith(b"@ SCOM"))+1
    span = list(re.finditer(rb"\S+",lines[i]))[6].span()
    a,b = span
    assert lines[i][a:b]==b".933"
    text = f"{slpf:.3f}"[1:].encode("ascii")
    assert len(text)==b-a
    lines[i] = lines[i][:a]+text+lines[i][b:]
    soil.write_bytes(b"".join(lines))


@dataclass
class Context:
    season: str
    payload: Path
    filex: str
    fields: dict
    mapping: dict
    doses: dict
    harvest: dict
    last_day: int
    templates: dict


def context(bundle, payload, season, b):
    filex = next(payload.glob("*.TMX"))
    trts = parse_filex(filex)["treatments"]
    metadata = pd.read_csv(bundle/"treatment_metadata.csv")
    mapping = {(r.water_level,r.nitrogen_level):int(r.treatment) for r in metadata.itertuples()}
    assert set(mapping.values())==set(trts)
    dose_by_factor = pd.read_csv(bundle/"fertilizer_event_audit.csv").groupby("施肥方案F")["N kg/ha"].sum()
    doses = {tn:float(dose_by_factor.loc[f["MF"]]) for tn,f in trts.items()}
    harvest_table = pd.read_csv(bundle/"harvest_schedule_audit.csv").dropna(subset=["model_output_date"])
    harvest = {tn:sorted(harvest_table.loc[harvest_table.factor.eq(f["MH"]),"model_output_date"])
               for tn,f in trts.items()}
    assert all(harvest.values())
    fields, templates = {}, {}
    for fn in GENOTYPE:
        ext = fn.split(".")[-1]
        lines = (payload/fn).read_text(encoding="utf-8").splitlines()
        if ext=="SPE":
            i = single_line(lines, lambda l: "XPODF, NSTFAC,NREXP,NRMIN" in l)
            lines[i] = lines[i][:12]+" "*27+"XPODF, NSTFAC"
        mapping_ext = field_map(lines,ext)
        for name in b.loc[b.location.eq(ext),"name"]:
            i,j = mapping_ext[name]
            read_field(lines[i],j)
            fields[name] = (ext,i,j)
        if ext=="CUL":
            fixed = {"CSDL":12.33,"PPSEN":0.,"FL-LF":400.,"SD-PM":400.}
            assert all(float(lines[i][j:j+6])==value for name,value in fixed.items()
                       for i,j in [mapping_ext[name]])
        templates[ext] = lines
    assert len(fields)==len(set(fields.values()))==126
    end = "2025-07-13" if season=="25SP" else "2026-07-17"
    return Context(season,payload,filex.name,fields,mapping,doses,harvest,
                   int(pd.Timestamp(end).strftime("%Y%j")),templates)


def genotype(work, ctx, vector, cleanup=True):
    lines = {ext:list(values) for ext,values in ctx.templates.items()}
    if not cleanup:
        return {}
    for name,value in vector.items():
        ext,i,j = ctx.fields[name]
        text = lines[ext][i]
        lines[ext][i] = text[:j]+format_field(value)+text[j+6:]
    actual = {}
    for ext,values in lines.items():
        path = work/f"TMGRO048.{ext}"
        path.write_text("\n".join(values)+"\n",encoding="ascii")
        reread = path.read_text(encoding="ascii").splitlines()
        assert reread==values
        for name,(part,i,j) in ctx.fields.items():
            if part==ext:
                actual[name] = read_field(reread[i],j)
    assert all(actual[name]==value for name,value in vector.items())
    return actual


class NativeOutputError(ValueError):
    """The official executable finished but did not produce valid responses."""


class NativeRunError(RuntimeError):
    """The official executable reported a failed simulation."""


def read_daily_output(path, season):
    try:
        return read_native(path)
    except ValueError as exc:
        treatment, header = None, None
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*TREATMENT\s+(\d+)",line)
            if match:
                treatment = match[1]
            if line.lstrip().startswith("@YEAR"):
                header = line.lstrip()[1:].split()
            parts = line.split()
            if header and len(parts)==len(header) and re.match(r"^20\d{2}\s",line.lstrip()):
                overflow = [name for name,value in zip(header,parts) if "*" in value]
                if overflow:
                    raise NativeOutputError(
                        f"{season} TN{treatment} {path.name} {parts[0]} DOY {parts[1]} "
                        f"native overflow: {', '.join(overflow)}") from exc
        raise NativeOutputError(f"{season} {path.name}: {exc}") from exc


def response_values(work, ctx):
    evaluate = (work/"Evaluate.OUT").read_text(encoding="utf-8").splitlines()
    header = next(l for l in evaluate if l.startswith("@RUN")).lstrip("@").split()
    phenology = {}
    for line in evaluate:
        parts = line.split()
        if parts and parts[0].isdigit():
            assert len(parts)==len(header)
            row = dict(zip(header,parts))
            phenology[int(row["TN"])] = {k:float(row[k]) for k in ("ADAPS","PDFPS")}
    plant,harvest,nitrogen,evap,water = (
        read_daily_output(work/name,ctx.season)
        for name in ("PlantGro.OUT","FreshWt.OUT","PlantN.OUT","ET.OUT","SoilWat.OUT")
    )
    summary = read_summary(work/"Summary.OUT")
    if len(summary)!=len(ctx.mapping) or set(summary.TRNO.astype(int))!=set(ctx.mapping.values()):
        raise NativeOutputError(f"{ctx.season} Summary.OUT does not contain all treatments")
    if not (summary.HDAT>=ctx.last_day).all():
        raise NativeOutputError(f"{ctx.season} Summary.OUT ends before the required date")
    rows = {}
    for tn,dates in ctx.harvest.items():
        crop = plant.loc[tn].set_index("DAP")
        if crop.index.has_duplicates or not all(d in crop.index for d in range(96)):
            raise NativeOutputError(f"{ctx.season} TN{tn} PlantGro.OUT lacks a unique DAP 0–95 series")
        try:
            terminal = harvest.loc[(tn,dates[-1])]
            events = harvest.loc[[(tn,d) for d in dates]]
        except KeyError as exc:
            raise NativeOutputError(f"{ctx.season} TN{tn} missing required harvest date") from exc
        if events.CHNUM.tolist()!=list(range(1,len(dates)+1)):
            raise NativeOutputError(f"{ctx.season} TN{tn} unexpected harvest events {events.CHNUM.tolist()}")
        for name in ("CHFPW","CHPDT"):
            if not np.all(np.diff(events[name])>=-1e-9):
                raise NativeOutputError(f"{ctx.season} TN{tn} cumulative {name} decreased")
        values = phenology[tn] | {f"LAI{d}":float(crop.loc[d,"LAID"]) for d in (45,67,95)}
        values["LAI_AUC"] = float(np.trapezoid(crop.loc[list(range(96)),"LAID"].to_numpy()))
        values.update({name:float(crop.loc[95,name]) for name in ("LWAD","SWAD","CWAD")})
        values.update({name:float(terminal[name]) for name in ("CHFPW","CHPDT","CHNUM","CPODN")})
        n = nitrogen.loc[(tn,dates[-1])]
        et = evap.loc[(tn,dates[-1])]
        wt = water.loc[(tn,dates[-1])]
        pg = plant.loc[(tn,dates[-1])]
        values.update({name:float(n[name]) for name in ("NUPC","LNAD","SNAD","LN%D","SN%D")})
        values.update({name:float(et[name]) for name in ("EOAC","EPAC","ESAC","ETAC")})
        values.update({name:float(wt[name]) for name in wt.index if re.fullmatch(r"SW\d+D",name)})
        values.update({name:float(pg[name]) for name in ("RDPD","RWAD","GWAD","P#AD")})
        values.update({f"{name}_DAP0_95_sum":float(crop.loc[list(range(96)),name].sum()) for name in ("WSPD","WSGD","NSTD")})
        seed, shell = float(terminal.MTDSD),float(terminal.MTDSH)
        values["mature_fruit_n_pct"] = None if seed+shell<=0 else float(
            (float(n["GN%D"])*seed+float(n.SHND)*shell)/(seed+shell))
        rows[tn] = values
    required = {}
    shared = {(w,f"N{i}"):ctx.mapping[w,f"N{i}"] for w in ("W1","W3") for i in range(4)}
    for (water_level,nitrogen_level),tn in shared.items():
        for group,families in CORE.items():
            for family,features in families.items():
                for feature in features:
                    value = rows[tn][feature]
                    if not np.isfinite(value) or value<0:
                        raise NativeOutputError(f"{ctx.season} TN{tn} required response {feature}={value:g}")
                    required[f"{group}|{family}|{feature}_{water_level}_{nitrogen_level}"] = value
    for feature in CONTRAST:
        for nlevel in range(4):
            n = f"N{nlevel}"
            required[f"water_response|{feature}|W3-W1_{n}"] = rows[shared["W3",n]][feature]-rows[shared["W1",n]][feature]
        for nlevel in range(3):
            lo,hi = f"N{nlevel}",f"N{nlevel+1}"
            slopes = {}
            for water_level in ("W1","W3"):
                tnlo,tnhi = shared[water_level,lo],shared[water_level,hi]
                gap = ctx.doses[tnhi]-ctx.doses[tnlo]
                assert gap>0
                slopes[water_level] = (rows[tnhi][feature]-rows[tnlo][feature])/gap
                required[f"nitrogen_response|{feature}|{water_level}_{hi}-{lo}"] = slopes[water_level]
            required[f"water_nitrogen_interaction|{feature}|{hi}-{lo}"] = slopes["W3"]-slopes["W1"]
    if not np.isfinite(list(required.values())).all():
        raise NativeOutputError(f"{ctx.season} nonfinite required response")
    return required, rows


def forward(run, exe, ctx, label, vector, *, cleanup=True, keep=False):
    record_dir = run/"records"/ctx.season
    record = record_dir/f"{label}.json"
    with TemporaryDirectory(prefix=f"{ctx.season}_{label}_",dir=run/"scratch") as temp:
        work = Path(temp)
        for p in ctx.payload.iterdir():
            shutil.copy2(p,work/p.name)
        try:
            actual = genotype(work,ctx,vector,cleanup)
            payload_hashes = {name:sha(work/name) for name in (*GENOTYPE,ctx.filex,"SOIL.SOL","DSSBatch.v48")}
            with (work/"model.log").open("wb") as log:
                proc = subprocess.run([str(exe),"CRGRO048","B","DSSBatch.v48"],cwd=work,
                                      stdout=log,stderr=subprocess.STDOUT,timeout=150)
            if proc.returncode:
                raise NativeRunError(f"DSSAT exit code {proc.returncode}")
            error = work/"ERROR.OUT"
            if error.exists() and error.read_text(errors="replace").strip():
                raise NativeRunError(error.read_text(errors="replace").strip()[:3000])
            values, diagnostics = response_values(work,ctx)
            result = dict(status="ok", season=ctx.season, label=label, actual=actual,
                          responses=values, diagnostics=diagnostics, input_sha256=payload_hashes)
        except Exception as exc:
            failure_kind = ("native_output" if isinstance(exc,NativeOutputError) else
                            "native_run" if isinstance(exc,NativeRunError) else
                            "timeout" if isinstance(exc,subprocess.TimeoutExpired) else "execution_or_contract")
            result = dict(status="failed", season=ctx.season, label=label,
                          failure_kind=failure_kind,
                          error=f"{type(exc).__name__}: {exc}",vector=vector)
        if keep or result["status"]!="ok":
            save = run/"native_evidence"/ctx.season/label
            save.mkdir(parents=True)
            for p in work.iterdir():
                if p.is_file():
                    shutil.copy2(p,save/p.name)
            result["native_evidence"]=str(save)
        write(record,result)
        return result


def phase(run, exe, tasks, state):
    failures = []
    status(run,state,finished=0,planned=len(tasks),failures=0)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        pending = {pool.submit(forward,run,exe,*task):task for task in tasks}
        for done,future in enumerate(as_completed(pending),1):
            result = future.result()
            if result["status"]!="ok":
                failures.append(result)
            if done%12==0 or failures or done==len(tasks):
                status(run,state,finished=done,planned=len(tasks),failures=len(failures))
            if failures:
                for item in pending:
                    item.cancel()
                break
    if failures:
        write(run/"gate_failure.json",{"phase":state,"first_failures":failures})
        raise RuntimeError(f"{state}: {failures[0]['error']}")


def main():
    run = ROOT/"workspace/runs"/RUN_ID
    run.mkdir(parents=True,exist_ok=False)
    try:
        status(run,"preparing")
        (run/"scratch").mkdir()
        plan = ROOT/"docs/reports"/PLAN
        shutil.copy2(plan,run/"approved_plan.md")
        shutil.copy2(__file__,run/Path(__file__).name)
        b = bounds(plan)
        nom, actual = design(b)
        b["center"] = [float(format_field((lo+hi)/2)) for lo,hi in zip(b.lower,b.upper)]
        b.to_csv(run/"approved_bounds.csv",index=False)
        nom.to_csv(run/"morris_X_nominal.csv",index_label="point_id")
        actual.to_csv(run/"morris_X_serialized.csv",index_label="point_id")
        exe = run/"DSCSM048.EXE"
        shutil.copy2("C:/DSSAT48/DSCSM048.EXE",exe)
        assert sha(exe)==EXE_HASH
        index = json.loads((ROOT/"configs/experiments/current_bundles.json").read_text())
        contexts = []
        for season,entry in index["bundles"].items():
            bundle = ROOT/"data/user/experiments"/entry["bundle_id"]
            assert verify_calibrated_input_bundle(bundle).manifest_sha256==entry["manifest_sha256"]
            payload = run/f"{season}_fixed_inputs"
            model_payload(bundle,payload,SLPF[season])
            ctx = context(bundle,payload,season,b)
            (run/"records"/season).mkdir(parents=True)
            contexts.append(ctx)
        assert len(contexts)==2 and contexts[0].fields==contexts[1].fields and contexts[0].templates==contexts[1].templates
        field_rows = [dict(name=n,file=f"TMGRO048.{ext}",line=i+1,first_column=j+1,last_column=j+6)
                      for n,(ext,i,j) in contexts[0].fields.items()]
        pd.DataFrame(field_rows).to_csv(run/"native_field_mapping.csv",index=False)
        write(run/"run_manifest.json",dict(run_id=RUN_ID,official_dssat_sha256=sha(exe),slpf=SLPF,
              sasc="native bundle default -99",seed=SEED,r=TRAJECTORIES,p=LEVELS,delta=STEP/(LEVELS-1),
              input_bundles=index["bundles"],plan_sha256=sha(run/"approved_plan.md"),runner_sha256=sha(Path(__file__)),
              design_sha256=sha(run/"morris_X_serialized.csv"),bounds_sha256=sha(run/"approved_bounds.csv"),
              fixed_payload_sha256={c.season:{p.name:sha(p) for p in sorted(c.payload.iterdir())} for c in contexts},
              treatment_mapping={c.season:{f"{w}_{n}":t for (w,n),t in c.mapping.items()} for c in contexts},
              actual_n_doses={c.season:c.doses for c in contexts},
              approved_by_user=True,maximum_concurrent_model_processes=WORKERS))
        center = b.set_index("name").center.to_dict()
        status(run,"baseline_preflight")
        for c in contexts:
            raws = [forward(run,exe,c,"source_raw",{},cleanup=False,keep=True),
                    forward(run,exe,c,"source_clean",{},keep=True),
                    forward(run,exe,c,"center_1",center,keep=True),
                    forward(run,exe,c,"center_2",center,keep=True)]
            for record in raws:
                if record["status"]!="ok":
                    write(run/"gate_failure.json",{"phase":"baseline_preflight","first_failures":[record]})
                    raise RuntimeError(record["error"])
            assert raws[0]["responses"]==raws[1]["responses"] and raws[0]["diagnostics"]==raws[1]["diagnostics"]
            assert raws[2]["responses"]==raws[3]["responses"] and raws[2]["diagnostics"]==raws[3]["diagnostics"]
            info=(run/"native_evidence"/c.season/"source_clean"/"INFO.OUT").read_text(errors="replace")
            native_slpf=re.findall(r"^\s*0\.13\s+0\.65\s+75\.0\s+1\.00\s+(\d\.\d+)\s+SA001",info,re.M)
            assert len(native_slpf)==len(c.mapping) and all(float(x)==SLPF[c.season] for x in native_slpf)
        boundary = []
        for c in contexts:
            for i,row in enumerate(b.itertuples()):
                for edge in ("lower","upper"):
                    value=float(getattr(row,edge))
                    assert value==float(format_field(value)),(row.name,edge)
                    boundary.append((c,f"boundary_{i:03d}_{edge}",center|{row.name:value}))
        phase(run,exe,boundary,"boundary_preflight")
        table=actual.to_dict("records")
        pilot_n=4*(len(b)+1)
        phase(run,exe,[(c,f"point_{i:04d}",table[i]) for i in range(pilot_n) for c in contexts],"paired_pilot")
        phase(run,exe,[(c,f"point_{i:04d}",table[i]) for i in range(pilot_n,len(actual)) for c in contexts],"formal_running")
        status(run,"deterministic_replays")
        for c in contexts:
            for i in (0,len(actual)//2,len(actual)-1):
                replay=forward(run,exe,c,f"replay_{i:04d}",table[i],keep=True)
                original=json.loads((run/"records"/c.season/f"point_{i:04d}.json").read_text(encoding="utf-8"))
                assert replay["status"]=="ok" and replay["responses"]==original["responses"] and replay["diagnostics"]==original["diagnostics"]
        status(run,"simulation_complete",formal_forward_calls=len(actual)*2,pilot_reused=True)
    except Exception as exc:
        prior=json.loads((run/"campaign_status.json").read_text(encoding="utf-8"))
        status(run,"stopped",phase=prior["status"],error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
