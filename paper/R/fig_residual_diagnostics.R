residual_point_scales <- function(profile) {
  nitrogen <- unlist(profile$nitrogen_colors, use.names = TRUE)
  water <- unlist(profile$water_shapes, use.names = TRUE)
  list(
    ggplot2::scale_fill_manual(
      name = "Nitrogen level", values = nitrogen, drop = FALSE,
      guide = ggplot2::guide_legend(
        order = 2, override.aes = list(shape = 21, colour = "#202020")
      )
    ),
    ggplot2::scale_shape_manual(
      name = "Water treatment", values = water, drop = FALSE,
      guide = ggplot2::guide_legend(order = 1, override.aes = list(fill = "white"))
    )
  )
}

residual_theme <- function(profile) {
  theme_q1(profile) +
    ggplot2::theme(
      panel.grid.major.y = ggplot2::element_line(colour = "#E8E8E8", linewidth = 0.25),
      strip.background = ggplot2::element_rect(fill = "#F3F3F3", colour = NA),
      strip.text = ggplot2::element_text(face = "bold", colour = "#303030"),
      legend.title = ggplot2::element_text(face = "bold", colour = "#303030"),
      panel.spacing = grid::unit(4, "pt")
    )
}

residual_summary <- function(data) {
  groups <- split(data, interaction(data$dataset_role, data$variable, drop = TRUE))
  rows <- lapply(groups, function(frame) {
    residual <- frame$residual
    data.frame(
      dataset_role = frame$dataset_role[[1]],
      variable = frame$variable[[1]],
      variable_label = frame$variable_label[[1]],
      unit = frame$unit[[1]],
      n = length(residual),
      bias = mean(residual),
      rmse = sqrt(mean(residual^2)),
      median_residual = stats::median(residual),
      residual_sd = if (length(residual) > 1) stats::sd(residual) else NA_real_,
      residual_mad = stats::mad(residual),
      max_abs_residual = max(abs(residual))
    )
  })
  do.call(rbind, rows)
}

make_qq_data <- function(data) {
  groups <- split(data, interaction(data$dataset_role, data$variable, drop = TRUE))
  rows <- lapply(groups, function(frame) {
    frame <- frame[order(frame$residual), , drop = FALSE]
    spread <- if (nrow(frame) > 1) stats::sd(frame$residual) else NA_real_
    if (!is.finite(spread) || spread <= .Machine$double.eps) {
      frame$standardized_residual <- 0
    } else {
      frame$standardized_residual <- (frame$residual - mean(frame$residual)) / spread
    }
    frame$theoretical_quantile <- stats::qnorm(stats::ppoints(nrow(frame)))
    frame
  })
  do.call(rbind, rows)
}

build_residual_diagnostics <- function(comparison, treatment_metadata, variables,
                                       profile, is_demo = FALSE) {
  data <- comparison[comparison$variable %in% variables, , drop = FALSE]
  if (nrow(data) == 0) stop("No requested variables are available for residual diagnostics")
  inferential <- data$dataset_role %in% c("calibration", "validation")
  if (any(inferential)) data <- data[inferential, , drop = FALSE]
  data <- attach_treatment_metadata(data, treatment_metadata,
                                    unique(as.character(data$treatment)))
  data$residual <- data$simulated - data$observed
  data$fitted <- data$simulated
  data$variable_panel <- paste0(data$variable_label, "\n[", data$unit, "]")
  variable_order <- unique(data$variable_panel[match(variables, data$variable)])
  data$variable_panel <- factor(data$variable_panel, levels = variable_order)
  qq <- make_qq_data(data)
  metrics <- residual_summary(data)

  role_names <- c(calibration = "Calibration", validation = "Validation",
                  legacy_unsplit = "Legacy unsplit", diagnostic = "Diagnostic")
  roles <- unique(as.character(data$dataset_role))
  results <- list()
  for (role in roles) {
    frame <- data[data$dataset_role == role, , drop = FALSE]
    qq_frame <- qq[qq$dataset_role == role, , drop = FALSE]
    role_label <- if (role %in% names(role_names)) role_names[[role]] else role

    p_fitted <- ggplot2::ggplot(frame, ggplot2::aes(fitted, residual)) +
      ggplot2::geom_hline(yintercept = 0, colour = "#555555", linewidth = 0.4,
                          linetype = "dashed") +
      ggplot2::geom_point(
        ggplot2::aes(fill = nitrogen_level, shape = water_level),
        colour = "#202020", size = 1.65, stroke = 0.4, alpha = 0.88
      ) +
      ggplot2::facet_wrap(~variable_panel, ncol = 1, scales = "free") +
      residual_point_scales(profile) +
      ggplot2::labs(title = "Residuals vs fitted", x = "Simulated value",
                    y = "Residual (simulated − observed)") +
      residual_theme(profile)

    p_time <- ggplot2::ggplot(frame, ggplot2::aes(time, residual)) +
      ggplot2::geom_hline(yintercept = 0, colour = "#555555", linewidth = 0.4,
                          linetype = "dashed") +
      ggplot2::geom_point(
        ggplot2::aes(fill = nitrogen_level, shape = water_level),
        colour = "#202020", size = 1.65, stroke = 0.4, alpha = 0.88
      ) +
      ggplot2::facet_wrap(~variable_panel, ncol = 1, scales = "free") +
      residual_point_scales(profile) +
      ggplot2::labs(title = "Residuals vs time", x = "Days after planting",
                    y = "Residual (simulated − observed)") +
      residual_theme(profile)

    p_qq <- ggplot2::ggplot(qq_frame, ggplot2::aes(theoretical_quantile,
                                                    standardized_residual)) +
      ggplot2::geom_abline(slope = 1, intercept = 0, colour = "#555555",
                           linewidth = 0.4, linetype = "dashed") +
      ggplot2::geom_point(
        ggplot2::aes(fill = nitrogen_level, shape = water_level),
        colour = "#202020", size = 1.65, stroke = 0.4, alpha = 0.88
      ) +
      ggplot2::facet_wrap(~variable_panel, ncol = 1, scales = "free") +
      residual_point_scales(profile) +
      ggplot2::labs(title = "Normal Q–Q", x = "Theoretical normal quantile",
                    y = "Standardized residual") +
      residual_theme(profile)

    plot <- patchwork::wrap_plots(p_fitted, p_time, p_qq, ncol = 3, guides = "collect") +
      patchwork::plot_annotation(
        title = paste0(role_label, " residual diagnostics"),
        subtitle = "Positive residuals indicate model overprediction; Q–Q panels are descriptive, not a normality test",
        caption = demo_caption(is_demo),
        theme = ggplot2::theme(
          plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt),
          plot.subtitle = ggplot2::element_text(size = profile$font_size_pt,
                                                colour = "#4D4D4D"),
          plot.caption = ggplot2::element_text(size = 5, colour = "#666666")
        )
      ) & ggplot2::theme(legend.position = "top")
    results[[role]] <- list(
      plot = plot,
      source = frame,
      qq = qq_frame,
      metrics = metrics[metrics$dataset_role == role, , drop = FALSE],
      height_mm = min(profile$max_height_mm, max(105, 38 * length(unique(frame$variable))))
    )
  }
  results
}
