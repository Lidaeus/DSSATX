validate_sobol_columns <- function(data, required, table_name) {
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop(table_name, " missing: ", paste(missing, collapse = ", "))
  invisible(TRUE)
}

sobol_domain_label <- function(domain) {
  ifelse(domain == "general_genetic", "General genetic effects", "Water-nitrogen response")
}

build_sobol_convergence <- function(rankings, metrics, run_scale, profile, is_demo = FALSE) {
  if ("season" %in% names(metrics)) {
    stop("Use build_sobol_multiseason_convergence for multi-season Sobol evidence")
  }
  validate_sobol_columns(rankings, c("base_samples", "ranking_domain", "parameter", "score", "rank"),
                         "sobol_scale_rankings.csv")
  validate_sobol_columns(metrics, c("ranking_domain", "spearman", "top_k_jaccard",
                                    "max_top_k_rank_shift", "threshold_spearman",
                                    "threshold_top_k_jaccard", "threshold_max_top_k_rank_shift"),
                         "sobol_convergence_metrics.csv")
  validate_sobol_columns(run_scale, c("base_samples", "actual_model_runs"), "sobol_run_scale.csv")
  rankings$base_samples <- as.numeric(rankings$base_samples)
  rankings$rank <- as.numeric(rankings$rank)
  rankings$score <- as.numeric(rankings$score)
  samples <- sort(unique(rankings$base_samples))
  if (length(samples) != 2) stop("Sobol figure requires exactly two sample sizes")
  domains <- c("general_genetic", "water_nitrogen_response")
  if (!setequal(unique(rankings$ranking_domain), domains)) stop("Sobol rankings require both domains")

  # The union of the two Top-8 lists makes rank movement visible rather than
  # hiding candidates that entered or left at the larger sample size.
  selected_parameters <- do.call(rbind, lapply(domains, function(domain) {
    subset <- rankings[rankings$ranking_domain == domain & rankings$rank <= 8, , drop = FALSE]
    unique(subset[, c("ranking_domain", "parameter")])
  }))
  rank_data <- merge(rankings, selected_parameters, by = c("ranking_domain", "parameter"))
  rank_data$domain_label <- sobol_domain_label(rank_data$ranking_domain)
  parameter_order <- do.call(rbind, lapply(split(rank_data, rank_data$ranking_domain), function(part) {
    mean_rank <- aggregate(rank ~ parameter, data = part, FUN = mean)
    mean_rank[order(mean_rank$rank, mean_rank$parameter), ]
  }))
  # Preserve a deterministic ordering within separate facets.
  rank_data$parameter <- factor(rank_data$parameter, levels = unique(parameter_order$parameter))
  rank_end <- rank_data[rank_data$base_samples == max(samples), , drop = FALSE]
  rank_plot <- ggplot2::ggplot(rank_data, ggplot2::aes(base_samples, rank, group = parameter, colour = parameter)) +
    ggplot2::geom_line(linewidth = 0.65, alpha = 0.85) +
    ggplot2::geom_point(size = 2.0) +
    ggplot2::geom_text(data = rank_end, ggplot2::aes(x = base_samples + 9, label = parameter),
                       hjust = 0, size = 2.45, show.legend = FALSE) +
    ggplot2::scale_x_continuous(breaks = samples) +
    ggplot2::scale_y_reverse(breaks = c(1, 4, 8, 12), limits = c(12.5, 0.5)) +
    ggplot2::facet_wrap(~domain_label, scales = "free_y") +
    ggplot2::labs(title = "Top-8 membership changes with Sobol sample size",
                  subtitle = "Union of N=64 and N=128 Top-8 candidates; each line is one parameter",
                  x = "Base sample size (N)", y = "Rank (1 = larger aggregate total-order effect)") +
    theme_q1(profile) +
    ggplot2::coord_cartesian(xlim = c(min(samples) - 3, max(samples) + 32), clip = "off") +
    ggplot2::theme(legend.position = "none", plot.margin = ggplot2::margin(5.5, 45, 5.5, 5.5),
                   strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
                   strip.text = ggplot2::element_text(face = "bold"))

  metrics$domain_label <- sobol_domain_label(metrics$ranking_domain)
  metric_long <- rbind(
    data.frame(domain_label = metrics$domain_label, metric = "Spearman rho", value = as.numeric(metrics$spearman),
               threshold = as.numeric(metrics$threshold_spearman), direction = "minimum"),
    data.frame(domain_label = metrics$domain_label, metric = "Top-8 Jaccard", value = as.numeric(metrics$top_k_jaccard),
               threshold = as.numeric(metrics$threshold_top_k_jaccard), direction = "minimum"),
    data.frame(domain_label = metrics$domain_label, metric = "Maximum Top-8 rank shift", value = as.numeric(metrics$max_top_k_rank_shift),
               threshold = as.numeric(metrics$threshold_max_top_k_rank_shift), direction = "maximum")
  )
  metric_long$pass <- ifelse(metric_long$direction == "minimum", metric_long$value >= metric_long$threshold,
                             metric_long$value <= metric_long$threshold)
  metric_long$metric <- factor(metric_long$metric,
                               levels = c("Spearman rho", "Top-8 Jaccard", "Maximum Top-8 rank shift"))
  metric_plot <- ggplot2::ggplot(metric_long, ggplot2::aes(value, domain_label, colour = pass, shape = pass)) +
    ggplot2::geom_vline(ggplot2::aes(xintercept = threshold), linetype = 2, colour = "#666666", linewidth = 0.45) +
    ggplot2::geom_point(size = 2.5, stroke = 0.7) +
    ggplot2::facet_wrap(~metric, scales = "free_x", nrow = 1) +
    ggplot2::scale_colour_manual(values = c("TRUE" = profile$palette$positive, "FALSE" = profile$palette$negative),
                                 labels = c("Pass", "Not met")) +
    ggplot2::scale_shape_manual(values = c("TRUE" = 16, "FALSE" = 4), labels = c("Pass", "Not met")) +
    ggplot2::labs(title = "Prespecified N=64 to N=128 convergence checks",
                  subtitle = "Dashed line: required threshold; all displayed checks must pass before quantitative rank interpretation",
                  x = NULL, y = NULL) +
    theme_q1(profile) +
    ggplot2::theme(legend.position = "none", strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
                   strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.4))

  run_scale$base_samples <- as.numeric(run_scale$base_samples)
  run_scale$actual_model_runs <- as.numeric(run_scale$actual_model_runs)
  run_caption <- paste0("XXQL2501: N=", run_scale$base_samples, " (", run_scale$actual_model_runs, " model runs)", collapse = "; ")
  plot <- rank_plot / metric_plot +
    patchwork::plot_layout(heights = c(1.05, 0.75), guides = "collect") +
    patchwork::plot_annotation(
      tag_levels = "a",
      title = "Sobol screening: sample-size sensitivity is material at the current budget",
      subtitle = run_caption,
      caption = if (isTRUE(is_demo)) {
        "DEMO — convergence thresholds not met; use only as a transparent screening and numerical-uncertainty record"
      } else NULL,
      theme = ggplot2::theme(plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
                             plot.subtitle = ggplot2::element_text(colour = "#4D4D4D", size = profile$font_size_pt),
                             plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1),
                             plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt))
    )
  list(plot = plot, ranking_source = rank_data, metrics_source = metric_long,
       run_scale_source = run_scale, height_mm = 130)
}

build_sobol_multiseason_convergence <- function(rankings, metrics, run_scale, summary, profile, is_demo = TRUE) {
  validate_sobol_columns(summary, c("season", "evidence_status", "detail", "bootstrap_valid_fraction", "bootstrap_threshold"),
                         "sobol_stability_summary.csv")
  validate_sobol_columns(metrics, c("season", "ranking_domain", "spearman", "top_k_jaccard",
                                    "max_top_k_rank_shift", "threshold_spearman",
                                    "threshold_top_k_jaccard", "threshold_max_top_k_rank_shift", "passes"),
                         "sobol_convergence_metrics.csv")
  validate_sobol_columns(rankings, c("season", "base_samples", "ranking_domain", "parameter", "rank"),
                         "sobol_scale_rankings.csv")
  validate_sobol_columns(run_scale, c("season", "base_samples", "actual_model_runs"), "sobol_run_scale.csv")

  summary$status_label <- factor(
    summary$evidence_status,
    levels = c("converged", "rank_convergence_not_met", "bootstrap_resample_gate_not_met"),
    labels = c("Converged", "Rank gate\nnot met", "Bootstrap gate\nnot met")
  )
  summary$tile_value <- 1
  summary$display_label <- ifelse(
    is.na(summary$bootstrap_valid_fraction), as.character(summary$status_label),
    paste0(as.character(summary$status_label), "\n", sprintf("%.3f", as.numeric(summary$bootstrap_valid_fraction)),
           " < ", sprintf("%.2f", as.numeric(summary$bootstrap_threshold)))
  )
  status_plot <- ggplot2::ggplot(summary, ggplot2::aes(season, tile_value, fill = status_label)) +
    ggplot2::geom_tile(colour = "white", linewidth = 1.1) +
    ggplot2::geom_text(ggplot2::aes(label = display_label), size = 2.8, fontface = "bold") +
    ggplot2::scale_fill_manual(values = c("Converged" = profile$palette$positive,
                                          "Rank gate\nnot met" = "#D55E00",
                                          "Bootstrap gate\nnot met" = "#CC79A7")) +
    ggplot2::scale_y_continuous(limits = c(0.4, 1.6), breaks = NULL) +
    ggplot2::labs(title = "Season-specific Sobol numerical-evidence status", x = NULL, y = NULL, fill = NULL) +
    theme_q1(profile) + ggplot2::theme(legend.position = "bottom", axis.text.x = ggplot2::element_text(face = "bold"))

  metrics$domain_label <- sobol_domain_label(metrics$ranking_domain)
  metric_long <- rbind(
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = "Spearman rho",
               value = as.numeric(metrics$spearman), threshold = as.numeric(metrics$threshold_spearman),
               direction = "minimum", pass = as.logical(metrics$passes)),
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = "Top-8 Jaccard",
               value = as.numeric(metrics$top_k_jaccard), threshold = as.numeric(metrics$threshold_top_k_jaccard),
               direction = "minimum", pass = as.logical(metrics$passes)),
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = "Max Top-8 shift",
               value = as.numeric(metrics$max_top_k_rank_shift), threshold = as.numeric(metrics$threshold_max_top_k_rank_shift),
               direction = "maximum", pass = as.logical(metrics$passes))
  )
  metric_long$pass <- ifelse(metric_long$direction == "minimum", metric_long$value >= metric_long$threshold,
                             metric_long$value <= metric_long$threshold)
  metric_long$metric <- factor(metric_long$metric,
                               levels = c("Spearman rho", "Top-8 Jaccard", "Max Top-8 shift"))
  metric_plot <- ggplot2::ggplot(metric_long, ggplot2::aes(value, interaction(season, domain_label, sep = " — "), colour = pass, shape = pass)) +
    ggplot2::geom_vline(ggplot2::aes(xintercept = threshold), linetype = 2, colour = "#666666", linewidth = 0.4) +
    ggplot2::geom_point(size = 2.15, stroke = 0.6) +
    ggplot2::facet_wrap(~metric, scales = "free_x", nrow = 1) +
    ggplot2::scale_colour_manual(values = c("TRUE" = profile$palette$positive, "FALSE" = profile$palette$negative)) +
    ggplot2::scale_shape_manual(values = c("TRUE" = 16, "FALSE" = 4)) +
    ggplot2::labs(title = "N=128 to N=256 prespecified convergence checks",
                  subtitle = "Dashed line: required threshold; XXQL2501 is shown above because its bootstrap gate stopped this comparison",
                  x = NULL, y = NULL) +
    theme_q1(profile) + ggplot2::theme(legend.position = "none",
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      axis.text.y = ggplot2::element_text(size = profile$font_size_pt - 1.2))

  rank_data <- do.call(rbind, lapply(split(rankings, interaction(rankings$season, rankings$ranking_domain, drop = TRUE)), function(part) {
    selected <- unique(part[part$rank <= 8, c("season", "ranking_domain", "parameter")])
    merge(part, selected, by = c("season", "ranking_domain", "parameter"))
  }))
  rank_data$base_samples <- as.numeric(rank_data$base_samples)
  rank_data$rank <- as.numeric(rank_data$rank)
  rank_data$domain_panel <- ifelse(rank_data$ranking_domain == "general_genetic", "Genetic", "W-N response")
  rank_end <- rank_data[rank_data$base_samples == max(rank_data$base_samples), , drop = FALSE]
  rank_plot <- ggplot2::ggplot(rank_data, ggplot2::aes(base_samples, rank, group = parameter, colour = parameter)) +
    ggplot2::geom_line(linewidth = 0.5, alpha = 0.85) + ggplot2::geom_point(size = 1.65) +
    ggplot2::geom_text(data = rank_end, ggplot2::aes(x = base_samples + 10, label = parameter),
                       hjust = 0, size = 2.0, show.legend = FALSE) +
    ggplot2::scale_y_reverse(breaks = c(1, 4, 8, 12), limits = c(12.5, 0.5)) +
    ggplot2::facet_grid(rows = ggplot2::vars(domain_panel), cols = ggplot2::vars(season), scales = "free_y") +
    ggplot2::labs(title = "Top-8 union rank movement at the two completed seasonal comparisons",
                  subtitle = "Each facet contains the union of its N=128 and N=256 Top-8 parameter lists",
                  x = "Base sample size (N)", y = "Rank (1 = larger aggregate total-order effect)") +
    theme_q1(profile) + ggplot2::coord_cartesian(xlim = c(124, 295), clip = "off") +
    ggplot2::theme(legend.position = "none", plot.margin = ggplot2::margin(5.5, 33, 5.5, 5.5),
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.7))

  plot <- status_plot / rank_plot / metric_plot +
    patchwork::plot_layout(heights = c(0.36, 1.0, 0.70), guides = "collect") +
    patchwork::plot_annotation(tag_levels = "a",
      title = "Sobol screening: expanded sample-size checks remain season dependent",
      caption = "DEMO — pooled Sobol ranking is science pending: only XXQL2502 passed all prespecified checks; no interaction-strength inference is made",
      theme = ggplot2::theme(plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)))
  list(plot = plot, ranking_source = rank_data, metrics_source = metric_long,
       run_scale_source = run_scale, summary_source = summary, height_mm = 165)
}

build_sobol_multiseason_effects <- function(rankings, metrics, run_scale, summary, effects,
                                            response_scales, profile, is_demo = TRUE) {
  validate_sobol_columns(summary, c("season", "evidence_status", "bootstrap_valid_fraction", "bootstrap_threshold"),
                         "sobol_stability_summary.csv")
  validate_sobol_columns(metrics, c("season", "ranking_domain", "spearman", "top_k_jaccard",
                                    "max_top_k_rank_shift", "threshold_spearman",
                                    "threshold_top_k_jaccard", "threshold_max_top_k_rank_shift", "passes"),
                         "sobol_convergence_metrics.csv")
  validate_sobol_columns(effects, c("season", "response_id", "response_label", "parameter", "S1",
                                    "S1_ci_low", "S1_ci_high", "ST", "ST_ci_low", "ST_ci_high",
                                    "interaction_remainder", "interaction_ci_low", "interaction_ci_high",
                                    "interaction_supported", "total_effect_rank", "display_in_figure"),
                         "sobol_effect_decomposition.csv")
  validate_sobol_columns(response_scales, c("season", "response_id", "response_sd", "unit", "component_count"),
                         "sobol_response_scales.csv")

  summary$status_label <- factor(
    summary$evidence_status,
    levels = c("converged", "rank_convergence_not_met", "bootstrap_resample_gate_not_met"),
    labels = c("Converged", "Rank gate\nnot met", "Bootstrap gate\nnot met")
  )
  summary$tile_value <- 1
  summary$display_label <- ifelse(
    is.na(summary$bootstrap_valid_fraction), as.character(summary$status_label),
    paste0(as.character(summary$status_label), "\n", sprintf("%.3f", as.numeric(summary$bootstrap_valid_fraction)),
           " < ", sprintf("%.2f", as.numeric(summary$bootstrap_threshold)))
  )
  status_plot <- ggplot2::ggplot(summary, ggplot2::aes(season, tile_value, fill = status_label)) +
    ggplot2::geom_tile(colour = "white", linewidth = 1.0) +
    ggplot2::geom_text(ggplot2::aes(label = display_label), size = 2.7, fontface = "bold") +
    ggplot2::scale_fill_manual(values = c("Converged" = profile$palette$positive,
                                          "Rank gate\nnot met" = "#D55E00",
                                          "Bootstrap gate\nnot met" = "#CC79A7")) +
    ggplot2::scale_y_continuous(limits = c(0.4, 1.6), breaks = NULL) +
    ggplot2::labs(title = "Numerical evidence is season specific", x = NULL, y = NULL, fill = NULL) +
    theme_q1(profile) +
    ggplot2::theme(legend.position = "none", axis.text.x = ggplot2::element_text(face = "bold"))

  effects$display_in_figure <- as.logical(effects$display_in_figure)
  effects$interaction_supported <- as.logical(effects$interaction_supported)
  effects$total_effect_rank <- as.numeric(effects$total_effect_rank)
  effect_source <- effects[effects$display_in_figure & effects$total_effect_rank <= 3, , drop = FALSE]
  effect_source <- effect_source[order(effect_source$response_id, -effect_source$total_effect_rank), , drop = FALSE]
  effect_source$parameter_key <- paste(effect_source$response_id, effect_source$parameter, sep = "___")
  effect_source$parameter_key <- factor(effect_source$parameter_key, levels = unique(effect_source$parameter_key))
  effect_long <- rbind(
    data.frame(effect_source[, c("season", "response_id", "response_label", "parameter", "parameter_key")],
               index = "First order (S1)", estimate = as.numeric(effect_source$S1),
               ci_low = as.numeric(effect_source$S1_ci_low), ci_high = as.numeric(effect_source$S1_ci_high)),
    data.frame(effect_source[, c("season", "response_id", "response_label", "parameter", "parameter_key")],
               index = "Total effect (ST)", estimate = as.numeric(effect_source$ST),
               ci_low = as.numeric(effect_source$ST_ci_low), ci_high = as.numeric(effect_source$ST_ci_high))
  )
  effect_long$index <- factor(effect_long$index, levels = c("First order (S1)", "Total effect (ST)"))
  effect_plot <- ggplot2::ggplot() +
    ggplot2::geom_vline(xintercept = 0, linetype = 1, colour = "#BDBDBD", linewidth = 0.35) +
    ggplot2::geom_vline(xintercept = 1, linetype = 3, colour = "#BDBDBD", linewidth = 0.35) +
    ggplot2::geom_segment(data = effect_source,
      ggplot2::aes(x = S1, xend = ST, y = parameter_key, yend = parameter_key,
                   colour = interaction_supported), linewidth = 1.0, alpha = 0.55) +
    ggplot2::geom_errorbar(data = effect_long,
      ggplot2::aes(y = parameter_key, xmin = ci_low, xmax = ci_high, colour = index),
      width = 0.14, linewidth = 0.38, orientation = "y",
      position = ggplot2::position_dodge(width = 0.34)) +
    ggplot2::geom_point(data = effect_long,
      ggplot2::aes(x = estimate, y = parameter_key, fill = index, shape = index),
      size = 2.0, stroke = 0.55, position = ggplot2::position_dodge(width = 0.34), colour = "#222222") +
    ggplot2::facet_wrap(~response_label, ncol = 2, scales = "free_y") +
    ggplot2::scale_y_discrete(labels = function(value) sub("^.*___", "", value)) +
    ggplot2::scale_colour_manual(values = c(
      "FALSE" = "#BDBDBD", "TRUE" = "#7B3294",
      "First order (S1)" = "#0072B2", "Total effect (ST)" = "#D55E00"
    ), guide = "none") +
    ggplot2::scale_fill_manual(values = c("First order (S1)" = "white", "Total effect (ST)" = "#D55E00")) +
    ggplot2::scale_shape_manual(values = c("First order (S1)" = 21, "Total effect (ST)" = 21)) +
    ggplot2::labs(title = "First-order and total effects for fixed scalar responses (XXQL2502, N=256)",
      subtitle = "Top three by ST; bars are 95% paired-bootstrap intervals. Purple segments: ST-S1 interval excludes zero.",
      x = "Sobol sensitivity index", y = NULL, fill = NULL, shape = NULL) +
    theme_q1(profile) +
    ggplot2::theme(legend.position = "bottom", legend.box = "horizontal",
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.8),
      axis.text.y = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 1.0))

  metrics$domain_label <- sobol_domain_label(metrics$ranking_domain)
  metric_long <- rbind(
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = "Spearman rho",
               value = as.numeric(metrics$spearman), threshold = as.numeric(metrics$threshold_spearman), direction = "minimum"),
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = "Top-8 Jaccard",
               value = as.numeric(metrics$top_k_jaccard), threshold = as.numeric(metrics$threshold_top_k_jaccard), direction = "minimum"),
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = "Max Top-8 shift",
               value = as.numeric(metrics$max_top_k_rank_shift), threshold = as.numeric(metrics$threshold_max_top_k_rank_shift), direction = "maximum")
  )
  metric_long$pass <- ifelse(metric_long$direction == "minimum", metric_long$value >= metric_long$threshold,
                             metric_long$value <= metric_long$threshold)
  metric_long$metric <- factor(metric_long$metric, levels = c("Spearman rho", "Top-8 Jaccard", "Max Top-8 shift"))
  metric_plot <- ggplot2::ggplot(metric_long,
      ggplot2::aes(value, interaction(season, domain_label, sep = " — "), colour = pass, shape = pass)) +
    ggplot2::geom_vline(ggplot2::aes(xintercept = threshold), linetype = 2, colour = "#666666", linewidth = 0.4) +
    ggplot2::geom_point(size = 2.1, stroke = 0.6) +
    ggplot2::facet_wrap(~metric, scales = "free_x", nrow = 1) +
    ggplot2::scale_colour_manual(values = c("TRUE" = profile$palette$positive, "FALSE" = profile$palette$negative)) +
    ggplot2::scale_shape_manual(values = c("TRUE" = 16, "FALSE" = 4)) +
    ggplot2::labs(title = "N=128 to N=256 prespecified rank-convergence checks",
                  subtitle = "Dashed line: threshold; XXQL2501 stopped at the bootstrap-resample gate", x = NULL, y = NULL) +
    theme_q1(profile) + ggplot2::theme(legend.position = "none",
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      axis.text.y = ggplot2::element_text(size = profile$font_size_pt - 1.2))

  plot <- status_plot / effect_plot / metric_plot +
    patchwork::plot_layout(heights = c(0.27, 1.35, 0.55), guides = "keep") +
    patchwork::plot_annotation(tag_levels = "a",
      title = "Sobol effects and their numerical support are response- and season-dependent",
      caption = "DEMO — S1 is the main-effect fraction; ST includes all interactions. ST-S1 is an aggregate interaction-involving remainder, not a pairwise interaction. Quantitative decomposition is restricted to convergence-validated XXQL2502.",
      theme = ggplot2::theme(plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)))
  list(plot = plot, ranking_source = rankings, metrics_source = metric_long,
       run_scale_source = run_scale, summary_source = summary, effects_source = effect_source,
       response_scales_source = response_scales, height_mm = 170)
}
