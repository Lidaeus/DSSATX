build_model_performance <- function(comparison, variables, profile, is_demo = FALSE) {
  data <- comparison[comparison$variable %in% variables, , drop = FALSE]
  if (nrow(data) == 0) stop("No requested model-performance variables are available")
  inferential <- data$dataset_role %in% c("calibration", "validation")
  if (any(inferential)) data <- data[inferential, , drop = FALSE]

  metric_groups <- interaction(data$variable, data$dataset_role, drop = TRUE)
  metric_rows <- lapply(split(data, metric_groups), function(frame) {
    residual <- frame$simulated - frame$observed
    data.frame(variable = frame$variable[[1]], dataset_role = frame$dataset_role[[1]], n = nrow(frame),
               rmse = sqrt(mean(residual^2)), mae = mean(abs(residual)), bias = mean(residual))
  })
  metrics <- do.call(rbind, metric_rows)
  palette <- profile$palette
  panels <- lapply(variables[variables %in% unique(data$variable)], function(variable) {
    frame <- data[data$variable == variable, , drop = FALSE]
    values <- c(frame$observed, frame$simulated)
    padding <- max(diff(range(values)), 1) * 0.05
    limits <- c(min(0, min(values)) - padding, max(values) + padding)
    metric <- metrics[metrics$variable == variable, ]
    role_names <- c(calibration = "Calibration", validation = "Validation",
                    legacy_unsplit = "Legacy", diagnostic = "Diagnostic")
    metric_text <- paste(vapply(seq_len(nrow(metric)), function(index) {
      sprintf("%s: n = %d\nRMSE = %.3g; Bias = %.3g",
              role_names[[metric$dataset_role[[index]]]], metric$n[[index]],
              metric$rmse[[index]], metric$bias[[index]])
    }, character(1)), collapse = "\n")
    unit <- frame$unit[[1]]
    suffix <- if (nzchar(unit)) paste0(" (", unit, ")") else ""
    ggplot2::ggplot(frame, ggplot2::aes(observed, simulated)) +
      ggplot2::geom_abline(slope = 1, intercept = 0, colour = "#333333", linewidth = 0.45) +
      ggplot2::geom_point(ggplot2::aes(colour = dataset_role, shape = dataset_role),
                          size = 1.7, stroke = 0.55, fill = "white", alpha = 0.9) +
      ggplot2::annotate("label", x = limits[[1]] + 0.04 * diff(limits),
                        y = limits[[2]] - 0.04 * diff(limits), hjust = 0, vjust = 1,
                        label = metric_text, size = 2.1,
                        linewidth = 0, fill = "white", alpha = 0.82) +
      ggplot2::scale_colour_manual(values = c(calibration = palette$calibration,
                                              validation = palette$validation,
                                              legacy_unsplit = palette$neutral,
                                              diagnostic = palette$neutral),
                                   labels = c(calibration = "Calibration", validation = "Validation",
                                              legacy_unsplit = "Legacy unsplit", diagnostic = "Diagnostic"),
                                   drop = FALSE) +
      ggplot2::scale_shape_manual(values = c(calibration = 16, validation = 2,
                                             legacy_unsplit = 1, diagnostic = 1),
                                  labels = c(calibration = "Calibration", validation = "Validation",
                                             legacy_unsplit = "Legacy unsplit", diagnostic = "Diagnostic"),
                                  drop = FALSE) +
      ggplot2::coord_equal(xlim = limits, ylim = limits, expand = FALSE) +
      ggplot2::labs(title = frame$variable_label[[1]], x = paste0("Observed", suffix),
                    y = paste0("Simulated", suffix)) +
      theme_q1(profile)
  })
  columns <- min(2L, length(panels))
  plot <- patchwork::wrap_plots(panels, ncol = columns, guides = "collect") +
    patchwork::plot_annotation(tag_levels = "a", caption = demo_caption(is_demo),
      theme = ggplot2::theme(plot.tag = ggplot2::element_text(face = "bold"),
                             plot.caption = ggplot2::element_text(colour = "#666666", size = 5))) &
    ggplot2::theme(legend.position = "top")
  list(plot = plot, source = data, metrics = metrics,
       height_mm = min(profile$max_height_mm, 78 * ceiling(length(panels) / columns)))
}
