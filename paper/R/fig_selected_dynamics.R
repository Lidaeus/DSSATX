attach_treatment_metadata <- function(data, treatment_metadata, treatments) {
  if (is.null(treatment_metadata)) {
    stop("Treatment metadata is required for water-nitrogen figures", call. = FALSE)
  }
  data$treatment <- as.character(data$treatment)
  treatment_metadata$treatment <- as.character(treatment_metadata$treatment)
  result <- merge(data, treatment_metadata, by = "treatment", all.x = TRUE, sort = FALSE)
  missing <- result[is.na(result$water_level) | is.na(result$nitrogen_level), "treatment"]
  if (length(missing) > 0) {
    stop("Missing water/nitrogen metadata for treatments: ",
         paste(unique(missing), collapse = ", "), call. = FALSE)
  }
  labels <- treatment_metadata$treatment_label[match(treatments, treatment_metadata$treatment)]
  result$treatment_label <- factor(result$treatment_label, levels = labels)
  result
}

management_scales <- function(profile) {
  nitrogen <- unlist(profile$nitrogen_colors, use.names = TRUE)
  water <- unlist(profile$water_shapes, use.names = TRUE)
  list(
    ggplot2::scale_colour_manual(
      name = "Nitrogen level", values = nitrogen, drop = FALSE,
      guide = ggplot2::guide_legend(order = 2, override.aes = list(shape = NA, linewidth = 1.1))
    ),
    ggplot2::scale_fill_manual(values = nitrogen, drop = FALSE, guide = "none"),
    ggplot2::scale_shape_manual(
      name = "Water treatment", values = water, drop = FALSE,
      guide = ggplot2::guide_legend(order = 1)
    )
  )
}

dynamics_theme <- function(profile) {
  theme_q1(profile) +
    ggplot2::theme(
      panel.grid.major.y = ggplot2::element_line(colour = "#E8E8E8", linewidth = 0.25),
      strip.background = ggplot2::element_rect(fill = "#F3F3F3", colour = NA),
      strip.text = ggplot2::element_text(face = "bold", colour = "#303030"),
      panel.spacing = grid::unit(4, "pt"),
      legend.title = ggplot2::element_text(face = "bold", colour = "#303030"),
      legend.box = "horizontal"
    )
}

add_observation_errorbars <- function(plot, observations) {
  errors <- observations[is.finite(observations$observed_se) & observations$observed_se >= 0, , drop = FALSE]
  if (nrow(errors) == 0) return(plot)
  plot + ggplot2::geom_errorbar(
    data = errors,
    ggplot2::aes(x = time, ymin = observed - observed_se, ymax = observed + observed_se),
    width = 0, linewidth = 0.35, colour = "#303030"
  )
}

build_process_dynamics <- function(comparison, trajectory, treatment_metadata, variables,
                                   treatments, profile, is_demo = FALSE) {
  observations <- comparison[comparison$variable %in% variables &
                               as.character(comparison$treatment) %in% treatments, , drop = FALSE]
  simulations <- trajectory[trajectory$variable %in% variables &
                              trajectory$statistic == "deterministic" &
                              as.character(trajectory$treatment) %in% treatments, , drop = FALSE]
  if (nrow(observations) == 0 || nrow(simulations) == 0) {
    stop("Continuous process figures require both observations and daily DSSAT trajectories")
  }
  counts <- stats::aggregate(time ~ variable + treatment, simulations, length)
  if (any(counts$time < 8)) {
    stop("A process trajectory needs at least eight daily values per variable-treatment panel")
  }
  observations <- attach_treatment_metadata(observations, treatment_metadata, treatments)
  simulations <- attach_treatment_metadata(simulations, treatment_metadata, treatments)
  observations$variable_panel <- paste0(observations$variable_label, "\n[", observations$unit, "]")
  simulations$variable_panel <- paste0(simulations$variable_label, "\n[", simulations$unit, "]")
  panel_levels <- unique(simulations$variable_panel[match(variables, simulations$variable)])
  observations$variable_panel <- factor(observations$variable_panel, levels = panel_levels)
  simulations$variable_panel <- factor(simulations$variable_panel, levels = panel_levels)

  plot <- ggplot2::ggplot() +
    ggplot2::geom_line(
      data = simulations,
      ggplot2::aes(x = time, y = simulated, colour = nitrogen_level,
                   group = interaction(treatment, statistic)),
      linewidth = profile$data_linewidth_pt, lineend = "round"
    ) +
    ggplot2::geom_point(
      data = observations,
      ggplot2::aes(x = time, y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.9, stroke = 0.45
    ) +
    ggplot2::facet_grid(variable_panel ~ treatment_label, scales = "free_y", switch = "y") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Observed and simulated growth dynamics",
      subtitle = "Lines: daily DSSAT simulation; points: observed means; error bars: ±SE when available",
      x = "Days after planting", y = NULL, caption = demo_caption(is_demo)
    ) +
    dynamics_theme(profile)
  plot <- add_observation_errorbars(plot, observations)
  list(
    plot = plot,
    observations = observations,
    simulation = simulations,
    height_mm = min(profile$max_height_mm, max(82, 38 * length(variables)))
  )
}

build_harvest_dynamics <- function(comparison, treatment_metadata, increment_variable,
                                   cumulative_variable, treatments, profile, is_demo = FALSE) {
  increment <- comparison[comparison$variable == increment_variable &
                            as.character(comparison$treatment) %in% treatments, , drop = FALSE]
  cumulative <- comparison[comparison$variable == cumulative_variable &
                             as.character(comparison$treatment) %in% treatments, , drop = FALSE]
  if (nrow(increment) == 0 || nrow(cumulative) == 0) {
    stop("Harvest dynamics require paired incremental and cumulative observations")
  }
  increment <- attach_treatment_metadata(increment, treatment_metadata, treatments)
  cumulative <- attach_treatment_metadata(cumulative, treatment_metadata, treatments)
  increment <- increment[order(increment$treatment, increment$time), , drop = FALSE]
  cumulative <- cumulative[order(cumulative$treatment, cumulative$time), , drop = FALSE]

  p_increment <- ggplot2::ggplot(increment, ggplot2::aes(x = time)) +
    ggplot2::geom_segment(
      ggplot2::aes(xend = time, y = 0, yend = simulated, colour = nitrogen_level),
      linewidth = 0.55, alpha = 0.75
    ) +
    ggplot2::geom_point(
      ggplot2::aes(y = simulated, colour = nitrogen_level),
      shape = 1, size = 1.7, stroke = 0.55
    ) +
    ggplot2::geom_point(
      ggplot2::aes(y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.9, stroke = 0.45
    ) +
    ggplot2::facet_wrap(~treatment_label, nrow = 1, scales = "free_y") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Incremental harvest by event",
      subtitle = "Lollipops: simulation; filled points: observed means",
      x = "Days after planting", y = paste0(increment$variable_label[[1]], " [", increment$unit[[1]], "]")
    ) +
    dynamics_theme(profile)
  p_increment <- add_observation_errorbars(p_increment, increment)

  p_cumulative <- ggplot2::ggplot(cumulative, ggplot2::aes(x = time)) +
    ggplot2::geom_line(
      ggplot2::aes(y = simulated, colour = nitrogen_level, group = treatment),
      linewidth = profile$data_linewidth_pt, lineend = "round"
    ) +
    ggplot2::geom_point(
      ggplot2::aes(y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.9, stroke = 0.45
    ) +
    ggplot2::facet_wrap(~treatment_label, nrow = 1, scales = "free_y") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Cumulative harvest at observed events",
      subtitle = "Lines connect simulated values only at observation/harvest dates; points are observed means",
      x = "Days after planting", y = paste0(cumulative$variable_label[[1]], " [", cumulative$unit[[1]], "]")
    ) +
    dynamics_theme(profile)
  p_cumulative <- add_observation_errorbars(p_cumulative, cumulative)

  p_cumulative <- p_cumulative + ggplot2::theme(legend.position = "none")
  plot <- patchwork::wrap_plots(p_increment, p_cumulative, ncol = 1, heights = c(1, 1)) +
    patchwork::plot_annotation(
      tag_levels = "a", caption = demo_caption(is_demo),
      theme = ggplot2::theme(plot.tag = ggplot2::element_text(face = "bold"),
                             plot.caption = ggplot2::element_text(colour = "#666666", size = 5))
    )
  list(plot = plot, increment = increment, cumulative = cumulative,
       height_mm = min(profile$max_height_mm, 145))
}

monotone_cumulative_curve <- function(daily) {
  groups <- split(daily, interaction(daily$variable, daily$treatment, drop = TRUE))
  curves <- lapply(groups, function(frame) {
    frame <- frame[order(frame$time), , drop = FALSE]
    frame <- frame[!duplicated(frame$time), , drop = FALSE]
    if (nrow(frame) < 4) stop("Smooth cumulative view requires at least four daily model values")
    tolerance <- max(1e-8, max(abs(frame$simulated), na.rm = TRUE) * 1e-8)
    if (any(diff(frame$simulated) < -tolerance)) {
      stop("Cumulative DSSAT trajectory decreases; refusing monotone visual interpolation")
    }
    interpolation <- stats::splinefun(frame$time, frame$simulated, method = "monoH.FC")
    grid <- seq(min(frame$time), max(frame$time), length.out = max(240, nrow(frame) * 4))
    values <- interpolation(grid)
    values <- pmin(max(frame$simulated), pmax(min(frame$simulated), values))
    result <- frame[rep(1, length(grid)), , drop = FALSE]
    result$time <- grid
    result$simulated <- values
    result$curve_definition <- "Monotone cubic Hermite interpolation of simulated cumulative values at harvest dates"
    result
  })
  do.call(rbind, curves)
}

build_cumulative_smooth <- function(comparison, trajectory, treatment_metadata,
                                    cumulative_variable, treatments, profile, is_demo = FALSE) {
  observations <- comparison[comparison$variable == cumulative_variable &
                               as.character(comparison$treatment) %in% treatments, , drop = FALSE]
  daily <- trajectory[trajectory$variable == cumulative_variable &
                        trajectory$statistic == "deterministic" &
                        as.character(trajectory$treatment) %in% treatments, , drop = FALSE]
  if (nrow(observations) == 0 || nrow(daily) == 0) {
    stop("Smooth cumulative view requires observations and daily FreshWt.OUT output")
  }
  observations <- attach_treatment_metadata(observations, treatment_metadata, treatments)
  daily <- attach_treatment_metadata(daily, treatment_metadata, treatments)
  curve <- monotone_cumulative_curve(observations)

  plot <- ggplot2::ggplot() +
    ggplot2::geom_line(
      data = curve,
      ggplot2::aes(x = time, y = simulated, colour = nitrogen_level, group = treatment),
      linewidth = profile$data_linewidth_pt, lineend = "round"
    ) +
    ggplot2::geom_point(
      data = observations,
      ggplot2::aes(x = time, y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.9, stroke = 0.45
    ) +
    ggplot2::facet_wrap(~treatment_label, nrow = 1, scales = "free_y") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Continuous cumulative harvest trajectory",
      subtitle = "Smooth lines interpolate simulated cumulative values at harvest dates; points are observed means",
      x = "Days after planting",
      y = paste0(observations$variable_label[[1]], " [", observations$unit[[1]], "]"),
      caption = paste(
        "Visual interpolation only; model metrics are calculated from original outputs.",
        ifelse(isTRUE(is_demo), demo_caption(TRUE), "")
      )
    ) +
    dynamics_theme(profile)
  plot <- add_observation_errorbars(plot, observations)
  list(plot = plot, observations = observations, daily = daily, curve = curve,
       height_mm = min(profile$max_height_mm, 82))
}
