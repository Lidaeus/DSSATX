validate_sobol_columns <- function(data, required, table_name) {
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop(table_name, " missing: ", paste(missing, collapse = ", "))
  invisible(TRUE)
}

sobol_domain_label <- function(domain, lang = SA_DEFAULT_LANG) {
  ifelse(domain == "general_genetic", sa_t("shared.domain_general_genetic", lang), sa_t("shared.domain_wn_response", lang))
}

build_sobol_convergence <- function(rankings, metrics, run_scale, profile, is_demo = FALSE, lang = SA_DEFAULT_LANG) {
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
  rank_data$domain_label <- sobol_domain_label(rank_data$ranking_domain, lang)
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
    ggplot2::labs(title = sa_t("sobol_conv.rank_title", lang),
                  subtitle = sa_t("sobol_conv.rank_subtitle", lang),
                  x = sa_t("sobol_conv.rank_x", lang), y = sa_t("sobol_conv.rank_y", lang)) +
    theme_q1(profile) +
    ggplot2::coord_cartesian(xlim = c(min(samples) - 3, max(samples) + 32), clip = "off") +
    ggplot2::theme(legend.position = "none", plot.margin = ggplot2::margin(5.5, 45, 5.5, 5.5),
                   strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
                   strip.text = ggplot2::element_text(face = "bold"))

  metrics$domain_label <- sobol_domain_label(metrics$ranking_domain, lang)
  metric_long <- rbind(
    data.frame(domain_label = metrics$domain_label, metric = sa_t("metric.spearman_rho", lang), value = as.numeric(metrics$spearman),
               threshold = as.numeric(metrics$threshold_spearman), direction = "minimum"),
    data.frame(domain_label = metrics$domain_label, metric = sa_t("metric.top8_jaccard", lang), value = as.numeric(metrics$top_k_jaccard),
               threshold = as.numeric(metrics$threshold_top_k_jaccard), direction = "minimum"),
    data.frame(domain_label = metrics$domain_label, metric = sa_t("metric.max_top8_shift_long", lang), value = as.numeric(metrics$max_top_k_rank_shift),
               threshold = as.numeric(metrics$threshold_max_top_k_rank_shift), direction = "maximum")
  )
  metric_long$pass <- ifelse(metric_long$direction == "minimum", metric_long$value >= metric_long$threshold,
                             metric_long$value <= metric_long$threshold)
  metric_long$metric <- factor(metric_long$metric,
                               levels = c(sa_t("metric.spearman_rho", lang), sa_t("metric.top8_jaccard", lang), sa_t("metric.max_top8_shift_long", lang)))
  metric_plot <- ggplot2::ggplot(metric_long, ggplot2::aes(value, domain_label, colour = pass, shape = pass)) +
    ggplot2::geom_vline(ggplot2::aes(xintercept = threshold), linetype = 2, colour = "#666666", linewidth = 0.45) +
    ggplot2::geom_point(size = 2.5, stroke = 0.7) +
    ggplot2::facet_wrap(~metric, scales = "free_x", nrow = 1) +
    ggplot2::scale_colour_manual(values = c("TRUE" = profile$palette$positive, "FALSE" = profile$palette$negative),
                                 labels = c(sa_t("shared.pass", lang), sa_t("shared.not_met", lang))) +
    ggplot2::scale_shape_manual(values = c("TRUE" = 16, "FALSE" = 4), labels = c(sa_t("shared.pass", lang), sa_t("shared.not_met", lang))) +
    ggplot2::labs(title = sa_t("sobol_conv.metric_title", lang),
                  subtitle = sa_t("sobol_conv.metric_subtitle", lang),
                  x = NULL, y = NULL) +
    theme_q1(profile) +
    ggplot2::theme(legend.position = "none", strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
                   strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.4))

  run_scale$base_samples <- as.numeric(run_scale$base_samples)
  run_scale$actual_model_runs <- as.numeric(run_scale$actual_model_runs)
  run_caption <- paste(sa_tf("sobol_conv.run_caption", lang, run_scale$base_samples, run_scale$actual_model_runs), collapse = "; ")
  plot <- rank_plot / metric_plot +
    patchwork::plot_layout(heights = c(1.05, 0.75), guides = "collect") +
    patchwork::plot_annotation(
      tag_levels = "a",
      title = sa_t("sobol_conv.title", lang),
      subtitle = run_caption,
      caption = if (isTRUE(is_demo)) {
        sa_t("sobol_conv.demo_caption", lang)
      } else NULL,
      theme = ggplot2::theme(plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
                             plot.subtitle = ggplot2::element_text(colour = "#4D4D4D", size = profile$font_size_pt),
                             plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1),
                             plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt))
    )
  list(plot = plot, ranking_source = rank_data, metrics_source = metric_long,
       run_scale_source = run_scale, height_mm = 130)
}

build_sobol_multiseason_convergence <- function(rankings, metrics, run_scale, summary, profile, is_demo = TRUE, lang = SA_DEFAULT_LANG) {
  validate_sobol_columns(summary, c("season", "evidence_status", "detail", "bootstrap_valid_fraction", "bootstrap_threshold"),
                         "sobol_stability_summary.csv")
  validate_sobol_columns(metrics, c("season", "ranking_domain", "spearman", "top_k_jaccard",
                                    "max_top_k_rank_shift", "threshold_spearman",
                                    "threshold_top_k_jaccard", "threshold_max_top_k_rank_shift", "passes"),
                         "sobol_convergence_metrics.csv")
  validate_sobol_columns(rankings, c("season", "base_samples", "ranking_domain", "parameter", "rank"),
                         "sobol_scale_rankings.csv")
  validate_sobol_columns(run_scale, c("season", "base_samples", "actual_model_runs"), "sobol_run_scale.csv")

  sobol_status_levels <- c("converged", "rank_convergence_not_met", "bootstrap_resample_gate_not_met")
  sobol_status_labels <- c(sa_t("shared.converged", lang), sa_t("shared.rank_gate_not_met", lang), sa_t("shared.bootstrap_gate_not_met", lang))
  summary$status_label <- factor(
    summary$evidence_status,
    levels = sobol_status_levels,
    labels = sobol_status_labels
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
    ggplot2::scale_fill_manual(values = setNames(
      c(profile$palette$positive, "#D55E00", "#CC79A7"),
      sobol_status_labels
    )) +
    ggplot2::scale_y_continuous(limits = c(0.4, 1.6), breaks = NULL) +
    ggplot2::labs(title = sa_t("sobol_ms_conv.status_title", lang), x = NULL, y = NULL, fill = NULL) +
    theme_q1(profile) + ggplot2::theme(legend.position = "bottom", axis.text.x = ggplot2::element_text(face = "bold"))

  metrics$domain_label <- sobol_domain_label(metrics$ranking_domain, lang)
  metric_long <- rbind(
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = sa_t("metric.spearman_rho", lang),
               value = as.numeric(metrics$spearman), threshold = as.numeric(metrics$threshold_spearman),
               direction = "minimum", pass = as.logical(metrics$passes)),
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = sa_t("metric.top8_jaccard", lang),
               value = as.numeric(metrics$top_k_jaccard), threshold = as.numeric(metrics$threshold_top_k_jaccard),
               direction = "minimum", pass = as.logical(metrics$passes)),
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = sa_t("metric.max_top8_shift_short", lang),
               value = as.numeric(metrics$max_top_k_rank_shift), threshold = as.numeric(metrics$threshold_max_top_k_rank_shift),
               direction = "maximum", pass = as.logical(metrics$passes))
  )
  metric_long$pass <- ifelse(metric_long$direction == "minimum", metric_long$value >= metric_long$threshold,
                             metric_long$value <= metric_long$threshold)
  metric_long$metric <- factor(metric_long$metric,
                               levels = c(sa_t("metric.spearman_rho", lang), sa_t("metric.top8_jaccard", lang), sa_t("metric.max_top8_shift_short", lang)))
  metric_plot <- ggplot2::ggplot(metric_long, ggplot2::aes(value, interaction(season, domain_label, sep = " — "), colour = pass, shape = pass)) +
    ggplot2::geom_vline(ggplot2::aes(xintercept = threshold), linetype = 2, colour = "#666666", linewidth = 0.4) +
    ggplot2::geom_point(size = 2.15, stroke = 0.6) +
    ggplot2::facet_wrap(~metric, scales = "free_x", nrow = 1) +
    ggplot2::scale_colour_manual(values = c("TRUE" = profile$palette$positive, "FALSE" = profile$palette$negative)) +
    ggplot2::scale_shape_manual(values = c("TRUE" = 16, "FALSE" = 4)) +
    ggplot2::labs(title = sa_t("sobol_ms_conv.metric_title", lang),
                  subtitle = sa_t("sobol_ms_conv.metric_subtitle", lang),
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
  rank_data$domain_panel <- ifelse(rank_data$ranking_domain == "general_genetic", sa_t("shared.panel_genetic", lang), sa_t("shared.panel_wn_response", lang))
  rank_end <- rank_data[rank_data$base_samples == max(rank_data$base_samples), , drop = FALSE]
  rank_plot <- ggplot2::ggplot(rank_data, ggplot2::aes(base_samples, rank, group = parameter, colour = parameter)) +
    ggplot2::geom_line(linewidth = 0.5, alpha = 0.85) + ggplot2::geom_point(size = 1.65) +
    ggplot2::geom_text(data = rank_end, ggplot2::aes(x = base_samples + 10, label = parameter),
                       hjust = 0, size = 2.0, show.legend = FALSE) +
    ggplot2::scale_y_reverse(breaks = c(1, 4, 8, 12), limits = c(12.5, 0.5)) +
    ggplot2::facet_grid(rows = ggplot2::vars(domain_panel), cols = ggplot2::vars(season), scales = "free_y") +
    ggplot2::labs(title = sa_t("sobol_ms_conv.rank_title", lang),
                  subtitle = sa_t("sobol_ms_conv.rank_subtitle", lang),
                  x = sa_t("sobol_ms_conv.rank_x", lang), y = sa_t("sobol_ms_conv.rank_y", lang)) +
    theme_q1(profile) + ggplot2::coord_cartesian(xlim = c(124, 295), clip = "off") +
    ggplot2::theme(legend.position = "none", plot.margin = ggplot2::margin(5.5, 33, 5.5, 5.5),
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.7))

  plot <- status_plot / rank_plot / metric_plot +
    patchwork::plot_layout(heights = c(0.36, 1.0, 0.70), guides = "collect") +
    patchwork::plot_annotation(tag_levels = "a",
      title = sa_t("sobol_ms_conv.title", lang),
      caption = sa_t("sobol_ms_conv.caption", lang),
      theme = ggplot2::theme(plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 0),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)))
  list(plot = plot, ranking_source = rank_data, metrics_source = metric_long,
       run_scale_source = run_scale, summary_source = summary, height_mm = 165)
}

build_sobol_multiseason_effects <- function(rankings, metrics, run_scale, summary, effects,
                                            response_scales, profile, is_demo = TRUE, lang = SA_DEFAULT_LANG) {
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

  sobol_status_levels <- c("converged", "rank_convergence_not_met", "bootstrap_resample_gate_not_met")
  sobol_status_labels <- c(sa_t("shared.converged", lang), sa_t("shared.rank_gate_not_met", lang), sa_t("shared.bootstrap_gate_not_met", lang))
  summary$status_label <- factor(
    summary$evidence_status,
    levels = sobol_status_levels,
    labels = sobol_status_labels
  )
  summary$tile_value <- 1
  summary$display_label <- ifelse(
    is.na(summary$bootstrap_valid_fraction), as.character(summary$status_label),
    paste0(as.character(summary$status_label), "\n", sprintf("%.3f", as.numeric(summary$bootstrap_valid_fraction)),
           " < ", sprintf("%.2f", as.numeric(summary$bootstrap_threshold)))
  )
  # Evidence status is a validity annotation, not an effect magnitude. Keep
  # this strip neutral and use marker shape/text for the gate result.
  status_plot <- ggplot2::ggplot(summary, ggplot2::aes(season, tile_value)) +
    ggplot2::geom_tile(fill = "#F7F7F7", colour = "#BDBDBD", linewidth = 0.55) +
    ggplot2::geom_point(ggplot2::aes(shape = status_label), size = 2.5,
                        colour = "#222222", stroke = 0.7) +
    ggplot2::geom_text(ggplot2::aes(label = display_label), nudge_y = -0.22,
                       size = 2.35, lineheight = 0.9) +
    ggplot2::scale_shape_manual(values = stats::setNames(c(16, 1, 4), sobol_status_labels), guide = "none") +
    ggplot2::scale_y_continuous(limits = c(0.4, 1.6), breaks = NULL) +
    ggplot2::labs(title = sa_t("sobol_ms_eff.status_title", lang), x = NULL, y = NULL, fill = NULL) +
    theme_q1(profile) +
    ggplot2::theme(legend.position = "none", axis.text.x = ggplot2::element_text(face = "bold"))

  effects$display_in_figure <- as.logical(effects$display_in_figure)
  effects$interaction_supported <- as.logical(effects$interaction_supported)
  effects$total_effect_rank <- as.numeric(effects$total_effect_rank)
  effect_source <- effects[effects$display_in_figure & effects$total_effect_rank <= 3, , drop = FALSE]
  effect_source <- effect_source[order(effect_source$response_id, -effect_source$total_effect_rank), , drop = FALSE]
  response_scales$display_response_label <- ifelse(
    response_scales$response_id == "fruitd_end_mean",
    "Season-end cumulative harvested dry mass",
    response_scales$response_label
  )
  response_scales$scale_label <- paste0(
    response_scales$display_response_label,
    "\nSD = ", formatC(as.numeric(response_scales$response_sd), format = "fg", digits = 4),
    " ", response_scales$unit
  )
  effect_source <- merge(
    effect_source,
    response_scales[, c("season", "response_id", "scale_label")],
    by = c("season", "response_id"), all.x = TRUE, sort = FALSE
  )
  # Keep the y key as character, not a global factor. With free y scales this
  # lets each response facet retain only its own three displayed parameters.
  effect_source$parameter_key <- paste(effect_source$response_id, effect_source$parameter, sep = "___")
  sobol_index_labels <- c(sa_t("sobol.first_order_s1", lang), sa_t("sobol.total_effect_st", lang))
  effect_long <- rbind(
    data.frame(effect_source[, c("season", "response_id", "response_label", "scale_label", "parameter", "parameter_key")],
               index = sa_t("sobol.first_order_s1", lang), estimate = as.numeric(effect_source$S1),
               ci_low = as.numeric(effect_source$S1_ci_low), ci_high = as.numeric(effect_source$S1_ci_high)),
    data.frame(effect_source[, c("season", "response_id", "response_label", "scale_label", "parameter", "parameter_key")],
               index = sa_t("sobol.total_effect_st", lang), estimate = as.numeric(effect_source$ST),
               ci_low = as.numeric(effect_source$ST_ci_low), ci_high = as.numeric(effect_source$ST_ci_high))
  )
  effect_long$index <- factor(effect_long$index, levels = sobol_index_labels)
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
    ggplot2::geom_text(data = effect_source,
      ggplot2::aes(x = -0.30, y = parameter_key, label = parameter),
      inherit.aes = FALSE, hjust = 0, size = 2.0, colour = "#333333") +
    ggplot2::facet_wrap(~scale_label, ncol = 2, scales = "free_y") +
    ggplot2::scale_y_discrete(labels = NULL) +
    ggplot2::coord_cartesian(clip = "off") +
    ggplot2::scale_colour_manual(values = c(setNames(c("#BDBDBD", "#7B3294"), c("FALSE", "TRUE")),
                                            setNames(c("#0072B2", "#D55E00"), sobol_index_labels)),
                                 guide = "none") +
    ggplot2::scale_fill_manual(values = setNames(c("white", "#D55E00"), sobol_index_labels)) +
    ggplot2::scale_shape_manual(values = setNames(c(21, 21), sobol_index_labels)) +
    ggplot2::labs(title = sa_t("sobol_ms_eff.effect_title", lang),
      subtitle = sa_t("sobol_ms_eff.effect_subtitle", lang),
      x = sa_t("sobol_ms_eff.effect_x", lang), y = NULL, fill = NULL, shape = NULL) +
    theme_q1(profile) +
    ggplot2::theme(legend.position = "bottom", legend.box = "horizontal",
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.8),
      axis.text.y = ggplot2::element_blank(), axis.ticks.y = ggplot2::element_blank())

  metrics$domain_label <- sobol_domain_label(metrics$ranking_domain, lang)
  metric_long <- rbind(
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = sa_t("metric.spearman_rho", lang),
               value = as.numeric(metrics$spearman), threshold = as.numeric(metrics$threshold_spearman), direction = "minimum"),
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = sa_t("metric.top8_jaccard", lang),
               value = as.numeric(metrics$top_k_jaccard), threshold = as.numeric(metrics$threshold_top_k_jaccard), direction = "minimum"),
    data.frame(season = metrics$season, domain_label = metrics$domain_label, metric = sa_t("metric.max_top8_shift_short", lang),
               value = as.numeric(metrics$max_top_k_rank_shift), threshold = as.numeric(metrics$threshold_max_top_k_rank_shift), direction = "maximum")
  )
  metric_long$pass <- ifelse(metric_long$direction == "minimum", metric_long$value >= metric_long$threshold,
                             metric_long$value <= metric_long$threshold)
  metric_long$metric <- factor(metric_long$metric, levels = c(sa_t("metric.spearman_rho", lang), sa_t("metric.top8_jaccard", lang), sa_t("metric.max_top8_shift_short", lang)))
  metric_plot <- ggplot2::ggplot(metric_long,
      ggplot2::aes(value, interaction(season, domain_label, sep = " — "), colour = pass, shape = pass)) +
    ggplot2::geom_vline(ggplot2::aes(xintercept = threshold), linetype = 2, colour = "#666666", linewidth = 0.4) +
    ggplot2::geom_point(size = 2.1, stroke = 0.6, colour = "#222222") +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.2f", value)),
                       nudge_y = 0.18, size = 2.15, colour = "#333333") +
    ggplot2::facet_wrap(~metric, scales = "free_x", nrow = 1) +
    ggplot2::scale_shape_manual(values = c("TRUE" = 16, "FALSE" = 1), guide = "none") +
    ggplot2::labs(title = sa_t("sobol_ms_eff.metric_title", lang),
                  subtitle = sa_t("sobol_ms_eff.metric_subtitle", lang), x = NULL, y = NULL) +
    theme_q1(profile) + ggplot2::theme(legend.position = "none",
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      axis.text.y = ggplot2::element_text(size = profile$font_size_pt - 1.2))

  plot <- status_plot / effect_plot / metric_plot +
    patchwork::plot_layout(heights = c(0.28, 1.40, 0.62), guides = "keep") +
    patchwork::plot_annotation(tag_levels = "a",
      title = sa_t("sobol_ms_eff.title", lang),
      caption = sa_t("sobol_ms_eff.caption", lang),
      theme = ggplot2::theme(plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)))
  list(plot = plot, ranking_source = rankings, metrics_source = metric_long,
       run_scale_source = run_scale, summary_source = summary, effects_source = effect_source,
       response_scales_source = response_scales, height_mm = 170)
}

# ---------------------------------------------------------------------------
# Results-first Sobol figure.
#
# This is the scientific result view: one small multiple per displayed scalar
# response, with the Top-3 parameters by ST and paired S1/ST intervals. Status
# and sample-size diagnostics remain in the bound source tables and diagnostic
# figure, rather than competing with the effect decomposition here.
# ---------------------------------------------------------------------------

sobol_response_display_label <- function(response_id, response_label, lang = SA_DEFAULT_LANG) {
  labels_en <- c(
    anthesis_mean = "Anthesis", lai_auc_mean = "Canopy (LAI AUC)",
    agb_end_mean = "Aboveground biomass", fruitd_end_mean = "Season-end cumulative harvested dry mass",
    water_fruitd_mean = "Water response: fruit mass", nitrogen_fruitd_mean = "N response: fruit mass",
    wn_interaction_fruitd = "W×N interaction: fruit mass"
  )
  labels_zh <- c(
    anthesis_mean = "开花期", lai_auc_mean = "冠层（LAI AUC）",
    agb_end_mean = "季末地上部生物量", fruitd_end_mean = "季末累计收获果实干重",
    water_fruitd_mean = "水分效应：果实干重", nitrogen_fruitd_mean = "氮响应：果实干重",
    wn_interaction_fruitd = "水×氮交互：果实干重"
  )
  labels <- if (identical(lang, "zh")) labels_zh else labels_en
  out <- unname(labels[as.character(response_id)])
  out[is.na(out)] <- as.character(response_label)[is.na(out)]
  out
}

build_sobol_results <- function(effects, response_scales, profile,
                                is_demo = TRUE, top_k = 3,
                                lang = SA_DEFAULT_LANG) {
  validate_sobol_columns(effects,
                         c("season", "response_id", "response_label", "parameter",
                           "S1", "S1_ci_low", "S1_ci_high", "ST", "ST_ci_low",
                           "ST_ci_high", "interaction_supported", "total_effect_rank",
                           "display_in_figure"),
                         "sobol_effect_decomposition.csv")
  validate_sobol_columns(response_scales,
                         c("season", "response_id", "response_label", "unit",
                           "response_sd", "display_in_figure"),
                         "sobol_response_scales.csv")
  effects$display_in_figure <- as.logical(effects$display_in_figure)
  effects$interaction_supported <- as.logical(effects$interaction_supported)
  effects$total_effect_rank <- as.numeric(effects$total_effect_rank)
  source <- effects[effects$display_in_figure & effects$total_effect_rank <= top_k, , drop = FALSE]
  source <- source[order(source$response_id, source$total_effect_rank), , drop = FALSE]
  if (nrow(source) == 0) stop("No displayed Sobol effects available")

  response_scales$display_response_label <- sobol_response_display_label(
    response_scales$response_id, response_scales$response_label, lang
  )
  response_scales$scale_label <- paste0(
    response_scales$display_response_label,
    "\nSD = ", formatC(as.numeric(response_scales$response_sd), format = "fg", digits = 4),
    " ", response_scales$unit
  )
  source <- merge(source,
                  response_scales[, c("season", "response_id", "scale_label")],
                  by = c("season", "response_id"), all.x = TRUE, sort = FALSE)
  source$parameter_key <- paste(source$response_id, source$parameter, sep = "___")
  index_labels <- c(sa_t("sobol.first_order_s1", lang), sa_t("sobol.total_effect_st", lang))
  long <- rbind(
    data.frame(source[, c("season", "response_id", "response_label", "scale_label",
                          "parameter", "parameter_key")],
               index = index_labels[[1]], estimate = as.numeric(source$S1),
               ci_low = as.numeric(source$S1_ci_low), ci_high = as.numeric(source$S1_ci_high)),
    data.frame(source[, c("season", "response_id", "response_label", "scale_label",
                          "parameter", "parameter_key")],
               index = index_labels[[2]], estimate = as.numeric(source$ST),
               ci_low = as.numeric(source$ST_ci_low), ci_high = as.numeric(source$ST_ci_high))
  )
  long$index <- factor(long$index, levels = index_labels)
  plot <- ggplot2::ggplot() +
    ggplot2::geom_vline(xintercept = 0, colour = "#BDBDBD", linewidth = 0.35) +
    ggplot2::geom_vline(xintercept = 1, linetype = 3, colour = "#BDBDBD", linewidth = 0.35) +
    ggplot2::geom_segment(data = source,
      ggplot2::aes(x = S1, xend = ST, y = parameter_key, yend = parameter_key,
                   colour = interaction_supported), linewidth = 1.0, alpha = 0.6) +
    ggplot2::geom_errorbar(data = long,
      ggplot2::aes(y = parameter_key, xmin = ci_low, xmax = ci_high, colour = index),
      width = 0.14, linewidth = 0.38, orientation = "y",
      position = ggplot2::position_dodge(width = 0.34)) +
    ggplot2::geom_point(data = long,
      ggplot2::aes(x = estimate, y = parameter_key, fill = index, shape = index),
      size = 2.0, stroke = 0.55, position = ggplot2::position_dodge(width = 0.34),
      colour = "#222222") +
    ggplot2::geom_text(data = source,
      ggplot2::aes(x = -0.30, y = parameter_key, label = parameter),
      inherit.aes = FALSE, hjust = 0, size = 2.0, colour = "#333333") +
    ggplot2::facet_wrap(~scale_label, ncol = 2, scales = "free_y") +
    ggplot2::scale_y_discrete(labels = NULL) +
    ggplot2::coord_cartesian(clip = "off") +
    ggplot2::scale_colour_manual(
      values = c("FALSE" = "#BDBDBD", "TRUE" = "#7B3294",
                 setNames(c("#0072B2", "#D55E00"), index_labels)), guide = "none"
    ) +
    ggplot2::scale_fill_manual(values = setNames(c("white", "#D55E00"), index_labels)) +
    ggplot2::scale_shape_manual(values = setNames(c(21, 21), index_labels)) +
    ggplot2::labs(
      title = sa_t("sobol_results.title", lang),
      subtitle = sa_t("sobol_results.subtitle", lang),
      x = sa_t("sobol_ms_eff.effect_x", lang), y = NULL, fill = NULL, shape = NULL
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      legend.position = "top", legend.justification = "left", legend.box = "horizontal",
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.8),
      axis.text.y = ggplot2::element_blank(), axis.ticks.y = ggplot2::element_blank(),
      plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
      plot.subtitle = ggplot2::element_text(colour = "#4D4D4D", size = profile$font_size_pt)
    ) +
    patchwork::plot_annotation(
      tag_levels = "a",
      caption = if (isTRUE(is_demo)) sa_t("sobol_results.demo_caption", lang) else NULL,
      theme = ggplot2::theme(
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 0),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)
      )
    )
  list(plot = plot, effects_source = source, response_scales_source = response_scales,
       height_mm = 155)
}
