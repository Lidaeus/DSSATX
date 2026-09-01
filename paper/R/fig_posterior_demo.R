# fig_posterior_demo.R - Parameter Posterior Distribution, Density & Contraction
# Produces Fig. S5 / Fig. 5: Publication-grade parameter posterior density & shrinkage

build_posterior_contraction <- function(data, profile, is_demo = FALSE, posterior_samples = NULL) {
  required <- c("parameter", "prior_q05", "prior_q95", "prior_median", "posterior_q05",
                "posterior_q95", "posterior_median", "iqr_shrinkage", "frac_near_lower",
                "frac_near_upper")
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop("posterior_diagnostics.csv missing: ", paste(missing, collapse = ", "))
  numeric <- setdiff(required, c("parameter", "domain", "description", "unit"))
  for (column in numeric) data[[column]] <- as.numeric(data[[column]])
  data <- data[stats::complete.cases(data[, required]), , drop = FALSE]
  if (nrow(data) == 0) stop("posterior diagnostics has no complete rows")
  
  data$parameter <- factor(data$parameter, levels = data$parameter)
  
  # Calculate shrinkage percentage
  data$shrinkage_pct <- data$iqr_shrinkage * 100
  data$boundary_tag <- ifelse(data$frac_near_lower > 0.1, "Lower Hit",
                       ifelse(data$frac_near_upper > 0.1, "Upper Hit", "Interior"))
  
  # If detailed posterior sample realizations are available, draw full density distributions
  if (!is.null(posterior_samples) && nrow(posterior_samples) > 0 && "parameter" %in% names(posterior_samples)) {
    plot_data <- merge(posterior_samples, data, by = "parameter")
    
    plot <- ggplot2::ggplot(plot_data, ggplot2::aes(x = value)) +
      # Prior uniform background band
      ggplot2::geom_rect(ggplot2::aes(xmin = prior_q05, xmax = prior_q95, ymin = -Inf, ymax = Inf),
                         fill = "#F2F4F4", colour = "#BDC3C7", linetype = "dashed", linewidth = 0.4, alpha = 0.6) +
      # Posterior Kernel Density Curve
      ggplot2::geom_density(ggplot2::aes(y = ggplot2::after_stat(scaled)),
                            fill = "#3498DB", colour = "#1B4F72", alpha = 0.55, linewidth = 0.8) +
      # Median & Prior lines
      ggplot2::geom_vline(ggplot2::aes(xintercept = posterior_median), colour = "#C0392B", linewidth = 0.9, linetype = "solid") +
      ggplot2::geom_vline(ggplot2::aes(xintercept = prior_median), colour = "#7F8C8D", linewidth = 0.7, linetype = "dotted") +
      # Facet by parameter with free scales
      ggplot2::facet_wrap(~parameter, scales = "free", ncol = 4) +
      # Labels & Themes
      ggplot2::labs(
        title = "Parameter Posterior Density & Prior Contraction Diagnostic",
        subtitle = "Prior range (shaded dashed box) vs PEST++ IES posterior ensemble density (blue curve), median (red line), prior median (grey dotted)",
        x = "Parameter Value",
        y = "Relative Posterior Density",
        caption = demo_caption(is_demo)
      ) +
      theme_q1(profile) +
      ggplot2::theme(
        strip.background = ggplot2::element_rect(fill = "#EAEDED", colour = "#BDC3C7"),
        strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt * 0.9),
        panel.spacing = ggplot2::unit(4, "mm"),
        axis.text.y = ggplot2::element_blank(),
        axis.ticks.y = ggplot2::element_blank()
      ) +
      demo_watermark(is_demo)
      
    height_calc <- max(110, ceiling(length(unique(data$parameter)) / 4) * 38)
    return(list(plot = plot, source = data, height_mm = height_calc))
  }
  
  # Standard Interval & Shrinkage Multi-Panel Layout
  plot <- ggplot2::ggplot(data, ggplot2::aes(y = 1)) +
    # Prior bounds interval
    ggplot2::geom_segment(ggplot2::aes(x = prior_q05, xend = prior_q95, yend = 1),
                          colour = "#BDC3C7", linewidth = 2.5, lineend = "round") +
    ggplot2::geom_point(ggplot2::aes(x = prior_median), shape = 23, fill = "white",
                        colour = "#7F8C8D", size = 2.5, stroke = 0.8) +
    # Posterior 90% interval & median
    ggplot2::geom_segment(ggplot2::aes(x = posterior_q05, xend = posterior_q95, yend = 1),
                          colour = "#2980B9", linewidth = 4.2, lineend = "round", alpha = 0.85) +
    ggplot2::geom_point(ggplot2::aes(x = posterior_median), shape = 21, fill = "#C0392B",
                        colour = "white", size = 3.0, stroke = 0.6) +
    # Inset annotation text for shrinkage
    ggplot2::geom_text(ggplot2::aes(x = prior_q05, y = 1.35,
                                    label = paste0("Shrink: ", round(shrinkage_pct, 1), "%\n(", boundary_tag, ")")),
                       hjust = 0, size = profile$font_size_pt * 0.28, fontface = "bold", colour = "#2C3E50") +
    ggplot2::facet_wrap(~parameter, scales = "free_x", ncol = 4) +
    ggplot2::ylim(0.6, 1.55) +
    ggplot2::labs(
      title = "Parameter Posterior Contraction & Boundary Confinement",
      subtitle = "Prior 5–95% bounds (grey bar) vs Calibrated Posterior 5–95% interval (blue bar) & Median (red dot)",
      x = "Parameter Physical Domain Scale", y = NULL, caption = demo_caption(is_demo)
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      axis.text.y = ggplot2::element_blank(),
      axis.ticks.y = ggplot2::element_blank(),
      axis.line.y = ggplot2::element_blank(),
      strip.background = ggplot2::element_rect(fill = "#EAEDED", colour = "#BDC3C7"),
      strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt * 0.9),
      panel.spacing = ggplot2::unit(4.5, "mm")
    ) +
    demo_watermark(is_demo)
    
  height_calc <- max(100, ceiling(nrow(data) / 4) * 32)
  list(plot = plot, source = data, height_mm = height_calc)
}
