from pathlib import Path
import zipfile,re,shutil,json,hashlib,sys,xml.etree.ElementTree as ET
sys.stdout.reconfigure(encoding='utf8')
ROOT=Path(r'D:\三季节数据汇总');OUT=ROOT/'数据质控_20261007'
src=ROOT/'2025春'/'2025春土壤含水量数据集.xlsx'
with zipfile.ZipFile(OUT/'_C257值片段.xlsx') as z:
    authored=z.read('xl/worksheets/sheet1.xml').decode('utf8')
    tree=ET.fromstring(authored);ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    value=tree.find('.//s:c[@r="C257"]/s:v',ns).text
    assert float(value)==6702
with zipfile.ZipFile(src) as z:
    before={i.filename:z.read(i.filename) for i in z.infolist()};infos=z.infolist();comment=z.comment
xml=before['xl/worksheets/sheet1.xml'].decode('utf8')
cell=re.search(r'<c\b[^>]*\br="C257"[^>]*>.*?</c>',xml,re.S)
assert cell is not None and re.search(r'<v>7135(?:\.0)?</v>',cell.group())
newcell=re.sub(r'<v>[^<]*</v>',f'<v>{value}</v>',cell.group(),count=1)
updated=xml[:cell.start()]+newcell+xml[cell.end():]
backup=OUT/'修订前备份';backup.mkdir(exist_ok=True)
copy=backup/src.name
if not copy.exists():shutil.copy2(src,copy)
temporary=OUT/'_水分定点修改.xlsx'
with zipfile.ZipFile(temporary,'w') as z:
    z.comment=comment
    for i in infos:z.writestr(i,updated.encode('utf8') if i.filename=='xl/worksheets/sheet1.xml' else before[i.filename])
with zipfile.ZipFile(temporary) as z:
    assert all(z.read(k)==v for k,v in before.items() if k!='xl/worksheets/sheet1.xml')
    assert z.read('xl/worksheets/sheet1.xml').decode('utf8').replace(newcell,cell.group(),1)==xml
shutil.copy2(temporary,src)
log={'date':'2026-10-07','file':str(src),'sheet':'Sheet1','cell':'C257','old':7135,'new':6702,'basis':'用户明确指定：反算干重保留为6702；属于反算修订，不标为新增原始称重','unchanged':'E257手填含水率与G257公式/缓存、其他所有单元格、公式、外链及包内其他部件均保留','backup':str(copy),'sha256_before':hashlib.sha256(copy.read_bytes()).hexdigest(),'sha256_after':hashlib.sha256(src.read_bytes()).hexdigest()}
(OUT/'C257修订记录.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(log,ensure_ascii=False,indent=2))
