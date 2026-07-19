build_posterior_contraction <- function(data, profile, is_demo = FALSE) {
  required <- c("parameter", "prior_q05", "prior_q95", "prior_median", "posterior_q05",
                "posterior_q95", "posterior_median", "iqr_shrinkage", "frac_near_lower",
                "frac_near_upper")
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop("posterior_diagnostics.csv missing: ", paste(missing, collapse = ", "))
  numeric <- setdiff(required, "parameter")
  for (column in numeric) data[[column]] <- as.numeric(data[[column]])
  data <- data[stats::complete.cases(data[, required]), , drop = FALSE]
  if (nrow(data) == 0) stop("posterior diagnostics has no complete rows")
  data$parameter <- factor(data$parameter, levels = data$parameter)
  plot <- ggplot2::ggplot(data, ggplot2::aes(y = 1)) +
    ggplot2::geom_segment(ggplot2::aes(x = prior_q05, xend = prior_q95, yend = 1),
                          colour = profile$palette$neutral, linewidth = 1.1) +
    ggplot2::geom_point(ggplot2::aes(x = prior_median), shape = 21, fill = "white",
                        colour = profile$palette$neutral, size = 2.2, stroke = 0.5) +
    ggplot2::geom_segment(ggplot2::aes(x = posterior_q05, xend = posterior_q95, yend = 1),
                          colour = profile$palette$simulated, linewidth = 1.6) +
    ggplot2::geom_point(ggplot2::aes(x = posterior_median), colour = profile$palette$simulated,
                        size = 2.0) +
    ggplot2::facet_wrap(~parameter, scales = "free_x", ncol = 3) +
    ggplot2::labs(title = "Conditional-ensemble parameter contraction",
                  subtitle = "Prior and IES conditional-ensemble 5–95% intervals; not a Bayesian posterior",
                  x = "Parameter value (parameter-specific scale)", y = NULL, caption = demo_caption(is_demo)) +
    theme_q1(profile) +
    ggplot2::theme(axis.text.y = ggplot2::element_blank(), axis.ticks.y = ggplot2::element_blank(),
                   strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
                   strip.text = ggplot2::element_text(face = "bold")) +
    demo_watermark(is_demo)
  list(plot = plot, source = data, height_mm = 92)
}
