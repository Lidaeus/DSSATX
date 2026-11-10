# v15_s3_v4root — V15 S3 根系吸氮 v4-R2 联立核变体

> 状态：研究变体（engineering_validated；未经科学率定授权）
> 基线：v15_s1_interface（S1，2026-11-01 冻结为历史参照，本变体不改动其任何字节）
> 机制来源：dssat_csm_os_4864 `Plant/CROPGRO/CG_Nitrogen.f90` 的
> `NI_ROOT_KERNEL`（mode 2）与 `NI_ROOT_UPTAKE`（n_v4 世代根系吸氮设计）
> 首建：2026-11-07（macOS，gfortran-16 x86_64）

## 1. 覆盖文件与构建

| 文件 | 作用 |
|---|---|
| `NUPTAK.for` | 唯一机制改动文件；同名覆盖冻结 S1 树的 `Plant/CROPGRO/NUPTAK.for` |
| `RootUptake.nml.template` | 内核选择 nml（缺省复现 S1） |
| `native_root_tests.f90` + `run_native_tests.sh` | 直连真实对象的属性测试（19 项） |
| `eval_ab_forward.py` | 确定性 A/B 评估（S1 vs S3 × 12 处理水氮响应） |

构建（仓库根）：`make v4root-build`（rsync 冻结源码 → `.local/build-v15-s3-v4root-src/`，
叠加 overlay 后 CMake/Ninja 构建；产物 `.local/build-v15-s3-v4root/bin/dscsm048`，
sha256 `1a812c1a17666a349ebe39a3f31f85f7200289e45f40fa6664d54bb8171634d0`）。
单测：`make v4root-tests`。冻结树 `vnext_v15_s1/source` 全程字节不动。

## 2. 根系吸氮设计机制

### 2.1 S1 现行（kernel 1，缺省）：双通道相加

逐层 `U = U_pass + U_act`（kg N/ha/d）：

- 质流：`U_pass = 0.1·RWU·σ·C`（σ_NO3=0.70、σ_NH4=0.30 硬码，C 为孔隙水浓度 mg N/L）
- 主动：`U_act = 100·RLV·DLAYR·F_DIFF·(HATS+LATS)·Φ_efflux`，
  HATS/LATS 为双亲和 MM（V_MAX_H=0.003/K_M_H=0.28；V_MAX_L=0.015/K_M_L=35），
  按 RTNO3/RTNH4 与参照值之比缩放
- **相加式**：高浓度时质流与主动同时线性增长——v4 线明确否定的双重计数形态
  （`research/n_integration_v2/integrated_mechanism_spec.zh.md:70`）

### 2.2 S3 新核（kernel 2）：v4-R2 联立求解

单通道膜 Michaelis-Menten 在**根表浓度 cr** 处求值，与（质流+有效扩散）供给
联立平衡（移植自 `CG_Nitrogen.f90:1769-1798`，64 步二分）：

```
根长      Lroot = 100·RLV·DLAYR                     [m root/m²]
孔隙浓度  C     = 10·SNO3/(DLAYR·SW)               [mg N/L]（≡ v4 的 NO3·BD/θ）
质流供给  mf    = 0.01·RWU·C                       [g N/m²/d]
膜能力    cap   = Lroot·root_v·poolfactor          [g N/m²/d]
膜通量    mem(c)= cap·c/(root_k+c)
湿度因子  wet   = 三角形（LL→DUL 升、DUL→SAT 降），poolfactor = feedback·√wet

若 mem(C) ≤ mf：uptake = mem(C)，cr = C（膜不限制）
否则二分解     mem(cr) = mf + 0.001·diffusion_k·wet·Lroot·(C−cr)
               uptake  = mem(cr) ∈ [0, mem(C)]
```

含义：膜吸收把根表浓度从土体浓度 C 拉低到 cr，质流+扩散补充亏缺；
**总吸收 = 膜在亏缺浓度下的实际通量，不是 mf+主动相加**。由此：
- 高 C → 膜饱和封顶 `uptake → cap`（消除双重计数的奢侈过吸收）
- 低 RWU/低湿 → 平滑转为扩散限制（水氮耦合的下行约束）

NH4（kernel 2）改用 v4 原生形式（去 ANDEM 共同缩放与 0.04 低浓截断）：
`U_NH4 = 10·[0.1·Lroot·√wet·(1−exp(−0.08·NH4))·RTNH4]`，库存下限 0.5 µg/g
（NO3 为 0.25）。逐层账本写入 `RootKernelLedger.csv`
（day_index,layer,c,rwu,rootlength,wet,poolfactor,mf,mem_at_cr,cr,diffusion,uptake,nh4,mode）。

## 3. 负反馈信号工作机制

**植物氮状态 ψ**（N_BUFFER_V2 `nb_plan`，日初、先于 NUPTAK；叶+茎）：
亏缺 `(Σn−Ncrit)/(Ncrit−Nmin)` ∈ [−1,0)；奢侈 `(Σn−Ncrit)/(Nmax−Ncrit)` ∈ (0,1]。

**当日吸收负反馈（S3 接线）**：`feedback = nb_feedback_response(ψ, α_H)`
（S1 接口修复的 tanh 正则化 logistic：ψ≤0 恒 1；ψ>0 随 α_H·ψ 下调），
经 `poolfactor = feedback·√wet` **乘 root_v**——与 v4 的
`exp(−pool_beta·fill)` / QH1 `fQ=1/(1+x²)` 同拓扑（库充盈→Vmax 降→
联立解自动降吸收），状态量用 V15 现有 ψ 而非引入平行 Q3 池。
单测定量验证：ψ=1（满奢侈）时吸收降至亏缺态的 1.6%（0.030 vs 1.88 kg/ha）。

**接受侧硬上界（保留 V15 账目链，次序不变）**：
kernel 势 → D_max 账目上限（`nb_plan` 头窗，NUF 同比缩放）→
碳受限缩放（CROPGRO.for）→ `nb_allocate` → `nb_settle_root`（未接受量按比例
回写 UNO3/UNH4、预付碳退款）——承担 v4 `NI_ACCEPT_UPTAKE`/`NI_SETTLE` 角色。

**生长侧多日闭环（承 S1 不变）**：ψ<0 → `XNSTRES=max(0.5, 1−β_grow·(−ψ))`
→ NSTRES 下调、根冠分配上调（`nb_root_partition`）、光合因子
（`nb_photo_factor`）与果实 N（PODS `nb_function_response`）下调；
次日 SOILNI 扣土。

## 4. 开关与率定接线

运行目录放 `RootUptake.nml`（或 `DSSAT_ROOT_UPTAKE_NML` 指向任意路径——
率定沙箱用 env）：

```
&ROOTUPTAKE root_kernel=2, root_v=0.0002, root_k=10.0, diffusion_k=0.005 /
```

- `root_kernel=1`（缺省/nml 缺失）：**逐字节复现 S1**（回归锚点，已验证）
- `root_kernel=2`：v4-R2 联立核
- root_v [g N/m root/d]、root_k [mg N/L]、diffusion_k [L/m root/d]：
  4864 `stage5_engineering.nml` 工程值，**UNCALIBRATED，不进 PEST 率定域**
- SPE 16 字段卡与 protocol.py 注入格式零改动；现有率定管线无需适配

## 5. 验证证据（2026-11-07，macOS x86_64）

| 证据 | 结果 |
|---|---|
| 原生属性测试（`make v4root-tests`，直连真实 NUPTAK+N_BUFFER_V2） | 19/19 通过：膜/供给界、高 C 膜饱和（消除比例增长）、干层零吸收、零蒸腾纯扩散为正且质流增强、逐层守恒 Σ=TRNU×10、奢侈 ψ 下调 98% |
| 回归①（硬门） | nml 缺失时与 S1 冻结二进制 26SP 全 12 处理：12 个 N_BUFFER 账本 + Summary/Evaluate/PlantGro/FreshWt 全部零差异（唯一差异为输出头时间戳） |
| 回归② | kernel=2 全 12 处理跑通；RootKernelLedger 972 层-日；day1 mf=0 时 cr=3.0<C=14（根表耗竭、纯扩散供给）✓；引擎内置 N/C 守恒断言全程未触发 |
| 确定性 A/B（基线参数，xxql2601 sasc70 12 处理，`eval_ab_forward.py`；鲜果产量口径 CHFPWS，非干重 PWAMS） | S1 植株 N 对施氮梯度钝化（N1 即饱和：83→100→100→100）；**S3 恢复梯度响应**（W3：49→64→70→73；W2：59→67→66→74）。鲜果产量：S1 对水氮全面钝化（41-47 t/ha 平坦），**S3 呈水氮互作**——W3 施氮 +48%（19.0→28.2）、W2 +23%、W1 水分限制下氮响应消失（+7%）。绝对吸收水平 S3 为 S1 的 60-77%（UNCALIBRATED root_v 所致，属预期） |
| IES A/B（同种子 20261107、同边界、50×4、4 agents） | S1：mean Phi 4523.18→206.63（最优成员 154.9）；**S3：mean Phi 2417.95→163.85（最优成员 125.3），最终 Phi 低 20.6%**；两侧均零模型失败（S1 8/50、S3 11/50 被 high-Phi 筛选）。证据 `.local/v4root-ab-ies.csv` |
| 机制账本（26SP 全季，972 层-日） | 质流分担 mf/uptake = 17%（扩散主导供给），day1 纯扩散日 cr=3.0<C=14 mg/L（根表耗竭可见）。证据 `.local/v4root-kernel-ledger-r2-26sp.csv` |

## 6. 消融差异清单（相对 v4 原型的有意取舍）

1. θ 用 SW（v4 用 SPAM 快照 `SW_AVAIL+LL−0.5·RWU/DLAYR`）——免 SPAM 补丁
2. RWU 沿用 `GET('SPAM','UH2O')`+EP 回退（v4 缺快照即 error stop）
3. Φ_efflux=1−ψ⁶ 在 kernel 2 不施加（v4 无对应物；奢侈封锁由强 feedback 承担）
4. 反馈键控 ψ（器官 N 储备状态）而非 v4 的 Q3 无机转运池——免结算次序冲突
5. NH4 的 RTNH4 缩放保留物种级（v4 同）；σ_NH4/SCALE_NH4 双通道在 kernel 2 弃用

## 7. 后续（不在本变体内）

- root_v/root_k/diffusion_k 率定化：需先扩 bounds（AGENTS 规程审批）
- Q3 池/QH1 fQ/动态接收容量：若 ψ 键控消融不足再评估
- v4 同化链（共享碳预算 NI_ASSIMILATE）、LAI 优先扩叶、C4 碳账：独立设计

## 8. 登记

`n_buffer_v15/configs/mechanism_variants.json` 追加条目
`v15_s3_v4root`（binary=`.local/build-v15-s3-v4root/bin/dscsm048`，
sha256 见上；真实构建+真实运行，满足"不得拼装未实际运行的模型"）。
