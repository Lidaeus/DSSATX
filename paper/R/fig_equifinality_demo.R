build_candidate_prediction_distance <- function(data, profile, is_demo = FALSE) {
  required <- c("pair_id", "parameter_distance", "d_validation", "d_diagnostic", "prediction_distance")
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop("candidate_pair_predictions.csv missing: ", paste(missing, collapse = ", "))
  for (column in setdiff(required, "pair_id")) data[[column]] <- as.numeric(data[[column]])
  data <- data[stats::complete.cases(data[, required]), required, drop = FALSE]
  if (nrow(data) < 1 || nrow(data) > 3) stop("candidate pairs must contain 1–3 complete rows")
  data$pair_label <- factor(paste0("Pair ", data$pair_id), levels = rev(paste0("Pair ", sort(data$pair_id))))
  parameter_plot <- ggplot2::ggplot(data, ggplot2::aes(y = pair_label, x = parameter_distance)) +
    ggplot2::geom_col(fill = profile$palette$highlight, width = 0.56) +
    ggplot2::labs(title = "Candidate-pair parameter separation", x = "Normalized parameter distance", y = NULL,
                  caption = demo_caption(is_demo)) + theme_q1(profile) + demo_watermark(is_demo)
  long <- rbind(data.frame(pair_label = data$pair_label, role = "Validation", distance = data$d_validation),
                data.frame(pair_label = data$pair_label, role = "Diagnostic", distance = data$d_diagnostic))
  prediction_plot <- ggplot2::ggplot(long, ggplot2::aes(y = pair_label, x = distance, colour = role, shape = role)) +
    ggplot2::geom_vline(xintercept = 1, colour = profile$palette$neutral, linetype = "dashed", linewidth = 0.45) +
    ggplot2::geom_point(size = 2.5) +
    ggplot2::scale_colour_manual(values = c(Validation = profile$palette$simulated,
                                            Diagnostic = profile$palette$negative)) +
    ggplot2::scale_shape_manual(values = c(Validation = 16, Diagnostic = 17)) +
    ggplot2::labs(title = "Deterministic prediction distance", subtitle = "RMS normalized by fixed scales; reference = 1",
                  x = "Prediction distance", y = NULL, caption = demo_caption(is_demo)) +
    theme_q1(profile) + demo_watermark(is_demo)
  list(plot = parameter_plot + prediction_plot + patchwork::plot_layout(widths = c(1, 1.25)),
       source = data, distance_source = long, height_mm = 65)
}
