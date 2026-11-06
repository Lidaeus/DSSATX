# Plan §5 (treatment-level conditional-ensemble residual distributions).  The
# violin-of-all-events idea is deliberately NOT implemented: member x treatment
# aggregated statistics are computed upstream (conditional_residual_by_treatment_
# member.csv) so ~200 ensemble repeats are never mistaken for extra independent
# observations.  This module renders only; it never reads DSSAT/PEST++ files.

WATER_ORDER <- c("W1", "W2", "W3", "CK")
NITROGEN_ORDER <- c("N0", "N1", "N2", "N3")

order_conditional_treatments <- function(data) {
  # Fixed scientific order: water W1->W2->W3->CK, nitrogen N0->N3 within water
  # (plan §5.3).  Row labels carry the explicit Cal/Val role suffix.
  data$water_rank <- match(data$water_level, WATER_ORDER)
  data$nitrogen_rank <- match(data$nitrogen_level, NITROGEN_ORDER)
  data <- data[order(data$season_id, data$water_rank, data$nitrogen_rank,
                     as.integer(data$treatment)), , drop = FALSE]
  role_suffix <- ifelse(data$dataset_role == "calibration", "Cal", "Val")
  data$row_label <- paste0(data$water_level, data$nitrogen_level, " · TN",
                           data$treatment, " · ", role_suffix)
  data$row_label <- factor(data$row_label, levels = rev(unique(data$row_label)))
  data
}

summarise_member_distribution <- function(residual_members, statistic) {
  # Forest statistics across members per season x treatment.
  rows <- lapply(split(residual_members,
                       interaction(residual_members$season_id, residual_members$treatment, drop = TRUE)),
                 function(frame) {
                   values <- frame[[statistic]]
                   data.frame(
                     season_id = frame$season_id[[1]],
                     treatment = frame$treatment[[1]],
                     dataset_role = frame$dataset_role[[1]],
                     n_members = nrow(frame),
                     median = stats::median(values),
                     q025 = stats::quantile(values, 0.025, names = FALSE, na.rm = TRUE),
                     q25 = stats::quantile(values, 0.25, names = FALSE, na.rm = TRUE),
                     q75 = stats::quantile(values, 0.75, names = FALSE, na.rm = TRUE),
                     q975 = stats::quantile(values, 0.975, names = FALSE, na.rm = TRUE)
                   )
                 })
  do.call(rbind, rows)
}

build_treatment_residual_uncertainty <- function(residual_members, treatment_metadata,
                                                 variable = "FRESH_CUM",
                                                 statistic = "terminal_relative_error_pct",
                                                 profile, is_demo = FALSE) {
  data <- residual_members[residual_members$variable == variable, , drop = FALSE]
  if (nrow(data) == 0) stop("No member-level residuals for variable ", variable)
  if (!all(is.finite(data[[statistic]]))) {
    stop("Non-finite member statistic: ", statistic)
  }
  data$treatment <- as.character(data$treatment)
  data <- attach_conditional_metadata(data, treatment_metadata)
  data <- order_conditional_treatments(data)

  forest <- summarise_member_distribution(data, statistic)
  forest$treatment <- as.character(forest$treatment)
  forest <- merge(forest, unique(data[, c("season_id", "treatment", "row_label",
                                          "nitrogen_level", "dataset_role")]),
                  by = c("season_id", "treatment"), sort = FALSE)
  forest <- forest[order(forest$season_id, -as.integer(forest$treatment)), , drop = FALSE]
  label_levels <- rev(unique(data$row_label))
  forest$row_label <- factor(as.character(forest$row_label), levels = label_levels)

  # Right-hand companion panel: member-level RRMSE guards against signed-bias
  # cancellation hiding a poor fit (plan §5.3).
  rrmse_forest <- summarise_member_distribution(data, "rrmse_pct")
  rrmse_forest$treatment <- as.character(rrmse_forest$treatment)
  rrmse_forest <- merge(rrmse_forest, unique(data[, c("season_id", "treatment", "row_label",
                                                      "nitrogen_level", "dataset_role")]),
                        by = c("season_id", "treatment"), sort = FALSE)
  rrmse_forest$row_label <- factor(as.character(rrmse_forest$row_label), levels = label_levels)

  nitrogen <- unlist(profile$nitrogen_colors, use.names = TRUE)
  season_levels <- intersect(c("25SP", "26SP"), unique(data$season_id))

  statistic_label <- switch(statistic,
    terminal_relative_error_pct = "Terminal relative error (%)",
    signed_relative_bias_pct = "Signed relative bias (%)",
    rrmse_pct = "Member-level RRMSE (%)",
    statistic)

  yield_type <- if (variable == "FRESH_CUM") "fresh-yield" else "dry-yield"
  p_main <- ggplot2::ggplot(forest, ggplot2::aes(x = median, y = row_label,
                                                 colour = nitrogen_level)) +
    ggplot2::geom_vline(xintercept = 0, linetype = "dashed",
                        colour = "#8C8C8C", linewidth = 0.4) +
    ggplot2::geom_segment(ggplot2::aes(x = q025, xend = q975,
                                       y = row_label, yend = row_label),
                          linewidth = 0.35, alpha = 0.55, lineend = "butt") +
    ggplot2::geom_segment(ggplot2::aes(x = q25, xend = q75,
                                       y = row_label, yend = row_label),
                          linewidth = 1.5, lineend = "butt") +
    ggplot2::geom_point(size = 1.5, shape = 21, fill = "white", stroke = 0.5) +
    ggplot2::facet_grid(season_id ~ ., scales = "free_y", space = "free_y", switch = "y") +
    ggplot2::scale_colour_manual(name = "Nitrogen level", values = nitrogen, drop = FALSE) +
    ggplot2::labs(title = paste0("Treatment-level ", yield_type, " error distributions"),
                  subtitle = paste0("Left: terminal relative error; right: event-series RRMSE. ",
                                    "Thin = 95% interval, thick = IQR, point = median."),
                  x = statistic_label, y = NULL) +
    dynamics_theme(profile) +
    ggplot2::theme(strip.placement = "outside",
                   strip.text.y.left = ggplot2::element_text(angle = 0, face = "bold"))

  p_rrmse <- ggplot2::ggplot(rrmse_forest, ggplot2::aes(x = median, y = row_label,
                                                        colour = nitrogen_level)) +
    ggplot2::geom_segment(ggplot2::aes(x = q025, xend = q975,
                                       y = row_label, yend = row_label),
                          linewidth = 0.35, alpha = 0.55, lineend = "butt") +
    ggplot2::geom_segment(ggplot2::aes(x = q25, xend = q75,
                                       y = row_label, yend = row_label),
                          linewidth = 1.5, lineend = "butt") +
    ggplot2::geom_point(size = 1.5, shape = 21, fill = "white", stroke = 0.5) +
    ggplot2::facet_grid(season_id ~ ., scales = "free_y", space = "free_y", switch = "y") +
    ggplot2::scale_colour_manual(name = "Nitrogen level", values = nitrogen, drop = FALSE) +
    ggplot2::labs(x = "Member-level RRMSE (%)", y = NULL) +
    dynamics_theme(profile) +
    ggplot2::theme(axis.text.y = ggplot2::element_blank(),
                   strip.placement = "outside",
                   strip.text.y.left = ggplot2::element_blank(),
                   strip.background = ggplot2::element_blank(),
                   legend.position = "none")

  plot <- (p_main | p_rrmse) +
    patchwork::plot_annotation(
      caption = paste(
        "One distribution per conditional-ensemble member aggregated per treatment;",
        "member repeats are not independent observations.",
        ifelse(isTRUE(is_demo), demo_caption(TRUE), "")
      ),
      theme = ggplot2::theme(plot.caption = ggplot2::element_text(colour = "#666666", size = 5))
    )

  list(plot = plot, source = data, forest = forest, rrmse_forest = rrmse_forest,
       height_mm = min(profile$max_height_mm, 142))
}
