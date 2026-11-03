"""Whole-crop nitrate input experiments; synthetic scenarios, never fit targets."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,json,os,re,shutil,subprocess
import numpy as np
import pandas as pd
import lai_workflow as flow
from lai_workflow import OUT,CN,dump,sha

# Native OPTEMPXY2K format 77 serializes application rates as F5.0.
# Use exactly representable integer amounts in whole-crop experiments;
# the pure native kernel tests provide dense fractional supply gradients.
RATES=[0.,1.,2.,3.,4.,5.,6.,7.,8.,9.,10.,12.]
INITIAL_NO3=[.25,.5,.75,1.,1.5,2.,3.,4.,6.,8.,12.,16.]

def schedule(kind,run):
    d=np.arange(126);rate=RATES[run-1]
    if kind=='initial_N':return np.zeros(126)
    if kind in ['gradient','low_light']:return np.full(126,rate)
    if kind=='recovery':
        result=np.full(126,1.);resume=[0.,1.,2.,3.,4.,6.][(run-1)%6]
        if run<=6:result[(d>=35)&(d<85)]=0
        result[d>=85]=resume
        return result
    if kind=='pulse':
        rate=[1.,2.,4.][(run-1)%3]
        return np.full(126,rate) if (run-1)//3%2==0 else np.where(d%7==0,7*rate,0.)
    raise ValueError(kind)

def modify(work,kind):
    p=work/'XXQL2601.TMX';text=p.read_text(encoding='ascii')
    # Common soil/initial conditions/planting/irrigation/P-K inputs. Only N
    # schedules differ; original measured-treatment identities are not reused.
    start=text.index('*TREATMENTS');end=text.index('*CULTIVARS')
    header='*TREATMENTS                        -------------FACTOR LEVELS------------\n@N R O C TNAME.................... CU FL SA IC MP MI MF MR MC MT ME MH SM\n'
    rows=[]
    for i in range(1,13):
        original=next(l for l in text[start:end].splitlines() if re.match(r'^\s*'+str(i)+r'\s+1\s+0\s+0\b',l))
        prefix=f'{i:2d} 1 0 0 '+f'CTL_{kind[:6]}_{i:02d}'.ljust(25)
        levels=[1,2,2,i if kind=='initial_N' else 2,2,2,i,0,0,2,0,3,2]
        rows.append(prefix+''.join(f'{n:3d}' for n in levels))
    text=text[:start]+header+'\n'.join(rows)+'\n\n'+text[end:]
    # Identical small initial mineral pools at the native residual boundaries.
    lines=text.splitlines();in_initial=False;layer=False
    for i,line in enumerate(lines):
        if line.startswith('*'):in_initial=line.startswith('*INITIAL CONDITIONS');layer=False
        if in_initial and line.startswith('@'):layer='ICBL' in line
        elif in_initial and layer and line.strip() and not line.startswith('!'):
            fields=line.split()
            if fields[0]=='2':
                # Native IPSLIN format I3,F5,8(1X,F5): retain exactly 14
                # columns through SH2O, then two six-column mineral fields.
                lines[i]=line[:14]+f'{.5:6.2f}{.25:6.2f}'
                assert float(lines[i][15:20])==.5 and float(lines[i][21:26])==.25
    text='\n'.join(lines)+'\n'
    if kind=='initial_N':
        start=text.index('*INITIAL CONDITIONS');end=text.index('*PLANTING',start)
        block=text[start:end];headers=[m.start() for m in re.finditer(r'^@C\s+PCR\b',block,re.M)]
        originals=[]
        for j,pos in enumerate(headers):
            candidate=block[pos:headers[j+1] if j+1<len(headers) else len(block)]
            data=[l for l in candidate.splitlines() if l.strip() and not l.startswith('@')]
            if int(data[0].split()[0])==2:originals=candidate.splitlines()
        assert originals
        replacement=['*INITIAL CONDITIONS']
        for run,value in enumerate(INITIAL_NO3,1):
            layer=False
            for line in originals:
                if line.startswith('@'):
                    layer='ICBL' in line;replacement.append(line)
                elif line.strip():
                    line=f'{run:3d}'+line[3:]
                    if layer:line=line[:20]+f'{value:6.2f}'
                    replacement.append(line)
            replacement.append('')
        text=text[:start]+'\n'.join(replacement)+'\n'+text[end:]
    start=text.index('*FERTILIZERS');end=text.index('*RESIDUES',start)
    original=text[start:end].splitlines()
    pk=[]
    for line in original:
        fields=line.split()
        if len(fields)>=11 and fields[0]=='1' and float(fields[5])==0:pk.append(line[2:])
    fert=['*FERTILIZERS (INORGANIC)','@F FDATE  FMCD  FACD  FDEP  FAMN  FAMP  FAMK  FAMC  FAMO  FOCD FERNAME']
    schedules=[]
    for run in range(1,13):
        fert.extend(f'{run:2d}'+line for line in pk)
        for dap,amount in enumerate(schedule(kind,run)):
            date=f'26{73+dap:03d}'
            if amount>0:fert.append(f'{run:2d} {date} FE008 AP002 {10.:5.2f} {amount:5.2f}  0.00  0.00  0.00  0.00  0.00 CTL')
            schedules.append(dict(run=run,dap=dap,yrdoy=2026000+73+dap,nitrate_fertilizer_kgN_ha=float(amount),
                scenario=kind,synthetic=True))
    # Native management iterates applications in input order. Chronological
    # sorting must include the retained P/K applications, not just the N list.
    fert=fert[:2]+sorted(fert[2:],key=lambda line:(int(line[:2]),int(line[3:8])))
    text=text[:start]+'\n'.join(fert)+'\n\n'+text[end:]
    p.write_text(text,encoding='ascii')
    assert len(pk)>0 and len(rows)==12
    if kind=='low_light':
        p=work/'XXTW2403.WTH';lines=p.read_text(encoding='ascii').splitlines()
        for i,line in enumerate(lines):
            if re.match(r'^2026\d{3}\s',line):
                day=int(line[:7])-2026073
                if 35<=day<65:lines[i]=line[:7]+f'{float(line[7:13])*.25:6.1f}'+line[13:]
        p.write_text('\n'.join(lines)+'\n',encoding='ascii')
    pd.DataFrame(schedules).to_csv(work/'controlled_N_schedule.csv',index=False)
    # Read-back fixed columns that native FileX readers consume.
    current='';events=[];treatments=[]
    for line in text.splitlines():
        if line.startswith('*'):
            current=line
            continue
        if line.startswith('@') or not line.strip():continue
        if current.startswith('*TREATMENTS'):
            run=int(line[:2]);levels=list(map(int,line[34:].split()))
            assert levels[:6]==[1,2,2,run if kind=='initial_N' else 2,2,2] and levels[6]==run
            treatments.append(levels)
        if current.startswith('*FERTILIZERS') and line[9:14]=='FE008':
            events.append((int(line[:2]),int(line[3:8]),float(line[27:33])))
    expected=[(r['run'],int(str(r['yrdoy'])[2:]),r['nitrate_fertilizer_kgN_ha']) for r in schedules if r['nitrate_fertilizer_kgN_ha']>0]
    assert events==expected,(events[:2],expected[:2])
    assert len(treatments)==12
    return dict(scenario=kind,synthetic=True,not_observations=True,NO3_source='FE008 calcium nitrate; DETAIL.CDE',
        common_conditions='soil analysis 2, shared moisture/NH4 profile, planting 2, irrigation 2, same non-N fertilization',
        initial_NO3_ppm=INITIAL_NO3 if kind=='initial_N' else [.25]*12,
        nutrient_input_totals={str(i):float(schedule(kind,i).sum()) for i in range(1,13)},
        no_phenology_or_growth_calendar_guard=True)

def execute(item):
    revision,kind,variant=item
    b=json.loads((OUT/'frozen_baseline.json').read_text(encoding='utf8'))
    attempt='a4' if kind in ['recovery','initial_N'] else 'a3'
    work=OUT/'controlled'/f'{revision}_{kind}_{variant}_{attempt}';work.mkdir(parents=True,exist_ok=False)
    for filename in b['inputs']:shutil.copy2(Path(b['source'])/filename,work/filename)
    flow.p1.redirect(work/'DSSATPRO.v48',work)
    provenance=modify(work,kind)
    cfg=dict(b['config']);cfg.update(flow.variants()[variant])
    (work/'NIntegration.nml').write_text('&NINTEGRATION\n'+''.join(f' {k}={v:.17g}\n' for k,v in cfg.items())+'/\n')
    exe=OUT/'bin'/f'dscsm048_v4_lai_{revision}.exe'
    result=dict(name=work.name,config=cfg,provenance=provenance,binary_sha256=sha(exe),success=False,
        input_hashes={p.name:sha(p) for p in work.iterdir() if p.is_file()})
    try:
        env=os.environ.copy();env.update(DSSAT_N_CONFIG=str(work/'NIntegration.nml'),DSSAT_P0_TRACE='0')
        with (work/'stdout.log').open('wb') as so,(work/'stderr.log').open('wb') as se:
            r=subprocess.run([str(exe),'B','DSSBatch.v48'],cwd=work,env=env,stdout=so,stderr=se,timeout=240)
        assert r.returncode==0,(work/'stderr.log').read_text(errors='replace')[-2000:]
        assert re.search(r'Normal end of run\s+12\b',(work/'INFO.OUT').read_text())
        result['budget']=flow.p1.audit_c4(work,cfg)
        result['LAI_budget']=flow.audit_lai(work,cfg);result['rate_budget']=flow.audit_limits(work,cfg)
        result['P2_budget']=flow.p2.audit_p2(work,cfg)
        result['success']=True
    except Exception as e:result.update(error_type=type(e).__name__,error=str(e))
    dump(work/'receipt.json',result)
    print(work.name,'PASS' if result['success'] else 'FAIL',result.get('error',''),flush=True)
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--revision',default='r3');ap.add_argument('--scenario',choices=['all','gradient','recovery','pulse','low_light','initial_N'],default='all');a=ap.parse_args()
    scenarios=['gradient','recovery','pulse','low_light','initial_N'] if a.scenario=='all' else [a.scenario]
    tasks=[(a.revision,kind,variant) for kind in scenarios for variant in ['slow_reserve','lai_slow']]
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(execute,tasks))
    dump(OUT/f'controlled_receipts_{a.revision}_{a.scenario}.json',results)
    assert all(r['success'] for r in results),'Keep failures; do not relax budgets or use synthetic observations'
