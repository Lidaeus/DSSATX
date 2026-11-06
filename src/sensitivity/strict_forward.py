"""Forward-record and required-response policy for versioned strict SA runs."""
from pathlib import Path
import csv
import hashlib
import json
import math
import re
import uuid
import zipfile


def validate_parameter_domain(frame):
    """Keep the reference photosynthesis denominator positive throughout a box."""
    rows={str(r['name']).upper():r for r in frame.to_dict('records')
          if str(r['status']).lower() in {'active','fixed'}}
    if {'LNREF','FNPGN1'} <= rows.keys():
        if float(rows['LNREF']['lower']) <= float(rows['FNPGN1']['upper']):
            raise ValueError('Reference N domain must guarantee lower(LNREF) > upper(FNPGN1); '
                             'otherwise QDR reference photosynthesis can be zero')


def validate_responses(values, contract):
    required = contract.get('ranking_observations', [])
    missing = [n for n in required if n not in values or values[n] is None
               or not math.isfinite(float(values[n]))
               or (not n.startswith('WN_') and float(values[n]) == -99.0)]
    if missing:
        raise ValueError('Required sensitivity responses missing/nonfinite: ' + ', '.join(missing))


def preserve_record(run_dir, workspace, parameters, values, error, elapsed):
    run_dir, workspace = Path(run_dir), Path(workspace)
    target = workspace / '_sa_records' / uuid.uuid4().hex
    target.mkdir(parents=True, exist_ok=False)
    payload = {'parameters': parameters, 'responses': values, 'error': error,
               'status': 'failed' if error else 'completed', 'elapsed_seconds': elapsed}
    payload['parameter_hash'] = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()
    (target/'record.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    # Preserve native evidence without duplicating the 10 MB executable per call.
    with zipfile.ZipFile(target/'native.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as z:
        for p in run_dir.iterdir():
            if p.is_file() and (p.suffix.upper() in {'.OUT','.TMX','.SOL','.CUL','.ECO','.SPE','.CSV','.TXT','.BASE'}):
                z.write(p, p.name)
    return target


def read_genotype_parameters(directory, cultivar='TM0008'):
    """Read serialized scalar/anchor fields for independent EE step evidence."""
    directory = Path(directory)
    out = {}
    for ext, header, row_id in [('CUL','@VAR#',cultivar),('ECO','@ECO#','TM0001')]:
        lines = (directory/f'TMGRO048.{ext}').read_text(encoding='utf-8').splitlines()
        h = next(x for x in lines if x.startswith(header)).split()
        row = next(x for x in lines if x.startswith(row_id))
        # The first cultivar/ecotype data field starts at the header's MG or CSDL.
        if ext == 'CUL':
            names = h[4:]
            numbers = re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)', row[36:])
        else:
            names = h[2:]
            numbers = row[24:].split()
        if len(numbers) != len(names):
            raise ValueError(f'{ext} readback column count: {len(numbers)} != {len(names)}')
        out.update(zip(names, map(float,numbers)))
    lines = (directory/'TMGRO048.SPE').read_text(encoding='utf-8').splitlines()
    anchors = [
        ('PARMAX,PHTMAX', ['PARMAX','PHTMAX','KCAN','KC_SLOPE']),
        ('PROLFI,PROLFG,PROLFF', ['PROLFI','PROLFG','PROLFF','PROSTI','PROSTG','PROSTF']),
        ('PRORTI,PRORTG,PRORTF', ['PRORTI','PRORTG','PRORTF','PROSHI','PROSHG','PROSHF']),
        ('CMOBMX,CADSTF', ['CMOBMX','CADSTF','CADPR1','NMOBMX','NVSMOB','NRCVR']),
        ('FNPGN(4)', ['FNPGN1','FNPGN2','FNPGN3','FNPGN4']),
        ('SLWREF,SLWSLO', ['SLWREF','SLWSLO','NSLOPE','LNREF','PGREF']),
        ('WTFSD,PORPT', ['WTFSD','PORPT','FRSTMF','FRLFF','ATOP','FRCNOD']),
        ('FINREF,SLAREF', ['FINREF','SLAREF','SIZREF','VSSINK','EVMODC']),
        ('RTDEPI,RFAC1', ['RTDEPI','RFAC1','RTSEN','RLDSM','RTSDF','RWUEP1','RWUMX']),
        ('RTNO3,RTNH4', ['RTNO3','RTNH4','PORMIN','RTEXF']),
        ('SENRTE,SENRT2', ['SENRTE','SENRT2','SENDAY']),
        ('ICMP,TCMP', ['ICMP','TCMP']),
        ('PGEFF SCV KDIF', ['PGEFF']), ('DSWBAR,XFRMAX', ['DSWBAR']),
    ]
    for anchor,names in anchors:
        line = next((x for x in lines if anchor in x), None)
        if line:
            numbers = re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)', line)[:len(names)]
            out.update(zip(names,map(float,numbers)))
    for stage,label in enumerate(['VEGETATIVE','EARLY','LATE'],start=1):
        line = next(x for x in lines if label in x and 'DEVELOPMENT' in x)
        nums = line.split()[:4]
        out.update(zip([f'TB{stage}',f'TO1{stage}',f'TO2{stage}',f'TM{stage}'],map(float,nums)))
    line = next(x for x in lines if 'XPODF' in x and 'NSTFAC' in x)
    out['NSTFAC'] = float(re.findall(r'[-+]?(?:\d+\.?\d*|\.\d+)',line[:line.index('XPODF')])[0])
    for i,line in enumerate(lines):
        if 'SENPOR.........' in line:
            nums = list(map(float,lines[i+1].split()[:8]))
            out['SENPOR_LATE'],out['SENMAX_LATE'] = nums[3],nums[7]
        for name,marker,idx in [('SWBAR_REC','XSWBAR',2),('YSWBAR_MID','YSWBAR',2)]:
            if marker+'(' in line:
                out[name] = float(line.split()[idx])
    # P coefficients live in the named phosphorus tables.
    for line in lines:
        for prefix in ('OPTLFP','OPTSTP','OPTSDP'):
            if prefix+'-EM' in line and not line.lstrip().startswith('!'):
                out[prefix+'_FS'] = float(line.split()[2])
    return {k.upper():v for k,v in out.items()}
