# fig_water_nitrogen_response.R - Agronomic Water-Nitrogen Response Gradients & Interactions
# Produces Fig. 5 / Fig. 6: Publication-grade agronomic water x nitrogen interaction and marginal response ladders

build_water_nitrogen_response <- function(comparison_data, treatment_metadata, profile, is_demo = FALSE) {
  # Filter terminal fresh and dry fruit harvest observations
  harv <- comparison_data[comparison_data$variable %in% c("FRESH_CUM", "DRY_CUM"), ]
  if (nrow(harv) == 0) stop("No cumulative harvest variables found for water-nitrogen response figure")
  
  # Pick terminal harvest event per treatment & season
  # Sort by time
  harv <- harv[order(harv$season_id, harv$treatment, harv$time), ]
  harv_term <- do.call(rbind, by(harv, list(harv$season_id, harv$treatment, harv$variable), function(df) df[nrow(df), ]))
  
  # Merge water and nitrogen metadata
  merged <- merge(harv_term, treatment_metadata, by.x = c("season_id", "treatment"), by.y = c("season_id", "treatment"), all.x = TRUE)
  merged <- merged[!is.na(merged$water_level) & !is.na(merged$nitrogen_level), ]
  
  # Calculate Nitrogen Response Gradients: Delta Y(N) = Y(N) - Y(N0) within each (Season, Water_Level, Variable)
  calc_gradient <- function(df) {
    # Find N0
    n0_row <- df[df$nitrogen_level == "N0", ]
    if (nrow(n0_row) == 0) return(NULL)
    n0_obs <- mean(n0_row$observed, na.rm = TRUE)
    n0_sim <- mean(n0_row$simulated, na.rm = TRUE)
    
    df$delta_obs <- df$observed - n0_obs
    df$delta_sim <- df$simulated - n0_sim
    df$rel_resp_obs_pct <- (df$delta_obs / n0_obs) * 100
    df$rel_resp_sim_pct <- (df$delta_sim / n0_sim) * 100
    df
  }
  
  splits <- split(merged, list(merged$season_id, merged$water_level, merged$variable), drop = TRUE)
  graded_list <- lapply(splits, calc_gradient)
  graded_df <- do.call(rbind, graded_list)
  if (is.null(graded_df) || nrow(graded_df) == 0) stop("Could not compute nitrogen response gradients (missing N0 reference)")
  
  # Filter to Fresh Fruit Yield
  plot_df <- graded_df[graded_df$variable == "FRESH_CUM", ]
  plot_df$delta_obs_t <- plot_df$delta_obs / 1000.0
  plot_df$delta_sim_t <- plot_df$delta_sim / 1000.0
  plot_df$nitrogen_level <- factor(plot_df$nitrogen_level, levels = c("N0", "N1", "N2", "N3"))
  plot_df$water_level <- factor(plot_df$water_level, levels = c("W1", "W2", "W3", "CK"))
  
  # Colors from profile
  n_colors <- profile$nitrogen_colors
  if (is.null(n_colors)) n_colors <- c(N3 = "#C0392B", N2 = "#E67E22", N1 = "#2980B9", N0 = "#7F8C8D")
  
  # Panel A: Absolute Terminal Yield by W x N (Grouped Bars: Obs vs Sim)
  plot_a <- ggplot2::ggplot(plot_df, ggplot2::aes(x = nitrogen_level)) +
    ggplot2::geom_bar(ggplot2::aes(y = observed / 1000.0, fill = nitrogen_level), stat = "identity", position = ggplot2::position_nudge(x = -0.18), width = 0.32, alpha = 0.95, colour = "black", linewidth = 0.3) +
    ggplot2::geom_bar(ggplot2::aes(y = simulated / 1000.0, colour = nitrogen_level), stat = "identity", fill = "white", position = ggplot2::position_nudge(x = 0.18), width = 0.32, linewidth = 0.8) +
    ggplot2::facet_grid(season_id ~ water_level, scales = "free_y") +
    ggplot2::scale_fill_manual(values = n_colors) +
    ggplot2::scale_colour_manual(values = n_colors) +
    ggplot2::labs(
      title = "A. Total Fresh Fruit Yield by Water × Nitrogen Level",
      subtitle = "Solid filled bars = Observed field yield; Open bordered bars = Simulated yield",
      x = "Nitrogen Application Level",
      y = "Fresh Fruit Yield (t ha-1)"
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      legend.position = "none",
      strip.background = ggplot2::element_rect(fill = "#EAEDED", colour = "#BDC3C7"),
      strip.text = ggplot2::element_text(face = "bold")
    )
    
  # Panel B: Marginal Nitrogen Response Gradient: Delta Y(N) = Y(N) - Y(N0)
  plot_b <- ggplot2::ggplot(plot_df[plot_df$nitrogen_level != "N0", ], ggplot2::aes(x = nitrogen_level)) +
    ggplot2::geom_hline(yintercept = 0, linetype = "dashed", colour = "#7F8C8D", linewidth = 0.5) +
    ggplot2::geom_point(ggplot2::aes(y = delta_obs_t, fill = nitrogen_level), shape = 21, size = 3.5, stroke = 0.6, colour = "black", position = ggplot2::position_nudge(x = -0.12)) +
    ggplot2::geom_point(ggplot2::aes(y = delta_sim_t, colour = nitrogen_level), shape = 23, fill = "white", size = 3.2, stroke = 1.0, position = ggplot2::position_nudge(x = 0.12)) +
    ggplot2::geom_segment(ggplot2::aes(x = as.numeric(nitrogen_level) - 0.12, xend = as.numeric(nitrogen_level) + 0.12,
                                       y = delta_obs_t, yend = delta_sim_t), colour = "#BDC3C7", linewidth = 0.6, linetype = "dotted") +
    ggplot2::facet_grid(season_id ~ water_level) +
    ggplot2::scale_fill_manual(values = n_colors) +
    ggplot2::scale_colour_manual(values = n_colors) +
    ggplot2::labs(
      title = "B. Marginal Agronomic Nitrogen Response: ΔY = Y(N) − Y(N0)",
      subtitle = "Filled circle = Observed response; Open diamond = Simulated response (Strict positive gradient)",
      x = "Nitrogen Level (relative to N0)",
      y = "Marginal Yield Increase (t ha-1)",
      caption = demo_caption(is_demo)
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      legend.position = "none",
      strip.background = ggplot2::element_rect(fill = "#EAEDED", colour = "#BDC3C7"),
      strip.text = ggplot2::element_text(face = "bold")
    ) +
    demo_watermark(is_demo)
    
  composite_plot <- patchwork::wrap_plots(plot_a, plot_b, ncol = 1)
  list(plot = composite_plot, source = plot_df, height_mm = 160)
}
