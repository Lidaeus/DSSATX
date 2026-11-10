# Leaf nitrogen content (LN%D) model performance and temporal dynamics.
# Obey publication.json contracts: R >= 4.3, strict two-track separation,
# strictly empirical points and deterministic trajectory lines; no statistical smoother.

build_leaf_nitrogen <- function(comparison, trajectory, treatment_metadata,
                                profile, is_demo = FALSE) {
  if (is.null(treatment_metadata)) {
    stop("Treatment metadata is required for leaf nitrogen figures", call. = FALSE)
  }

  # 1. Filter observations and simulations for LN%D
  obs_data <- comparison[comparison$variable == "LN%D", , drop = FALSE]
  if (nrow(obs_data) == 0) {
    stop("fig_leaf_nitrogen requires LN%D observations in comparison table", call. = FALSE)
  }

  sim_data <- trajectory[trajectory$variable == "LN%D" &
                           trajectory$statistic == "deterministic", , drop = FALSE]
  if (nrow(sim_data) == 0) {
    stop("fig_leaf_nitrogen requires LN%D daily simulations in trajectory table", call. = FALSE)
  }

  # 2. Attach treatment metadata
  obs_data <- attach_treatment_metadata(obs_data, treatment_metadata, unique(as.character(obs_data$treatment)))
  sim_data <- attach_treatment_metadata(sim_data, treatment_metadata, unique(as.character(sim_data$treatment)))

  # Ensure nitrogen levels and water levels follow canonical factor orders
  nitrogen_levels_order <- c("N3", "N2", "N1", "N0", "CK")
  if ("CK" %in% treatment_metadata$nitrogen_level) profile$nitrogen_colors$CK <- "#707070"
  water_levels_order <- c("W3", "W2", "W1", "CK")
  obs_data$nitrogen_level <- factor(obs_data$nitrogen_level, levels = nitrogen_levels_order)
  sim_data$nitrogen_level <- factor(sim_data$nitrogen_level, levels = nitrogen_levels_order)
  obs_data$water_level <- factor(obs_data$water_level, levels = water_levels_order)
  sim_data$water_level <- factor(sim_data$water_level, levels = water_levels_order)

  # 3. Compute evaluation metrics
  n_pts <- nrow(obs_data)
  residual <- obs_data$simulated - obs_data$observed
  rmse <- sqrt(mean(residual^2))
  obs_mean <- mean(obs_data$observed)
  nrmse <- if (obs_mean > 0) (rmse / obs_mean) * 100.0 else NA_real_
  mae <- mean(abs(residual))
  bias <- mean(residual)
  ss_res <- sum(residual^2)
  ss_tot <- sum((obs_data$observed - obs_mean)^2)
  r2 <- if (stats::sd(obs_data$observed) > 0 && stats::sd(obs_data$simulated) > 0) {
    stats::cor(obs_data$observed, obs_data$simulated)^2
  } else NA_real_
  nse <- if (ss_tot > 0) 1.0 - (ss_res / ss_tot) else NA_real_
  denom_d <- sum((abs(obs_data$simulated - obs_mean) + abs(obs_data$observed - obs_mean))^2)
  d_index <- if (denom_d > 0) 1.0 - (ss_res / denom_d) else NA_real_

  metrics <- data.frame(
    variable = "LN%D",
    n = n_pts,
    rmse = rmse,
    nrmse_pct = nrmse,
    mae = mae,
    bias = bias,
    r2 = r2,
    nse = nse,
    d_index = d_index,
    stringsAsFactors = FALSE
  )

  # 4. Panel (a): 1:1 Scatter Plot
  all_vals <- c(obs_data$observed, obs_data$simulated)
  if ("observed_se" %in% names(obs_data)) {
    valid_se <- is.finite(obs_data$observed_se) & obs_data$observed_se > 0
    if (any(valid_se)) {
      all_vals <- c(all_vals,
                    obs_data$observed[valid_se] - obs_data$observed_se[valid_se],
                    obs_data$observed[valid_se] + obs_data$observed_se[valid_se])
    }
  }
  all_vals <- all_vals[is.finite(all_vals)]
  val_min <- 0
  val_max <- max(all_vals) * 1.08
  limits <- c(val_min, val_max)

  annot_text <- sprintf(
    "n = %d\nRMSE = %.2f pp\nNRMSE = %.1f %%\nR\u00B2 = %.3f\nd = %.3f\nBias = %+.2f pp",
    n_pts, rmse, nrmse, r2, d_index, bias
  )

  p_scatter <- ggplot2::ggplot(obs_data, ggplot2::aes(x = observed, y = simulated)) +
    ggplot2::geom_abline(slope = 1, intercept = 0, colour = "#555555", linewidth = 0.5, linetype = "dashed") +
    (if ("observed_se" %in% names(obs_data)) {
      err_sub <- obs_data[is.finite(obs_data$observed_se) & obs_data$observed_se > 0, , drop = FALSE]
      if (nrow(err_sub) > 0) {
        ggplot2::geom_errorbar(
          data = err_sub,
          ggplot2::aes(y = simulated, xmin = observed - observed_se, xmax = observed + observed_se),
          width = 0, linewidth = 0.35, colour = "#666666"
        )
      } else NULL
    } else NULL) +
    ggplot2::geom_point(
      ggplot2::aes(fill = nitrogen_level, shape = water_level),
      colour = "#222222", size = 2.4, stroke = 0.55
    ) +
    ggplot2::annotate(
      "label", x = limits[2] - 0.04 * diff(limits), y = limits[1] + 0.04 * diff(limits),
      hjust = 1, vjust = 0, label = annot_text, size = 2.1,
      linewidth = 0, fill = "white", alpha = 0.85
    ) +
    ggplot2::coord_equal(xlim = limits, ylim = limits, expand = FALSE) +
    ggplot2::scale_fill_manual(values = unlist(profile$nitrogen_colors), guide = "none") +
    ggplot2::scale_shape_manual(values = unlist(profile$water_shapes), guide = "none") +
    ggplot2::labs(
      title = "Leaf N 1:1 Evaluation",
      x = "Observed leaf N [%]",
      y = "Simulated leaf N [%]"
    ) +
    theme_q1(profile)

  # 5. Panel (b): Dynamic Temporal Curves Across Nitrogen Levels
  # Facet by water regime present in the data
  water_facets <- unique(as.character(sim_data$water_level))
  water_facets <- water_facets[!is.na(water_facets)]
  # Exclude treatments with fewer than 8 daily simulation values if any
  sim_counts <- stats::aggregate(time ~ treatment, sim_data, length)
  valid_tmts <- sim_counts$treatment[sim_counts$time >= 8]
  sim_plot <- sim_data[sim_data$treatment %in% valid_tmts, , drop = FALSE]
  if ("season_id" %in% names(obs_data) && any(!is.na(obs_data$season_id))) {
    sim_plot <- sim_plot[sim_plot$season_id %in% unique(obs_data$season_id), , drop = FALSE]
  }
  # Keep only treatments that have observations for consistent comparison
  sim_plot <- sim_plot[sim_plot$treatment %in% unique(obs_data$treatment), , drop = FALSE]

  # Format facet labels
  sim_plot$facet_label <- paste0(sim_plot$water_level, " Water Regime")
  obs_plot <- obs_data
  obs_plot$facet_label <- paste0(obs_plot$water_level, " Water Regime")
  facet_levels <- paste0(water_levels_order, " Water Regime")
  facet_levels <- facet_levels[facet_levels %in% unique(obs_plot$facet_label)]
  sim_plot$facet_label <- factor(sim_plot$facet_label, levels = facet_levels)
  obs_plot$facet_label <- factor(obs_plot$facet_label, levels = facet_levels)

  p_dynamics <- ggplot2::ggplot() +
    ggplot2::geom_line(
      data = sim_plot,
      ggplot2::aes(
        x = time, y = simulated, colour = nitrogen_level,
        group = interaction(treatment, if ("season_id" %in% names(sim_plot)) season_id else 1)
      ),
      linewidth = line_width_mm(profile$data_linewidth_pt), lineend = "round"
    ) +
    (if ("observed_se" %in% names(obs_plot)) {
      err_dyn <- obs_plot[is.finite(obs_plot$observed_se) & obs_plot$observed_se > 0, , drop = FALSE]
      if (nrow(err_dyn) > 0) {
        ggplot2::geom_errorbar(
          data = err_dyn,
          ggplot2::aes(x = time, ymin = observed - observed_se, ymax = observed + observed_se),
          width = 0, linewidth = 0.35, colour = "#444444"
        )
      } else NULL
    } else NULL) +
    ggplot2::geom_point(
      data = obs_plot,
      ggplot2::aes(x = time, y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#222222", size = 2.2, stroke = 0.55
    ) +
    ggplot2::facet_wrap(~ facet_label, scales = "fixed", ncol = length(facet_levels)) +
    management_scales(profile) +
    ggplot2::labs(
      title = "Leaf Nitrogen Dynamics Across Nitrogen Levels",
      x = "Days after planting (DAP)",
      y = "Leaf N concentration [%]"
    ) +
    dynamics_theme(profile)

  # 6. Compose with patchwork
  p_scatter <- p_scatter + ggplot2::guides(colour = "none", fill = "none", shape = "none")
  composite <- (p_scatter / p_dynamics) +
    patchwork::plot_layout(heights = c(1, 1), guides = "collect") +
    patchwork::plot_annotation(
      tag_levels = "a",
      caption = demo_caption(is_demo),
      theme = ggplot2::theme(
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5)
      )
    ) &
    ggplot2::theme(
      legend.position = "bottom",
      legend.box = "vertical",
      legend.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt)
    )

  list(
    plot = composite,
    source = obs_data,
    metrics = metrics,
    daily = sim_plot,
    height_mm = min(profile$max_height_mm, 158.0)
  )
}
