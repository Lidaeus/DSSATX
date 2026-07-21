validate_sobol_columns <- function(data, required, table_name) {
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop(table_name, " missing: ", paste(missing, collapse = ", "))
  invisible(TRUE)
}

sobol_domain_label <- function(domain) {
  ifelse(domain == "general_genetic", "General genetic effects", "Water-nitrogen response")
}

build_sobol_convergence <- function(rankings, metrics, run_scale, profile, is_demo = FALSE) {
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
