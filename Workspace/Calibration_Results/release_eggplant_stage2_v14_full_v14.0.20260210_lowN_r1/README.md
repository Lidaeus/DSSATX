版本：v14_full_20260210_lowN_r1

背景
本版本基于 eggplant_stage2_v14_full 率定结果整理，可复现包含 lowN 处理的 v14_full 全流程。修复 Evaluate.OUT 路径解析后，观测组包含 ADAPM/CNAMM/HIAMM/HWAMM/LAIXM。

关键文件一览
- inputs/DSSBatch.v48：低N未屏蔽的批处理输入
- inputs/_v14_excl_tighten.csv：参数收敛范围收紧依据
- control/eggplant_stage2_v14_full.pst：完整参数、边界与观测权重
- control/eggplant_stage2_v14_full_params.csv：参数清单（初始值）
- control/eggplant_stage2_v14_full_params.csv.tpl：参数模板
- control/eggplant_stage2_v14_full.weights.csv：观测权重
- control/eggplant_stage2_v14_full.adjusted.weights.csv：权重调整结果
- control/eggplant_stage2_v14_full.adjusted.obs_data.csv：观测值调整结果
- results/eggplant_stage2_v14_full.0.par.csv：初始参数值
- results/eggplant_stage2_v14_full.6.par.csv：最终迭代参数值
- results/eggplant_stage2_v14_full_best_parameters.csv：最佳实现参数
- results/eggplant_stage2_v14_full_best_parameters_fixed.csv：确定性模拟参数表
- results/eggplant_stage2_v14_full_parameter_uncertainty.csv：参数不确定性
- results/eggplant_stage2_v14_full_bound_hits.csv：边界命中记录
- results/eggplant_stage2_v14_full_error_diag.csv：逐观测残差诊断
- results/eggplant_stage2_v14_full_deterministic_*_compare.csv：确定性对比数据
- results/metrics_grid.csv：综合统计指标
- logs/eggplant_stage2_v14_full.rec：PEST++ 运行记录
- logs/eggplant_stage2_v14_full.log：运行日志
- plots/：散点图与时序图

参数与取值范围
- 完整参数与边界：control/eggplant_stage2_v14_full.pst（parval1、parlbnd、parubnd）
- 初始值：results/eggplant_stage2_v14_full.0.par.csv
- 最终迭代值：results/eggplant_stage2_v14_full.6.par.csv
- 最佳实现参数：results/eggplant_stage2_v14_full_best_parameters.csv

权重与观测组
- 权重文件：control/eggplant_stage2_v14_full.weights.csv、control/eggplant_stage2_v14_full.adjusted.weights.csv
- 观测组与 sigma（默认设置）：
  - ADAPM：25.0
  - HWAMM：50.0
  - PWAMM：20.0
  - LAIXM：0.8
  - CNAMM：25.0
  - HIAMM：0.10
  - LAIDM：2.0 × laidm_sigma_factor
  - LWADM：150.0 × lwadm_sigma_factor
  - SWADM：200.0 × swadm_sigma_factor
  - PWADM：基于 pwadm_sigma0、pwadm_cv 与 harvest_early_weight_factor 动态生成

率定流程（复现命令）
1) 生成率定控制文件
python build_pest.py --mode eggplant_stage2 --prefix eggplant_stage2_v14_full --noptmax 6 --ies-num-reals 80 --batch .\DSSBatch.v48 --tighten-from .\_v14_excl_tighten.csv --tighten-frac 0.10

2) 运行率定
pestpp-ies eggplant_stage2_v14_full.pst

3) 生成统计与图件
python analyze_results.py --prefix eggplant_stage2_v14_full
python analyze_results.py --metrics-grid --prefix eggplant_stage2_v14_full

变更记录
- v14_full_20260210_lowN_r1
  - 修复 Evaluate.OUT 路径解析，确保使用运行目录文件
  - 恢复 ADAPM/CNAMM/HIAMM/HWAMM/LAIXM 观测组
  - 使用 _v14_excl_tighten.csv 进行 10% 参数收紧
  - 重新生成 plots 与统计指标
