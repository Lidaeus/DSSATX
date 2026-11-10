script_arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_path <- normalizePath(sub("^--file=", "", script_arg[[1]]), winslash = "/", mustWork = TRUE)
script_dir <- dirname(script_path)
project_root <- normalizePath(file.path(script_dir, "..", ".."), winslash = "/", mustWork = TRUE)

# R can start in the legacy C locale on Windows even when the source and CSV
# contracts are UTF-8.  Establish a UTF-8 CTYPE before sourcing any module.
if (.Platform$OS.type == "windows" && !isTRUE(l10n_info()[["UTF-8"]])) {
  utf8_locale <- Sys.setlocale("LC_CTYPE", "English_United States.utf8")
  if (is.na(utf8_locale) || !isTRUE(l10n_info()[["UTF-8"]])) {
    stop("A UTF-8 Windows locale is required to render paper figures", call. = FALSE)
  }
}

source_utf8 <- function(name) {
  source(file.path(script_dir, name), local = FALSE, encoding = "UTF-8")
}
for (module in c(
  "common.R", "publication_fonts.R", "sa_i18n.R", "fig_model_performance.R",
  "fig_model_performance_uncertainty.R", "fig_treatment_residual_uncertainty.R",
  "fig_selected_dynamics.R", "fig_residual_diagnostics.R",
  "fig_all_treatment_dynamics.R", "fig_phi_convergence.R", "fig_posterior_demo.R",
  "fig_spearman_demo.R", "fig_equifinality_demo.R", "fig_sa_morris.R",
  "fig_sa_sobol.R", "fig_sa_interaction.R", "fig_sa_selection.R",
  "fig_water_nitrogen_response.R", "fig_standing_fruit_balance.R",
  "fig_leaf_nitrogen.R", "fig_model_framework.R", "fig_partition_ablation.R",
  "fig_validation_sample.R", "fig_environment_management.R", "fig_sensitivity_update.R",
  "fig_growth_dynamics.R", "fig_harvest_dynamics.R", "fig_management_response.R",
  "fig_dual_morris_screening.R", "spring_figure_bundle.R"
)) source_utf8(module)

check_r_dependencies()
args <- parse_cli_args(commandArgs(trailingOnly = TRUE))
input_dir <- normalizePath(require_arg(args, "input_dir"), winslash = "/", mustWork = TRUE)
out_dir <- require_arg(args, "out_dir")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
out_dir <- normalizePath(out_dir, winslash = "/", mustWork = TRUE)
profile_path <- if (is.null(args$profile)) file.path(project_root, "configs", "figures", "publication.json") else args$profile
profile <- load_publication_profile(profile_path)
# i18n: --lang en|zh (default en for backward compatibility).  SA figure
# builders receive this to localise titles, axes, legends and captions.
lang <- if (is.null(args$lang)) SA_DEFAULT_LANG else args$lang
if (!is.null(args$formats)) profile$formats <- split_csv_arg(args$formats)

# Figure selection: each scientific question is one module. --figure-ids selects
# a subset so SA figures (fig1_sa, figs1/figs2) can be rendered from an SA data
# bundle without a calibration trajectory, and calibration figures (fig2_phi,
# fig3_performance, fig4_dynamics, figs3/figs4) can be rendered without SA data.
# Default "all" preserves backward-compatible full rendering.
figure_ids <- if (is.null(args$figure_ids)) "all" else args$figure_ids
selected <- function(id) figure_ids == "all" || id %in% split_csv_arg(figure_ids)
requested_ids <- if (figure_ids == "all") character() else split_csv_arg(figure_ids)
is_refitted_partition_request <- "fig8_refitted_partition" %in% requested_ids
if (is_refitted_partition_request && length(requested_ids) != 1L) {
  stop("Fig8 refitted partition requires its own frozen bundle and figure selection")
}
is_dual_morris_request <- "fig3_dual_morris_screening" %in% requested_ids
if (is_dual_morris_request && length(requested_ids) != 1L) {
  stop("Fig3 Morris requires its own frozen bundle and figure selection")
}
spring_ids <- c("fig4_spring_evaluation", "fig5_spring_growth", "fig6_spring_harvest")
is_spring_request <- any(requested_ids %in% spring_ids)
if (is_spring_request && any(!requested_ids %in% spring_ids)) {
  stop("Deterministic spring figures require their own frozen bundle and figure selection")
}
stage2_ids<-c("fig2_environment_stage2","fig3_sensitivity_stage2","fig4_validation_stage2",
  "fig5_growth_stage2","fig6_harvest_stage2","fig7_response_stage2","fig8_forward_stage2",
  "figs_weather_stage2","figs_density_stage2","figs_correlation_stage2","figs_contrasts_stage2")
is_stage2_request<-any(requested_ids %in% stage2_ids)
if(is_stage2_request && any(!requested_ids %in% stage2_ids))stop("Stage 2 figures require a dedicated bundle and selection")
reconstruction_ids <- c("fig1_framework_prototype", "fig8_ablation_prototype", "fig4_validation_prototype")
is_reconstruction_request <- any(requested_ids %in% reconstruction_ids)
if (is_reconstruction_request && any(!requested_ids %in% reconstruction_ids)) {
  stop("Reconstruction prototypes require their own frozen bundle and figure selection")
}
if (is_reconstruction_request && .Platform$OS.type == "windows") {
  grDevices::windowsFonts("Microsoft YaHei" = grDevices::windowsFont("Microsoft YaHei"))
}
is_t4_request <- any(requested_ids %in% c("figs5_posterior", "figs6_spearman", "figs7_equifinality"))
is_sa_request <- any(requested_ids %in% c("fig1_sa", "figs1_sa_stability", "figs1b_sa_effects",
                                          "fig_sa_summary",
                                          "figs1c_sa_interaction", "figs1d_sa_selection"))
is_single_seed_request <- any(requested_ids %in% c("figs1d_single_seed_selection", "figs1b_single_seed_effects",
                                                  "figs1_single_seed_ranking", "figs1b_single_seed_fresh"))
is_sobol_request <- any(requested_ids %in% c("figs2_sobol_convergence", "figs2_sobol_results"))
# Conditional-ensemble uncertainty figures (plan 2026-08-28): a dedicated
# frozen bundle; the diagnostic figure ids deliberately claim no formal
# Fig/FigS number until the author approves one on validated data.
is_conditional_request <- any(requested_ids %in% c(
  "fig_model_performance_uncertainty", "diagnostic_conditional_residual_by_treatment",
  "fig4_dynamics_conditional", "figs4_all_treatments_conditional"))
if (sum(c(is_t4_request, is_sa_request, is_single_seed_request, is_sobol_request, is_conditional_request)) > 1) {
  stop("Morris SA, Sobol SA, T4, and conditional-ensemble figures require separate frozen bundles", call. = FALSE)
}
standard_ids <- c("fig2_phi", "fig3_performance", "figs3_residuals", "fig4_dynamics", "figs4_all_treatments", "fig_leaf_nitrogen", "fig_water_nitrogen_response")
if (is_conditional_request && any(requested_ids %in% standard_ids)) {
  stop("Conditional-ensemble figures require a dedicated bundle and cannot be mixed with standard paper figures", call. = FALSE)
}
if (is_t4_request) {
  if (any(vapply(standard_ids, selected, logical(1)))) {
    stop("T4 demo figures require a dedicated bundle and cannot be mixed with standard paper figures", call. = FALSE)
  }
}
if (is_sa_request) {
  if (any(requested_ids %in% standard_ids)) {
    stop("SA figures require a dedicated bundle and cannot be mixed with calibration figures", call. = FALSE)
  }
}
if (is_sobol_request) {
  if (any(requested_ids %in% standard_ids)) {
    stop("Sobol figures require a dedicated bundle and cannot be mixed with calibration figures", call. = FALSE)
  }
}
needs_trajectory <- selected("fig4_dynamics") || selected("figs4_all_treatments") || (selected("fig_leaf_nitrogen") && figure_ids != "all")
needs_treatment_metadata <- selected("figs3_residuals") || selected("fig4_dynamics") || selected("figs4_all_treatments") || (selected("fig_leaf_nitrogen") && figure_ids != "all")

bundle <- if (is_refitted_partition_request) {
  read_refitted_partition_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_spring_request) {
  read_spring_figure_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_dual_morris_request) {
  read_dual_morris_screening(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_stage2_request) {
  read_stage2_bundle(input_dir,isTRUE(args$allow_unvalidated_demo))
} else if (is_reconstruction_request) {
  read_reconstruction_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_t4_request) {
  read_t4_demo_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_single_seed_request) {
  read_single_seed_sa_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_sa_request) {
  read_sa_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_sobol_request) {
  read_sobol_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_conditional_request) {
  read_conditional_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else {
  read_paper_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
}
if (!is_refitted_partition_request && !is_spring_request && !is_dual_morris_request && !is_stage2_request && !is_reconstruction_request && !is_t4_request && !is_sa_request && !is_single_seed_request && !is_sobol_request && !is_conditional_request) {
  require_calibration_scenario(bundle)
}
# A label override is presentation-only; the source gates above still apply.
# The explicit author instruction is retained in the output manifest.
label_note <- if (is.null(args$publication_label_note)) "" else trimws(args$publication_label_note)
render_is_demo <- isTRUE(bundle$is_demo) && !nzchar(label_note)
if ((is_refitted_partition_request || is_spring_request || is_dual_morris_request) && isTRUE(bundle$is_demo)) {
  render_is_demo <- TRUE
  label_note <- ""
}
variables <- split_csv_arg(if (is.null(args$variables)) "LAID,LWAD,SWAD,FRESH_INC" else args$variables)
process_variables <- split_csv_arg(if (is.null(args$process_variables)) "LAID,LWAD" else args$process_variables)
treatments <- split_csv_arg(if (is.null(args$treatments)) "2,13" else args$treatments)
stem <- if (render_is_demo) "DEMO" else "Fig"
artifacts <- character()

if (is_refitted_partition_request) {
  profile$font_family <- "Times New Roman"
  profile$mixed_times_simsun <- TRUE
  scope <- if (is.null(bundle$manifest$growth_scope)) "process" else bundle$manifest$growth_scope
  suffix <- switch(scope, season_end = "_season_end",
    process_excluding_final_25sp = "_exclude_25sp_final_growth", process = "")
  if (is.null(suffix)) stop("Unrecognized Fig8 growth evaluation scope: ", scope)
  fig8_metric <- if (is.null(args$fig8_metric)) "nrmse_pct" else args$fig8_metric
  if (!fig8_metric %in% c("nrmse_pct", "r2")) stop("Fig8 metric must be nrmse_pct or r2")
  if (fig8_metric == "r2" && scope != "process") stop("Fig8 r2 versions require the full process bundle")
  fig8_versions <- if (fig8_metric == "r2") c(with_terminal_yield = TRUE, process_only = FALSE) else
    c(with_terminal_yield = TRUE)
  for (version in names(fig8_versions)) {
    result <- build_refitted_partition(bundle, profile, render_is_demo,
      metric = fig8_metric, include_terminal_yield = fig8_versions[[version]])
    version_suffix <- if (fig8_metric == "r2") paste0("_r2_", version) else suffix
    base <- file.path(out_dir, paste0(if (render_is_demo) "DEMO_" else "", "Fig8_refitted_partition_ablation", version_suffix))
    artifacts <- c(artifacts, save_figure_set(result$plot, base, profile, profile$double_column_width_mm, result$height_mm))
    for (field in c("source", "metrics")) {
      destination <- paste0(base, ".", field, ".csv")
      utils::write.csv(result[[field]], destination, row.names = FALSE, fileEncoding = "UTF-8")
      artifacts <- c(artifacts, destination)
    }
  }
}

if (is_spring_request) {
  profile$font_family <- "Times New Roman"
  profile$mixed_times_simsun <- TRUE
  status_note <- if (!render_is_demo) NULL else if (bundle$manifest$engineering_status == "engineering_failed")
    sprintf("DEMO · 工程门未通过（末轮 %d/%d）", bundle$manifest$retained, bundle$manifest$members) else
    "DEMO · 科学审查待完成"
  order <- unlist(bundle$manifest$treatment_order)
  specs <- list(
    list(id = spring_ids[1], stem = "Fig4_multivariable_evaluation", kind = "evaluation"),
    list(id = spring_ids[2], stem = "Fig5_canopy_organ_dynamics", kind = "growth"),
    list(id = spring_ids[3], stem = "Fig6_harvest_dynamics", kind = "harvest"),
    list(id = spring_ids[3], stem = "Fig6_harvest_dynamics_smooth_visual", kind = "smooth")
  )
  for (spec in specs) {
    if (!selected(spec$id)) next
    result <- switch(spec$kind,
      evaluation = build_spring_one_to_one(bundle$comparison, profile, status_note),
      growth = build_spring_growth(bundle$comparison, bundle$trajectory, bundle$selection, profile, order, status_note),
      harvest = build_spring_harvest(bundle$comparison, bundle$selection, profile, order, status_note),
      smooth = build_spring_harvest(bundle$comparison, bundle$selection, profile, order, status_note, smooth = TRUE))
    base <- file.path(out_dir, paste0(if (render_is_demo) "DEMO_" else "", spec$stem))
    artifacts <- c(artifacts, save_figure_set(result$plot, base, profile, profile$double_column_width_mm, result$height_mm))
    for (field in names(result)[vapply(result, is.data.frame, logical(1))]) {
      destination <- paste0(base, ".", field, ".csv")
      utils::write.csv(result[[field]], destination, row.names = FALSE, fileEncoding = "UTF-8")
      artifacts <- c(artifacts, destination)
    }
  }
}

if (is_dual_morris_request) {
  profile$font_family <- "Times New Roman"
  profile$mixed_times_simsun <- TRUE
  result <- build_dual_morris_screening(bundle, profile, render_is_demo)
  base <- file.path(out_dir, paste0(if (render_is_demo) "DEMO_" else "", "Fig3_dual_morris_screening"))
  artifacts <- save_figure_set(result$plot, base, profile, result$width_mm, result$height_mm)
  for (field in c("heatmap", "ranking", "supplement_labels", "summary")) {
    destination <- paste0(base, ".", field, ".csv")
    utils::write.csv(result[[field]], destination, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, destination)
  }
}

if(is_stage2_request) {
  t<-bundle$tables
  stage2_specs<-list(
    list(id="fig2_environment_stage2",name="Fig2_environment_management",kind="environment"),
    list(id="fig3_sensitivity_stage2",name="Fig3_sensitivity_ensemble_update",kind="sensitivity"),
    list(id="fig4_validation_stage2",name="Fig4_multivariable_performance",kind="validation"),
    list(id="fig5_growth_stage2",name="Fig5_growth_dynamics",kind="growth"),
    list(id="fig6_harvest_stage2",name="Fig6_harvest_dynamics",kind="harvest"),
    list(id="fig6_harvest_stage2",name="Fig6_harvest_dynamics_smooth_visual",kind="harvest_smooth"),
    list(id="fig7_response_stage2",name="Fig7_water_nitrogen_response",kind="response"),
    list(id="fig8_forward_stage2",name="Fig8_partition_forward_comparison",kind="forward"),
    list(id="figs_weather_stage2",name="FigS_weather_comparison",kind="weather"),
    list(id="figs_density_stage2",name="FigS_parameter_density_141",kind="density"),
    list(id="figs_correlation_stage2",name="FigS_parameter_correlation_141",kind="correlation"),
    list(id="figs_contrasts_stage2",name="FigS_management_contrasts",kind="contrasts")
  )
  for(spec in stage2_specs) {
    if(!selected(spec$id))next
    result<-switch(spec$kind,
      environment=build_environment_management(t$weather_daily,t$management_events,t$season_dates,profile,render_is_demo),
      sensitivity=build_sensitivity_update(t$morris_process_scores,t$parameter_intervals,profile,render_is_demo),
      validation=build_validation_sample(t$validation_sample_pairs,t$performance_metrics,profile,render_is_demo),
      growth=build_growth_dynamics(t$comparison,t$simulation_trajectory,t$representative_treatments,profile,render_is_demo),
      harvest=build_harvest_dynamics(t$comparison,t$representative_treatments,profile,render_is_demo),
      harvest_smooth=build_harvest_dynamics(t$comparison,t$representative_treatments,profile,render_is_demo,smooth=TRUE),
      response=build_management_response(t$terminal_pairs,t$treatment_metadata,profile,render_is_demo),
      forward=build_partition_forward_compact(t$partition_function,t$ablation_metrics,profile,render_is_demo),
      weather=build_weather_reference_comparison(t$weather_stripes,t$weather_daily_difference,t$season_dates,profile,render_is_demo),
      density=build_stage2_density(t$parameter_samples,t$parameter_intervals,profile,render_is_demo),
      correlation=build_spearman_structure(t$spearman_correlation,profile,render_is_demo),
      contrasts=build_management_contrasts(t$water_nitrogen_contrasts,t$water_nitrogen_contrast_summary,profile,render_is_demo))
    if(spec$kind=="correlation")result$plot<-result$plot+
      ggplot2::labs(title=NULL,subtitle=NULL,fill="Spearman ρ",caption="参考IES的141个非base成员；上三角与对角线参数名；两两秩相关不等于可辨识性。")+
      ggplot2::theme(plot.caption=ggplot2::element_text(size=5.7,hjust=0))
    if(is.null(result$metrics) && spec$kind %in% c("validation","growth","harvest","harvest_smooth")) result$metrics<-t$performance_metrics
    base<-file.path(out_dir,paste0(if(render_is_demo)"DEMO_" else "",spec$name))
    artifacts<-c(artifacts,save_figure_set(result$plot,base,profile,profile$double_column_width_mm,result$height_mm))
    for(field in setdiff(names(result),c("plot","height_mm","width_mm"))) {
      if(!is.data.frame(result[[field]]))next
      destination<-paste0(base,".",field,".csv")
      utils::write.csv(result[[field]],destination,row.names=FALSE,fileEncoding="UTF-8")
      artifacts<-c(artifacts,destination)
    }
  }
}

if (is_reconstruction_request) {
  specifications <- list(
    list(id="fig1_framework_prototype", name="Fig1_framework_prototype", kind="framework"),
    list(id="fig8_ablation_prototype", name="Fig8_ablation_prototype", kind="ablation"),
    list(id="fig8_ablation_prototype", name="Fig8_ablation_prototype_smooth_visual", kind="smooth"),
    list(id="fig4_validation_prototype", name="Fig4_validation_prototype", kind="validation")
  )
  for (spec in specifications) {
    if (!selected(spec$id)) next
    result <- switch(spec$kind,
      framework=build_model_framework(bundle$nodes,bundle$edges,profile,render_is_demo),
      ablation=build_partition_ablation(bundle$events,bundle$function_data,bundle$metrics,profile,render_is_demo),
      smooth=build_partition_ablation(bundle$events,bundle$function_data,bundle$metrics,profile,render_is_demo,smooth=TRUE),
      validation=build_validation_sample(bundle$pairs,bundle$metrics,profile,render_is_demo)
    )
    base <- file.path(out_dir,paste0(if(render_is_demo) "DEMO_" else "",spec$name))
    artifacts <- c(artifacts,save_figure_set(result$plot,base,profile,profile$double_column_width_mm,result$height_mm))
    for (field in intersect(c("source","edges","metrics","function_source"),names(result))) {
      destination <- paste0(base,".",field,".csv")
      utils::write.csv(result[[field]],destination,row.names=FALSE,fileEncoding="UTF-8")
      artifacts <- c(artifacts,destination)
    }
  }
}

if (is_single_seed_request) {
  specifications <- list(
    list(id="figs1d_single_seed_selection", name="FigS1d_single_seed_elbow", builder="elbow"),
    list(id="figs1b_single_seed_effects", name="FigS1b_single_seed_mu_sigma", builder="geometry"),
    list(id="figs1_single_seed_ranking", name="FigS1_single_seed_core_ranking", builder="ranking"),
    list(id="figs1b_single_seed_fresh", name="FigS1b_single_seed_fresh_yield", builder="fresh")
  )
  for (spec in specifications) {
    if (!selected(spec$id)) next
    result <- switch(spec$builder,
      elbow=build_single_seed_selection(bundle$rankings,bundle$summary,profile,render_is_demo),
      geometry=build_single_seed_geometry(bundle$effects,bundle$summary,profile,render_is_demo),
      ranking=build_single_seed_ranking(bundle$effects,bundle$summary,profile,render_is_demo),
      fresh=build_single_seed_geometry(bundle$effects,bundle$summary,profile,render_is_demo,responses="FRESH_END")
    )
    base <- file.path(out_dir,paste0(if(render_is_demo) "DEMO_" else "",spec$name))
    width <- if(is.null(result$width_mm)) profile$double_column_width_mm else result$width_mm
    artifacts <- c(artifacts,save_figure_set(result$plot,base,profile,width,result$height_mm))
    source <- paste0(base,".source.csv")
    utils::write.csv(result$source,source,row.names=FALSE,fileEncoding="UTF-8")
    artifacts <- c(artifacts,source)
  }
}

if (is_sa_request) {
  if (selected("fig1_sa")) {
    result <- build_morris_main(
      bundle$rankings, bundle$group_summary, bundle$focus, profile, render_is_demo, lang = lang
    )
    base <- file.path(out_dir, if (render_is_demo) "DEMO_Fig1_sa_morris" else "Fig1_sa_morris")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    ranking_source <- paste0(base, ".ranking_source.csv")
    group_source <- paste0(base, ".group_source.csv")
    utils::write.csv(result$ranking_source, ranking_source, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$group_source, group_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, ranking_source, group_source)
  }
  if (selected("figs1_sa_stability")) {
    result <- build_morris_stability(
      bundle$seed_rankings, bundle$stability, bundle$focus, profile, render_is_demo, lang = lang
    )
    base <- file.path(out_dir, if (render_is_demo) "DEMO_FigS1_sa_stability" else "FigS1_sa_stability")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    rank_source <- paste0(base, ".rank_source.csv")
    stability_source <- paste0(base, ".stability_source.csv")
    utils::write.csv(result$rank_source, rank_source, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$stability_source, stability_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, rank_source, stability_source)
  }
  # W4 (plan §5.3): response-level mu*-sigma small multiples.  This is the
  # second evidence class of Fig.S1, requiring the W2 morris_response_effects.csv.
  # Fail fast when the figure is explicitly requested but the bundle lacks the
  # effects table — a silent skip would let the command succeed with no output.
  if (selected("figs1b_sa_effects")) {
    if (!isTRUE(bundle$has_effects)) {
      stop("figs1b_sa_effects was requested but the bundle does not carry ",
           "morris_response_effects.csv. Rebuild the bundle with the W2 exporter.",
           call. = FALSE)
    }
    result <- build_morris_response_effects(
      bundle$effects, bundle$focus, profile, render_is_demo, lang = lang
    )
    base <- file.path(out_dir, if (render_is_demo) "DEMO_FigS1b_sa_effects" else "FigS1b_sa_effects")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    effects_source <- paste0(base, ".effects_source.csv")
    utils::write.csv(result$effects_source, effects_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, effects_source)
  }

  # Task 2: Morris + Sobol summary composite (plan §9 Fig.1 alternative).
  if (selected("fig_sa_summary")) {
    sobol_effects <- NULL
    if (!is.null(args$sobol_effects_csv) && nzchar(args$sobol_effects_csv) && file.exists(args$sobol_effects_csv)) {
      sobol_effects <- utils::read.csv(args$sobol_effects_csv, stringsAsFactors = FALSE, check.names = FALSE)
    }
    result <- build_sa_summary(
      bundle$rankings, bundle$group_summary, bundle$focus, sobol_effects,
      profile, render_is_demo, lang = lang
    )
    base <- file.path(out_dir, if (render_is_demo) "DEMO_Fig_sa_summary" else "Fig_sa_summary")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    ranking_source <- paste0(base, ".ranking_source.csv")
    utils::write.csv(result$ranking_source, ranking_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, ranking_source)
    if (!is.null(result$sobol_source)) {
      sobol_source <- paste0(base, ".sobol_source.csv")
      utils::write.csv(result$sobol_source, sobol_source, row.names = FALSE, fileEncoding = "UTF-8")
      artifacts <- c(artifacts, sobol_source)
    }
  }

  # Task 3a: Morris interaction mu*-sigma scatter.
  if (selected("figs1c_sa_interaction")) {
    interaction_csv <- if (!is.null(args$interaction_csv) && nzchar(args$interaction_csv)) {
      args$interaction_csv
    } else file.path(input_dir, "morris_interaction_summary.csv")
    if (!file.exists(interaction_csv)) {
      stop("figs1c_sa_interaction requires morris_interaction_summary.csv (run ",
           "tools/sa/aggregate_morris_interaction.py). Expected: ", interaction_csv,
           call. = FALSE)
    }
    summary_data <- utils::read.csv(interaction_csv, stringsAsFactors = FALSE, check.names = FALSE)
    result <- build_morris_interaction(summary_data, profile, render_is_demo, lang = lang)
    base <- file.path(out_dir, if (render_is_demo) "DEMO_FigS1c_sa_interaction" else "FigS1c_sa_interaction")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$column_width_mm, result$height_mm
    ))
    src <- paste0(base, ".interaction_source.csv")
    utils::write.csv(result$interaction_source, src, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, src)
  }

  # Task 3b: Parameter selection rationality funnel (55 -> 23).
  if (selected("figs1d_sa_selection")) {
    cross_summary <- utils::read.csv(file.path(input_dir, "morris_cross_season_summary.csv"),
                                     stringsAsFactors = FALSE, check.names = FALSE)
    sobol_candidates <- utils::read.csv(file.path(project_root,
      "configs", "sa", "approved_topk", "eggplant_formal_sobol_top23_v1_20260721.csv"),
      stringsAsFactors = FALSE, check.names = FALSE)
    # Strip BOM from first column name if present
    names(sobol_candidates)[1] <- sub("^\\ufeff", "", names(sobol_candidates)[1])
    param_labels <- NULL
    labels_csv <- if (!is.null(args$param_labels_csv) && nzchar(args$param_labels_csv)) {
      args$param_labels_csv
    } else file.path(project_root, "workspace", "sa", "supplement_tables", "Table_S1_morris_sampling_space.csv")
    if (file.exists(labels_csv)) {
      param_labels <- utils::read.csv(labels_csv, stringsAsFactors = FALSE, check.names = FALSE)
    }
    result <- build_selection_rationality(
      cross_summary, sobol_candidates, param_labels, profile, render_is_demo, lang = lang
    )
    base <- file.path(out_dir, if (render_is_demo) "DEMO_FigS1d_sa_selection" else "FigS1d_sa_selection")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$column_width_mm, result$height_mm
    ))
    src <- paste0(base, ".selection_source.csv")
    utils::write.csv(result$selection_source, src, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, src)
  }
}

if (is_sobol_request && selected("figs2_sobol_convergence")) {
  result <- if (isTRUE(bundle$is_multiseason)) {
    if (isTRUE(bundle$has_effects)) {
      build_sobol_multiseason_effects(bundle$rankings, bundle$metrics, bundle$run_scale,
                                      bundle$summary, bundle$effects, bundle$response_scales,
                                      profile, render_is_demo, lang = lang)
    } else {
      build_sobol_multiseason_convergence(bundle$rankings, bundle$metrics, bundle$run_scale,
                                          bundle$summary, profile, render_is_demo)
    }
  } else {
    build_sobol_convergence(bundle$rankings, bundle$metrics, bundle$run_scale, profile, render_is_demo)
  }
  figure_stem <- if (isTRUE(bundle$has_effects)) "FigS2_sobol_effects" else "FigS2_sobol_convergence"
  base <- file.path(out_dir, if (render_is_demo) paste0("DEMO_", figure_stem) else figure_stem)
  artifacts <- c(artifacts, save_figure_set(result$plot, base, profile,
                                             profile$double_column_width_mm, result$height_mm))
  ranking_source <- paste0(base, ".ranking_source.csv")
  metrics_source <- paste0(base, ".metrics_source.csv")
  run_scale_source <- paste0(base, ".run_scale_source.csv")
  utils::write.csv(result$ranking_source, ranking_source, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(result$metrics_source, metrics_source, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(result$run_scale_source, run_scale_source, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, ranking_source, metrics_source, run_scale_source)
  if (!is.null(result$summary_source)) {
    summary_source <- paste0(base, ".summary_source.csv")
    utils::write.csv(result$summary_source, summary_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, summary_source)
  }
  if (!is.null(result$effects_source)) {
    effects_source <- paste0(base, ".effects_source.csv")
    response_scales_source <- paste0(base, ".response_scales_source.csv")
    utils::write.csv(result$effects_source, effects_source, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$response_scales_source, response_scales_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, effects_source, response_scales_source)
  }
}

if (is_sobol_request && selected("figs2_sobol_results")) {
  if (!isTRUE(bundle$is_multiseason) || !isTRUE(bundle$has_effects)) {
    stop("figs2_sobol_results requires the multi-season Sobol effects bundle", call. = FALSE)
  }
  result <- build_sobol_results(bundle$effects, bundle$response_scales,
                                profile, render_is_demo, lang = lang)
  base <- file.path(out_dir, if (render_is_demo) "DEMO_FigS2_sobol_results" else "FigS2_sobol_results")
  artifacts <- c(artifacts, save_figure_set(
    result$plot, base, profile, profile$double_column_width_mm, result$height_mm
  ))
  effects_source <- paste0(base, ".effects_source.csv")
  scales_source <- paste0(base, ".response_scales_source.csv")
  utils::write.csv(result$effects_source, effects_source, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(result$response_scales_source, scales_source, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, effects_source, scales_source)
}

if (is_t4_request) {
  if (figure_ids == "all") stop("T4 demo bundles require explicit --figure-ids", call. = FALSE)
  if (selected("figs5_posterior")) {
    result <- build_posterior_contraction(bundle$posterior, profile, render_is_demo)
    base <- file.path(out_dir, if (render_is_demo) "DEMO_FigS5_posterior_contraction" else "FigS5_posterior_contraction")
    artifacts <- c(artifacts, save_figure_set(result$plot, base, profile, profile$double_column_width_mm, result$height_mm))
    source_path <- paste0(base, ".source.csv"); utils::write.csv(result$source, source_path, row.names = FALSE)
    artifacts <- c(artifacts, source_path)

    if (!is.null(bundle$posterior_samples)) {
      dens_result <- build_posterior_contraction(bundle$posterior, profile, render_is_demo, posterior_samples = bundle$posterior_samples)
      dens_base <- file.path(out_dir, if (render_is_demo) "DEMO_FigS5_posterior_density" else "FigS5_posterior_density")
      artifacts <- c(artifacts, save_figure_set(dens_result$plot, dens_base, profile, profile$double_column_width_mm, dens_result$height_mm))
      dens_source <- paste0(dens_base, ".source.csv"); utils::write.csv(dens_result$source, dens_source, row.names = FALSE)
      artifacts <- c(artifacts, dens_source)
    }
  }
  if (selected("figs6_spearman")) {
    result <- build_spearman_structure(bundle$spearman, profile, render_is_demo)
    base <- file.path(out_dir, if (render_is_demo) "DEMO_FigS6_spearman_structure" else "FigS6_spearman_structure")
    width_mm <- if (result$height_mm > 100) profile$double_column_width_mm else profile$column_width_mm
    artifacts <- c(artifacts, save_figure_set(result$plot, base, profile, width_mm, result$height_mm))
    source_path <- paste0(base, ".source.csv"); utils::write.csv(result$source, source_path, row.names = FALSE)
    artifacts <- c(artifacts, source_path)
  }
  if (selected("figs7_equifinality")) {
    result <- build_candidate_prediction_distance(bundle$pair_predictions, profile, render_is_demo)
    base <- file.path(out_dir, if (render_is_demo) "DEMO_FigS7_candidate_prediction_distance" else "FigS7_candidate_prediction_distance")
    artifacts <- c(artifacts, save_figure_set(result$plot, base, profile, profile$double_column_width_mm, result$height_mm))
    source_path <- paste0(base, ".source.csv"); utils::write.csv(result$source, source_path, row.names = FALSE)
    distance_path <- paste0(base, ".distance_source.csv"); utils::write.csv(result$distance_source, distance_path, row.names = FALSE)
    artifacts <- c(artifacts, source_path, distance_path)
  }
}

if (selected("fig3_performance")) {
  performance <- build_model_performance(bundle$comparison, variables, profile, render_is_demo)
  performance_base <- file.path(out_dir, paste0(stem, if (render_is_demo) "_model_performance" else "3_model_performance"))
  artifacts <- c(artifacts, save_figure_set(performance$plot, performance_base, profile,
                                           profile$double_column_width_mm, performance$height_mm))
  performance_source <- paste0(performance_base, ".source.csv")
  performance_metrics <- paste0(performance_base, ".metrics.csv")
  utils::write.csv(performance$source, performance_source, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(performance$metrics, performance_metrics, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, performance_source, performance_metrics)
}

if (needs_trajectory && is.null(bundle$trajectory)) {
  stop("Dynamic figures require simulation_trajectory.csv; export with --trajectory-run-dir or select figures without --figure-ids that need it")
}
if (needs_treatment_metadata && is.null(bundle$treatment_metadata)) {
  stop("Water-nitrogen figures require treatment_metadata.csv; export with --treatment-metadata-csv or select figures without --figure-ids that need it")
}
supplement_treatments <- if (!is.null(args$supplement_treatments)) {
  split_csv_arg(args$supplement_treatments)
} else if (!is.null(bundle$treatment_metadata)) {
  unique(as.character(bundle$treatment_metadata$treatment))
} else {
  character()
}
supplement_process_variables <- split_csv_arg(
  if (is.null(args$supplement_process_variables)) "LAID,LWAD" else args$supplement_process_variables
)

# ── conditional-ensemble uncertainty figures (dedicated bundle) ────────────
if (is_conditional_request) {
  if (figure_ids == "all") {
    stop("Conditional-ensemble bundles require explicit --figure-ids", call. = FALSE)
  }
  conditional_stem <- if (render_is_demo) "DEMO_conditional" else "conditional"
  if (selected("fig_model_performance_uncertainty")) {
    result <- build_model_performance_uncertainty(
      bundle$prediction, bundle$treatment_metadata, "FRESH_CUM", profile, render_is_demo
    )
    base <- file.path(out_dir, paste0(conditional_stem, "_model_performance_uncertainty"))
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    source_path <- paste0(base, ".source.csv")
    metrics_path <- paste0(base, ".metrics.csv")
    utils::write.csv(result$source, source_path, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$metrics, metrics_path, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, source_path, metrics_path)
  }
  if (selected("diagnostic_conditional_residual_by_treatment")) {
    result <- build_treatment_residual_uncertainty(
      bundle$residual_members, bundle$treatment_metadata, "FRESH_CUM",
      "terminal_relative_error_pct", profile, render_is_demo
    )
    base <- file.path(out_dir, paste0(conditional_stem, "_treatment_residual_uncertainty"))
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    forest_path <- paste0(base, ".forest.csv")
    rrmse_path <- paste0(base, ".rrmse.csv")
    source_path <- paste0(base, ".source.csv")
    utils::write.csv(result$forest, forest_path, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$rrmse_forest, rrmse_path, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$source, source_path, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, forest_path, rrmse_path, source_path)
  }
  if (selected("fig4_dynamics_conditional")) {
    frozen_selection <- utils::read.csv(
      file.path(project_root, "configs", "figures", "selected_treatments_conditional.csv"),
      fileEncoding = "UTF-8", stringsAsFactors = FALSE
    )
    season_treatments <- frozen_selection[order(frozen_selection$display_order),
                                          c("season_id", "treatment")]
    process <- build_process_dynamics_conditional(
      bundle$prediction, bundle$trajectory, bundle$treatment_metadata,
      process_variables, season_treatments, profile, render_is_demo
    )
    process_base <- file.path(out_dir, paste0(conditional_stem, "_selected_process_dynamics"))
    artifacts <- c(artifacts, save_figure_set(
      process$plot, process_base, profile, profile$double_column_width_mm, process$height_mm
    ))
    process_obs <- paste0(process_base, ".observations.csv")
    process_sim <- paste0(process_base, ".daily_simulation.csv")
    utils::write.csv(process$observations, process_obs, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(process$daily, process_sim, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, process_obs, process_sim)

    harvest <- build_harvest_dynamics_conditional(
      bundle$prediction, bundle$treatment_metadata, "FRESH_INC", "FRESH_CUM",
      season_treatments, profile, render_is_demo
    )
    harvest_base <- file.path(out_dir, paste0(conditional_stem, "_selected_harvest_dynamics"))
    artifacts <- c(artifacts, save_figure_set(
      harvest$plot, harvest_base, profile, profile$double_column_width_mm, harvest$height_mm
    ))
    harvest_increment <- paste0(harvest_base, ".increment.csv")
    harvest_cumulative <- paste0(harvest_base, ".cumulative.csv")
    utils::write.csv(harvest$increment, harvest_increment, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(harvest$cumulative, harvest_cumulative, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, harvest_increment, harvest_cumulative)
  }
  if (selected("figs4_all_treatments_conditional")) {
    all_variables <- unique(c(supplement_process_variables, "DRY_CUM", "FRESH_CUM"))
    all_results <- build_all_treatment_dynamics_conditional(
      bundle$prediction, bundle$trajectory, bundle$treatment_metadata,
      all_variables, profile, render_is_demo
    )
    for (variable in names(all_results)) {
      result <- all_results[[variable]]
      all_base <- file.path(out_dir, paste0(conditional_stem, "_all_treatments_", variable))
      artifacts <- c(artifacts, save_figure_set(
        result$plot, all_base, profile, profile$double_column_width_mm, result$height_mm
      ))
      all_obs <- paste0(all_base, ".observations.csv")
      all_sim <- paste0(all_base, ".daily_simulation.csv")
      utils::write.csv(result$observations, all_obs, row.names = FALSE, fileEncoding = "UTF-8")
      utils::write.csv(result$daily, all_sim, row.names = FALSE, fileEncoding = "UTF-8")
      artifacts <- c(artifacts, all_obs, all_sim)
    }
  }
}

if (selected("figs3_residuals")) {
  residuals <- build_residual_diagnostics(bundle$comparison, bundle$treatment_metadata,
                                          variables, profile, render_is_demo)
  for (role in names(residuals)) {
    result <- residuals[[role]]
    residual_base <- file.path(out_dir, if (render_is_demo) {
      paste0("DEMO_residuals_", role)
    } else paste0("FigS3_residuals_", role))
    artifacts <- c(artifacts, save_figure_set(result$plot, residual_base, profile,
                                             profile$double_column_width_mm, result$height_mm))
    residual_source <- paste0(residual_base, ".source.csv")
    residual_qq <- paste0(residual_base, ".qq.csv")
    residual_metrics <- paste0(residual_base, ".metrics.csv")
    utils::write.csv(result$source, residual_source, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$qq, residual_qq, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$metrics, residual_metrics, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, residual_source, residual_qq, residual_metrics)
  }
}

if (selected("fig4_dynamics")) {
  process <- build_process_dynamics(bundle$comparison, bundle$trajectory,
                                    bundle$treatment_metadata, process_variables,
                                    treatments, profile, render_is_demo)
  process_base <- file.path(out_dir, paste0(stem, if (render_is_demo) "_process_dynamics" else "4_process_dynamics"))
  artifacts <- c(artifacts, save_figure_set(process$plot, process_base, profile,
                                           profile$double_column_width_mm, process$height_mm))
  process_obs <- paste0(process_base, ".observations.csv")
  process_sim <- paste0(process_base, ".daily_simulation.csv")
  utils::write.csv(process$observations, process_obs, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(process$simulation, process_sim, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, process_obs, process_sim)

  harvest <- build_harvest_dynamics(bundle$comparison, bundle$treatment_metadata,
                                    "FRESH_INC", "FRESH_CUM", treatments,
                                    profile, render_is_demo)
  harvest_base <- file.path(out_dir, paste0(stem, if (render_is_demo) "_harvest_dynamics" else "4_harvest_dynamics"))
  artifacts <- c(artifacts, save_figure_set(harvest$plot, harvest_base, profile,
                                           profile$double_column_width_mm, harvest$height_mm))
  harvest_increment <- paste0(harvest_base, ".increment.csv")
  harvest_cumulative <- paste0(harvest_base, ".cumulative.csv")
  utils::write.csv(harvest$increment, harvest_increment, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(harvest$cumulative, harvest_cumulative, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, harvest_increment, harvest_cumulative)

  smooth <- build_cumulative_smooth(bundle$comparison, bundle$trajectory,
                                    bundle$treatment_metadata, "FRESH_CUM", treatments,
                                    profile, render_is_demo)
  smooth_base <- file.path(out_dir, paste0(stem, if (render_is_demo) "_cumulative_smooth" else "4_cumulative_smooth"))
  artifacts <- c(artifacts, save_figure_set(smooth$plot, smooth_base, profile,
                                           profile$double_column_width_mm, smooth$height_mm))
  smooth_obs <- paste0(smooth_base, ".observations.csv")
  smooth_daily <- paste0(smooth_base, ".daily_simulation.csv")
  smooth_curve <- paste0(smooth_base, ".smooth_curve.csv")
  utils::write.csv(smooth$observations, smooth_obs, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(smooth$daily, smooth_daily, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(smooth$curve, smooth_curve, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, smooth_obs, smooth_daily, smooth_curve)
}

if (selected("figs4_all_treatments")) {
  all_process <- build_all_treatment_process(
    bundle$comparison, bundle$trajectory, bundle$treatment_metadata,
    supplement_process_variables, supplement_treatments, profile, render_is_demo
  )
  for (variable in names(all_process)) {
    result <- all_process[[variable]]
    process_all_base <- file.path(out_dir, if (render_is_demo) {
      paste0("DEMO_all_treatments_", variable)
    } else paste0("FigS4_all_treatments_", variable))
    artifacts <- c(artifacts, save_figure_set(result$plot, process_all_base, profile,
                                             profile$double_column_width_mm, result$height_mm))
    process_all_obs <- paste0(process_all_base, ".observations.csv")
    process_all_sim <- paste0(process_all_base, ".daily_simulation.csv")
    utils::write.csv(result$observations, process_all_obs, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$simulation, process_all_sim, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, process_all_obs, process_all_sim)
  }

  all_harvest <- build_all_treatment_harvest(
    bundle$comparison, bundle$trajectory, bundle$treatment_metadata,
    "FRESH_INC", "FRESH_CUM", supplement_treatments, profile, render_is_demo
  )
  for (kind in c("increment", "cumulative_event")) {
    result <- all_harvest[[kind]]
    harvest_all_base <- file.path(out_dir, if (render_is_demo) {
      paste0("DEMO_all_treatments_", kind)
    } else paste0("FigS4_all_treatments_", kind))
    artifacts <- c(artifacts, save_figure_set(result$plot, harvest_all_base, profile,
                                             profile$double_column_width_mm, result$height_mm))
    harvest_all_source <- paste0(harvest_all_base, ".source.csv")
    utils::write.csv(result$source, harvest_all_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, harvest_all_source)
  }
  smooth_all <- all_harvest$cumulative_smooth
  smooth_all_base <- file.path(out_dir, if (render_is_demo) {
    "DEMO_all_treatments_cumulative_smooth"
  } else "FigS4_all_treatments_cumulative_smooth")
  artifacts <- c(artifacts, save_figure_set(smooth_all$plot, smooth_all_base, profile,
                                           profile$double_column_width_mm, smooth_all$height_mm))
  smooth_all_obs <- paste0(smooth_all_base, ".observations.csv")
  smooth_all_daily <- paste0(smooth_all_base, ".daily_simulation.csv")
  smooth_all_curve <- paste0(smooth_all_base, ".smooth_curve.csv")
  utils::write.csv(smooth_all$observations, smooth_all_obs, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(smooth_all$daily, smooth_all_daily, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(smooth_all$curve, smooth_all_curve, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, smooth_all_obs, smooth_all_daily, smooth_all_curve)
}

if (selected("fig2_phi") && !is.null(bundle$phi)) {
  convergence <- build_phi_convergence(bundle$phi, profile, render_is_demo)
  convergence_base <- file.path(out_dir, paste0(stem, if (render_is_demo) "_phi_convergence" else "2_phi_convergence"))
  artifacts <- c(artifacts, save_figure_set(convergence$plot, convergence_base, profile,
                                           profile$column_width_mm, convergence$height_mm))
  convergence_source <- paste0(convergence_base, ".source.csv")
  convergence_summary <- paste0(convergence_base, ".summary.csv")
  utils::write.csv(convergence$source, convergence_source, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(convergence$summary, convergence_summary, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, convergence_source, convergence_summary)
}

if (selected("fig_leaf_nitrogen")) {
  if (!is.null(bundle$comparison) && "LN%D" %in% bundle$comparison$variable &&
      !is.null(bundle$trajectory) && "LN%D" %in% bundle$trajectory$variable) {
    leaf_n_res <- build_leaf_nitrogen(bundle$comparison, bundle$trajectory,
                                      bundle$treatment_metadata, profile, render_is_demo)
    leaf_n_base <- file.path(out_dir, paste0(stem, if (render_is_demo) "_leaf_nitrogen" else "LeafN_leaf_nitrogen"))
    artifacts <- c(artifacts, save_figure_set(leaf_n_res$plot, leaf_n_base, profile,
                                             profile$double_column_width_mm, leaf_n_res$height_mm))
    leaf_n_source <- paste0(leaf_n_base, ".source.csv")
    leaf_n_metrics <- paste0(leaf_n_base, ".metrics.csv")
    leaf_n_daily <- paste0(leaf_n_base, ".daily_simulation.csv")
    utils::write.csv(leaf_n_res$source, leaf_n_source, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(leaf_n_res$metrics, leaf_n_metrics, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(leaf_n_res$daily, leaf_n_daily, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, leaf_n_source, leaf_n_metrics, leaf_n_daily)
  } else if (figure_ids != "all") {
    stop("fig_leaf_nitrogen requested but LN%D data not present in bundle", call. = FALSE)
  }
}

if (selected("fig_water_nitrogen_response")) {
  if (!is.null(bundle$comparison) && !is.null(bundle$treatment_metadata) &&
      "season_id" %in% names(bundle$comparison) && "season_id" %in% names(bundle$treatment_metadata)) {
    wn_res <- build_water_nitrogen_response(bundle$comparison, bundle$treatment_metadata, profile, render_is_demo)
    wn_base <- file.path(out_dir, paste0(stem, if (render_is_demo) "_water_nitrogen_response" else "6_water_nitrogen_response"))
    artifacts <- c(artifacts, save_figure_set(wn_res$plot, wn_base, profile,
                                             profile$double_column_width_mm, wn_res$height_mm))
    wn_source <- paste0(wn_base, ".source.csv")
    utils::write.csv(wn_res$source, wn_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, wn_source)
    water_base <- file.path(out_dir, if (render_is_demo) "DEMO_water_response" else "Fig6_water_response")
    artifacts <- c(artifacts, save_figure_set(wn_res$water_plot, water_base, profile,
        profile$double_column_width_mm, wn_res$water_height_mm))
    water_source <- paste0(water_base, ".source.csv")
    utils::write.csv(wn_res$water_source, water_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, water_source)
  } else if (figure_ids != "all") {
    stop("fig_water_nitrogen_response requires season_id in both comparison and treatment_metadata", call. = FALSE)
  }
}

manifest <- list(
  schema_version = 2,
  created_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
  renderer = paste0("R ", getRversion()),
  package_versions = as.list(vapply(unique(c(required_packages,if(is_single_seed_request) "ggrepel" else character())),
    function(package) as.character(utils::packageVersion(package)), character(1))),
  git_commit = trimws(system2("git", c("-C", shQuote(project_root), "rev-parse", "HEAD"),
                              stdout = TRUE, stderr = FALSE)[[1]]),
  git_dirty = length(system2("git", c("-C", shQuote(project_root), "status", "--porcelain"),
                             stdout = TRUE, stderr = FALSE)) > 0,
  profile_id = profile$profile_id,
  profile = sha256_record(profile_path),
  run_id = bundle$manifest$run_id,
  data_status = bundle$manifest$data_status,
  science_validated = identical(bundle$manifest$data_status, "science_validated"),
  source_is_demo = isTRUE(bundle$is_demo),
  demo_label_visible = render_is_demo,
  publication_label_note = label_note,
  scientific_status_promoted = FALSE,
  input_manifest = sha256_record(file.path(input_dir, "paper_data_manifest.json")),
  artifacts = lapply(artifacts, sha256_record)
)
manifest_path <- file.path(out_dir, "figure_manifest.json")
if (is_refitted_partition_request) {
  manifest$figure_id <- "fig8_refitted_partition"
  manifest$runs <- bundle$manifest$runs
  manifest$matching <- bundle$manifest$matching
  manifest$growth_scope <- scope
  manifest$comparison_metric <- fig8_metric
  manifest$include_terminal_yield <- as.list(fig8_versions)
  manifest$growth_sampling_dates <- bundle$manifest$growth_sampling_dates
  manifest$excluded_growth_dates <- bundle$manifest$excluded_growth_dates
  manifest$retained_coefficients <- bundle$manifest$retained_coefficients
  manifest$renderer_sources <- lapply(file.path(script_dir, c("common.R", "publication_fonts.R",
    "make_all.R", "fig_partition_ablation.R")), sha256_record)
  manifest$font_policy <- list(latin_digits = "Times New Roman", chinese = "SimSun")
}
if (is_spring_request) {
  manifest$figure_ids <- as.list(requested_ids)
  manifest$validation_refresh <- bundle$manifest$validation_refresh
  manifest$selection <- bundle$manifest$selection
  manifest$engineering_status <- bundle$manifest$engineering_status
  manifest$renderer_sources <- lapply(file.path(script_dir, c("common.R", "publication_fonts.R",
    "make_all.R", "spring_figure_bundle.R", "fig_validation_sample.R", "fig_growth_dynamics.R",
    "fig_harvest_dynamics.R")), sha256_record)
  manifest$font_policy <- list(latin_digits = "Times New Roman", chinese = "SimSun")
}
if (is_dual_morris_request) {
  manifest$figure_id <- "fig3_dual_morris_screening"
  manifest$selection_status <- bundle$manifest$selection_status
  manifest$renderer_sources <- lapply(file.path(script_dir, c("common.R", "publication_fonts.R",
    "make_all.R", "fig_dual_morris_screening.R")), sha256_record)
  manifest$font_policy <- list(latin_digits = "Times New Roman", chinese = "SimSun")
}
jsonlite::write_json(manifest, manifest_path, auto_unbox = TRUE, pretty = TRUE)
if(is_stage2_request) {
  renderers<-file.path(script_dir,c("common.R","publication_fonts.R","make_all.R",
    "fig_environment_management.R","fig_sensitivity_update.R","fig_validation_sample.R",
    "fig_growth_dynamics.R","fig_harvest_dynamics.R","fig_management_response.R",
    "fig_partition_ablation.R","fig_spearman_demo.R"))
  for(spec in stage2_specs) {
    if(!selected(spec$id))next
    name<-paste0(if(render_is_demo)"DEMO_" else "",spec$name)
    per_figure<-manifest;per_figure$figure_id<-spec$id
    per_figure$ablation_design<-bundle$manifest$ablation
    per_figure$font_policy<-list(latin_digits="Times New Roman",chinese="SimSun",explicit_glyph_runs=TRUE)
    per_figure$artifacts<-Filter(function(a)startsWith(basename(a$path),paste0(name,".")),manifest$artifacts)
    per_figure$renderer_sources<-lapply(renderers,sha256_record)
    jsonlite::write_json(per_figure,file.path(out_dir,paste0(name,".figure_manifest.json")),auto_unbox=TRUE,pretty=TRUE)
  }
}
if (is_reconstruction_request) {
  for (spec in specifications) {
    if (!selected(spec$id)) next
    name <- paste0(if(render_is_demo) "DEMO_" else "",spec$name)
    per_figure <- manifest
    per_figure$figure_id <- spec$id
    per_figure$design_number_is_provisional <- TRUE
    per_figure$artifacts <- Filter(function(a) startsWith(basename(a$path),paste0(name,".")),manifest$artifacts)
    per_figure$renderer_sources <- lapply(file.path(script_dir,c("common.R","make_all.R",
      switch(spec$kind,framework="fig_model_framework.R",ablation="fig_partition_ablation.R",
        smooth="fig_partition_ablation.R",validation="fig_validation_sample.R"))),sha256_record)
    jsonlite::write_json(per_figure,file.path(out_dir,paste0(name,".figure_manifest.json")),auto_unbox=TRUE,pretty=TRUE)
  }
}
cat(normalizePath(manifest_path, winslash = "/", mustWork = TRUE), "\n")
