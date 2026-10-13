# Subproject: Critical Nitrogen Dilution & Nutrition Index (CNC-NNI)

**Identifier**: `SUBPROJECT-CRITICAL-N`  
**Standard**: CROPGRO Nitrogen Dilution Dual-Phase Architecture:
- **Phase 1 (Scheme A)**: Posterior Soft-Constraint Regularization (Zero-Invasive Production Baseline)
- **Phase 2 (Scheme B)**: Dynamic Internal Photosynthetic Acclimation Coupling & Senescence Limiter (Mechanistic Research Engine)  
**Target Crop**: Greenhouse Indeterminate Eggplant / Tomato (`CRGRO048` / `TMGRO048`)  
**Status**: Fully Implemented & Isolated (Zero Intrusion into Core `src/` Calibration and Production `C:\DSSAT48\`)

---

## 1. Executive Summary & Scientific Motivation

In greenhouse indeterminate eggplant cultivation with multi-harvest management, traditional DSSAT CROPGRO parameter calibration suffers from two deep structural pathologies:
1. **Sawtooth Harvest Discontinuities**: Fruit harvesting abruptly reduces standing tops dry biomass ($CWAD$) by $>14\%$, artificially inflating apparent standing nitrogen concentration ($\Delta N_{\text{act}} > +0.45\%$) and triggering spurious $+0.05\sim +0.09$ jumps in the Nitrogen Nutrition Index ($NNI$).
2. **Defoliation Avalanche / Death Spiral**: In co-calibration, unconstrained optimization attempts to lower simulated tissue N by opening endogenous mobilization parameters, crossing the lethal threshold:
   $$LFSEN = SENRTE \times \frac{NRUSLF}{0.16} > WLDOTN$$
   precipitating catastrophic premature defoliation cascades ($ALFDOT < 0 \implies \text{LAI} \downarrow \implies PG \downarrow \implies WLDOTN \downarrow\downarrow \implies \frac{LFSEN}{WLDOTN} \uparrow\uparrow$).

To solve these pathologies without disrupting ongoing production calibration workflows, this subproject implements a strictly isolated **two-phase dual-track architecture**:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                          SUBPROJECT-CRITICAL-N DUAL-TRACK ARCHITECTURE                 │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
        ┌───────────────────────────────────┴───────────────────────────────────┐
        ▼                                                                       ▼
【Phase 1: 方案 A - 后验软约束正则化与状态补齐 (Stage R0 生产基准)】    【Phase 2: 方案 B - 内源动态光合耦合与衰老限幅器 (科研原型)】
(Scheme A: Posterior Soft-Constraint & State Harmonization)              (Scheme B: Dynamic Acclimation & Senescence Limiter Prototype)
· 零代码侵入、零编译依赖、即插即用                                       · 纯沙箱 Fortran 补丁规范与源码原型
· 累积果实氮显式状态 CHPDTN 与有效生物量 W_eff，采摘日 Delta NNI = 0       · 连续平滑 NNI 光合门控 S(NNI) 探索性调控
· 渐近下限临界氮曲线 Nc(W) = Nc_inf + (a - Nc_inf)*[max(W0, W)]^(-b)    · 衰老限幅器 LFSEN_actual = min(LFSEN, gamma*WLDOTN + delta*WTLF)
· PEST++ 零残差单侧松弛投影算子 r_tol 与 Pseudo-Huber 平滑变换           · 原型离散时间代理模型质量守恒审计
· 冻结外生不变量协议 (CNC_A/B/W0/NC_INF fixed)                           · 适用于：机理深化推演、消融试验与下一代模型研发
· 适用于：当前生产环境自动化参数率定与生理弹性区间约束                   · 状态：受审科研原型（待真实 DSSAT 逐日通量审计与功能库深化）
```

---

## 2. Phase 2 (Scheme B) Core Scientific Mechanisms & Formulations

### 2.1 Dynamic Internal Photosynthetic Acclimation Coupling (`PHOTO.for`)
In native CROPGRO, leaf nitrogen concentration modulates photosynthesis via `AGEFAC` / `AGEFCC`. In Scheme B, this response is coupled with the macroscopic Nitrogen Nutrition Index:
$$NNI = \frac{\text{PCNL}}{N_c(W_{\text{eff}})}$$
where $W_{\text{eff}} = \frac{CWAD + \sum \text{HARVEST\_DRY}}{1000.0}$ (t DM/ha), and the upgraded asymptotic lower-bound critical dilution curve is:
$$N_c(W_{\text{eff}}) = N_{c,\infty} + (a - N_{c,\infty}) \cdot [\max(W_0, W_{\text{eff}})]^{-b}$$
($a = 4.85\%$, $b = 0.38$, $W_0 = 1.00\text{ t DM/ha}$, $N_{c,\infty} = 1.70\%$).

The coupled photosynthesis factor is defined as:
$$AGEFAC_{\text{CNC}} = AGEFAC_{\text{native}} \cdot \mathcal{S}(NNI)$$
Bounded strictly within $[S_{\min}, S_{\max}] = [0.30, 1.05]$. Three continuous functional forms are supported:
1. **Bounded Sigmoid (Logistic Saturation)**:
   $$\mathcal{S}_{\text{Sigmoid}}(NNI) = NNI_{\min} + \frac{S_{\max} - NNI_{\min}}{1.0 + \exp\left(-\frac{4.0 \cdot (NNI - 1.0)}{\gamma}\right)} \quad (\gamma = 0.65)$$
2. **Hill Cooperativity Response**:
   $$\mathcal{S}_{\text{Hill}}(NNI) = S_{\min} + (S_{\max} - S_{\min}) \cdot \min\left(1.0, \; \frac{NNI^h}{K_{0.5}^h + NNI^h} \cdot (K_{0.5}^h + 1.0)\right) \quad (h = 3.0, K_{0.5} = 0.85)$$
3. **Michaelis-Menten Saturating Kinetics**:
   $$\mathcal{S}_{\text{MM}}(NNI) = S_{\min} + (S_{\max} - S_{\min}) \cdot \min\left(1.0, \; \frac{(1.0 + K_m) \cdot NNI}{K_m + NNI}\right) \quad (K_m = 0.35)$$

### 2.2 Leaf Senescence Rate Limiter & Avalanche Governor (`SENES.for`)
To prevent the lethal defoliation avalanche when nitrogen is mobilized for fruit growth, Scheme B injects a mandatory senescence rate limiter:
$$LFSEN_{\text{actual}} = \min\left(LFSEN_{\text{native}}, \; \gamma_{\text{sen}} \cdot WLDOTN + \delta_{\text{sen}} \cdot WTLF\right)$$
where $\gamma_{\text{sen}} \in [0.85, 0.95]$ (default $0.90$), and $\delta_{\text{sen}} \in [0.0, 0.015]$ (default $0.015$ in Fortran patch for basal canopy turnover when $WLDOTN = 0$).

### 2.3 Stage R1 Three-Way Decoupled Reconstruction (MOBIL + SENES + GROW)
In Stage R1, the underlying mechanism triggering the defoliation avalanche is root-solved at the source:
1. **`MOBIL.for`**: Defines leaf safe buffer nitrogen $N_{\text{buf, free}} = \max(0.0, \; WTNLF - \text{PROLFG} \cdot 0.16 \cdot (WTLF - WCRLF))$. Mobilization is decoupled into safe buffer flux $NRUSLF_{\text{safe}} = \min(NRUSLF, N_{\text{buf, free}})$ and stress mobilization $NRUSLF_{\text{stress}} = \max(0.0, NRUSLF - NRUSLF_{\text{safe}})$.
2. **`SENES.for`**: Defoliation senescence is driven solely by stress mobilization: $LFSEN = SENRTE \cdot NRUSLF_{\text{stress}} / 0.16$ (safe buffer mobilization has a senescence factor of 0).
3. **`GROW.for`**: Fixes the double-deduction and area penalty bugs:
   - Line 482 leaf dry weight deduction: $NRUSLF_{\text{safe}} \cdot 1.0 + NRUSLF_{\text{stress}} / 0.16$ (safe buffer N is solute mass, not $6.25\times$ protein structure loss).
   - Line 1051 leaf area shrinkage: Area is deducted solely for stress mobilization $(NRUSLF_{\text{stress}} / 0.16) \cdot SLA$ (safe buffer mobilization does not shrink leaf area).
4. **`CROPGRO.for`**: Routes $\text{PROLFG}$ and decoupled fluxes smoothly across subroutines.

### 2.4 Strict Analytical Mass Balance Conservation (`mass_balance.py`)
Plant nitrogen balance follows the exact telescoping identity:
$$\Delta \text{Storage} \equiv \sum \text{Inputs} - \sum \text{Outputs}$$
$$\text{Storage} = WTNLF + WTNST + WTNRT + WTNPOD$$
$$\text{Outputs} = \sum SLNDOT + \sum \text{HARVEST\_N} + \sum NLEAK$$
$$\text{Inputs} = SEEDNI + \sum TRNU$$
When the governor restricts $LFSEN$, non-senesced leaf tissue remains in $WTLF$, and its structural nitrogen remains in $WTNLF$. The mobilized nitrogen ($NRUSLF$) was already added to $NAVL$ and incorporated into fruit/vegetative organs. Algebraic cancellation yields:
$$\text{Residual}_N \equiv 0.000000 \quad (< 10^{-10}\text{ g N/m}^2)$$

---

## 3. Directory Layout

```
subprojects/critical_n/
├── README.md                          # Comprehensive technical specification & usage
├── __init__.py                        # Subproject root package init
├── core/                              # [Scheme A Core]
│   ├── __init__.py
│   ├── dilution_curve.py              # Greenwood-Lemaire Nc curve, NNI, W0 clamp, singularity guards
│   ├── effective_biomass.py           # Cumulative effective biomass W_eff, N_act,cum, sawtooth elimination
│   └── objective_penalty.py           # Symmetrical tolerance interval loss function J_CNC
├── adapters/                          # [Scheme A Adapters]
│   ├── __init__.py
│   ├── stream_parser.py               # Fast fixed-column stream parser (<15 ms) for PlantGro/PlantN/FreshWt
│   ├── pest_cnc_exporter.py           # PestCNC.OUT exporter with rigid line invariant & -99.0 sentinels
│   └── instruction_generator.py       # PestCNC.OUT.ins instruction generator & observation mapping
├── calibration/                       # [Scheme A PEST++ Integration]
│   ├── __init__.py
│   ├── bounds_protocol.py             # Frozen invariant protocol: CNC_A=4.85, CNC_B=0.38, CNC_W0=1.00 fixed
│   ├── cnc_builder.py                 # Sparse phenological subsampling & pyemu.Pst attachment helper
│   └── runner_adapter.py              # Drop-in, zero-disruption DSSAT post-processor wrapper
├── scheme_b/                          # [Phase 2 Scheme B Mechanistic Engine]
│   ├── __init__.py
│   ├── acclimation.py                 # Continuous NNI photosynthetic acclimation (Sigmoid, Hill, MM)
│   ├── senescence_limiter.py          # Leaf senescence governor LFSEN = min(LFSEN, gamma * WLDOTN)
│   ├── mass_balance.py                # Machine-precision carbon and nitrogen mass balance auditor
│   ├── cropgro_proxy.py               # High-fidelity discrete-time CropGro C-N simulation engine
│   ├── adapter.py                     # High-level comparative simulation adapter (Native vs Scheme B)
│   └── patch_manager.py               # Fortran fixed-format (Col <= 72) validator & sandboxed applicator
├── fortran_patch/                     # [Phase 2 Fortran Specifications & Patches]
│   ├── README.md                      # Detailed compilation, signature changes, and coding rules
│   ├── patches/
│   │   ├── PHOTO.for.patch            # Clean unified diff patch for PHOTO.for
│   │   ├── SENES.for.patch            # Clean unified diff patch for SENES.for
│   │   └── CROPGRO.for.patch          # Clean unified diff patch for CROPGRO.for
│   └── src_scheme_b/                  # Drop-in patched Fortran source files ready for compilation
│       ├── PHOTO_CNC.FOR              # PHOTO with NNI_IN acclimation coupling
│       ├── SENES_CNC.FOR              # SENES with WLDOTN senescence limiter
│       └── CROPGRO_CNC.FOR            # CROPGRO linking NNI to PHOTO and WLDOTN to SENES
├── scripts/
│   ├── __init__.py
│   ├── run_cnc_postprocessor.py       # Standalone CLI tool to post-process DSSAT run outputs (Scheme A)
│   ├── demo_cnc_evaluation.py         # End-to-end runnable demo validating against DSSAT run data (Scheme A)
│   ├── compare_nni_trajectories.py    # Diagnostic script showing standing vs cumulative trajectories (Scheme A)
│   └── compare_scheme_b_dynamics.py   # Multi-treatment simulation comparing Native vs Scheme B (Phase 2)
└── tests/
    ├── __init__.py
    ├── test_dilution_curve.py         # Nc curve, singularity guards, Sigmoid gate, NaN/inf guards
    ├── test_effective_biomass.py      # W_eff, N_act,cum, sawtooth jump elimination, tracker
    ├── test_objective_penalty.py      # Tolerance intervals, N0 collapse, N3 luxury consumption
    ├── test_stream_parser.py          # Fast stream parser performance benchmark & whitespace tolerance
    ├── test_pest_cnc_exporter.py      # Line count invariance, exact 64-char widths, dataframe export
    ├── test_instruction_generator.py  # PEST instruction syntax, pyemu parse verification
    ├── test_cnc_builder.py            # Subsampling dates boundaries, metadata resolution, pyemu.Pst injection
    ├── test_bounds_protocol.py        # Invariant violation rejection, parameter registration
    ├── test_end_to_end_isolation.py   # Zero impact on src/ and core calibration workflows
    ├── test_scheme_b_acclimation.py   # Scheme B acclimation functions, monotonicity, bounds, zero-div guards
    ├── test_scheme_b_senescence.py    # Scheme B senescence governor, avalanche prevention, ALFDOT >= 0
    ├── test_scheme_b_mass_balance.py  # Strict mass balance audit (C & N closure < 1e-10 g N/m^2)
    ├── test_scheme_b_fortran_patch.py # Fortran 72-column compliance (0 violations) & sandboxed patch application
    └── test_scheme_b_simulation.py    # Multi-treatment simulation comparisons and DataFrame exports
```

---

## 4. Execution & CLI Usage

### 4.1 Running Phase 2 (Scheme B) Comparative Simulation & Verification

Execute side-by-side comparative simulation across N0, N1, N2, N3 treatments:

```bash
python subprojects/critical_n/scripts/compare_scheme_b_dynamics.py \
    --days 100 \
    --acclimation-type sigmoid \
    --out-dir subprojects/critical_n/reports
```

Expected output summary:
- **N0 (Severe Deficit)**: Defoliation avalanche suppressed, canopy leaf area preserved ($\Delta \text{Defoliation Saved} > 6.0\text{ g DM/m}^2$).
- **N3 (Luxury Excess)**: Runaway vegetative overgrowth smoothly plateaued.
- **Nitrogen Mass Balance Residual**: Machine precision satisfied ($\text{Max } R_N < 10^{-10}\text{ g N/m}^2$).

### 4.2 Programmatic Scheme B Python API

```python
from subprojects.critical_n.scheme_b.adapter import SchemeBAdapter
from subprojects.critical_n.scheme_b.acclimation import AcclimationType

adapter = SchemeBAdapter(acclimation_type=AcclimationType.SIGMOID)

# Run full multi-treatment evaluation
results = adapter.run_all_treatments(duration_days=100)

for trt_id, (metrics, recs_nat, recs_b) in results.items():
    print(f"Treatment: {trt_id}")
    print(f"  Native LAI: {metrics.native_final_lai:.2f} -> Scheme B LAI: {metrics.scheme_b_final_lai:.2f}")
    print(f"  Defoliation saved: {metrics.total_suppressed_defoliation:.2f} g DM/m^2")
    print(f"  N Mass Balance Conserved: {metrics.mass_balance_verified}")

# Export tidy comparison DataFrame
df = adapter.build_comparison_dataframe(results)
df.to_csv("scheme_b_comparison.csv", index=False)
```

### 4.3 Phase 1 (Scheme A) CLI Operations

```bash
# Post-processing a DSSAT execution directory (< 15 ms)
python -m subprojects.critical_n.scripts.run_cnc_postprocessor \
    --run-dir scratch/test_0.5 \
    --out-file scratch/test_0.5/PestCNC.OUT

# Running the end-to-end Scheme A demo
python subprojects/critical_n/scripts/demo_cnc_evaluation.py

# Comparing standing vs cumulative trajectories
python subprojects/critical_n/scripts/compare_nni_trajectories.py --run-dir scratch/test_0.5
```

---

### 4.4 Compilation & Verification of Custom Scheme B DSSAT Binary

The subproject includes an automated, isolated Fortran build and regression pipeline that compiles both vanilla baseline and Scheme B binaries without ever touching `C:\DSSAT48\DSCSM048.EXE`:

```bash
# Automated toolchain detection, CMake/Ninja build, and benchmark verification:
python subprojects/critical_n/scripts/build_and_verify_dssat.py

# Output executables generated in subprojects/critical_n/bin/:
#   - subprojects/critical_n/bin/dscsm048_vanilla.exe  (Baseline reference)
#   - subprojects/critical_n/bin/dscsm048_cnc.exe      (Scheme B custom binary)
```

Verification suite executed by `build_and_verify_dssat.py`:
1. **Official DSSAT Benchmarks**: `Tomato.v48` (Florida multi-year field trials), `Maize.v48`, `Potato.v48`, `Rice.v48` (all Exit Code 0, valid `Summary.OUT` / `Evaluate.OUT`).
2. **Greenhouse Experiment**: `XXQL2501.TMX` / `DSSBatch.v48` (all 10 water-nitrogen treatments, Exit Code 0, full daily `PlantGro.OUT` and `FreshWt.OUT`).
3. **Production Safety**: Hash audit guarantees `C:\DSSAT48\DSCSM048.EXE` remains 100% untouched.

---

## 5. Verification & QA Status

- **Subproject Unit & Integration Tests**: Comprehensive tests in `subprojects/critical_n/tests/` PASS (75+ tests covering asymptotic CNC, strict harvest continuity Delta NNI = 0, PEST++ zero-residual relaxation, PyEMU Pst attachment, and end-to-end PEST++ ies binary execution).
- **Fortran Fixed-Format Compliance**: All patched Fortran files (`PHOTO_CNC.FOR`, `SENES_CNC.FOR`, `CROPGRO_CNC.FOR`) verified against 72-column limits (**0 violations**).
- **Toolchain & Compilation Health**: GNU Fortran 16.2.0, CMake 4.4.2, Ninja 1.13.2 verified via `test_dssat_compiler_and_binary.py`.
- **Sandbox Binaries**: `dscsm048_vanilla.exe` and `dscsm048_cnc.exe` compiled and verified in `subprojects/critical_n/bin/`.
- **Main Project Migration & Safety Tests**: `python tests/test_migration.py` PASS (9/9), `pytest tests/test_dssat_safety.py` PASS (14/14).
- **Production Isolation**: Core codebase in `src/` and production environment `C:\DSSAT48\` are completely untouched and unaffected.
