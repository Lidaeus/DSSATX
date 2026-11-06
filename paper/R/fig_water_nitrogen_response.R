# fig_water_nitrogen_response.R - Agronomic Water-Nitrogen Response Gradients & Interactions
# Produces Fig. 6: terminal yield curves across discrete nitrogen levels,
# plus a separate signed water-response figure.

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
  plot_df$season_id <- factor(plot_df$season_id, levels = c("25SP", "26SP", "25FA"))
  
  # Colors from profile
  n_colors <- unlist(profile$nitrogen_colors, use.names = TRUE)
  if (is.null(n_colors)) n_colors <- c(N3 = "#C0392B", N2 = "#E67E22", N1 = "#2980B9", N0 = "#7F8C8D")
  
  # Each treatment's observed and simulated points share exactly the same x.
  # Connect the discrete N levels within each season/water panel; no smoothing.
  plot_df$nitrogen_position <- as.integer(plot_df$nitrogen_level)
  plot_a <- ggplot2::ggplot(plot_df, ggplot2::aes(x = nitrogen_position)) +
    ggplot2::geom_segment(ggplot2::aes(xend = nitrogen_position,
        y = observed / 1000.0, yend = simulated / 1000.0),
        colour = "#BDC3C7", linewidth = line_width_mm(0.5), linetype = "dotted") +
    ggplot2::geom_line(ggplot2::aes(y = observed / 1000.0, group = 1),
        colour = "#222222", linewidth = line_width_mm(profile$data_linewidth_pt)) +
    ggplot2::geom_line(ggplot2::aes(y = simulated / 1000.0, group = 1),
        colour = "#929292", linewidth = line_width_mm(profile$data_linewidth_pt)) +
    ggplot2::geom_point(ggplot2::aes(y = observed / 1000.0, fill = nitrogen_level, shape = water_level),
        colour = "#222222", size = 2.1, stroke = 0.4) +
    ggplot2::geom_point(ggplot2::aes(y = simulated / 1000.0, colour = nitrogen_level, shape = water_level),
        fill = "white", size = 2.1, stroke = 0.6) +
    ggplot2::facet_grid(season_id ~ water_level, scales = "free_y") +
    ggplot2::scale_x_continuous(breaks = 1:4, labels = c("N0", "N1", "N2", "N3"),
        limits = c(0.7, 4.3), expand = c(0, 0)) +
    ggplot2::scale_y_continuous(expand = ggplot2::expansion(mult = c(0.10, 0.12))) +
    ggplot2::scale_shape_manual(values = unlist(profile$water_shapes)) +
    ggplot2::scale_fill_manual(values = n_colors) +
    ggplot2::scale_colour_manual(values = n_colors) +
    ggplot2::labs(
      title = "Terminal fresh-fruit yield across nitrogen levels",
      subtitle = "Filled points / dark line: observed; open points / grey line: simulated",
      x = "Nitrogen level",
      y = expression("Fresh-fruit yield (t " * ha^{-1} * ")"),
      caption = paste("Straight lines join available treatments; y-axis ranges differ by season.",
                      demo_caption(is_demo))
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      legend.position = "none",
      strip.background = ggplot2::element_rect(fill = "#EAEDED", colour = "#BDC3C7"),
      strip.text = ggplot2::element_text(face = "bold"),
      panel.spacing = grid::unit(3, "mm"),
      plot.margin = ggplot2::margin(3, 4, 3, 4, unit = "mm")
    ) +
    demo_watermark(is_demo)
    
  # Complement nitrogen responses with signed water responses at matched N.
  # Missing W x N cells stay absent; CK is not an irrigation-gradient level.
  fresh <- merged[merged$variable == "FRESH_CUM" & merged$water_level != "CK", ]
  water_rows <- lapply(split(fresh, list(fresh$season_id, fresh$nitrogen_level), drop = TRUE), function(d) {
    ref <- d[d$water_level == "W1", ]
    if (nrow(ref) != 1L) return(NULL)
    d$water_delta_observed <- (d$observed - ref$observed) / 1000
    d$water_delta_simulated <- (d$simulated - ref$simulated) / 1000
    d[d$water_level != "W1", ]
  })
  water_data <- do.call(rbind, water_rows)
  water_data$season_id <- factor(water_data$season_id, levels = c("25SP", "26SP", "25FA"))
  water_data$nitrogen_level <- factor(water_data$nitrogen_level, levels = c("N0", "N1", "N2", "N3"))
  water_data$water_position <- match(water_data$water_level, c("W2", "W3"))
  water_plot <- ggplot2::ggplot(water_data, ggplot2::aes(x = water_position)) +
    ggplot2::geom_hline(yintercept = 0, colour = "#707070", linetype = "dashed", linewidth = 0.3) +
    ggplot2::geom_segment(ggplot2::aes(x = water_position - .10, xend = water_position + .10,
        y = water_delta_observed, yend = water_delta_simulated), colour = "#B0B0B0", linewidth = .3) +
    ggplot2::geom_point(ggplot2::aes(y = water_delta_observed, fill = nitrogen_level, shape = water_level),
        colour = "#222222", size = 2, stroke = .4, position = ggplot2::position_nudge(x = -.10)) +
    ggplot2::geom_point(ggplot2::aes(y = water_delta_simulated, colour = nitrogen_level, shape = water_level),
        fill = "white", size = 2, stroke = .6, position = ggplot2::position_nudge(x = .10)) +
    ggplot2::scale_x_continuous(breaks = 1:2, labels = c("W2", "W3"), limits = c(.6, 2.4)) +
    ggplot2::scale_fill_manual(values = n_colors) +
    ggplot2::scale_colour_manual(values = n_colors) +
    ggplot2::scale_shape_manual(values = unlist(profile$water_shapes)) +
    ggplot2::facet_grid(season_id ~ nitrogen_level) +
    ggplot2::labs(title = "Water response at matched nitrogen: ΔY = Y(W) − Y(W1)",
        subtitle = "Filled: observed; open: simulated; absent treatment combinations are left blank",
        x = "Water level (reference: W1)", y = "Fresh-yield difference (t ha-1)", caption = demo_caption(is_demo)) +
    theme_q1(profile) + ggplot2::theme(legend.position = "none",
        strip.background = ggplot2::element_rect(fill = "#EAEDED", colour = NA)) + demo_watermark(is_demo)
  list(plot = plot_a, source = plot_df,
       height_mm = min(profile$max_height_mm, 35 + 31 * length(unique(plot_df$season_id))),
       water_plot = water_plot, water_source = water_data,
       water_height_mm = min(profile$max_height_mm, 35 + 37 * length(unique(plot_df$season_id))))
}
