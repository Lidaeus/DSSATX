 # Eggplant stage2 v14 复现包说明
 
 ## 背景信息
 - 版本：eggplant_stage2_v14_exclTN5_TN9_TN13
 - 目的：在剔除 TN5/TN9/TN13 处理的前提下，完成 stage2 联合率定，并产出高拟合度参数集合
 - 率定程序：PEST++ IES（pestpp-ies.exe 5.2.16）
 - 运行时间：2026-02-09（本次复现输出）
 
 ## 复现包结构
 - run_dir：PEST 控制文件、模板与指令文件、批处理文件、实验文件与品种/生态型/物种参数文件
 - results：分析输出（best parameters、诊断、bound hits 等）
 - plots：拟合散点与时序图
 - scripts：用于构建/运行/分析的脚本快照
 
 ## 参数与取值范围
 - 参数值：
   - results/eggplant_stage2_v14_exclTN5_TN9_TN13_best_parameters.csv
   - results/eggplant_stage2_v14_exclTN5_TN9_TN13_best_parameters_fixed.csv
 - 参数范围：
   - run_dir/eggplant_stage2_v14_exclTN5_TN9_TN13.pst（Parameter Data 段）
   - run_dir/eggplant_stage2_v14_exclTN5_TN9_TN13_params.csv（初始参数快照）
 
 ## 权重与观测构建
 - 权重文件：
   - run_dir/eggplant_stage2_v14_exclTN5_TN9_TN13.weights.csv
   - run_dir/eggplant_stage2_v14_exclTN5_TN9_TN13.adjusted.weights.csv
 - 观测调整：
   - run_dir/eggplant_stage2_v14_exclTN5_TN9_TN13.adjusted.obs_data.csv
 
 ## 关键输入文件
 - 批处理：run_dir/DSSBatch_excl_TN5_TN9_TN13.v48
 - 实验文件：run_dir/XXQL2501.TMX、XXQL2501.TMA、XXQL2501.TMT
 - 品种/生态型/物种参数：run_dir/TMGRO048.CUL、TMGRO048.ECO、TMGRO048.SPE
 - DSSAT 控制文件：run_dir/DSSATPRO.v48、DSSAT48.INH、DSSAT48.INP
 
 ## 率定流程（复现步骤）
 1. 在 run_dir 目录运行 IES：
    - c:\DSSAT48\Tomato_Cal\pestpp-5.2.16-win\bin\pestpp-ies.exe eggplant_stage2_v14_exclTN5_TN9_TN13.pst
 2. 生成分析与图表（可复现本次 plots）：
    - python scripts/analyze_results.py --prefix eggplant_stage2_v14_exclTN5_TN9_TN13 --run-dir run_dir --batch run_dir/DSSBatch_excl_TN5_TN9_TN13.v48
 
 ## 诊断与结果产物
 - 误差诊断：results/eggplant_stage2_v14_exclTN5_TN9_TN13_error_diag.csv
 - 参数不确定性：results/eggplant_stage2_v14_exclTN5_TN9_TN13_parameter_uncertainty.csv
 - 触边报告：results/eggplant_stage2_v14_exclTN5_TN9_TN13_bound_hits.csv
 - 图表输出：plots/eggplant_stage2_v14_exclTN5_TN9_TN13
 
 ## 复现注意事项
 - 确保 DSSAT 可执行文件路径可用（DSCSM048.EXE）
 - 确保 run_dir 内模板与指令文件齐全
 - 本复现包为“完整拷贝”，不会修改原始 Workspace
