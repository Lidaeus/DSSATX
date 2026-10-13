"""subprojects/critical_n: Critical Nitrogen Dilution & Nutrition Index Integration.

Implements Scheme A (Posterior Soft-Constraint Mapping) for DSSAT CROPGRO:
- Cumulative effective biomass W_eff = CWAD + CUMHARVEST
- Greenwood-Lemaire critical dilution curve Nc(W) = a * W^(-b)
- Nitrogen Nutrition Index (NNI = N_act,cum / Nc)
- Sawtooth discontinuity elimination across fruit harvest events
- Fast fixed-column streaming parser & PestCNC.OUT exporter (<10 ms)
- Rigid PEST++ instruction generation (PestCNC.ins) & sparse phenological subsampling
- Symmetrical physiological tolerance interval objective penalty function
- Frozen external invariants protocol (CNC_A=4.85, CNC_B=0.38, CNC_W0=1.00 fixed)
"""

__version__ = "1.0.0"
