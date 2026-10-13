# v49 局部机制多臂试验：设计、验收与执行交接

日期：2026-09-02。性质：探索性局部 IES，不是正式晋级或独立验证。

## 1. 不变条件与归因边界

- 锚点严格为 v48 `_r2` 第4轮成员55，来源 `workspace/reports/e02_formal_v48_20260902_candidates/lowest_phi_params.csv`。不调用旧的“最佳成员”自动标签。
- 使用官方 `DSCSM048.EXE`；两季22处理与 v48 完全相同，全部属于本轮拟合资料，不称独立验证。25FA不参与。
- bundle、观测数据和目标函数均不变；不重建 bundle、不改原始实测值。
- 各臂 ICNS_25SP、ICNS_26SP 均开放为 **0.4–0.8**。A臂仅开放这两个参数，辨别初始氮再优化的贡献。
- ICNS仍乘在现有bundle上：25SP double-N bundle；26SP s0p34 bundle。26SP相对原始实测的名义乘积为0.136–0.272，实际受 NH4=0.1、NO3=0.5 下限截断。不是把原始实测直接乘0.4–0.8。深度仍为25SP≤100cm、26SP≤60cm。
- 所有非本臂参数固定到成员55，包括33个土壤参数与PAGE/PENV。固定参数仍必须写入DSSAT，不能退回bundle或模板默认值。
- XFPHT、XFRT、FINREF不再扩界，本轮固定。FRLFF仅E臂开放，沿用0.15–0.50；原v48搜索范围保留在各冻结表的source_lower/source_upper，不改旧冻结文件。
- E是独立的冠层机制臂，必然会改变同化面积和碳分配；不能将E的收益解释为纯氮吸收机制。B/C/D/F/G才保持冠层参数固定。

## 2. 分臂配置

所有范围均包含成员55。除下表及公共ICNS两个参数外，其他参数固定。

| 臂 | 增加的自由参数及范围 | 活跃数 | 执行 |
|---|---|---:|---|
| A_ic_control | 无，只有两季ICNS | 2 | IES |
| B_n_uptake | RTNO3 0.008–0.035；RTNH4 0.015–0.050 | 4 | IES |
| C_n_demand | NSTFAC 0.15–0.35；PROLFI 0.20–0.28；PROLFG 0.13–0.20 | 5 | IES |
| D_leaf_n_photo | FNPGN1 0.9–1.8；FNPGN2 2.2–4.2 | 4 | IES |
| E_canopy | SLAVR 185–240；LFMAX 1.6–2.0；FRLFF 0.15–0.50；SENRTE 1.5–4.5 | 6 | IES |
| F_water_podset | SWFAC_REC 0.3–1；YSWFAC_MID 0–1 | 4 | 完成确定性筛查；暂缓IES |
| G_water_fill | TRFAC_XMID 0.1–0.7；YTRFAC_MAX 0–0.3 | 4 | IES |

B只定向探索RTNO3下界，不同时降低所有氮参数下界；C不降低NSTFAC/PROLFI/PROLFG下界，且PROLFI≥PROLFG在全域成立。D联合移动两个响应断点，FNPGN1始终小于FNPGN2。E不进一步整体降低SLAVR/LFMAX边界。

SWBAR_REC=0.477073、YSWBAR_MID=0.987525在各臂固定，绝不扩大到1以上。新水分曲线默认值在非对应臂固定：SWFAC_REC=1、YSWFAC_MID=1、TRFAC_XMID=0.5、YTRFAC_MAX=0，保持旧向量的实际曲线。

各臂60个集合行（59个随机成员+base），noptmax=3，6 agents。各臂顺序执行，机器同时只有6个worker，不启动36/42个worker。使用按参数名固定种子的LHS；共同ICNS样本逐行相同；观测扰动逐行相同，base行无观测扰动；PEST有效rand_seed=20260902。LHS是本次小型机制探索的初始化方式，不与v48原始高维随机先验混称同一种分布。

## 3. 目标函数与判据

实际生成的PST共有1432个观测槽、1168个正权重观测；各臂obsval、weight、obgnme逐项与v48一致。

- 末次鲜产量沿用分季RRMSE项 λ=750；25%是复跑后验收线，**不是优化器内的不可违背不等式**。
- N_RESPONSE、W_RESPONSE均沿用分季×响应层独立SST，λ=3；不跨季/跨变量合并分母。
- 26SP N_DOSE_GRADIENT沿用45个观测，静态Phi预算1.5，包含非N0相邻剂量梯度与CV；不增加/修改该族。本族与传统N−N0响应必须分开报告。
- 采收日志变换等所有细节继承v48，不能把原始输出与PST变换后的数值直接比较。

自动评价对固定成员55和A臂分别计算，不仅比较Phi：

1. 每季累积鲜产NSE下降≤0.03；末期处理间鲜产RRMSE≤25%，且增加≤3个百分点；LAI NSE下降≤0.03。
2. B/C/D：26SP各水分层氮响应RMSE相对改善率的均值≥15%，两季至少3个N响应层改善，任一水响应层RMSE不增加超过10%。
3. E：26SP后两次LAI RMSE改善≥15%；25SP首次LAI RMSE不增加超过10%，并满足总体保护条件。
4. F/G：各水响应层RMSE相对改善率均值≥15%，26SP任一N响应层RMSE不增加超过10%。
5. 输出非N0梯度/CV残差Phi、各N/W层、冠层分阶段指标供人工复核。自动通过规模/冠层门槛不等于已完成全部科学晋级；不自动合并赢家，不自动开放全参数，不自动启动下一轮正式率定。

冠层分阶段使用各变量的实际观测日期：首次=early，中间且不属于末两次=middle，末两次=late；无中期观测时不伪造middle。分别输出LAI、叶干重、茎干重、株高，保护25SP；阶段NSE仍可能受小样本/SST影响，应同时读RMSE与偏差。末次产量不输出NSE。

## 4. 已完成的机制筛查

成员55确定性复跑的产量与冠层指标复现：25SP/26SP累积鲜产NSE=0.910803/0.892480，末期RRMSE=10.2843%/14.5651%，LAI NSE=0.769389/0.690128。

- 25SP SWFAC=0.426–1、TURFAC=0.284–1；26SP两者均为1。两季NSTD均为0。
- 重建的表层SWBAR日输出近似值两季均覆盖0–1。**SWFAC=1不意味着SWBAR=1**，故不能断言没有任何水分效应。
- LN%D范围25SP为1.64–3.88%，26SP为1.86–3.81%。约88.5%/89.9%的处理—日PCNL≥锚点FNPGN2。
- LN%D是PCNL（总叶质量基准），不是RNITP（扣除碳储备后的结构叶氮）。PCNL≥FNPGN2可作为平台覆盖的单侧下限证据；PCNL低于断点不能反证实际RNITP进入响应区。不伪造AGEFAC轨迹。
- B/C/D/E/G中点改变了观测输出；F中点没有改变。F再测试YSWFAC_MID=0、SWFAC_REC=1，并分别配对ICNS锚点、两季均0.4、两季均0.8：最大输出差仅0.1，加权变化SSE均小于7e-9，远低于筛查阈值1e-6。保留配置和结果，但本次暂缓F的IES。这是当前局部条件下的微弱响应，不宣称全局无敏感性。
- G可能主要改变25SP：26SP锚点TURFAC=1，而YTRFAC在1处固定为0。不能期待该曲线凭空解决26SP水处理差异。

水分含义按[官方PODS源码](https://github.com/DSSAT/dssat-csm-os/blob/develop/Plant/CROPGRO/PODS.for)和[官方Opgrow源码](https://github.com/DSSAT/dssat-csm-os/blob/develop/Plant/CROPGRO/Opgrow.for)核验：SWBAR是深度积分后的可提取水之比；WSPD/WSGD是输出周期内1−SWFAC/1−TURFAC。这里校验为逐日输出。源码参考分支与本地4.8.5二进制版本有差异，未替换官方可执行文件。

SWBAR重建采用实际DSSAT48.INP有效分层与SoilWat.OUT，计算Σ[(SW−LL)Δz]/Σ[(DUL−LL)Δz]至DSWBAR并限于0–1；不是只取SW1D，更不是各层比值简单平均。日输出已舍入且与PODS日内调用时点可能不同，标记为近似重建，不冒充内部精确状态。

Antigravity进行了只读设计复核。对其“LN%D=RNITP”“只用第一层重建SWBAR”“XSWFAC直接控制光合”的说法未采纳，以上为核验后的解释。

## 5. 工程修复和验收

1. `build_pest.py::_parse_filex_seedling_params` 原先把fixed等值边界一律拒绝；已允许fixed的lower=init=upper，active仍要求非零区间，并检查有限数值。
2. 旧模板发现流程会漏掉固定土壤参数。新启动器通过每臂`fixed_anchor_params.csv`显式`--fixed-from`注入，仅包含本臂非活跃参数；PST检查全部132个参数完整、活跃白名单准确、所有固定值等于成员55。
3. `run_multiseason.py`新增可选`--keep-soil-water`并转发至现有单季runner，仅保留输出，不改变模拟计算。
4. 真实DSSAT复跑配合各臂全部`.ins`解析，1432槽均为有限数值，45个梯度观测不再存在历史错行问题。按原合同变换后锚点复现成功。
5. 初始参数和观测集合均对齐为0–58、base；base噪声为0，防止集合成员名不一致。
6. 28项相关测试通过；预检失败的早期构建目录移到`workspace/reports/v49_mechanism_20260902/build_without_fixed_soil_*`备查，未删除旧批次或观测数据。
7. `execution_seal.json`记录关键代码、PST、冻结边界、设计、集合、模板及可执行文件SHA256，队列每臂启动前核对。修改这些文件将停止后续队列，需重新验收，不要运行中修改。

## 6. 文件与执行说明

- 启动器：`tools/calibration/run_v49_mechanism_multiarm_20260902.py`
- 复跑评价：`tools/analysis/evaluate_v49_mechanism_20260902.py`
- 测试：`tests/test_v49_mechanism_design.py`
- 设计：`configs/runs/e02_v49_*_60x3_20260902.json`
- 冻结边界：`data/parameter_registry/bounds_frozen/eggplant/eggplant_e02_v49_*_20260902.csv`
- 总目录：`workspace/reports/v49_mechanism_20260902/`
- 运行目录：`workspace/runs/e02_v49_{臂名}_60x3_20260902/`
- `suite_manifest.json`：分臂及来源；`smoke_audit.json`：指令解析/复现；`water_curve_screen.json`：F筛查。
- `queue_status.json`、`queue.stdout.log`、`queue.stderr.log`：后台队列状态。`execution_seal.json`是启动时最终哈希依据，早期`v49_preflight_audit.json`中的PST哈希是配对噪声封存前的构建快照。
- 每臂`lowest_phi/fit_metrics.csv`、`objective_residuals.csv`、`phi_by_season_token.csv`、`mechanism_ranges.csv`、`*_mechanism_daily.csv`；`candidate_summary.json`含相对两种对照的门槛。
- `results_summary.json`随每臂完成更新。未生成结果不等于该臂已经完成。

准备复现顺序（不要覆盖当前运行目录重复执行）：

```powershell
python -X utf8 tools/calibration/run_v49_mechanism_multiarm_20260902.py --prepare --build --smoke --screen-water
python -X utf8 tools/analysis/evaluate_v49_mechanism_20260902.py --anchor
python -X utf8 tools/calibration/run_v49_mechanism_multiarm_20260902.py --seal
python -X utf8 tools/calibration/run_v49_mechanism_multiarm_20260902.py --run
```

任一模型失败、缺失预期第3轮或复跑评价失败会停止队列并保留错误，不能把manager_exit_code=0单独当成科学成功。本次未绘图，未生成不确定性区间。
