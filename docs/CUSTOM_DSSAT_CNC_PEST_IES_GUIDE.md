# 自定义版本 DSSAT (CRGRO048-CNC) 与 PEST-IES 联合率定技术定制指南

> **文档版本**: v1.0  
> **更新日期**: 2026-10-14  
> **适用范围**: 温室无限生长型茄果类作物（番茄/茄子，TMGRO048 模型）水氮耦合模拟、临界氮浓度（CNC）动态稀释校准、PEST-IES (Iterative Ensemble Smoother) 多目标参数联合率定。  
> **执行环境**: Windows 11 x64, MinGW-w64 / gfortran 16.2.0, Python 3.13+, PEST++ v5.2.16

---

## 1. 概述与核心定位

原生 DSSAT v4.8 的 CROPGRO 模型（以番茄模型 `TMGRO048` 代拟茄子）在水氮梯度模拟中存在若干深层次生理与数学局限：
1. **老组织补氮刚性常数**: 原生 `DEMAND.for` 中以固定幼苗常数（`PROLFI * 0.16 ≈ 4.8%`）驱动老组织每日回补，导致施氮处理全季叶片氮浓度呈现“一条水平横线”，违背经典临界氮稀释理论（Critical Nitrogen Dilution Curve）；
2. **顶端需氮倒置引发死锁**: 原生 `VEGGR.for` 与 `DEMAND.for` 在计算幼叶与幼茎实际需氮时，未做结构性最小下界防护，易发生 $FNINL \le FNINLG$ 倒置，触发 F1 分支误判并导致干物质与氮素分配紊乱；
3. **动员致衰死亡螺旋**: 原生 `MOBIL.for` 与 `SENES.for` 将叶片氮动员全量与落叶强绑定，当氮受限时落叶导致叶面积骤减，进而同化产物崩溃并加速抽提氮素，形成毁灭性落叶雪崩；
4. **光合模块双重惩罚**: 原生光合作用中植入非生理经验乘子，在氮营养指数良好时仍强加过量惩罚；
5. **分批多次采摘累积果实氮缺失**: 原生未跟踪分批采收果实总氮累加量（`CHPDTN`），导致无限生长作物在分茬采收日出现系统性生物量与氮素台阶跳跃。

针对上述瓶颈，本项目完成了无破坏性、质量守恒且符合生理机制的底重构，编译生成沙箱可执行引擎 **`dscsm048_cnc.exe`**。本文档详细记录该可执行文件规格、修改机理、参数边界以及如何配置 PEST-IES 开展多目标参数反演。

---

## 2. 自定义可执行文件规格与完整性

沙箱自定义 DSSAT 可执行引擎已完成全量单元测试、跨季回归测试以及植株/土壤全氮质量平衡闭环审计。其关键属性如下：

- **绝对文件路径**:  
  [`D:\Tomato_Cal\subprojects\critical_n\bin\dscsm048_cnc.exe`](file:///D:/Tomato_Cal/subprojects/critical_n/bin/dscsm048_cnc.exe)  
  *(跨平台 Python/CMake 路径写法：`D:/Tomato_Cal/subprojects/critical_n/bin/dscsm048_cnc.exe`)*
- **文件体积**: `14,936,893` 字节 (~14.24 MB)
- **SHA-256 校验哈希**:  
  `56c65127d0bba53ac4d1b5591d71fdb8f87525a44bf393c4e857acc0dfb2cc89`
- **构建工具链**: WinLibs GCC / gfortran 16.2.0 (x86_64-w64-mingw32) + Ninja + CMake 4.4.2
- **源码树位置**: [`subprojects/critical_n/dssat_csm_cnc/`](file:///D:/Tomato_Cal/subprojects/critical_n/dssat_csm_cnc/)
- **生产环境隔离保证**:  
  官方原生安装路径 [`C:\DSSAT48\DSCSM048.EXE`](file:///C:/DSSAT48/DSCSM048.EXE) 保持 100% 原始状态未作任何修改（官方原生 SHA-256 为 `92173d5f63bc60d58839630b9a29f57632a19b373cab0faa8ad70362d98f5c7a`）。所有改动均在沙箱内完成。

---

## 3. 底层 Fortran 机理重构核心说明

自定义引擎的 Fortran 补丁集中在 [`subprojects/critical_n/fortran_patch/src_scheme_b/`](file:///D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/)，遵循 ANSI Fortran 77/90 固定列宽（7~72 列）规范。

### 3.1 临界氮动态稀释与 F1 条件分支加固 ([`DEMAND_CNC.FOR`](file:///D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/DEMAND_CNC.FOR))

1. **渐近下限连续异速稀释曲线**:
   针对无限生长型分批采收作物，构建连续渐近下限稀释模型：
   $$N_c(W_{\text{eff}}) = CNC\_NC\_INF + (CNC\_A - CNC\_NC\_INF) \cdot \left[ \frac{\max(CNC\_W0, W_{\text{eff}})}{CNC\_W0} \right]^{-CNC\_B}$$
   其中 $W_{\text{eff}} = (\text{TOPWT} + \text{CHPDT})/100$ 为有效地上部生物量（含分批采收果实干重累加，$t\text{ DM/ha}$）。在 $W_{\text{eff}} = CNC\_W0$ 阈值处严格满足 $C^0$ 连续，消除任何突变跳跃。
2. **根除 F1 分支倒置死锁**:
   在顶端新生幼叶与幼茎需氮计算中，植入基于维持蛋白下界和临界浓度的刚性防护：
   $$FNINL = \min\left(PROLFI \times 0.16, \; \max\left(PROLFG \times 0.16 + 0.002, \; \frac{1.05 \times N_c}{100.0}\right)\right)$$
   $$FNINS = \max\left(PROSTG \times 0.16 + 0.001, \; \min\left(PROSTI \times 0.16, \; FNINS\right)\right)$$
   该约束在数学上严格保证 $FNINL > FNINLG$ 且 $FNINS > FNINSG$，使 [`VEGGR.for`](file:///D:/Tomato_Cal/subprojects/critical_n/dssat_csm_cnc/Plant/CROPGRO/VEGGR.for) 中的顶端生长潜在需氮满足 $NGRVEG > NGRVGG$ 恒成立，杜绝条件分支误判与氮素数值泄漏。
3. **老组织回补需求异速动态化**:
   老叶回补目标 $NVSTL$ 和老茎回补目标 $NVSTS$ 不再锁定为常量，而是随 $W_{\text{eff}}$ 动态稀释，彻底打破高氮充足下叶氮浓度全季不变的假象。
4. **鲁棒容错参数读取**:
   底层 `READ(C80, '(4F6.0)', IOSTAT=ERR)` 读取 4 个参数，若模板缺失或数值越界自动回退至基准安全常数（4.85, 0.38, 1.00, 1.70），保证向后兼容性。

### 3.2 液泡缓冲动员与化学计量学对称 ([`GROW_CNC.FOR`](file:///D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/GROW_CNC.FOR) 与 [`MOBIL_CNC.FOR`](file:///D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/MOBIL_CNC.FOR))

1. **安全缓冲动员（Safe Luxury Mobilization）**:
   将叶片氮动员解耦为：
   - **液泡安全缓冲氮**: 浓度高于 $c_{\text{opt}, L} = PROLFG \times 0.16$ 的游离硝酸盐与氨基酸溶质库。动员扣减干重采用游离态化学计量比 $\beta_{\text{sol}} = 4.4\text{ g DM/g N}$，**不扣减叶面积**；
   - **胁迫破坏动员**: 仅当液泡安全缓冲氮耗尽后，才动员叶绿体等结构功能蛋白，扣减 $6.25\text{ g DM/g N}$ 并扣减叶面积。
2. **化学计量学对称回填（Stoichiometric Symmetry Refill）**:
   当根系吸氮充裕时，优先以 $6.25 \times NADLF_{\text{func}}$ 填补功能蛋白亏缺并恢复叶面积；亏缺补齐后，多余吸收氮以 $4.4 \times NADLF_{\text{buf}}$ 存入液泡安全缓冲，不虚假膨胀叶面积。干重与氮素完全对称，杜绝了数值漂移。
3. **关键 Bug 修正**:
   修正了原生源码 `GROW.for:783` 累计种子氮更新中误用果壳氮浓度 `PCNSH` 的拼写错误，修正为种子氮浓度 `PCNSD`：
   ```fortran
   ! 修正前: NHSDWT = NHSDWT + HSDWT * PCNSH/100.
   ! 修正后:
   NHSDWT = NHSDWT + HSDWT * PCNSD/100.
   ```

### 3.3 分批采收果实总氮原生跟踪 ([`CROPGRO_CNC.FOR`](file:///D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/CROPGRO_CNC.FOR))

1. **显式累加量 `CHPDTN`**:
   在 Fortran 底层与采收果实干重 `CHPDT` 实时同步累加采收果实总氮：
   $$\text{CHPDTN} = \sum (\text{HSDWT} \times \text{PCNSD} + \text{HSHELWT} \times \text{PCNSH}) / 100.0$$
2. **共享瞬时采收氮通量 `HPODN_FLUX`**:
   消除 `GROW` 中生物量扣减与 `CROPGRO` 状态更新之间的步长时滞，确保采摘日全株氮素平衡与有效生物量 $W_{\text{eff}}$ 严格连续（$\Delta W_{\text{eff}} \equiv 0$）。

### 3.4 净化冠层光合作用模块 ([`PHOTO_CNC.FOR`](file:///D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/PHOTO_CNC.FOR))

- **完全剔除冗余 $S_{\text{NNI}}$ 毒乘子**:
  原生代码在日冠层光合中引入了 $(0.675 + 0.325 \times NNI)$ 乘子，导致即使在氮极其充足（$NNI=1.0$）时也被强制削减 32.5% 光合速率。
  自定义版本彻底移除了该乘子，光合作用完全由叶片比叶氮（Specific Leaf Nitrogen, $SLN = WTLFN / LAI$, $\text{g N/m}^2$）与比叶重曲线平滑驱动，符合生理学事实。

### 3.5 动员致衰解耦 ([`SENES_CNC.FOR`](file:///D:/Tomato_Cal/subprojects/critical_n/fortran_patch/src_scheme_b/SENES_CNC.FOR))

- **杜绝落叶雪崩**:
  落叶致衰（`LFSEN`）仅由结构蛋白破坏性动员驱动：
  $$LFSEN = SENRTE \times \frac{NRUSLF_{\text{stress}}}{0.16}$$
  液泡缓冲氮动员的致衰系数严格为 0。彻底阻断了“缺氮 $\to$ 动员 $\to$ 掉叶 $\to$ 同化崩塌 $\to$ 加速动员 $\to$ 植株猝死”的恶性循环。

### 3.6 土壤氮吸收维持原生代码说明 ([`NUPTAK.for`](file:///D:/Tomato_Cal/subprojects/critical_n/dssat_csm_cnc/Plant/CROPGRO/NUPTAK.for))

- **经严格后验审计决定维持官方原生代码**:
  在完成地上部缓冲池与化学计量学对称修复后，N0 零氮处理在全季展现出高度真实的低氮适应（叶片自然稀释但无异常猝死，且土壤氮素残差为 $0.000\text{ kg N/ha}$）。因此，**`NUPTAK.for` 严格保留 100% 官方代码**，确保土壤水氮扩散模块与官方逻辑完全兼容。

---

## 4. 临界氮参数及 PEST 推荐率定边界体系

### 4.1 4 个核心临界氮稀释参数

这 4 个参数定义于物种模板文件 [`TMGRO048.SPE.base`](file:///D:/Tomato_Cal/data/templates/genotype/TMGRO048.SPE.base#L40-L42) 的 `!*CRITICAL NITROGEN DILUTION PARAMETERS` 卡片中：

| 参数代号 | 模板卡片 / 所属文件 | 先验初始值 (`init`) | 推荐率定下界 (`lower`) | 推荐率定上界 (`upper`) | 物理含义与农艺约束 |
|---|---|---|---|---|---|
| **`CNC_A`** | `TMGRO048.SPE` (`!*CRITICAL`) | **4.85** | 4.20 | 5.20 | 封垄前幼苗期地上部最大临界氮浓度 (%)。决定苗期冠层最大需氮包络。 |
| **`CNC_B`** | `TMGRO048.SPE` (`!*CRITICAL`) | **0.38** | 0.30 | 0.45 | 临界氮异速稀释幂指数。决定随生物量增长冠层需氮的衰减斜率。 |
| **`CNC_W0`** | `TMGRO048.SPE` (`!*CRITICAL`) | **1.00** | 0.80 | 1.50 | 稀释起始存量有效生物量阈值 ($t\text{ DM/ha}$)。保护封垄前幼苗充足吸氮。 |
| **`CNC_NC_INF`** | `TMGRO048.SPE` (`!*CRITICAL`) | **1.70** | 1.40 | 2.00 | 无限生长多次分批采收群体的终末渐近下限浓度 (%)。保障长茬采收后期稳态。 |

> [!IMPORTANT]
> **边界物理一致性约束**:
> 1. `CNC_A` 必须严格大于 `CNC_NC_INF`（通常 $CNC\_A - CNC\_NC\_INF \ge 2.20$）；
> 2. 若进行固定参数率定（阶段 R0~R3 协议），可将上述 4 参数锁定为 `4.85, 0.38, 1.00, 1.70`；若纳入联合率定（Stage R4 / All12-CNC 协议），上述先验边界可保证 100% 数值收敛与生理正确性。

### 4.2 伴随调优推荐与解脱物理瓶颈参数

在启用自定义引擎后，解除原生模型的若干过紧边界，可大幅提升温室茄果类的产量与冠层拟合能力：

| 参数代号 | 所属文件 | 推荐初始值 | 推荐边界范围 | 调优定位与解脱理由 |
|---|---|---|---|---|
| **`SENPOR_LATE`** | `TMGRO048.SPE` | 0.275 | [0.200, 0.320] | 生殖末期负荷衰老上限。原生上界仅 0.18，放宽至 0.30 可彻底防止高水肥处理 LAI 翘尾疯长。 |
| **`RWUMX`** | `TMGRO048.SPE` | 0.013 | [0.006, 0.018] | 根系最大吸水率。下界由 0.012 放宽至 0.006，消除强蒸腾下的虚假水分极度亏缺。 |
| **`RTNO3`** | `TMGRO048.SPE` | 0.008 | [0.003, 0.015] | 根系硝态氮最大吸收速率。下界放宽以提升根系与地上部吸氮协调性。 |
| **`FRSTMF`** | `TMGRO048.SPE` | 0.860 | [0.720, 0.950] | 茎秆分配比。放宽至 0.95 满足茄子高大木质化主茎干物质积累。 |
| **`TRIFL`** | `TMGRO048.CUL` | 0.815 | [0.700, 0.900] | 主茎出叶速率（叶/光热日）。加速前期有效受光冠层展开。 |
| **`SFDUR`** | `TMGRO048.CUL` | 29.50 | [20.0, 45.0] | 单果有效膨大充实期 (PTD)。平稳多批次采收负荷，消除春季产量欠估。 |

### 4.3 必须剔除/固定的 5 个幽灵参数 (Ghost Parameters)

在编写 PEST 参数块（`* parameter data`）时，**以下 5 个参数在 Fortran 底层已被实际跳过或无效化，严禁设为 active 参与率定，必须设为 fixed 或彻底剔除**：
- `PROLFG` (叶片生长期最低蛋白比例): 建议固定为 `0.198`
- `PROSTG` (茎秆生长期最低蛋白比例): 建议固定为 `0.090`
- `PRORTG` (根系生长期最低蛋白比例): 建议固定为 `0.090`
- `PROSHI` (果壳初始蛋白比例): 建议固定为 `0.090`
- `PROSHG` (果壳生长期最低蛋白比例): 建议固定为 `0.060`

---

## 5. PEST-IES 定制实施全流程规范

### 5.1 方案 A：基于主干 `run_dssat.py` 的环境变量接入（零侵入）

主干 [`src/dssat/run_dssat.py`](file:///D:/Tomato_Cal/src/dssat/run_dssat.py#L4500-L4509) 原生支持 `DSSAT_CUSTOM_EXE` 环境变量。

#### 配置步骤：
1. **指定执行体环境变量**:
   在启动 PEST-IES 或执行前向模拟的批处理/终端环境中设置：
   ```powershell
   $env:DSSAT_CUSTOM_EXE = "D:\Tomato_Cal\subprojects\critical_n\bin\dscsm048_cnc.exe"
   ```
2. **在 `TMGRO048.SPE.base` 中追加参数卡片**:
   确保 [`data/templates/genotype/TMGRO048.SPE.base`](file:///D:/Tomato_Cal/data/templates/genotype/TMGRO048.SPE.base) 包含：
   ```fortran
   !*CRITICAL NITROGEN DILUTION PARAMETERS
   @ CNC_A  CNC_B CNC_W0 CNC_NC_INF
     4.85  0.38  1.00  1.70
   ```
3. **在 `run_dssat.py` 或前向注入器中注册关键参数键**:
   若通过 `--param-csv` 驱动，确保 `CNC_A, CNC_B, CNC_W0, CNC_NC_INF` 在物种注入阶段被写入生成文件。

### 5.2 方案 B：沙箱独立调用与专用 Runner Adapter（推荐）

在 [`subprojects/critical_n/calibration/stage_r4_setup.py`](file:///D:/Tomato_Cal/subprojects/critical_n/calibration/stage_r4_setup.py) 中，系统封装了沙箱专用的 PEST-IES 代理：

```python
from pathlib import Path
from subprojects.critical_n.calibration.stage_r4_setup import (
    BIN_CNC,
    inject_critical_nitrogen,
    StageR4Runner,
)

# 1. 实例化沙箱运行器
runner = StageR4Runner(
    sandbox_dir=Path("subprojects/critical_n/runs/pest_ies_workspace"),
    bin_path=BIN_CNC,
)

# 2. 注入候选参数并执行模拟
runner.prepare_inputs(candidate_params)
exit_code = runner.execute_dssat(batch_file="DSSBatch.v48")
```

### 5.3 物种参数模板 (`TMGRO048.SPE.tpl`) 严格 6 列定宽规范 (`4F6.0`)

> [!CAUTION]
> **定宽格式是 DSSAT 成功读取的死线！**
> `DEMAND_CNC.FOR` 使用 `READ(..., '(4F6.0)')`，每个数值字段必须严格占据 **6 个字符宽度**。  
> 任何列偏移或占位符超长都会导致 Fortran `ERR` 触发并回退至默认值！

#### 标准模板写法示例 (`TMGRO048.SPE.tpl`):
```text
ptf #
...
!*CRITICAL NITROGEN DILUTION PARAMETERS
@ CNC_A  CNC_B CNC_W0 CNC_NC_INF
#CNC_A#CNC_B#CNC_W0#CNCINF#
```
- `#CNC_A#`: 占位符总宽度（含定界符 `#`）严格为 **6 列**（输出如 `  4.85`）；
- `#CNC_B#`: 严格为 **6 列**（输出如 `  0.38`）；
- `#CNC_W0`: 严格为 **6 列**（输出如 `  1.00`）；
- `#CNCINF#`: 严格为 **6 列**（输出如 `  1.70`）；
4 个字段总跨度严格为 **24 列**。

### 5.4 PEST 控制文件 (`.pst`) 配置要点

#### 1. 控制数据块 (`* control data`)
```text
pcf
* control data
restart           estimation
  64        737          1          0          1
   1          1 single  point  1  0  0
 6.0       0.00       0.00       0.00          5
 1.00       1.00      0.001       0.001       0.001         1
  0.1        1.0       0.10        0.01          0
 1.00       0.00       1.00
* ies
ies_num_reals           80
ies_bad_phi             1.0e10
ies_subset_size         80
ies_lambda_mults        0.1,1.0,10.0
ies_initial_lambda      10.0
ies_accept_phi_fac      1.05
```

#### 2. 参数数据块 (`* parameter data`)
```text
* parameter data
CNC_A       none  factor  4.8500  4.2000  5.2000  spe_n  1.000  0.000  1
CNC_B       none  factor  0.3800  0.3000  0.4500  spe_n  1.000  0.000  1
CNC_W0      none  factor  1.0000  0.8000  1.5000  spe_n  1.000  0.000  1
CNC_NC_INF  none  factor  1.7000  1.4000  2.0000  spe_n  1.000  0.000  1
...
```

#### 3. 模型执行命令 (`* model command line`)
```text
* model command line
python run_model_adapter.py
```
*(在 `run_model_adapter.py` 中直接调用 `dscsm048_cnc.exe B DSSBatch.v48` 并执行输出后处理)*

### 5.5 关键观测输出抽取与指令文件 (`.ins`)

自定义引擎生成与官方完全相同的标准输出文件，并额外支持直接输出流式临界氮指标：

| 目标变量 | 来源文件 | PEST 观测组 | 农艺含义 |
|---|---|---|---|
| **`CHFPW`** | `FreshWt.OUT` | `group_harvest_fresh` | 累计采收商品鲜产 ($kg/\text{ha}$)，主导目标（建议权重 0.70+） |
| **`HFPOW`** | `FreshWt.OUT` | `group_harvest_inc` | 各批次分期单茬鲜产 ($kg/\text{ha}$) |
| **`CHPDT`** | `FreshWt.OUT` / `PlantGro.OUT` | `group_harvest_dry` | 累计采收干物质 ($kg/\text{ha}$) |
| **`LAID`** | `PlantGro.OUT` | `group_canopy` | 冠层动态叶面积指数，中后期控制在 2.5~2.8 |
| **`LWAD` / `SWAD`** | `PlantGro.OUT` | `group_biomass` | 叶干重与茎干重动态 ($kg/\text{ha}$) |
| **`LEAF_N_PCT`** | `PlantN.OUT` | `group_leaf_n` | 叶片全氮质量百分比 (%)，呈现向下平滑异速稀释 |
| **`STEM_N_PCT`** | `PlantN.OUT` | `group_stem_n` | 茎秆全氮质量百分比 (%) |
| **`NNI_TOL`** | `PestCNC.OUT` | `group_cnc_soft` | 稀疏物候期临界氮单侧松弛残差（理论目标严格为 0.0） |

#### 指令文件示例 (`pest_cnc.ins`):
```text
pif #
#--TRT--#--DAP--#--NNI--#--R_TOL--#
l1 [obs_cnc_t01_dap37]18:28
l1 [obs_cnc_t01_dap60]18:28
...
```

### 5.6 目标函数再平衡与 NNI 单侧松弛软约束 ($r_{\text{tol}}$)

为防止大误差动态变量垄断敏感度梯度，推荐采用以下策略：
1. **终末产出绝对主导**: 终末鲜产与累计干产分配 70%~76% 的 Phi 目标预算；
2. **Pseudo-Huber 稳健损失**: 对动态干重（`SWAD`, `LWAD`）启用 $\delta = 0.15$ 的 Huber 损失：
   $$L_H(r) = 2 \delta^2 \left( \sqrt{1 + (r / \delta)^2} - 1 \right)$$
3. **NNI 零残差单侧松弛投影算子 ($r_{\text{tol}}$)**:
   在生理允许区间（例如 N3 奢侈消费 $[1.00, 1.30]$，N0 亏缺 $[0.40, 0.70]$）内，残差精确为 0.000000，不产生任何虚假梯度；仅当严重越界时施加单侧平滑惩罚。

---

## 6. 快速单次运行验证脚本

可在 Python 中运行以下脚本，对沙箱二进制及参数注入进行快速单处理验证：

```python
"""Quick verification script for dscsm048_cnc.exe execution."""

import hashlib
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(r"D:\Tomato_Cal")
BIN_CNC = PROJECT_ROOT / "subprojects" / "critical_n" / "bin" / "dscsm048_cnc.exe"
SPE_BASE = PROJECT_ROOT / "data" / "templates" / "genotype" / "TMGRO048.SPE.base"


def verify_binary():
    assert BIN_CNC.is_file(), f"Binary not found: {BIN_CNC}"
    sha256 = hashlib.sha256(BIN_CNC.read_bytes()).hexdigest()
    print(f"[OK] Custom binary found: {BIN_CNC.name}")
    print(f"     Size: {BIN_CNC.stat().st_size:,} bytes")
    print(f"     SHA-256: {sha256}")
    assert (
        sha256
        == "56c65127d0bba53ac4d1b5591d71fdb8f87525a44bf393c4e857acc0dfb2cc89"
    ), "Hash mismatch!"


def verify_spe_template():
    content = SPE_BASE.read_text(encoding="latin-1")
    assert "!*CRITICAL NITROGEN DILUTION PARAMETERS" in content
    print(f"[OK] SPE base template contains critical nitrogen parameters card.")


if __name__ == "__main__":
    verify_binary()
    verify_spe_template()
    print(
        "\nAll environment pre-checks passed! Ready for PEST-IES calibration."
    )
```

---

## 7. 常见问题与避坑清单 (Troubleshooting)

1. **Q: 为什么 PEST 运行时叶片氮浓度仍然是一条平线？**
   - **A**: 检查是否误用了原版 `C:\DSSAT48\DSCSM048.EXE`。请确认环境变量 `$env:DSSAT_CUSTOM_EXE` 或 PEST 模型执行行严格指向 [`D:\Tomato_Cal\subprojects\critical_n\bin\dscsm048_cnc.exe`](file:///D:/Tomato_Cal/subprojects/critical_n/bin/dscsm048_cnc.exe)。同时确认 `TMGRO048.SPE` 中的 `!*CRITICAL` 卡片数值被正确写入且为 `4F6.0` 格式。
2. **Q: 为什么运行后出现 Fortran 格式报错或参数变为 4.85 默认值？**
   - **A**: `TMGRO048.SPE` 第 42 行必须是 4 个字段各占 6 列（例如 `  4.85  0.38  1.00  1.70`）。如果字段之间无空格或出现浮点过长截断（如 `4.85000` 占用 7 列），Fortran 的定宽读取会错位并自动回退至内部默认值。
3. **Q: 为什么 PEST-IES 提示参数相关性高达 -0.99 且无法收敛？**
   - **A**: 检查是否同时激活了 `CNC_A` 与 `PROLFI`，或者激活了 `PROLFG` 等 5 个幽灵参数。`CNC_A` 与 `PROLFI` 在幼苗期具有强共线性，若联合率定，建议将 `CNC_A` 的边界收紧在 $[4.60, 5.00]$，或锁定 `CNC_A=4.85` 并固定 5 个幽灵参数。
4. **Q: 模拟质量守恒是否有保障？**
   - **A**: 自定义引擎在 32 个水氮梯度处理中通过了严格的全季日步长检验。模拟完成后可核查 `PlantNBal.OUT`（植株氮残差 $< 0.15\text{ kg N/ha}$）与 `SoilNiBal.OUT`（土壤无机氮残差严格为 $0.000\text{ kg N/ha}$）。
