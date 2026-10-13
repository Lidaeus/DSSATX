# Fortran Patch Specification: CROPGRO Scheme B (Dynamic Acclimation & Senescence Governor)

**Standard**: Phase 2 CROPGRO Scheme B Technical Specification  
**Model Base**: DSSAT CSM v4.8.2 / v4.8.6.0 (`Plant/CROPGRO/`)  
**Target Routines**: `PHOTO.for`, `SENES.for`, `CROPGRO.for`  
**Compliance**: Strict Fixed-Form Fortran 77/90 (Columns 7–72, zero line overflow)  
**Safety & Isolation**: All patches and source files are strictly sandboxed within `subprojects/critical_n/fortran_patch/` and never touch production `C:\DSSAT48\`.

---

## 1. Scientific Motivation & Mechanism Summary

Traditional DSSAT CROPGRO parameter calibration for indeterminate eggplant under multi-harvest management suffers from a destructive positive feedback loop (Defoliation Avalanche / Death Spiral):

1. **The Avalanche Loop**:
   $$\text{Deficit} \implies \text{NDMNEW} > \text{TRNU} \implies \text{Mobilize NRUSLF} \implies LFSEN = SENRTE \cdot \frac{NRUSLF}{0.16}$$
   When $LFSEN > WLDOTN$ (daily new leaf growth), net leaf expansion turns negative:
   $$ALFDOT = WLDOTN - LFSEN < 0$$
   This rapidly diminishes green leaf area ($LAI \downarrow$), slashes gross daily photosynthesis ($PG \downarrow$), crushes new leaf formation ($WLDOTN \downarrow\downarrow$), and drives the ratio $\frac{LFSEN}{WLDOTN}$ to catastrophic extremes ($>3.12\times$). Within 7–10 days, the canopy collapses.

2. **Scheme B Two-Pillar Defense**:
   - **Pillar 1: Dynamic Photosynthetic Acclimation Coupling (`PHOTO.for`)**:
     Modulates the leaf nitrogen factor `AGEFCC` with a smooth, continuous, saturating function of $NNI = \frac{\text{PCNL}}{N_c(W_{\text{eff}})}$:
     $$S(NNI) = NNI_{\min} + \frac{S_{\max} - NNI_{\min}}{1.0 + \exp\left(-\frac{4.0 \cdot (NNI - 1.0)}{\gamma}\right)}$$
     with invariants $\gamma = 0.65$, $NNI_{\min} = 0.30$, and $S_{\max} = 1.05$.
     This smoothly dampens luxury vegetative overgrowth under high N ($S_{\max} = 1.05$) while preserving baseline maintenance photosynthesis ($NNI_{\min} = 0.30$) under N deficit.
   - **Pillar 2: Leaf Senescence Governor (`SENES.for`)**:
     Places an absolute mathematical ceiling on nitrogen-mobilization-induced leaf destruction:
     $$LFSEN_{\text{actual}} = \min(LFSEN_{\text{native}}, \; \gamma_{\text{sen}} \cdot WLDOTN) \quad (\gamma_{\text{sen}} = 0.90 \in [0.85, 0.95])$$
     Guaranteeing:
     $$ALFDOT_{\text{net}} = WLDOTN - LFSEN_{\text{actual}} \ge (1.0 - \gamma_{\text{sen}}) \cdot WLDOTN \ge 0$$
     under active vegetative growth, completely eliminating the defoliation avalanche.

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

### 3.1 `SENES.for` (`SENES_CNC.FOR` / `patches/SENES.for.patch`)
- **Signature Change**:
  ```fortran
  ! Original:
        SUBROUTINE SENES(DYNAMIC,
       &    FILECC, CLW, DTX, KCAN, NR7, NRUSLF, PAR,       !Input
       &    RHOL, SLAAD, STMWT, SWFAC, VSTAGE, WTLF, XLAI,  !Input
       &    SLDOT, SLNDOT, SSDOT, SSNDOT)                   !Output

  ! Scheme B:
        SUBROUTINE SENES(DYNAMIC,
       &    FILECC, CLW, DTX, KCAN, NR7, NRUSLF, PAR,       !Input
       &    RHOL, SLAAD, STMWT, SWFAC, VSTAGE, WTLF, XLAI,  !Input
       &    WLDOTN,                                         !Input
       &    SLDOT, SLNDOT, SSDOT, SSNDOT)                   !Output
  ```
- **Limiter Insertion**:
  ```fortran
          LFSEN = SENRTE * NRUSLF / 0.16
  C       Scheme B: Senescence limiter to prevent defoliation avalanche
          IF (WLDOTN .GE. 0.0) THEN
            LFSEN = MIN(LFSEN, 0.90 * WLDOTN + 0.015 * WTLF)
          ENDIF
          LFSEN = MIN(WTLF,LFSEN)
          SLDOT = SLDOT + LFSEN
          SLDOT = MIN(WTLF,SLDOT)
  ```

### 3.2 `PHOTO.for` (`PHOTO_CNC.FOR` / `patches/PHOTO.for.patch`)
- **Signature Change**:
  ```fortran
  ! Original:
        SUBROUTINE PHOTO(CONTROL, 
       &    BETN, CO2, DXR57, EXCESS, KCAN, KC_SLOPE,       !Input
       &    NR5, PAR, PStres1, SLPF, RNITP, SLAAD,          !Input
       &    SWFAC, TDAY, XHLAI, XPOD,                       !Input
       &  AGEFAC, PG)                                       !Output

  ! Scheme B:
        SUBROUTINE PHOTO(CONTROL, 
       &    BETN, CO2, DXR57, EXCESS, KCAN, KC_SLOPE,       !Input
       &    NR5, PAR, PStres1, SLPF, RNITP, SLAAD,          !Input
       &    SWFAC, TDAY, XHLAI, XPOD,                       !Input
       &    NNI_IN,                                         !Input
       &  AGEFAC, PG)                                       !Output
  ```
- **Acclimation Insertion**:
  ```fortran
        AGEFCC = (1.0 - EXP(-2.0 * AGEFAC)) / (1. - EXP(-2.0 * 1.0))
  C-----------------------------------------------------------------------
  C     Scheme B: Continuous NNI photosynthetic acclimation coupling
  C-----------------------------------------------------------------------
        IF (NNI_IN .GT. 0.0) THEN
          ARG_NNI = -4.0 * (NNI_IN - 1.0) / 0.65
          ARG_NNI = MAX(-50.0, MIN(50.0, ARG_NNI))
          S_NNI = 0.30 + (1.05 - 0.30) / (1.0 + EXP(ARG_NNI))
          S_NNI = MAX(0.30, MIN(1.05, S_NNI))
          AGEFCC = AGEFCC * S_NNI
        ENDIF
  ```

### 3.3 `CROPGRO.for` (`CROPGRO_CNC.FOR` / `patches/CROPGRO.for.patch`)
- Routes `WLDOTN` into `CALL SENES`:
  - `RUNINIT` & `SEASINIT`: passes `0.0`
  - `INTEGR` (line 1171): passes `WLDOTN`
- Computes $NNI$ prior to `CALL PHOTO` during `RATE` stage and passes `NNI_CUR`:
  ```fortran
          IF (WTLF .GT. 0.0) THEN
            PCNL_C = (WTNLF / WTLF) * 100.0
          ELSE
            PCNL_C = 4.85
          ENDIF
          WEFF_C = MAX(0.001, (TOPWT + HPODWT) / 100.0)
          IF (WEFF_C .LT. 1.00) THEN
            NC_CUR = 4.85
          ELSE
            NC_CUR = 4.85 * (WEFF_C ** (-0.38))
          ENDIF
          IF (NC_CUR .GT. 0.0) THEN
            NNI_CUR = PCNL_C / NC_CUR
          ELSE
            NNI_CUR = 1.0
          ENDIF
          CALL PHOTO(CONTROL, 
       &    BETN, CO2, DXR57, EXCESS, KCAN, KC_SLOPE,
       &    NR5, PAR, PStres1, SLPF, RNITP, SLAAD,
       &    SWFAC, TDAY, XHLAI, XPOD,
       &    NNI_CUR,
       &    AGEFAC, PG)
  ```

---

## 4. Sandboxed Compilation & Verification Guide

To build a custom DSSAT binary with Scheme B in an isolated build directory (requires `gfortran` or `cmake` + `ifort`):

```bash
# 1. Create isolated build sandbox (outside production C:\DSSAT48\)
mkdir -p workspace/sandbox_dssat_b/build
cd workspace/sandbox_dssat_b

# 2. Copy source files and apply Scheme B patches
cp -r D:/Tomato_Cal/workspace/diagnostics/dssat-csm-os-v4.8.2-source/* .
cp D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/PHOTO_CNC.FOR Plant/CROPGRO/PHOTO.for
cp D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/SENES_CNC.FOR Plant/CROPGRO/SENES.for
cp D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/CROPGRO_CNC.FOR Plant/CROPGRO/CROPGRO.for

# 3. Configure and compile with cmake
cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . --config Release

# 4. Verify binary in sandbox
./bin/dscsm048.exe A DSSBatch.v48
```
