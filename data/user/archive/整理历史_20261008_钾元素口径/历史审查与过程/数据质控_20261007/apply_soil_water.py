from pathlib import Path
import zipfile,re,shutil,json,hashlib,sys,xml.etree.ElementTree as ET,csv
sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(r'D:\三季节数据汇总');OUT=ROOT/'数据质控_20261007';src=ROOT/'2025秋'/'20260106_2号棚取土.xlsx'
ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
snap=json.loads((OUT/'snapshot.json').read_text(encoding='utf8'))['current']['2025秋\\20260106_2号棚取土.xlsx']['sheets']['Sheet1']
def val(a):return snap['formulas'][a]['cached'] if a in snap['formulas'] else snap['cells'][a]
with zipfile.ZipFile(OUT/'_秋季水分公式片段.xlsx') as z:authored=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
patch={};changes=[]
for r in range(2,242):
    a='H'+str(r);c=authored.find(f'.//s:c[@r="{a}"]',ns);formula=c.find('s:f',ns).text;v=c.find('s:v',ns).text
    expected=(val('C'+str(r))-val('D'+str(r)))/(val('D'+str(r))-val('B'+str(r))*100)
    assert abs(float(v)-expected)<1e-12
    patch[a]=(formula,v);changes.append([str(src),'Sheet1',a,snap['formulas'][a]['formula'],val(a),'='+formula,float(v),'用户确认湿/干重以0.01g计数、盒重为g；公式统一尺度'])
with zipfile.ZipFile(src) as z:before={i.filename:z.read(i.filename) for i in z.infolist()};infos=z.infolist();comment=z.comment
xml=before['xl/worksheets/sheet1.xml'].decode('utf8');updated=xml
oldcells={};newcells={}
for a,(formula,v) in patch.items():
    old=re.search(r'<c\b[^>]*\br="'+a+r'"[^>]*>.*?</c>',updated,re.S).group()
    new=re.sub(r'<f(?:\s[^>]*)?>.*?</f>',f'<f>{formula}</f>',old,count=1,flags=re.S)
    new=re.sub(r'<v>[^<]*</v>',f'<v>{v}</v>',new,count=1)
    assert old!=new;oldcells[a]=old;newcells[a]=new;updated=updated.replace(old,new,1)
backup=OUT/'修订前备份';backup.mkdir(exist_ok=True);copy=backup/src.name
if not copy.exists():shutil.copy2(src,copy)
temporary=OUT/'_秋季水分定点修改.xlsx'
with zipfile.ZipFile(temporary,'w') as z:
    z.comment=comment
    for i in infos:z.writestr(i,updated.encode('utf8') if i.filename=='xl/worksheets/sheet1.xml' else before[i.filename])
restored=updated
for a in patch:restored=restored.replace(newcells[a],oldcells[a],1)
assert restored==xml
with zipfile.ZipFile(temporary) as z:assert all(z.read(k)==v for k,v in before.items() if k!='xl/worksheets/sheet1.xml')
shutil.copy2(temporary,src)
with open(OUT/'秋季取土水分修订明细.csv','w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['文件','工作表','位置','原公式','原含水率','新公式','新含水率','依据']);w.writerows(changes)
log={'date':'2026-10-07','file':str(src),'cells_changed':'Sheet1!H2:H241','count':240,'formula':'(C-D)/(D-B*100)','raw_weights_unchanged':True,'other_package_components_identical':True,'backup':str(copy),'sha256_before':hashlib.sha256(copy.read_bytes()).hexdigest(),'sha256_after':hashlib.sha256(src.read_bytes()).hexdigest(),'first_value':changes[0][6]}
(OUT/'秋季取土水分修订记录.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(log,ensure_ascii=False,indent=2))
