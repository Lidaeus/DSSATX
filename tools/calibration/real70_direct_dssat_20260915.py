import os, shutil, subprocess, sys, re, json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
W = ROOT / 'workspace/reports/fullgen98v2_real70_22tmt_20260915'
DET = W / 'det_direct'
DC = ROOT / 'workspace/runs/full_genetic_98pct_v2_20260915/det_calib'

if DET.exists():
    shutil.rmtree(DET)
shutil.copytree(DC, DET)

# 22-treatment batch
lines = ["$BATCH(TOMATO_CAL)", "!", "! real70 full 22-treatment replay", "!",
         "@FILEX" + " "*88 + "TRTNO" + "     RP" + "     SQ" + "     OP" + "     CO"]
for tr in [2,3,4,5,9,10,11,12,13,14]:
    lines.append("XXQL2501.TMX" + " "*84 + str(tr).rjust(6) + "      1      0      0      0")
    lines.append("")
for tr in range(1,13):
    lines.append("XXQL2601.TMX" + " "*84 + str(tr).rjust(6) + "      1      0      0      0")
    lines.append("")
(DET / "DSSBatch.v48").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8", newline="")

# inject real70 params into ECO
p = pd.read_csv(W / 'det_real70/params.csv')
params = dict(zip(p['name'].astype(str).str.lower(), pd.to_numeric(p['value'], errors='coerce')))

eco_path = DET / 'TMGRO048.ECO'
if eco_path.exists():
    elines = eco_path.read_text(encoding='utf-8-sig').splitlines(keepends=True)
    header = None
    for j, line in enumerate(elines):
        if line.strip().startswith('@ECO#'):
            header = line.split()
            header[0] = header[0].lstrip('@')
            continue
        if header and line.strip().startswith('TM0001'):
            spans = [(m.start(), m.end()) for m in re.finditer(r'\S+', line)]
            for k, hname in enumerate(header):
                ln = hname.lower()
                if ln in params and k < len(spans):
                    val = params[ln]
                    s, e = spans[k]
                    new_tok = "{:.6g}".format(val)
                    if len(new_tok) <= (e - s):
                        elines[j] = elines[j][:s] + new_tok.rjust(e - s) + elines[j][e:]
                    else:
                        elines[j] = elines[j][:s] + new_tok[:e-s] + elines[j][e:]
            break
    eco_path.write_text(''.join(elines), encoding='utf-8', newline='')

# fix DSSATPRO (avoid regex backslash issue)
dssatpro = DET / 'DSSATPRO.v48'
if dssatpro.exists():
    tx = dssatpro.read_text(encoding='utf-8', errors='ignore')
    wpath = str(DET)
    out = []
    for l in tx.splitlines(keepends=True):
        if l.strip().startswith('CRD ') or l.strip().startswith('TMD '):
            key = l.strip().split()[0]
            out.append(key + ' ' + wpath + '\n')
        else:
            out.append(l)
    dssatpro.write_text(''.join(out), encoding='utf-8')

# run DSSAT directly
env = dict(os.environ)
r = subprocess.run([str(DET/'DSCSM048.EXE'), 'B', 'DSSBatch.v48'],
    cwd=DET, capture_output=True, text=True, env=env, timeout=300)
print('DSSAT rc:', r.returncode)
runs = set()
pg = DET/'PlantGro.OUT'
if pg.exists():
    for line in pg.read_text(errors='ignore').splitlines():
        m = re.match(r'\*RUN\s+(\d+)', line)
        if m: runs.add(int(m.group(1)))
print('PlantGro runs:', sorted(runs))
fw_runs = set()
fw = DET/'FreshWt.OUT'
if fw.exists():
    for line in fw.read_text(errors='ignore').splitlines():
        m = re.match(r'\*RUN\s+(\d+)', line)
        if m: fw_runs.add(int(m.group(1)))
print('FreshWt runs:', sorted(fw_runs))
if r.returncode != 0:
    eo = DET/'ERROR.OUT'
    if eo.exists():
        print('ERROR.OUT:', eo.read_text(errors='ignore')[:400])
