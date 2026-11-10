"""Transplant Artifact Tool-authored advice; preserve existing Excel cells and parts."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import hashlib, json, re, shutil, zipfile
import xml.etree.ElementTree as ET
import openpyxl

BASE = Path(__file__).parent
TARGET = BASE.parent / '更新数据核对与统计筛查.xlsx'
PATCH = BASE / '_新增预审列.xlsx'
DATA = json.loads((BASE / '逐项预审建议.json').read_text('utf-8'))
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ET.register_namespace('', NS)
Q = lambda s: '{' + NS + '}' + s
SHA = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

assert SHA(TARGET) == DATA['audit_sha256'], 'User workbook changed; refresh audit first.'
for p, sha in DATA['source_sha256'].items():
    assert SHA(Path(p)) == sha, f'Source changed: {p}'

with zipfile.ZipFile(TARGET) as z:
    original = {n: z.read(n) for n in z.namelist()}
    zipinfos = z.infolist()
with zipfile.ZipFile(PATCH) as z:
    patch = {n: z.read(n) for n in z.namelist()}

oldstyles = ET.fromstring(original['xl/styles.xml'])
newstyles = ET.fromstring(patch['xl/styles.xml'])
styles_text = original['xl/styles.xml'].decode('utf-8')
offsets = {k: len(oldstyles.find(Q(k))) for k in ['fonts', 'fills', 'borders', 'cellStyleXfs', 'cellXfs']}
existing_formats = oldstyles.find(Q('numFmts'))
next_fmt = max([163] + [int(x.get('numFmtId')) for x in existing_formats]) + 1
format_map = {}

def fragment(el):
    return ET.tostring(el, encoding='unicode').replace(' xmlns="' + NS + '"', '')

def append_collection(text, name, nodes):
    content = ''.join(fragment(n) for n in nodes)
    pattern = rf'<{name}\b([^>]*?)(?:/\s*>|>(.*?)</{name}>)'
    hit = re.search(pattern, text, re.S)
    if hit:
        attrs = hit.group(1)
        old_content = hit.group(2) or ''
        old_count = len(ET.fromstring('<' + name + '>' + old_content + '</' + name + '>'))
        attrs = re.sub(r'\s*count="\d+"', '', attrs)
        replacement = f'<{name}{attrs} count="{old_count + len(nodes)}">{old_content}{content}</{name}>'
        return text[:hit.start()] + replacement + text[hit.end():]
    # numFmts precedes fonts in spreadsheet schema.
    assert name == 'numFmts'
    return text.replace('<fonts', f'<numFmts count="{len(nodes)}">{content}</numFmts><fonts', 1)

for node in newstyles.find(Q('numFmts')):
    src_id = int(node.get('numFmtId'))
    format_map[src_id] = next_fmt
    node.set('numFmtId', str(next_fmt))
    next_fmt += 1
styles_text = append_collection(styles_text, 'numFmts', list(newstyles.find(Q('numFmts'))))
for collection in ['fonts', 'fills', 'borders', 'cellStyleXfs', 'cellXfs']:
    nodes = list(newstyles.find(Q(collection)))
    if collection in ['cellStyleXfs', 'cellXfs']:
        for node in nodes:
            for attr, group in [('fontId','fonts'), ('fillId','fills'), ('borderId','borders'), ('xfId','cellStyleXfs')]:
                if attr in node.attrib:
                    node.set(attr, str(int(node.get(attr)) + offsets[group]))
            fmt = int(node.get('numFmtId', '0'))
            node.set('numFmtId', str(format_map.get(fmt, fmt)))
    styles_text = append_collection(styles_text, collection, nodes)
ET.fromstring(styles_text)

# Resolve patch strings into inline strings, avoiding any changes to the user's shared-string table.
strings = []
if 'xl/sharedStrings.xml' in patch:
    strings = [''.join(si.itertext()) for si in ET.fromstring(patch['xl/sharedStrings.xml'])]
psheet = ET.fromstring(patch['xl/worksheets/sheet1.xml'])
add_rows = {}
for row in psheet.find(Q('sheetData')):
    rn = int(row.get('r'))
    for cell in list(row):
        if cell.find(Q('v')) is None and cell.find(Q('is')) is None:
            row.remove(cell)
            continue
        assert re.match(r'^(S|T|U|V|W|X|Y|Z|AA|AB)\d+$', cell.get('r'))
        cell.set('s', str(int(cell.get('s', '0')) + offsets['cellXfs']))
        if cell.get('t') in ['s', 'str']:
            val = cell.find(Q('v')).text or ''
            if cell.get('t') == 's':
                val = strings[int(val)]
            cell.remove(cell.find(Q('v')))
            cell.set('t', 'inlineStr')
            txt = ET.SubElement(ET.SubElement(cell, Q('is')), Q('t'))
            txt.text = val
    if len(row):
        add_rows[rn] = row

sheet_path = 'xl/worksheets/sheet2.xml'
sheet_text = original[sheet_path].decode('utf-8')
assert ET.fromstring(sheet_text).find(Q('dimension')).get('ref') == 'A2:R222'
seen_rows = set()
def extend_row(match):
    rowtext = match.group(0)
    rn = int(re.search(r'\br="(\d+)"', rowtext).group(1))
    if rn not in add_rows:
        return rowtext
    seen_rows.add(rn)
    newrow = add_rows[rn]
    if 'ht' in newrow.attrib:
        tag = rowtext[:rowtext.index('>') + 1]
        tag = re.sub(r'\s+(?:ht|customHeight)="[^"]*"', '', tag)
        tag = tag[:-1] + f' ht="{newrow.get("ht")}" customHeight="1">'
        rowtext = tag + rowtext[rowtext.index('>') + 1:]
    return rowtext.replace('</row>', ''.join(fragment(c) for c in newrow) + '</row>')

sheet_text = re.sub(r'<row\b[^>]*>.*?</row>', extend_row, sheet_text, flags=re.S)
extra = ''.join(fragment(add_rows[r]) for r in sorted(set(add_rows) - seen_rows))
sheet_text = sheet_text.replace('</sheetData>', extra + '</sheetData>', 1)
sheet_text = sheet_text.replace('</cols>', ''.join(fragment(c) for c in psheet.find(Q('cols'))) + '</cols>', 1)
sheet_text = re.sub(r'<dimension ref="[^"]*"', '<dimension ref="A2:AB233"', sheet_text, count=1)
ET.fromstring(sheet_text)

table_path = 'xl/tables/table2.xml'
table_text = original[table_path].decode('utf-8')
assert 'ref="A5:R222"' in table_text
table_text = table_text.replace('ref="A5:R222"', 'ref="A5:AB222"')
newcolumns = []
for i, header in enumerate(DATA['headers'], 19):
    el = ET.Element(Q('tableColumn'), {'id': str(i), 'name': header})
    newcolumns.append(el)
table_text = append_collection(table_text, 'tableColumns', newcolumns)
ET.fromstring(table_text)
modified = {'xl/styles.xml': styles_text.encode('utf-8'), sheet_path: sheet_text.encode('utf-8'), table_path: table_text.encode('utf-8')}

# A:R measurement snapshots, review decisions, cell styles, formulas and other worksheets must survive exactly.
before_xml = ET.fromstring(original[sheet_path])
after_xml = ET.fromstring(modified[sheet_path])
before_cells = {c.get('r'): ET.tostring(c) for row in before_xml.find(Q('sheetData')) for c in row}
after_cells = {c.get('r'): ET.tostring(c) for row in after_xml.find(Q('sheetData')) for c in row}
assert all(after_cells.get(k) == v for k,v in before_cells.items()), 'Existing cells changed.'

backup_dir = BASE / '修订前备份'
backup_dir.mkdir(exist_ok=True)
backup = backup_dir / '人工审核后_预审前.xlsx'
if backup.exists():
    assert SHA(backup) == DATA['audit_sha256'], 'Backup belongs to a different revision.'
else:
    shutil.copy2(TARGET, backup)
temp = BASE / '_待核验统计表.xlsx'
with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
    for info in zipinfos:
        z.writestr(info, modified.get(info.filename, original[info.filename]))

oldbook = openpyxl.load_workbook(TARGET, data_only=False)
newbook = openpyxl.load_workbook(temp, data_only=False)
assert oldbook.sheetnames == newbook.sheetnames
for oldsheet in oldbook:
    newsheet = newbook[oldsheet.title]
    for row in oldsheet:
        for c in row:
            nc = newsheet.cell(c.row,c.column)
            assert (c.value,c.data_type,c._style) == (nc.value,nc.data_type,nc._style), (oldsheet.title,c.coordinate)
    assert ET.tostring(oldsheet.data_validations.to_tree()) == ET.tostring(newsheet.data_validations.to_tree())
    assert list(oldsheet.merged_cells.ranges) == list(newsheet.merged_cells.ranges)
    assert oldsheet.freeze_panes == newsheet.freeze_panes

sh = newbook['更新统计筛查']
pending = DATA['pending_rows']
assert [sh.cell(5,c).value for c in range(19,29)] == DATA['headers']
for case in DATA['cases']:
    assert abs(sum(case['peer_values'])/len(case['peer_values']) - case['peer_mean']) < 1e-10
    assert case['address'] not in case['peer_addresses']
    assert len(case['peer_values']) == 2
    recomputed_change = (case['peer_mean'] - case['current_value']) / 3 / case['original_group_mean']
    assert abs(recomputed_change - case['replacement_group_impact']) < 1e-10
    for r in case['audit_rows']:
        for col, val in enumerate(case['output'],19):
            actual = sh.cell(r,col).value
            if isinstance(val,(int,float)):
                assert abs(actual-val) < 1e-9
            else:
                assert actual == val
for r in DATA['already_reviewed_rows']:
    assert all(sh.cell(r,c).value is None for c in range(19,29))
assert sh.tables['ReviewTable1'].ref == 'A5:AB222'
assert len(sh.tables['ReviewTable1'].tableColumns) == 28
oldbook.close(); newbook.close()
assert SHA(TARGET) == DATA['audit_sha256'], 'Workbook changed during writing.'
for p, sha in DATA['source_sha256'].items():
    assert SHA(Path(p)) == sha
temp.replace(TARGET)
record = {
    'target':str(TARGET),'backup':str(backup),'original_sha256':DATA['audit_sha256'],
    'result_sha256':SHA(TARGET),'pending_rows':len(pending),'unique_locations':len(DATA['cases']),
    'retained_reviewed_rows':len(DATA['already_reviewed_rows']),
    'counts_unique':DATA['counts_unique'],'counts_rows':DATA['counts_rows'],
    'changed_package_parts':list(modified),'original_cells_preserved':len(before_cells),
    'other_five_sheets_byte_preserved':True,'all_existing_cell_values_styles_formulas_preserved':True,
    'original_review_status_and_decisions_preserved':True,'raw_source_sha256_unchanged':DATA['source_sha256'],
    'all_peer_means_independently_checked':True,'all_scenario_mean_changes_checked':True
}
(BASE/'预审写入与验证记录.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),'utf-8')
print(json.dumps(record,ensure_ascii=False,indent=2))
