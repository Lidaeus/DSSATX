# ---------------------------------------------------------------------------
# SA figure internationalisation: Chinese / English bilingual text dictionary.
#
# Every SA figure builder calls sa_t(key, lang) to obtain the localised string
# for a given key.  The make_all.R dispatcher passes --lang en|zh; when lang
# is omitted the default is "en" (backward-compatible with all existing calls
# and tests that do not pass a lang argument).
#
# Keys are grouped by builder for readability.  Dynamic strings (those that
# interpolate counts or thresholds) use sprintf-style templates resolved by
# sa_tf(key, lang, ...).
# ---------------------------------------------------------------------------

# Default language (backward compatibility: builders that do not receive lang).
SA_DEFAULT_LANG <- "en"

# --- lookup machinery ------------------------------------------------------

.sa_dict <- list()

.sa_add <- function(group, key, en, zh) {
  .sa_dict[[paste(group, key, sep = ".")]] <<- list(en = en, zh = zh)
}

sa_t <- function(key, lang = SA_DEFAULT_LANG) {
  entry <- .sa_dict[[key]]
  if (is.null(entry)) {
    warning("sa_i18n: missing key '", key, "'", call. = FALSE)
    return(key)
  }
  entry[[lang]]
}

sa_tf <- function(key, lang = SA_DEFAULT_LANG, ...) {
  tmpl <- sa_t(key, lang)
  sprintf(tmpl, ...)
}


# ===========================================================================
# Shared / domain labels
# ===========================================================================
.sa_add("shared", "domain_general_genetic", "General genetic effects", "通用遗传效应")
.sa_add("shared", "domain_wn_response", "Water-nitrogen response", "水氮响应")
.sa_add("shared", "panel_genetic", "Genetic", "遗传")
.sa_add("shared", "panel_wn", "W-N", "水氮")
.sa_add("shared", "panel_wn_response", "W-N response", "水氮响应")
.sa_add("shared", "stable", "Stable", "稳定")
.sa_add("shared", "more_seeds", "More seeds required", "需更多种子")
.sa_add("shared", "pass", "Pass", "通过")
.sa_add("shared", "not_met", "Not met", "未通过")
.sa_add("shared", "needs_more_seeds", "Needs more seeds", "需更多种子")
.sa_add("shared", "general_genetic_label", "General genetic", "通用遗传")
.sa_add("shared", "water_nitrogen_label", "Water-nitrogen", "水氮")
.sa_add("shared", "converged", "Converged", "已收敛")
.sa_add("shared", "rank_gate_not_met", "Rank gate\nnot met", "名次门\n未通过")
.sa_add("shared", "bootstrap_gate_not_met", "Bootstrap gate\nnot met", "Bootstrap门\n未通过")

# Response group labels (process groups)
.sa_add("group", "Phenology", "Phenology", "物候")
.sa_add("group", "Canopy", "Canopy", "冠层")
.sa_add("group", "Biomass", "Biomass", "生物量")
.sa_add("group", "Harvest", "Harvest", "采收")
.sa_add("group", "Water response", "Water response", "水分响应")
.sa_add("group", "Nitrogen response", "Nitrogen response", "氮响应")
.sa_add("group", "Water x nitrogen", "Water x nitrogen", "水×氮")
.sa_add("group", "Other", "Other", "其他")

# Metric labels
.sa_add("metric", "spearman_rho", "Spearman rho", "Spearman ρ")
.sa_add("metric", "top8_jaccard", "Top-8 Jaccard", "Top-8 Jaccard")
.sa_add("metric", "top15_jaccard", "Top-15 Jaccard", "Top-15 Jaccard")
.sa_add("metric", "max_top8_shift_long", "Maximum Top-8 rank shift", "Top-8最大名次变化")
.sa_add("metric", "max_top8_shift_short", "Max Top-8 shift", "Top-8最大变化")

# Sobol index labels
.sa_add("sobol", "first_order_s1", "First order (S1)", "一阶效应 (S1)")
.sa_add("sobol", "total_effect_st", "Total effect (ST)", "总效应 (ST)")


# ===========================================================================
# build_morris_main
# ===========================================================================
.sa_add("morris_main", "title", "Multi-season Morris screening maps conditional sensitivity", "多季Morris筛选映射条件敏感性")
.sa_add("morris_main", "rank_title", "Cross-season sensitivity ranking", "跨季敏感性排名")
.sa_add("morris_main", "rank_subtitle", "Points: seasons; diamond: equal-season mean; line: seasonal range", "点:各季节;菱形:等权季节均值;线:季节范围")
.sa_add("morris_main", "rank_x", "Morris score (within-domain scale)", "Morris得分（域内刻度）")
.sa_add("morris_main", "heat_title", "Process-specific sensitivity fingerprint", "过程特异性敏感性指纹")
.sa_add("morris_main", "mean_score_legend", "Mean score", "平均得分")
.sa_add("morris_main", "demo_subtitle", "Current evidence: the XXQL2502 water-nitrogen Top-15 boundary remains seed-sensitive", "当前证据:XXQL2502水氮域Top-15边界仍受种子影响")
.sa_add("morris_main", "demo_caption", "DEMO - science pending; current Morris evidence is not yet citable", "DEMO - 科学待定;当前Morris证据尚不可引用")


# ===========================================================================
# build_morris_stability
# ===========================================================================
.sa_add("morris_stab", "title", "Morris rank stability and seed-pair evidence", "Morris排名稳定性与种子对证据")
.sa_add("morris_stab", "rank_title", "Per-seed rank trajectories of the cross-season focus parameters", "跨季核心参数的逐种子名次轨迹")
.sa_add("morris_stab", "rank_x", "Prespecified seed index", "预设种子序号")
.sa_add("morris_stab", "rank_y", "Rank (1 = most sensitive)", "名次 (1 = 最敏感)")
.sa_add("morris_stab", "metric_x", "Seed pair index", "种子对序号")
.sa_add("morris_stab", "metric1_title", "Whole-ranking agreement", "全排名一致性")
.sa_add("morris_stab", "metric1_y", "Spearman rho", "Spearman ρ")
.sa_add("morris_stab", "metric2_title", "Top-15 membership agreement", "Top-15成员一致性")
.sa_add("morris_stab", "metric2_y", "Jaccard index", "Jaccard指数")
.sa_add("morris_stab", "metric_title", "Prespecified seed-pair checks", "预设种子对检查")
.sa_add("morris_stab", "metric_subtitle", "Filled points pass the gate; open points do not. Labels show the mean and number of passing pairs; lines span the pairwise range.", "实心点通过门槛；空心点未通过。标签为均值与通过数；线段表示种子对范围。")
.sa_add("morris_stab", "threshold_subtitle", "Dashed threshold = %s", "虚线阈值 = %s")
.sa_add("morris_stab", "demo_caption", "DEMO - science pending; current Morris evidence is not yet citable", "DEMO - 科学待定;当前Morris证据尚不可引用")


# ===========================================================================
# build_morris_response_effects (FigS1b mu*-sigma)
# ===========================================================================
.sa_add("morris_eff", "title", "Morris effects across core response families", "核心响应族的Morris效应")
.sa_add("morris_eff", "subtitle", "Top-%d parameters per response are labelled; grey points show the remainder.", "每个响应的前%d参数已标注;灰点为其余参数。")
.sa_add("morris_eff", "x", "Mean within-observation mu* share", "观测内μ*份额均值")
.sa_add("morris_eff", "y", "Mean observation-level sigma", "观测级σ均值")
.sa_add("morris_eff", "demo_caption", "DEMO - science pending. Points summarize exact observation-level statistics from .mio across treatments and seasons.\nHigh sigma indicates nonlinearity and/or interaction involvement, not a specific parameter pair.\nImportance is conditional on the sampled ranges and scenarios.", "DEMO - 科学待定。点为.mio观测级精确统计量跨处理与季节的汇总。\n高σ提示非线性和/或交互参与,非特定参数对。\n重要性条件化于采样范围与情景。")
.sa_add("morris_eff", "caption", "Points summarize exact observation-level statistics from .mio across treatments and seasons.\nHigh sigma indicates nonlinearity and/or interaction involvement, not a specific parameter pair.\nImportance is conditional on the sampled ranges and scenarios.", "点为.mio观测级精确统计量跨处理与季节的汇总。\n高σ提示非线性和/或交互参与,非特定参数对。\n重要性条件化于采样范围与情景。")


# ===========================================================================
# build_morris_s1_combined (Fig.S1 combined)
# ===========================================================================
.sa_add("morris_s1", "title", "Morris ranking stability and response-level elementary-effects geometry", "Morris排名稳定性与响应级基本效应几何")
.sa_add("morris_s1", "demo_caption", "DEMO - science pending; importance is conditional on the sampled parameter ranges and scenarios", "DEMO - 科学待定;重要性条件化于采样参数范围与情景")
.sa_add("morris_s1", "caption", "Importance is conditional on the sampled parameter ranges and scenarios", "重要性条件化于采样参数范围与情景")

# ===========================================================================
# Results-first sensitivity figures
# ===========================================================================
.sa_add("morris_results", "title", "Morris sensitivity fingerprints across response families", "Morris敏感性在响应过程族中的指纹")
.sa_add("morris_results", "heat_title", "Parameter effects by response family", "参数在各响应过程族中的效应")
.sa_add("morris_results", "group_score", "Morris group score", "Morris过程组得分")
.sa_add("morris_results", "score_title", "Cross-season effect magnitude of focal parameters", "核心参数的跨季效应量")
.sa_add("morris_results", "score_subtitle", "Values summarize the three-season mean; they are conditional on the sampled parameter ranges and scenarios.", "数值为三季均值；重要性条件化于采样参数范围与情景。")
.sa_add("morris_results", "score_x", "Cross-season mean Morris score", "跨季Morris平均得分")
.sa_add("morris_results", "caption", "English heatmap abbreviations: W resp.=water response; N resp.=nitrogen response; W×N=water×nitrogen interaction.\nParameter codes: TRIFL=main-stem leaf appearance; XFRT=fruit partitioning; LFMAX=maximum leaf photosynthesis; EM-FL=emergence to flowering.\nRTNO3=root nitrate uptake; RTNH4=root ammonium uptake; XFINT=fruit partitioning interval; NMOBMX=maximum nitrogen mobilization.", "横轴缩写：水分响应、氮素响应和水×氮交互。\n参数代码：TRIFL=主茎叶片出现；XFRT=果实分配；LFMAX=最大叶片光合；EM-FL=出苗至开花。\nRTNO3=根系硝态氮吸收；RTNH4=根系铵态氮吸收；XFINT=果实分配间隔；NMOBMX=最大氮再动员量。")
.sa_add("morris_results", "demo_caption", "DEMO - science pending; this figure presents sensitivity results, not seed-stability diagnostics.", "DEMO - 科学待定；本图展示敏感性结果，不展示种子稳定性诊断。")


# ===========================================================================
# build_sa_summary (Morris + Sobol composite)
# ===========================================================================
.sa_add("sa_summary", "title", "Cross-season Morris screening with response-level Sobol decomposition", "跨季Morris筛选与响应级Sobol分解")
.sa_add("sa_summary", "sobol_subtitle", "(c) Sobol S1/ST (convergence-validated season only)", "(c) Sobol S1/ST (仅收敛验证季节)")
.sa_add("sa_summary", "sobol_x", "Sobol sensitivity index", "Sobol敏感性指数")
.sa_add("sa_summary", "demo_caption", "DEMO - science pending; Sobol panel is the single convergence-validated season. Importance is conditional on the sampled parameter ranges and scenarios.", "DEMO - 科学待定;Sobol面板为单一收敛验证季节。重要性条件化于采样参数范围与情景。")
.sa_add("sa_summary", "caption", "Sobol panel is the single convergence-validated season. Importance is conditional on the sampled parameter ranges and scenarios.", "Sobol面板为单一收敛验证季节。重要性条件化于采样参数范围与情景。")


# ===========================================================================
# build_morris_interaction (FigS1c)
# ===========================================================================
.sa_add("interaction", "title", "Morris elementary-effects geometry and interaction hints", "Morris基本效应几何与交互提示")
.sa_add("interaction", "subtitle", "Each point is one parameter (top-%d by mu*). Size = sigma/mu* ratio; large ratio flags nonlinearity and/or interaction involvement. Axes are pseudo-log scaled. Observation-level medians; descriptive overview.", "每个点为一个参数(按μ*前%d)。大小=σ/μ*比值;大比值提示非线性和/或交互参与。坐标轴为伪对数尺度。观测级中位数;描述性概览。")
.sa_add("interaction", "x", "Median mu* (pseudo-log)", "中位μ* (伪对数)")
.sa_add("interaction", "y", "Median sigma (pseudo-log)", "中位σ (伪对数)")
.sa_add("interaction", "process_group", "Process group", "过程组")


# ===========================================================================
# build_selection_rationality (FigS1d)
# ===========================================================================
.sa_add("selection", "title", "Parameter dimensionality reduction: 55 Morris candidates to 23 Sobol screening set", "参数降维:55个Morris候选至23个Sobol筛选集")
.sa_add("selection", "elbow_subtitle", "(a) Parameter ranking by cross-season Morris score", "(a) 按跨季Morris得分的参数排名")
.sa_add("selection", "elbow_x", "Parameter rank", "参数排名")
.sa_add("selection", "elbow_y", "Cross-season mean score", "跨季平均得分")
.sa_add("selection", "cum_subtitle", "(b) Cumulative sensitivity coverage", "(b) 累积敏感性覆盖")
.sa_add("selection", "cum_x", "Number of included parameters", "纳入参数数")
.sa_add("selection", "cum_y", "Cumulative fraction", "累积占比")
.sa_add("selection", "threshold_label", "95%% information threshold", "95%%信息阈值")
.sa_add("selection", "selected_label", "Sobol candidate (%d)", "Sobol候选 (%d)")
.sa_add("selection", "screened_label", "Screened out (%d)", "筛除 (%d)")
.sa_add("selection", "demo_caption", "DEMO - science pending; selection is conditional on the sampled parameter ranges and scenarios", "DEMO - 科学待定;选择条件化于采样参数范围与情景")
.sa_add("selection", "caption", "Selection is conditional on the sampled parameter ranges and scenarios", "选择条件化于采样参数范围与情景")


# ===========================================================================
# build_sobol_convergence
# ===========================================================================
.sa_add("sobol_conv", "title", "Sobol screening: sample-size sensitivity is material at the current budget", "Sobol筛选:样本量敏感性在当前预算下显著")
.sa_add("sobol_conv", "rank_title", "Top-8 membership changes with Sobol sample size", "Top-8成员随Sobol样本量变化")
.sa_add("sobol_conv", "rank_subtitle", "Union of N=64 and N=128 Top-8 candidates; each line is one parameter", "N=64与N=128 Top-8候选的并集;每条线为一个参数")
.sa_add("sobol_conv", "rank_x", "Base sample size (N)", "基础样本量 (N)")
.sa_add("sobol_conv", "rank_y", "Rank (1 = larger aggregate total-order effect)", "名次 (1 = 更大聚合总效应)")
.sa_add("sobol_conv", "metric_title", "Prespecified N=64 to N=128 convergence checks", "预设N=64至N=128收敛检查")
.sa_add("sobol_conv", "metric_subtitle", "Dashed line: required threshold; all displayed checks must pass before quantitative rank interpretation", "虚线:要求阈值;所有展示检查须通过后方可定量解读名次")
.sa_add("sobol_conv", "run_caption", "XXQL2501: N=%s (%s model runs)", "XXQL2501: N=%s (%s次模型运行)")
.sa_add("sobol_conv", "demo_caption", "DEMO - convergence thresholds not met; use only as a transparent screening and numerical-uncertainty record", "DEMO - 收敛阈值未达;仅作透明筛选与数值不确定性记录")


# ===========================================================================
# build_sobol_multiseason_convergence
# ===========================================================================
.sa_add("sobol_ms_conv", "title", "Sobol screening: expanded sample-size checks remain season dependent", "Sobol筛选:扩展样本量检查仍依赖季节")
.sa_add("sobol_ms_conv", "status_title", "Season-specific Sobol numerical-evidence status", "季节特异性Sobol数值证据状态")
.sa_add("sobol_ms_conv", "metric_title", "N=128 to N=256 prespecified convergence checks", "预设N=128至N=256收敛检查")
.sa_add("sobol_ms_conv", "metric_subtitle", "Dashed line: required threshold; XXQL2501 is shown above because its bootstrap gate stopped this comparison", "虚线:要求阈值;XXQL2501因bootstrap门中止此比较而显示于上方")
.sa_add("sobol_ms_conv", "rank_title", "Top-8 union rank movement at the two completed seasonal comparisons", "两次已完成季节比较的Top-8并集名次变化")
.sa_add("sobol_ms_conv", "rank_subtitle", "Each facet contains the union of its N=128 and N=256 Top-8 parameter lists", "每个面板含其N=128与N=256 Top-8参数列表的并集")
.sa_add("sobol_ms_conv", "rank_x", "Base sample size (N)", "基础样本量 (N)")
.sa_add("sobol_ms_conv", "rank_y", "Rank (1 = larger aggregate total-order effect)", "名次 (1 = 更大聚合总效应)")
.sa_add("sobol_ms_conv", "caption", "DEMO - pooled Sobol ranking is science pending: only XXQL2502 passed all prespecified checks; no interaction-strength inference is made", "DEMO - 汇总Sobol排名科学待定:仅XXQL2502通过全部预设检查;不作交互强度推断")


# ===========================================================================
# build_sobol_multiseason_effects
# ===========================================================================
.sa_add("sobol_ms_eff", "title", "Sobol effects and their numerical support are response- and season-dependent", "Sobol效应及其数值支持依赖响应与季节")
.sa_add("sobol_ms_eff", "status_title", "Numerical evidence is season specific", "数值证据具有季节特异性")
.sa_add("sobol_ms_eff", "effect_title", "First-order and total effects for fixed scalar responses (XXQL2502, N=256)", "固定标量响应的一阶与总效应 (XXQL2502, N=256)")
.sa_add("sobol_ms_eff", "effect_subtitle", "Top three by ST; intervals are 95%% paired-bootstrap. Facet labels show response SD and unit; purple marks supported ST-S1.", "按ST前三；区间为95%%配对bootstrap。面板标签显示响应SD与单位；紫色表示受支持的ST-S1。")
.sa_add("sobol_ms_eff", "effect_x", "Sobol sensitivity index", "Sobol敏感性指数")
.sa_add("sobol_ms_eff", "metric_title", "N=128 to N=256 prespecified rank-convergence checks", "预设N=128至N=256名次收敛检查")
.sa_add("sobol_ms_eff", "metric_subtitle", "Dashed line: threshold; XXQL2501 stopped at the bootstrap-resample gate", "虚线:阈值;XXQL2501在bootstrap重采样门中止")
.sa_add("sobol_ms_eff", "caption", "DEMO - S1 is the main-effect fraction; ST includes all interactions. ST-S1 is an aggregate interaction-involving remainder, not a pairwise interaction. Quantitative decomposition is restricted to convergence-validated XXQL2502.", "DEMO - S1为主效应份额;ST含全部交互。ST-S1为聚合交互参与余量,非成对交互。定量分解限于收敛验证的XXQL2502。")

.sa_add("sobol_results", "title", "Sobol sensitivity decomposition across scientific responses", "不同科学响应的Sobol敏感性分解")
.sa_add("sobol_results", "subtitle", "Top three parameters by total effect; points and intervals show S1 and ST, while purple segments mark supported aggregate interaction remainder.", "按总效应选取前三参数；点和区间表示S1与ST，紫色线段表示有支持的聚合交互余量。")
.sa_add("sobol_results", "demo_caption", "DEMO - quantitative decomposition is shown for the current XXQL2502 evidence bundle; N denotes nitrogen and W×N denotes the water×nitrogen response.\nEstimates outside [0,1] are finite-sample outputs and must be read with their intervals; status and convergence diagnostics are retained in source tables.", "DEMO - 定量分解展示当前XXQL2502证据包；N表示氮素，W×N表示水×氮响应。\n超出[0,1]的点估计为有限样本结果，应结合区间解释；状态与收敛诊断保留在源表中。")
