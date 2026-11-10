from pathlib import Path
import sys
base=Path(r'D:\三季节数据汇总')
old=base/'数据质控_20261003'
new=base/'数据质控_20261007'
new.mkdir(exist_ok=True)
code=(old/'audit.py').read_text(encoding='utf8').replace("OUT=ROOT/'数据质控_20261003'","OUT=ROOT/'数据质控_20261007'")
code=code.replace("sorted(ROOT.glob('202*/*.xlsx'))","sorted(p for p in ROOT.glob('202*/*.xlsx') if not p.name.startswith('~$'))").replace("sorted(REF.rglob('*.xlsx'))","sorted(p for p in REF.rglob('*.xlsx') if not p.name.startswith('~$'))")
exec(compile(code,'audit_20261007','exec'))
sys.path.insert(0,str(old))
code2=(old/'investigate.py').read_text(encoding='utf8').replace("OUT=Path(r'D:\三季节数据汇总\数据质控_20261003')","OUT=Path(r'D:\三季节数据汇总\数据质控_20261007')")
exec(compile(code2,'investigate_20261007','exec'))
