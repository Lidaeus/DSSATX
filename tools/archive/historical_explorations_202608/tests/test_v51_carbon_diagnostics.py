import numpy as np
import pytest
from tools.analysis.analyze_v51_carbon_diagnostics_20260902 import parse_carbon, structural_leaf_n


def test_structural_n_uses_reserve_fraction_not_percent():
    assert structural_leaf_n([3.6], [10])[0] == pytest.approx(4.)
    assert structural_leaf_n([3.6], [0])[0] == pytest.approx(3.6)


@pytest.mark.parametrize('reserve', [-1, 100, np.nan])
def test_invalid_reserve_never_silently_clipped(reserve):
    with pytest.raises(ValueError): structural_leaf_n([3.6], [reserve])


def carbon_line(day, overflow=False):
    line=f' {2026:4d} {day:03d} {5:5d} {0:5d} {9:6d}'
    line+=''.join(f'{v:8.4f}' for v in [1.,.0021,.0014,.0003,0.])
    line+=f'{0.:8.5f}{3.828:7.3f}{7.641:7.3f} {30.171:6.3f} {21.809:6.3f}'
    line+=''.join(f' {v:7.4f}' for v in [0.,0.,0.])
    return line[:-7]+'*******' if overflow else line


def test_unrelated_overflow_retains_required_day(tmp_path):
    p=tmp_path/'PlantC.OUT'
    p.write_text('*RUN 1\n@YEAR DOY DAS DAP TWAD PHAD CMAD CGRD GRAD MRAD CHAD CL%D CS%D TGNN TGAV GN%D GL%D GC%D\n'+carbon_line(75)+'\n'+carbon_line(76,True)+'\n')
    f=parse_carbon(p)
    assert len(f)==2
    assert f['GC%D'].isna().sum()==1
    assert f['CL%D'].tolist()==[3.828,3.828]
    assert f.PHAD.tolist()==[1.,1.]
