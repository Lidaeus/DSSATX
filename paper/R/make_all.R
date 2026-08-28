script_arg <- grep("^--file=", commandArgs(trailingOnly = FALSE), value = TRUE)
script_path <- normalizePath(sub("^--file=", "", script_arg[[1]]), winslash = "/", mustWork = TRUE)
script_dir <- dirname(script_path)
project_root <- normalizePath(file.path(script_dir, "..", ".."), winslash = "/", mustWork = TRUE)

source(file.path(script_dir, "common.R"), local = FALSE)
source(file.path(script_dir, "sa_i18n.R"), local = FALSE)
source(file.path(script_dir, "fig_model_performance.R"), local = FALSE)
source(file.path(script_dir, "fig_model_performance_uncertainty.R"), local = FALSE)
source(file.path(script_dir, "fig_treatment_residual_uncertainty.R"), local = FALSE)
source(file.path(script_dir, "fig_selected_dynamics.R"), local = FALSE)
source(file.path(script_dir, "fig_residual_diagnostics.R"), local = FALSE)
source(file.path(script_dir, "fig_all_treatment_dynamics.R"), local = FALSE)
source(file.path(script_dir, "fig_phi_convergence.R"), local = FALSE)
source(file.path(script_dir, "fig_posterior_demo.R"), local = FALSE)
source(file.path(script_dir, "fig_spearman_demo.R"), local = FALSE)
source(file.path(script_dir, "fig_equifinality_demo.R"), local = FALSE)
source(file.path(script_dir, "fig_sa_morris.R"), local = FALSE)
source(file.path(script_dir, "fig_sa_sobol.R"), local = FALSE)
source(file.path(script_dir, "fig_sa_interaction.R"), local = FALSE)
source(file.path(script_dir, "fig_sa_selection.R"), local = FALSE)

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
is_t4_request <- any(requested_ids %in% c("figs5_posterior", "figs6_spearman", "figs7_equifinality"))
is_sa_request <- any(requested_ids %in% c("fig1_sa", "fig1_sa_results", "figs1_sa_stability", "figs1b_sa_effects",
                                          "figs1_sa", "fig_sa_summary",
                                          "figs1c_sa_interaction", "figs1d_sa_selection"))
is_sobol_request <- any(requested_ids %in% c("figs2_sobol_convergence", "figs2_sobol_results"))
# Conditional-ensemble uncertainty figures (plan 2026-08-28): a dedicated
# frozen bundle; the diagnostic figure ids deliberately claim no formal
# Fig/FigS number until the author approves one on validated data.
is_conditional_request <- any(requested_ids %in% c(
  "fig_model_performance_uncertainty", "diagnostic_conditional_residual_by_treatment",
  "fig4_dynamics_conditional", "figs4_all_treatments_conditional"))
if (sum(c(is_t4_request, is_sa_request, is_sobol_request, is_conditional_request)) > 1) {
  stop("Morris SA, Sobol SA, T4, and conditional-ensemble figures require separate frozen bundles", call. = FALSE)
}
standard_ids <- c("fig2_phi", "fig3_performance", "figs3_residuals", "fig4_dynamics", "figs4_all_treatments")
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
needs_trajectory <- selected("fig4_dynamics") || selected("figs4_all_treatments")
needs_treatment_metadata <- selected("figs3_residuals") || selected("fig4_dynamics") || selected("figs4_all_treatments")

bundle <- if (is_t4_request) {
  read_t4_demo_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_sa_request) {
  read_sa_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_sobol_request) {
  read_sobol_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else if (is_conditional_request) {
  read_conditional_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
} else {
  read_paper_bundle(input_dir, isTRUE(args$allow_unvalidated_demo))
}
if (!is_t4_request && !is_sa_request && !is_sobol_request && !is_conditional_request) {
  require_calibration_scenario(bundle)
}
variables <- split_csv_arg(if (is.null(args$variables)) "LAID,LWAD,SWAD,FRESH_INC" else args$variables)
process_variables <- split_csv_arg(if (is.null(args$process_variables)) "LAID,LWAD" else args$process_variables)
treatments <- split_csv_arg(if (is.null(args$treatments)) "2,13" else args$treatments)
stem <- if (bundle$is_demo) "DEMO" else "Fig"
artifacts <- character()

if (is_sa_request) {
  if (selected("fig1_sa")) {
    result <- build_morris_main(
      bundle$rankings, bundle$group_summary, bundle$focus, profile, bundle$is_demo, lang = lang
    )
    base <- file.path(out_dir, if (bundle$is_demo) "DEMO_Fig1_sa_morris" else "Fig1_sa_morris")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    ranking_source <- paste0(base, ".ranking_source.csv")
    group_source <- paste0(base, ".group_source.csv")
    utils::write.csv(result$ranking_source, ranking_source, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$group_source, group_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, ranking_source, group_source)
  }
  if (selected("fig1_sa_results")) {
    result <- build_morris_results(
      bundle$group_summary, bundle$summary, bundle$focus, profile, bundle$is_demo, lang = lang
    )
    base <- file.path(out_dir, if (bundle$is_demo) "DEMO_Fig1_sa_results" else "Fig1_sa_results")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    group_source <- paste0(base, ".group_source.csv")
    score_source <- paste0(base, ".score_source.csv")
    utils::write.csv(result$group_source, group_source, row.names = FALSE, fileEncoding = "UTF-8")
    utils::write.csv(result$score_source, score_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, group_source, score_source)
  }
  if (selected("figs1_sa_stability")) {
    result <- build_morris_stability(
      bundle$seed_rankings, bundle$stability, bundle$focus, profile, bundle$is_demo, lang = lang
    )
    base <- file.path(out_dir, if (bundle$is_demo) "DEMO_FigS1_sa_stability" else "FigS1_sa_stability")
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
      bundle$effects, bundle$focus, profile, bundle$is_demo, lang = lang
    )
    base <- file.path(out_dir, if (bundle$is_demo) "DEMO_FigS1b_sa_effects" else "FigS1b_sa_effects")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    effects_source <- paste0(base, ".effects_source.csv")
    utils::write.csv(result$effects_source, effects_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, effects_source)
  }

  # Task 1: Fig.S1 combined (stability + mu*-sigma in one figure, plan §9).
  if (selected("figs1_sa")) {
    if (!isTRUE(bundle$has_effects)) {
      stop("figs1_sa was requested but the bundle does not carry ",
           "morris_response_effects.csv. Rebuild the bundle with the W2 exporter.",
           call. = FALSE)
    }
    result <- build_morris_s1_combined(
      bundle$seed_rankings, bundle$stability, bundle$focus, bundle$effects,
      profile, bundle$is_demo, lang = lang
    )
    base <- file.path(out_dir, if (bundle$is_demo) "DEMO_FigS1_sa_combined" else "FigS1_sa_combined")
    artifacts <- c(artifacts, save_figure_set(
      result$plot, base, profile, profile$double_column_width_mm, result$height_mm
    ))
    for (suffix in c("rank_source", "stability_source", "effects_source")) {
      path <- paste0(base, ".", suffix, ".csv")
      utils::write.csv(result[[suffix]], path, row.names = FALSE, fileEncoding = "UTF-8")
      artifacts <- c(artifacts, path)
    }
  }

  # Task 2: Morris + Sobol summary composite (plan §9 Fig.1 alternative).
  if (selected("fig_sa_summary")) {
    sobol_effects <- NULL
    if (!is.null(args$sobol_effects_csv) && nzchar(args$sobol_effects_csv) && file.exists(args$sobol_effects_csv)) {
      sobol_effects <- utils::read.csv(args$sobol_effects_csv, stringsAsFactors = FALSE, check.names = FALSE)
    }
    result <- build_sa_summary(
      bundle$rankings, bundle$group_summary, bundle$focus, sobol_effects,
      profile, bundle$is_demo, lang = lang
    )
    base <- file.path(out_dir, if (bundle$is_demo) "DEMO_Fig_sa_summary" else "Fig_sa_summary")
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
    result <- build_morris_interaction(summary_data, profile, bundle$is_demo, lang = lang)
    base <- file.path(out_dir, if (bundle$is_demo) "DEMO_FigS1c_sa_interaction" else "FigS1c_sa_interaction")
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
      cross_summary, sobol_candidates, param_labels, profile, bundle$is_demo, lang = lang
    )
    base <- file.path(out_dir, if (bundle$is_demo) "DEMO_FigS1d_sa_selection" else "FigS1d_sa_selection")
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
                                      profile, bundle$is_demo, lang = lang)
    } else {
      build_sobol_multiseason_convergence(bundle$rankings, bundle$metrics, bundle$run_scale,
                                          bundle$summary, profile, bundle$is_demo)
    }
  } else {
    build_sobol_convergence(bundle$rankings, bundle$metrics, bundle$run_scale, profile, bundle$is_demo)
  }
  figure_stem <- if (isTRUE(bundle$has_effects)) "FigS2_sobol_effects" else "FigS2_sobol_convergence"
  base <- file.path(out_dir, if (bundle$is_demo) paste0("DEMO_", figure_stem) else figure_stem)
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
                                profile, bundle$is_demo, lang = lang)
  base <- file.path(out_dir, if (bundle$is_demo) "DEMO_FigS2_sobol_results" else "FigS2_sobol_results")
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
    result <- build_posterior_contraction(bundle$posterior, profile, bundle$is_demo)
    base <- file.path(out_dir, "DEMO_FigS5_posterior_contraction")
    artifacts <- c(artifacts, save_figure_set(result$plot, base, profile, profile$double_column_width_mm, result$height_mm))
    source_path <- paste0(base, ".source.csv"); utils::write.csv(result$source, source_path, row.names = FALSE)
    artifacts <- c(artifacts, source_path)
  }
  if (selected("figs6_spearman")) {
    result <- build_spearman_structure(bundle$spearman, profile, bundle$is_demo)
    base <- file.path(out_dir, "DEMO_FigS6_spearman_structure")
    artifacts <- c(artifacts, save_figure_set(result$plot, base, profile, profile$column_width_mm, result$height_mm))
    source_path <- paste0(base, ".source.csv"); utils::write.csv(result$source, source_path, row.names = FALSE)
    artifacts <- c(artifacts, source_path)
  }
  if (selected("figs7_equifinality")) {
    result <- build_candidate_prediction_distance(bundle$pair_predictions, profile, bundle$is_demo)
    base <- file.path(out_dir, "DEMO_FigS7_candidate_prediction_distance")
    artifacts <- c(artifacts, save_figure_set(result$plot, base, profile, profile$double_column_width_mm, result$height_mm))
    source_path <- paste0(base, ".source.csv"); utils::write.csv(result$source, source_path, row.names = FALSE)
    distance_path <- paste0(base, ".distance_source.csv"); utils::write.csv(result$distance_source, distance_path, row.names = FALSE)
    artifacts <- c(artifacts, source_path, distance_path)
  }
}

if (selected("fig3_performance")) {
  performance <- build_model_performance(bundle$comparison, variables, profile, bundle$is_demo)
  performance_base <- file.path(out_dir, paste0(stem, if (bundle$is_demo) "_model_performance" else "3_model_performance"))
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
  as.character(bundle$treatment_metadata$treatment)
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
  conditional_stem <- if (bundle$is_demo) "DEMO_conditional" else "conditional"
  if (selected("fig_model_performance_uncertainty")) {
    result <- build_model_performance_uncertainty(
      bundle$prediction, bundle$treatment_metadata, "DRY_CUM", profile, bundle$is_demo
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
      bundle$residual_members, bundle$treatment_metadata, "DRY_CUM",
      "terminal_relative_error_pct", profile, bundle$is_demo
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
      stringsAsFactors = FALSE
    )
    season_treatments <- frozen_selection[order(frozen_selection$display_order),
                                          c("season_id", "treatment")]
    process <- build_process_dynamics_conditional(
      bundle$prediction, bundle$trajectory, bundle$treatment_metadata,
      process_variables, season_treatments, profile, bundle$is_demo
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
      season_treatments, profile, bundle$is_demo
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
      all_variables, profile, bundle$is_demo
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
                                          variables, profile, bundle$is_demo)
  for (role in names(residuals)) {
    result <- residuals[[role]]
    residual_base <- file.path(out_dir, if (bundle$is_demo) {
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
                                    treatments, profile, bundle$is_demo)
  process_base <- file.path(out_dir, paste0(stem, if (bundle$is_demo) "_process_dynamics" else "4_process_dynamics"))
  artifacts <- c(artifacts, save_figure_set(process$plot, process_base, profile,
                                           profile$double_column_width_mm, process$height_mm))
  process_obs <- paste0(process_base, ".observations.csv")
  process_sim <- paste0(process_base, ".daily_simulation.csv")
  utils::write.csv(process$observations, process_obs, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(process$simulation, process_sim, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, process_obs, process_sim)

  harvest <- build_harvest_dynamics(bundle$comparison, bundle$treatment_metadata,
                                    "FRESH_INC", "FRESH_CUM", treatments,
                                    profile, bundle$is_demo)
  harvest_base <- file.path(out_dir, paste0(stem, if (bundle$is_demo) "_harvest_dynamics" else "4_harvest_dynamics"))
  artifacts <- c(artifacts, save_figure_set(harvest$plot, harvest_base, profile,
                                           profile$double_column_width_mm, harvest$height_mm))
  harvest_increment <- paste0(harvest_base, ".increment.csv")
  harvest_cumulative <- paste0(harvest_base, ".cumulative.csv")
  utils::write.csv(harvest$increment, harvest_increment, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(harvest$cumulative, harvest_cumulative, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, harvest_increment, harvest_cumulative)

  smooth <- build_cumulative_smooth(bundle$comparison, bundle$trajectory,
                                    bundle$treatment_metadata, "FRESH_CUM", treatments,
                                    profile, bundle$is_demo)
  smooth_base <- file.path(out_dir, paste0(stem, if (bundle$is_demo) "_cumulative_smooth" else "4_cumulative_smooth"))
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
    supplement_process_variables, supplement_treatments, profile, bundle$is_demo
  )
  for (variable in names(all_process)) {
    result <- all_process[[variable]]
    process_all_base <- file.path(out_dir, if (bundle$is_demo) {
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
    "FRESH_INC", "FRESH_CUM", supplement_treatments, profile, bundle$is_demo
  )
  for (kind in c("increment", "cumulative_event")) {
    result <- all_harvest[[kind]]
    harvest_all_base <- file.path(out_dir, if (bundle$is_demo) {
      paste0("DEMO_all_treatments_", kind)
    } else paste0("FigS4_all_treatments_", kind))
    artifacts <- c(artifacts, save_figure_set(result$plot, harvest_all_base, profile,
                                             profile$double_column_width_mm, result$height_mm))
    harvest_all_source <- paste0(harvest_all_base, ".source.csv")
    utils::write.csv(result$source, harvest_all_source, row.names = FALSE, fileEncoding = "UTF-8")
    artifacts <- c(artifacts, harvest_all_source)
  }
  smooth_all <- all_harvest$cumulative_smooth
  smooth_all_base <- file.path(out_dir, if (bundle$is_demo) {
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
  convergence <- build_phi_convergence(bundle$phi, profile, bundle$is_demo)
  convergence_base <- file.path(out_dir, paste0(stem, if (bundle$is_demo) "_phi_convergence" else "2_phi_convergence"))
  artifacts <- c(artifacts, save_figure_set(convergence$plot, convergence_base, profile,
                                           profile$column_width_mm, convergence$height_mm))
  convergence_source <- paste0(convergence_base, ".source.csv")
  convergence_summary <- paste0(convergence_base, ".summary.csv")
  utils::write.csv(convergence$source, convergence_source, row.names = FALSE, fileEncoding = "UTF-8")
  utils::write.csv(convergence$summary, convergence_summary, row.names = FALSE, fileEncoding = "UTF-8")
  artifacts <- c(artifacts, convergence_source, convergence_summary)
}

manifest <- list(
  schema_version = 2,
  created_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
  renderer = paste0("R ", getRversion()),
  package_versions = as.list(vapply(required_packages,
    function(package) as.character(utils::packageVersion(package)), character(1))),
  git_commit = trimws(system2("git", c("-C", shQuote(project_root), "rev-parse", "HEAD"),
                              stdout = TRUE, stderr = FALSE)[[1]]),
  git_dirty = length(system2("git", c("-C", shQuote(project_root), "status", "--porcelain"),
                             stdout = TRUE, stderr = FALSE)) > 0,
  profile_id = profile$profile_id,
  profile = sha256_record(profile_path),
  run_id = bundle$manifest$run_id,
  data_status = if (is_sa_request || is_sobol_request || is_conditional_request) bundle$manifest$data_status else if (bundle$is_demo) "legacy_layout_demo" else "science_validated",
  input_manifest = sha256_record(file.path(input_dir, "paper_data_manifest.json")),
  artifacts = lapply(artifacts, sha256_record)
)
manifest_path <- file.path(out_dir, "figure_manifest.json")
jsonlite::write_json(manifest, manifest_path, auto_unbox = TRUE, pretty = TRUE)
cat(normalizePath(manifest_path, winslash = "/", mustWork = TRUE), "\n")
