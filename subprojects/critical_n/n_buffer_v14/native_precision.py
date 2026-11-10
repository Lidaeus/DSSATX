"""Targeted six-column REAL field precision; unchanged native physiology."""
from pathlib import Path
import json

FIELDS = {'SLAVR': ('CUL', 'TM0008', 84), 'EM-V1': ('ECO', 'TM0001', 42),
          'TB1': ('SPE', 'VEGETATIVE DEVELOPMENT', 0),
          'VSSINK': ('SPE', 'FINREF,SLAREF', 18)}

def field(value):
    # Keep an explicit separator and decimal point for both native fixed-width
    # and independent whitespace/token readers. All four native fields are REAL.
    for decimals in range(4, -1, -1):
        token=f'{float(value):.{decimals}f}'
        if decimals == 0: token += '.'
        if len(token)<=5: return ' '+token.rjust(5)
    raise ValueError('Native precision field overflow')

def improve_fields(work, values):
    work=Path(work);records=[]
    for name,(kind,marker,start) in FIELDS.items():
        path=work/f'TMGRO048.{kind}';lines=path.read_text().splitlines()
        indices=[i for i,l in enumerate(lines) if (l.startswith(marker) if kind!='SPE' else marker in l)]
        if len(indices)!=1: raise ValueError('Unique precision field '+name)
        i=indices[0];before=lines[i][start:start+6];after=field(values[name])
        assert len(after)==6 and '.' in after
        lines[i]=lines[i][:start]+after+lines[i][start+6:]
        path.write_text('\n'.join(lines)+'\n',encoding='ascii')
        records.append(dict(name=name,requested=values[name],before=before,after=after,
                            parsed=float(after),native_type='REAL',native_format='F6'))
    (work/'native_precision_audit.json').write_text(json.dumps(records,indent=2),encoding='utf8')
    return records
