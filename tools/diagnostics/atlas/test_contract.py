"""Small independent contracts: units, weighting, missing cells and raw dates."""
import tempfile,unittest
from pathlib import Path
import numpy as np
import pandas as pd
from data import native_table,harvest_on_crop_grid
from metrics import contrasts

class DiagnosticContracts(unittest.TestCase):
    def test_native_run_is_not_treatment_id(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'native.OUT'
            p.write_text('*RUN  1 : W2_N0 CRGRO048\n TREATMENT 11 : W2_N0\n@YEAR DOY DAP LAID\n 2026 073 0 0.2\n')
            q=native_table(p)
            self.assertEqual(q.run.iloc[0],1);self.assertEqual(q.treatment.iloc[0],11)
            self.assertEqual(q.yrdoy.iloc[0],2026073)

    def test_duplicate_native_day_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'native.OUT'
            p.write_text('*RUN 1 : W2_N0 CRGRO048\n TREATMENT 11 : W2_N0\n@YEAR DOY DAP LAID\n 2026 073 0 0.2\n 2026 073 0 0.2\n')
            with self.assertRaises(ValueError):native_table(p)

    def test_contrasts_use_same_day_not_different_peaks(self):
        q=pd.DataFrame([dict(water_level='W2',nitrogen_level=n,dap=day,lai=value)
            for day,values in [(0,[0,1,1,1]),(1,[0,3,3,3])] for n,value in zip(['N0','N1','N2','N3'],values)])
        delta,summary=contrasts(q)
        r=summary[summary.variable.eq('lai')].iloc[0]
        self.assertEqual(r.high_N_max_range,0)
        self.assertEqual(r.N3_minus_N0_end,3)
        self.assertEqual(r.high_N_max_range_pct_peak,0)

    def test_missing_treatment_does_not_become_zero(self):
        q=pd.DataFrame([dict(water_level='W2',nitrogen_level=n,dap=0,lai=v) for n,v in [('N0',0),('N1',1),('N3',2)]])
        delta,summary=contrasts(q)
        self.assertTrue(np.isnan(summary.iloc[0].high_N_max_range))
        self.assertTrue(np.isnan(delta.iloc[0].N2_minus_N1))

    def test_all_zero_relative_contrast_is_undefined(self):
        q=pd.DataFrame([dict(water_level='W2',nitrogen_level=n,dap=0,lai=0.) for n in ['N0','N1','N2','N3']])
        _,s=contrasts(q)
        self.assertEqual(s.iloc[0].high_N_max_range,0)
        self.assertTrue(np.isnan(s.iloc[0].high_N_max_range_pct_peak))

    def test_pre_output_zero_requires_a_zero_cumulative_counter(self):
        base=pd.DataFrame(dict(run=[1,1,1],yrdoy=[2026001,2026002,2026003]))
        fresh=pd.DataFrame(dict(run=[1,1],yrdoy=[2026002,2026003],CHFPW=[0.,5.],HFPOW=[0.,5.],CHNUM=[0,1]))
        frame,n=harvest_on_crop_grid(base,fresh)
        self.assertEqual(n,1);self.assertEqual(frame.CHFPW.iloc[0],0)
        fresh.loc[0,['CHFPW','HFPOW','CHNUM']]=[5,5,1]
        frame,n=harvest_on_crop_grid(base,fresh)
        self.assertEqual(n,0);self.assertTrue(np.isnan(frame.CHFPW.iloc[0]))

if __name__=='__main__':unittest.main()
