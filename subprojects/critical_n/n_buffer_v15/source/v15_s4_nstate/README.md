# v15_s4_nstate — V15 S4 植株氮状态融合变体（ψ*）

> 状态：研究变体（engineering_validated；未经科学率定授权）
> 基线：v15_s3_v4root（S3，根吸核 v4-R2；本变体不改动其任何字节）；
> 遗传链 vnext_v15_s1（S1 冻结）→ S3（根吸核）→ **S4（氮状态融合）**
> 机制来源：4864 n_v4 世代的功能氮/参考带/NNI/growth_tau 概念与
> V15 自身的 ψ 双侧锚定、S2 信号 N 的融合
> 首建：2026-11-08（macOS，gfortran-16 x86_64）

## 1. 覆盖文件与构建

| 文件 | 作用 |
|---|---|
| `NUPTAK.for` | S3 版原样拷贝（root_kernel 1/2 开关承袭） |
| `N_BUFFER_V2.f90` | 唯一机制改动：NState.nml 读取、统一曲线 helper、ψ* 分支、ψ_pub 松弛、NStatePsi.csv 账本 |
| `NState.nml.template` | 状态选择 nml（缺省复现 S1/S3） |
| `native_nstate_tests.f90` + `run_native_tests.sh` | 属性测试（19 项，直连真实模块） |
| `replay_s4.py` / `plot_s4_diagnostics.py` | 2×2 因子重放与诊断图 |

构建：`make s4-build`（rsync 冻结 S1 源码 → `.local/build-v15-s4-nstate-src/`，
双 overlay，CMake/Ninja；产物 `.local/build-v15-s4-nstate/bin/dscsm048`，
sha256 `cf9464ba88581325e0dfed0a4ecda918e7a306c1ba6cd108aedc7d222d0da2a8`）。
单测：`make s4-tests`。S1/S3 目录与冻结树全程字节不动。

## 2. 融合状态 ψ* 的机制定义

**V15 S1 现状 ψ 的四个缺陷**：基准用总氮（储备积累→假奢侈）；plan 侧与
commit 侧双浓度基准（FNIN 目标 vs 稀释曲线）；亏缺侧无 NNI 解释；两侧
归一尺度独立无文档化关系。

**ψ*（对叶+茎）三要素融合**：

1. **功能氮基准**（v4 functional_n + S2 信号 N）：复用
   `nb_uptake_signal`（总 N 扣除"既被储备占用又超出当日可动量"的部分）；
   可动储备仍计入。锁死储备不再冒充奢侈。
2. **统一稀释曲线基准**：新增 `nb_curve_conc(weff)`（与 nb_commit 曲线、
   nb_targets 同式，含 curve_w0 低生物量平台），plan 与 commit 两侧共用，
   消除双基准。
3. **双侧锚定（nb_relative_state 原式，换输入）**：
   - 亏缺侧 `ψ* = (NNI_f − 1)/(1 − r_eff)`，NNI_f=功能氮氮营养指数
     （Lemaire 标准），r_eff=器官加权有效下沿（floor_ratio），锚定 −1
   - 奢侈侧 `ψ* = (N_func − Ncrit)/(Nmax − Ncrit)`，锚定 +1 于物理容量
     （cap_density）；**奢侈侧同样用功能氮**
   - 值连续（Ncrit 处两侧均 0）；两侧导数比 =(Nmax−Ncrit)/(Ncrit−Nmin)
     记录在案（不强行 C¹：到饥饿与到容量的生理距离本不对称）
   - 无死区（参考带概念留在修复/回补目标，状态保持分级信号）

**可选时间松弛（v4 growth_tau）**：`state_tau>0` 时发布态
`ψ_pub ← ψ_pub + (1−e^(−1/τ))(ψ*−ψ_pub)`；**getter 天然分流**——
`nb_get_psi()`（生长侧：XNSTRES/根冠分配/光合/PODS）返回 ψ_pub，
`nb_get_uptake_psi()`（根吸负反馈）恒为瞬时 ψ*（吸收响应快、生长响应慢）。
τ=0（缺省）ψ_pub≡ψ*，位级等价。

## 3. 开关矩阵与率定接线

单二进制 2×2 因子：`root_kernel(1/2) × nstate_mode(1/2)`
（RootUptake.nml / NState.nml 各自独立，均可经 DSSAT_ROOT_UPTAKE_NML /
DSSAT_NSTATE_NML 环境变量注入；两 nml 均缺省时逐字节复现 S1）。

| 组合 | 含义 |
|---|---|
| (1,1) | S1 等价（回归锚①，逐字节验证） |
| (2,1) | S3 等价（回归锚②，逐字节验证） |
| (1,2) | 状态贡献归因（S1 核 + ψ*） |
| (2,2) | **主推组合**（v4-R2 核 + ψ*） |

不新增率定参数：floor_ratio/cap_density/曲线参数沿用 SPE 卡与物种参数；
state_tau 为工程开关（缺省关）。NDecision/OrganNState 等既有账本在所有
模式下字节稳定；ψ* 专用账本 `NStatePsi.csv`
（run,trt,yrdoy,das,nstate_mode,psi_total,psi_star,nni_func,psi_pub,uptake_psi）。

## 4. 验证证据（2026-11-08，macOS x86_64）

| 证据 | 结果 |
|---|---|
| 原生属性测试（`make s4-tests`） | 19/19：曲线 helper 与 nb_targets 同式；ψ* 在 Ncrit 处两侧 0（值连续）；带下沿锚 −1、容量锚 +1；亏缺侧 NNI 线性；锁死储备剔除/可动保留；nml 缺省 mode=1；松弛 α=1−e^(−1/τ)、τ=0 位级跟随；getter 分流 |
| 双锚回归（26SP 12 处理，硬门） | (1,1) 与 S1 冻结二进制 8 账本逐字节一致；(2,1) 与 S3 二进制 7 账本（含 RootKernelLedger）逐字节一致 |
| (2,2)/(1,2) 全跑通 | 12 处理、NDecision 1513 行结构不变、NStatePsi 1513 行、守恒断言零触发 |
| 状态融合诊断（率定参数重放，`plot_s4_diagnostics.py`） | **假奢侈修正可见**：后期总氮基准 ψ 振荡 +0.6~0.8 而 ψ* 仅 +0.2~0.5，W1_N0 下 ψ* 收敛负值而总氮基准仍大幅振荡；NNI_f 梯度 W3_N3(≈1.0-1.1)>W2_N2(≈0.9-1.1)>W1_N0(后段 0.6-0.7) 正确；中期 ψ(总氮)低于 ψ* 属功能氮+统一曲线双要素联合效应（见 §5-3） |
| 鲜果产量 2×2（CHFPWS 口径） | 状态融合使两核平台下移、氮响应更陡（S4 主推 W3：60.3→70.1→71.8 t/ha；S3：63.9→77.2）；(k1,s2)与 S1 差异温和——状态贡献与核贡献可分离 |
| IES 50×4（同种子 20261107、同边界，(2,2)） | 三侧对比（`.local/v4root-ies-3way.csv`）：S1 4523→206.6（最优 154.9）；S3 2418→163.8（最优 125.3）；**S4 2568→166.3（最优成员 124.5，三侧最低）**。S4 有 1 个初始集合成员 model_failed（成员 23，第 0 代，边界参数抽取触发引擎断言被 PEST++ 容错丢弃；40/50 保留、9 筛选；对比 S1/S3 的 0 失败，如实记录待查——失败现场未保留，复跑可设 DSSAT_KEEP_FAILED_RUNS=1 取证） |

## 5. 消融差异与已知语义

1. ψ* 只改"状态表征"，不改分配目标（nb_ncrit/repair 目标仍用 DEMAND
   传入基准）与结算次序——表征层融合，机制层不动
2. 奢侈侧与亏缺侧共用功能氮基准；首日储备=0 时 ψ*≡ψ（语义自检）
3. 中期（亏缺段）ψ(总氮) 可低于 ψ*：功能氮扣储备与统一曲线 Ncrit
   （相对 plan 侧 FNIN 基准）两效应方向相反时的净结果，属融合设计的
   已知行为，非缺陷
4. state_tau 松弛只作用于生长侧（v4 同构）；根吸负反馈恒瞬时

## 6. 后续（不在本变体内）

参考带死区、C¹ 混合带、根/果进状态、Q3 池表征（另线）、state_tau 进
率定域（需消融证据支持）

## 7. 登记

`n_buffer_v15/configs/mechanism_variants.json` 追加 `v15_s4_nstate`
（真实构建+真实运行，独立 sha256；S3 条目与哈希保持不变）。
