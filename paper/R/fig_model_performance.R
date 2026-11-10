build_model_performance <- function(comparison, variables, profile, is_demo = FALSE,
                                    facet_columns = 2L) {
  # Explicit season metadata only: never infer season from treatment numbers.
  if ("season_id" %in% names(comparison) && length(unique(comparison$season_id)) > 1L) {
    if (anyNA(comparison$season_id) || any(!nzchar(comparison$season_id))) stop("Missing season_id")
    seasons <- unique(as.character(comparison$season_id))
    seasons <- c(intersect(c("25SP", "26SP", "25FA"), seasons),
                 setdiff(seasons, c("25SP", "26SP", "25FA")))
    single_variable <- length(variables) == 1L
    parts <- lapply(seasons, function(season) {
      part <- build_model_performance(comparison[comparison$season_id == season, , drop = FALSE],
                                      variables, profile, is_demo, facet_columns = 4L)
      part$metrics$season_id <- season
      part$plot <- part$plot + patchwork::plot_annotation(title = season)
      part
    })
    return(list(plot = patchwork::wrap_plots(lapply(parts, `[[`, "plot"),
                                             ncol = if (single_variable) length(parts) else 1L) +
                  patchwork::plot_annotation(
                    caption = if (isTRUE(is_demo)) "DEMO: layout QA only; not scientific evidence" else NULL,
                    theme = ggplot2::theme(plot.caption = ggplot2::element_text(size = 5))),
                source = do.call(rbind, lapply(parts, `[[`, "source")),
                metrics = do.call(rbind, lapply(parts, `[[`, "metrics")),
                height_mm = if (single_variable) 83 else min(profile$max_height_mm, 78 * length(parts))))
  }
  data <- comparison[comparison$variable %in% variables, , drop = FALSE]
  if ("simulation_date_gap_days" %in% names(data)) {
    data <- data[!is.finite(data$simulation_date_gap_days) | data$simulation_date_gap_days == 0, , drop = FALSE]
  }
  if (nrow(data) == 0) stop("No requested model-performance variables are available")
  mass <- data$variable %in% c("FRESH_CUM", "FRESH_INC", "DRY_CUM", "DRY_INC") &
    data$unit %in% c("kg ha⁻¹", "kg ha-1")
  data$observed[mass] <- data$observed[mass] / 1000
  data$simulated[mass] <- data$simulated[mass] / 1000
  data$observed_se[mass] <- data$observed_se[mass] / 1000
  data$unit[mass] <- "t ha⁻¹"
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
    if (!"observed_se" %in% names(frame)) frame$observed_se <- NA_real_
    se_values <- if ("observed_se" %in% names(frame) && !is.null(frame$observed_se)) {
      valid_se <- is.finite(frame$observed_se) & frame$observed_se >= 0 & is.finite(frame$observed)
      if (any(valid_se)) {
        c(frame$observed[valid_se] - frame$observed_se[valid_se],
          frame$observed[valid_se] + frame$observed_se[valid_se])
      } else {
        numeric(0)
      }
    } else {
      numeric(0)
    }
    values <- c(frame$observed, frame$simulated, se_values)
    values <- values[is.finite(values)]
    if (length(values) == 0) values <- c(0, 1)
    padding <- max(diff(range(values)), 1) * 0.05
    limits <- c(min(0, min(values)) - padding, max(values) + padding)
    metric <- metrics[metrics$variable == variable, ]
    role_names <- c(calibration = "Calibration", validation = "Held-out",
                    legacy_unsplit = "Legacy", diagnostic = "Diagnostic")
    metric_text <- paste(vapply(seq_len(nrow(metric)), function(index) {
      sprintf("%s (n = %d)\nRMSE %.3g\nBias %+.3g",
              role_names[[metric$dataset_role[[index]]]], metric$n[[index]],
              metric$rmse[[index]], metric$bias[[index]])
    }, character(1)), collapse = "\n")
    unit <- frame$unit[[1]]
    suffix <- if (nzchar(unit)) paste0(" (", unit, ")") else ""
    ggplot2::ggplot(frame, ggplot2::aes(observed, simulated)) +
      ggplot2::geom_abline(slope = 1, intercept = 0, colour = "#333333", linewidth = 0.45) +
      ggplot2::geom_errorbar(
        data = frame[is.finite(frame$observed_se) & frame$observed_se >= 0, , drop = FALSE],
        ggplot2::aes(xmin = observed - observed_se, xmax = observed + observed_se),
        orientation = "y", width = 0, linewidth = 0.3, colour = "#666666") +
      ggplot2::geom_point(ggplot2::aes(colour = dataset_role, shape = dataset_role),
                          size = 1.7, stroke = 0.55, fill = "white", alpha = 0.9) +
      ggplot2::annotate("label", x = limits[[1]] + 0.04 * diff(limits),
                        y = limits[[1]] + 0.92 * diff(limits), hjust = 0, vjust = 1,
                        label = metric_text, size = 2.1,
                        linewidth = 0, fill = "white", alpha = 0.82) +
      ggplot2::scale_colour_manual(values = c(calibration = palette$calibration,
                                              validation = palette$validation,
                                              legacy_unsplit = palette$neutral,
                                              diagnostic = palette$neutral),
                                   labels = c(calibration = "Calibration", validation = "Held-out",
                                              legacy_unsplit = "Legacy unsplit", diagnostic = "Diagnostic"),
                                   drop = FALSE) +
      ggplot2::scale_shape_manual(values = c(calibration = 16, validation = 2,
                                             legacy_unsplit = 1, diagnostic = 1),
                                  labels = c(calibration = "Calibration", validation = "Held-out",
                                             legacy_unsplit = "Legacy unsplit", diagnostic = "Diagnostic"),
                                  drop = FALSE) +
      ggplot2::coord_equal(xlim = limits, ylim = limits, expand = FALSE) +
      ggplot2::labs(title = paste(if ("season_id" %in% names(frame)) frame$season_id[[1]] else "",
                                  if (variable == "FRESH_CUM") "Fresh yield" else frame$variable_label[[1]]), x = paste0("Observed", suffix),
                    y = paste0("Simulated", suffix)) +
      theme_q1(profile)
  })
  columns <- min(facet_columns, length(panels))
  plot <- patchwork::wrap_plots(panels, ncol = columns, guides = "collect") +
    patchwork::plot_annotation(tag_levels = "a", caption = demo_caption(is_demo),
      theme = ggplot2::theme(plot.tag = ggplot2::element_text(face = "bold"),
                             plot.caption = ggplot2::element_text(colour = "#666666", size = 5))) &
    ggplot2::theme(legend.position = "top")
  list(plot = plot, source = data, metrics = metrics,
       height_mm = min(profile$max_height_mm, 78 * ceiling(length(panels) / columns)))
}
