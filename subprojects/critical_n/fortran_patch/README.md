# Fortran Patch Specification: CROPGRO Stage R1 + R2 (核心动力学解耦与需求端动态稀释)

**Standard**: Phase 2 CROPGRO Stage R1 + Stage R2 Technical Specification  
**Model Base**: DSSAT CSM v4.8.2 / v4.8.6.0 (`Plant/CROPGRO/`)  
**Target Routines**: `DEMAND.for`, `CROPGRO.for`, `MOBIL.for`, `SENES.for`, `GROW.for`, `PHOTO.for`  
**Compliance**: Strict Fixed-Form Fortran 77/90 (Columns 7–72, zero line overflow)  
**Safety & Isolation**: All patches and source files are strictly sandboxed within `subprojects/critical_n/fortran_patch/` and never touch production `C:\DSSAT48\`.

---

## 1. Scientific Motivation & Mechanism Summary

Traditional DSSAT CROPGRO parameter calibration for indeterminate eggplant under multi-harvest management suffers from a destructive positive feedback loop (Defoliation Avalanche / Death Spiral):

1. **The Avalanche Loop in Native DSSAT**:
   - In native CROPGRO, whenever daily nitrogen demand exceeds uptake ($NDMNEW > TRNU$), nitrogen is mobilized from leaves ($NRUSLF$).
   - Crucially, native CROPGRO assumes **all** mobilized nitrogen corresponds to structural leaf protein loss:
     $$LFSEN = SENRTE \cdot \frac{NRUSLF}{0.16}$$
     $$WLDOT = WLDOTN - SLDOT - \frac{NRUSLF}{0.16} - \dots$$
     $$ALFDOT = WLDOTN \cdot F - \left(SLDOT + \frac{NRUSLF}{0.16}\right) \cdot SLA$$
   - Thus, 1 unit of leaf N mobilization triggers a **double deduction** of dry weight and scales area shrinkage by $6.25\times$. When $LFSEN > WLDOTN$, net leaf growth collapses ($ALFDOT < 0$).
   - This diminishes green leaf area ($LAI \downarrow$), slashes gross daily photosynthesis ($PG \downarrow$), crushes new leaf formation ($WLDOTN \downarrow\downarrow$), and drives catastrophic premature canopy collapse within 7–10 days.

2. **Stage R1 Three-Way Decoupled Reconstruction (MOBIL + SENES + GROW)**:
   - **`MOBIL.for` (Leaf Safe Buffer N Definition & Decoupling)**:
     Defines safe buffer / storage nitrogen in leaves:
     $$N_{\text{buf, free}} = \max\left(0.0, \; WTNLF - \text{PROLFG} \cdot 0.16 \cdot (WTLF - WCRLF)\right)$$
     where $\text{PROLFG}$ is normal growth leaf protein fraction (e.g. 0.220 for tomato/eggplant).
     Total mobilization flux $NRUSLF$ is decoupled into:
     $$NRUSLF_{\text{safe}} = \min(NRUSLF, \; N_{\text{buf, free}})$$
     $$NRUSLF_{\text{stress}} = \max(0.0, \; NRUSLF - NRUSLF_{\text{safe}})$$
     Exact conservation holds identically: $NRUSLF_{\text{safe}} + NRUSLF_{\text{stress}} \equiv NRUSLF$.
   - **`SENES.for` (Stress-Driven Senescence)**:
     Leaf senescence is driven solely by stress mobilization (safe buffer mobilization has a senescence factor of 0):
     $$LFSEN = SENRTE \cdot \frac{NRUSLF_{\text{stress}}}{0.16}$$
     Retains the secondary safety ceiling $\min(LFSEN, 0.90 \cdot WLDOTN + 0.015 \cdot WTLF)$.
     When mobilization comes from buffer N ($NRUSLF_{\text{stress}} = 0$), $LFSEN = 0$! No defoliation occurs.
   - **`GROW.for` (Corrected Dry Weight & Leaf Area Deductions)**:
     - Dry weight loss (line 482): Safe buffer N is solute/buffer mass (loss coefficient 1.0), whereas stress N is structural protein (loss coefficient 6.25):
       $$WLDOT = WLDOTN - SLDOT - WLIDOT - WLFDOT - \left(NRUSLF_{\text{safe}} \cdot 1.0 + \frac{NRUSLF_{\text{stress}}}{0.16}\right) - CRUSLF$$
     - Leaf area shrinkage (line 1051): Safe buffer mobilization does not destroy cell wall structures, so only stress mobilization shrinks leaf area:
       $$ALFDOT = WLDOTN \cdot F - \left(SLDOT + WLIDOT + WLFDOT + \frac{NRUSLF_{\text{stress}}}{0.16}\right) \cdot SLA$$
   - **`CROPGRO.for` (Parameter Routing & Inter-Module Coupling)**:
     Reads $\text{PROLFG}$ at `RUNINIT`, routes $NRUSLF_{\text{safe}}$ and $NRUSLF_{\text{stress}}$ from `MOBIL` to `SENES` and `GROW`.
   - **`PHOTO.for` (Continuous NNI Acclimation Coupling)**:
     Modulates leaf nitrogen factor `AGEFCC` with a smooth saturating function of $NNI = \frac{\text{PCNL}}{N_c(W_{\text{eff}})}$ ($S(NNI) \in [0.30, 1.05]$).

---

## 2. Fortran Coding Standards & Fixed-Form Compliance

All patched code adheres strictly to fixed-form Fortran 77/90 rules:
- **Column 1**: Blank, comment character (`C`, `c`, `*`, `!`), or statement label.
- **Columns 1–5**: Statement label (integers only) or blank.
- **Column 6**: Continuation character (`&`, `1`, etc.) or blank.
- **Columns 7–72**: Fortran statements.
- **Columns > 72**: STRICTLY EMPTY / UNUSED. All lines have been verified with `validate_fortran_fixed_format()`: **0 violations detected across all files**.

---

## 3. Patch Inventory & Signature Changes

### 3.1 `MOBIL.for` (`MOBIL_CNC.FOR` / `patches/MOBIL.for.patch`)
- **Signature Change**:
  ```fortran
  ! Original:
        SUBROUTINE MOBIL(DYNAMIC,                           !Control
       &    NDMNEW, NMINEP, NMOBR, RPRO, TRNU,              !Input
       &    WNRLF, WNRRT, WNRSH, WNRST,                     !Input
       &    NMINEA, NRUSLF, NRUSRT, NRUSSH, NRUSST)         !Output

  ! Stage R1:
        SUBROUTINE MOBIL(DYNAMIC,                           !Control
       &    NDMNEW, NMINEP, NMOBR, PROLFG, RPRO, TRNU,      !Input
       &    WCRLF, WNRLF, WNRRT, WNRSH, WNRST,              !Input
       &    WTLF, WTNLF,                                    !Input
       &    NMINEA, NRUSLF, NRUSRT, NRUSSH, NRUSST,         !Output
       &    NRUSLF_SAFE, NRUSLF_STR)                        !Output
  ```
- **Decoupled Flux Computation**:
  ```fortran
  C       Phase R1: Decouple leaf N mobilization into safe vs stress
          IF (PROLFG .GT. 0.0) THEN
            NBUF_FREE = MAX(0.0,
       &      WTNLF - PROLFG * 0.16 * (WTLF - WCRLF))
          ELSE
            NBUF_FREE = 0.0
          ENDIF
          NRUSLF_SAFE = MIN(NRUSLF, NBUF_FREE)
          NRUSLF_STR  = MAX(0.0, NRUSLF - NRUSLF_SAFE)
  ```

### 3.2 `SENES.for` (`SENES_CNC.FOR` / `patches/SENES.for.patch`)
- **Signature & Senescence Update**:
  ```fortran
        SUBROUTINE SENES(DYNAMIC,
       &    FILECC, CLW, DTX, KCAN, NR7, NRUSLF_STR, PAR,   !Input
       &    RHOL, SLAAD, STMWT, SWFAC, VSTAGE, WTLF, XLAI,  !Input
       &    WLDOTN,                                         !Input
       &    SLDOT, SLNDOT, SSDOT, SSNDOT)                   !Output
  ...
  C       Phase R1: Senescence driven only by stress mobilization
          LFSEN = SENRTE * NRUSLF_STR / 0.16
          IF (WLDOTN .GE. 0.0) THEN
            LFSEN = MIN(LFSEN, 0.90 * WLDOTN + 0.015 * WTLF)
          ENDIF
          LFSEN = MIN(WTLF,LFSEN)
          SLDOT = SLDOT + LFSEN
          SLDOT = MIN(WTLF,SLDOT)
  ```

### 3.3 `GROW.for` (`GROW_CNC.FOR` / `patches/GROW.for.patch`)
- **Signature & Deduction Updates**:
  ```fortran
        SUBROUTINE GROW(CONTROL, ISWITCH, DYNAMIC, SOILPROP, 
       &  ...
       &  NPLTD, NRUSLF, NRUSRT, NRUSSH, NRUSST,            !Input
       &  NRUSLF_SAFE, NRUSLF_STR,                          !Input
       &  POTCAR, POTLIP, PPLTD, SDIDOT, SDPROR,            !Input
  ...
  C       Phase R1: Decoupled mass deduction (safe vs stress mobilization)
        WLDOT = WLDOTN - SLDOT - WLIDOT - WLFDOT
       &        - (NRUSLF_SAFE * 1.0 + NRUSLF_STR / 0.16) - CRUSLF

        ShutMob = ((NRUSLF_SAFE * 1.0 + NRUSLF_STR / 0.16)
       &           + CRUSLF) * 10.      !kg/ha
  ...
  C       Phase R1: Area shrinkage driven only by stress mobilization
        ALFDOT = WLDOTN*F - (SLDOT+WLIDOT+WLFDOT+NRUSLF_STR/0.16)*SLA
  ```

### 3.4 `CROPGRO.for` (`CROPGRO_CNC.FOR` / `patches/CROPGRO.for.patch`)
- **Stage R1**: Reads `PROLFG` at `RUNINIT` from `FILECC` (with safe fallback to `PROLFI * 0.815` or `0.220`).
- **Stage R1**: Routes `NRUSLF_SAFE` and `NRUSLF_STR` from `CALL MOBIL` to `CALL SENES` and `CALL GROW`.
- **Stage R2**: Tracks cumulative fruit harvest pod weight `CUM_HPODWT` across harvests and passes strictly continuous effective biomass `WEFF = (TOPWT + CUM_HPODWT) / 100.0` (t DM/ha) to `CALL DEMAND`.
- **Stage R2**: Eliminates single-day `HPODWT` sawteeth in `RATE` acclimation calculation `WEFF_C`.

### 3.5 `DEMAND.for` (`DEMAND_CNC.FOR` / `patches/DEMAND.for.patch`)
- **Stage R2 Dynamic Old Tissue Demand Reconstruction**:
  Replaces fixed constant target concentration $NVSTL = FNINL \approx 4.8\%$ with the asymptotic lower-bound critical dilution curve:
  $$N_c(W_{\text{eff}}) = N_{c,\infty} + (a - N_{c,\infty}) \cdot [\max(W_0, W_{\text{eff}})]^{-b}$$
  ($a = 4.85\%$, $b = 0.38$, $W_0 = 1.00\text{ t DM/ha}$, $N_{c,\infty} = 1.70\%$).
- Leaf target concentration:
  $$NVSTL(t) = \max\left(\text{PROLFF} \cdot 0.16, \; \frac{N_c(W_{\text{eff}}(t))}{100.0}\right)$$
- Stem target concentration allometrically coordinated with leaf dilution:
  $$NVSTS(t) = \max\left(\text{PROSTF} \cdot 0.16, \; \text{PROSTF} \cdot 0.16 + (FNINS - \text{PROSTF} \cdot 0.16) \cdot \phi\right)$$
  where $\phi = \max\left(0.0, \; \min\left(1.0, \; \frac{NVSTL - \text{PROLFF} \cdot 0.16}{FNINL - \text{PROLFF} \cdot 0.16}\right)\right)$.
- When $DXR57 > 0$, reproductive decline scales smoothly from current diluted concentrations towards maintenance protein.

### 3.6 `PHOTO.for` (`PHOTO_CNC.FOR` / `patches/PHOTO.for.patch`)
- Continuous NNI coupling for photosynthetic acclimation.

---

## 4. Sandboxed Compilation & Verification Guide

To build and verify the custom DSSAT binary with Stage R1 + Stage R2:

```bash
# Automated compilation and full verification suite
python subprojects/critical_n/scripts/build_and_verify_dssat.py

# Run specific unit and regression tests
python -m pytest subprojects/critical_n/tests/test_stage_r1_dynamics.py -v
python -m pytest subprojects/critical_n/tests/test_stage_r2_dynamics.py -v
python -m pytest subprojects/critical_n/tests/test_scheme_b_fortran_patch.py -v
```
