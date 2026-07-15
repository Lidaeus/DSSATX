build_phi_convergence <- function(phi, profile, is_demo = FALSE) {
  required <- c("iteration", "realization", "phi")
  missing <- setdiff(required, names(phi))
  if (length(missing) > 0) stop("phi_ensemble.csv missing: ", paste(missing, collapse = ", "))
  phi$iteration <- as.integer(phi$iteration)
  phi$phi <- as.numeric(phi$phi)
  phi <- phi[is.finite(phi$phi) & phi$phi >= 0, , drop = FALSE]
  summary <- do.call(rbind, lapply(split(phi, phi$iteration), function(frame) {
    values <- frame$phi
    data.frame(iteration = frame$iteration[[1]], n = length(values),
               q05 = unname(stats::quantile(values, 0.05)),
               q25 = unname(stats::quantile(values, 0.25)), median = stats::median(values),
               q75 = unname(stats::quantile(values, 0.75)),
               q95 = unname(stats::quantile(values, 0.95)))
  }))
  use_log <- all(summary$q05 > 0) && max(summary$q95) / min(summary$q05) >= 100
  plot <- ggplot2::ggplot(summary, ggplot2::aes(iteration, median)) +
    ggplot2::geom_ribbon(ggplot2::aes(ymin = q05, ymax = q95, fill = "5–95%"), alpha = 0.20) +
    ggplot2::geom_ribbon(ggplot2::aes(ymin = q25, ymax = q75, fill = "IQR"), alpha = 0.42) +
    ggplot2::geom_line(colour = profile$palette$simulated, linewidth = profile$data_linewidth_pt) +
    ggplot2::geom_point(colour = profile$palette$simulated, size = 1.7) +
    ggplot2::scale_fill_manual(values = c("5–95%" = profile$palette$uncertainty,
                                          IQR = profile$palette$uncertainty)) +
    ggplot2::scale_x_continuous(breaks = sort(unique(summary$iteration))) +
    ggplot2::labs(title = "IES measurement objective convergence",
                  subtitle = "Median, interquartile range, and 5–95% ensemble interval",
                  x = "IES iteration", y = "Measurement Phi", caption = demo_caption(is_demo)) +
    theme_q1(profile)
  if (use_log) plot <- plot + ggplot2::scale_y_log10()
  list(plot = plot, source = phi, summary = summary, height_mm = 68)
}
