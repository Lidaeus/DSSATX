"""Same-day contrasts with no forced ordering or significance thresholds."""
import numpy as np
import pandas as pd
from catalogue import V
from data import NORDER

def contrasts(d):
    rows=[];summary=[]
    for water,g in d.groupby('water_level'):
        for variable,(label,unit,kind,_) in V.items():
            if variable not in g:continue
            q=g.pivot(index='dap',columns='nitrogen_level',values=variable).reindex(columns=NORDER)
            high=q[['N1','N2','N3']]
            complete=high.notna().all(axis=1)
            span=(high.max(axis=1)-high.min(axis=1)).where(complete)
            scale=float(np.nanmax(abs(q.to_numpy()))) if q.notna().any().any() else np.nan
            ref=scale if scale>1e-12 else np.nan
            difference=q.N3-q.N0
            signed_peak=float(difference.loc[difference.abs().idxmax()]) if difference.notna().any() else np.nan
            for dap in q.index:
                rows.append(dict(water_level=water,variable=variable,dap=dap,unit=unit,
                    N3_minus_N0=difference.loc[dap],N3_minus_N2=q.N3.loc[dap]-q.N2.loc[dap],
                    N2_minus_N1=q.N2.loc[dap]-q.N1.loc[dap],N1_minus_N0=q.N1.loc[dap]-q.N0.loc[dap],
                    N3_minus_N1=q.N3.loc[dap]-q.N1.loc[dap],N123_range=span.loc[dap]))
            summary.append(dict(water_level=water,variable=variable,label=label,unit=unit,kind=kind,
                time_points=len(q),complete_high_N_points=int(complete.sum()),normalizer_peak_absolute=scale,
                high_N_max_range=float(span.max()) if span.notna().any() else np.nan,
                high_N_max_range_pct_peak=100*span.max()/ref,
                N3_minus_N0_max_abs=float(difference.abs().max()) if difference.notna().any() else np.nan,
                N3_minus_N0_signed_peak=signed_peak,N3_minus_N0_signed_peak_pct=100*signed_peak/ref,
                N3_minus_N0_end=float(difference.iloc[-1]),
                N3_minus_N0_end_pct_peak=100*difference.iloc[-1]/ref))
    return pd.DataFrame(rows),pd.DataFrame(summary)
