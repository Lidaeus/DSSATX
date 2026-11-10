from pathlib import Path
import json, hashlib, datetime, collections, sys
sys.stdout.reconfigure(encoding='utf-8')
import openpyxl
ROOT=Path(r'D:\三季节数据汇总')
REF=Path(r'D:\Tomato_Cal\data\user\ref\DSSAT文件')
OUT=ROOT/'数据质控_20261003'
OUT.mkdir(exist_ok=True)
def plain(v):
    if isinstance(v,(datetime.datetime,datetime.date,datetime.time)): return v.isoformat()
    return v
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):
    wf=openpyxl.load_workbook(p,data_only=False)
    wv=openpyxl.load_workbook(p,data_only=True)
    sheets={}
    for s in wf:
        sv=wv[s.title]; cells={}; formulas={}; errors={}; notes={}
        for row in s:
            for c in row:
                if c.value is None: continue
                cells[c.coordinate]=plain(c.value)
                if c.data_type=='f': formulas[c.coordinate]={'formula':c.value,'cached':plain(sv[c.coordinate].value)}
                if c.data_type=='e' or sv[c.coordinate].data_type=='e': errors[c.coordinate]=plain(sv[c.coordinate].value or c.value)
                if c.comment: notes[c.coordinate]=c.comment.text
        sheets[s.title]={'cells':cells,'formulas':formulas,'errors':errors,'notes':notes,'rows':s.max_row,'cols':s.max_column,'merged':[str(x) for x in s.merged_cells.ranges],'state':s.sheet_state}
    return {'sha256':sha(p),'size':p.stat().st_size,'sheets':sheets}
current={str(p.relative_to(ROOT)):load(p) for p in sorted(ROOT.glob('202*/*.xlsx'))}
reference={str(p.relative_to(REF)):load(p) for p in sorted(REF.rglob('*.xlsx'))}
json.dump({'current':current,'reference':reference},open(OUT/'snapshot.json','w',encoding='utf8'),ensure_ascii=False,indent=2)
lines=[]
for f,w in current.items():
    lines.append('\nFILE '+f)
    for n,s in w['sheets'].items():
        lines.append(f"SHEET {n} {s['rows']}x{s['cols']} cells={len(s['cells'])} formulas={len(s['formulas'])} errors={len(s['errors'])} state={s['state']} merges={s['merged'][:8]}")
        rows=collections.defaultdict(list)
        for a,v in s['cells'].items():
            c,r=openpyxl.utils.cell.coordinate_from_string(a)
            rows[r].append(f'{c}={v}')
        for r in list(sorted(rows))[:9]: lines.append(str(r)+' '+'; '.join(rows[r])[:1700])
        if s['errors']: lines.append('ERRORS '+str(s['errors']))
        if s['notes']: lines.append('NOTES '+str(s['notes']))
(OUT/'structure.txt').write_text('\n'.join(lines),encoding='utf8')
print(f'Loaded {len(current)} current books / {sum(len(x["sheets"]) for x in current.values())} sheets; {len(reference)} reference books')
print('\n'.join(lines)[:1500])
