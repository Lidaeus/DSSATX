attach_treatment_metadata <- function(data, treatment_metadata, treatments) {
  if (is.null(treatment_metadata)) {
    stop("Treatment metadata is required for water-nitrogen figures", call. = FALSE)
  }
  data$treatment <- as.character(data$treatment)
  treatment_metadata$treatment <- as.character(treatment_metadata$treatment)

  if (!"season_id" %in% names(data) && "season_id" %in% names(treatment_metadata)) {
    seasons <- unique(as.character(treatment_metadata$season_id))
    if (length(seasons) != 1L || anyNA(seasons)) {
      stop("Multi-season trajectories require explicit season_id; year cannot distinguish spring from autumn", call. = FALSE)
    }
    data$season_id <- seasons[[1]]
  }

  by_cols <- if ("season_id" %in% names(data) && "season_id" %in% names(treatment_metadata)) {
    c("season_id", "treatment")
  } else {
    "treatment"
  }

  result <- merge(data, treatment_metadata, by = by_cols, all.x = TRUE, sort = FALSE)
  missing <- result[is.na(result$water_level) | is.na(result$nitrogen_level), "treatment"]
  if (length(missing) > 0) {
    stop("Missing water/nitrogen metadata for treatments: ",
         paste(unique(missing), collapse = ", "), call. = FALSE)
  }
  present_labels <- unique(as.character(result$treatment_label))
  ordered_labels <- unique(treatment_metadata$treatment_label[treatment_metadata$treatment_label %in% present_labels])
  result$treatment_label <- factor(result$treatment_label, levels = ordered_labels)
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
      linewidth = line_width_mm(profile$data_linewidth_pt), lineend = "round"
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
      ggplot2::aes(y = simulated, colour = nitrogen_level, group = treatment_label),
      linewidth = line_width_mm(profile$data_linewidth_pt), lineend = "round"
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
  split_key <- if ("treatment_label" %in% names(daily)) {
    interaction(daily$variable, daily$treatment_label, drop = TRUE)
  } else if ("season_id" %in% names(daily)) {
    interaction(daily$variable, daily$treatment, daily$season_id, drop = TRUE)
  } else {
    interaction(daily$variable, daily$treatment, drop = TRUE)
  }
  groups <- split(daily, split_key)
  curves <- lapply(groups, function(frame) {
    frame <- frame[order(frame$time), , drop = FALSE]
    frame <- frame[!duplicated(frame$time), , drop = FALSE]
    # monoH.FC is defined for two or more ordered nodes. Autumn has three
    # genuine harvest events; do not fabricate a fourth node to draw the curve.
    if (nrow(frame) < 2) stop("Visual interpolation requires at least two distinct harvest dates")
    tolerance <- max(1e-8, max(abs(frame$simulated), na.rm = TRUE) * 1e-8)
    if (any(diff(frame$simulated) < -tolerance)) {
      stop("Cumulative DSSAT trajectory decreases; refusing monotone visual interpolation")
    }
    interpolation <- stats::splinefun(frame$time, frame$simulated, method = "monoH.FC")
    grid <- seq(min(frame$time), max(frame$time), length.out = max(240, nrow(frame) * 4))
    values <- interpolation(grid)
    values <- pmin(max(frame$simulated), pmax(min(frame$simulated), values))
    if (any(diff(values) < -tolerance)) stop("Interpolated cumulative harvest decreases")
    result <- frame[rep(1, length(grid)), , drop = FALSE]
    result$time <- grid
    result$simulated <- values
    result$curve_definition <- "Monotone cubic Hermite interpolation of simulated cumulative values at harvest dates"
    result
  })
  do.call(rbind, curves)
}

# ── conditional-ensemble dynamics (plan §6) ─────────────────────────────────
# These builders consume only the frozen conditional bundle tables; they never
# read DSSAT/PEST++ outputs and never apply regression-smoothing layers.

build_process_dynamics_conditional <- function(prediction, trajectory, treatment_metadata,
                                               variables, season_treatments, profile,
                                               is_demo = FALSE) {
  in_set <- function(frame) {
    keep <- paste(frame$season_id, frame$treatment) %in%
      paste(season_treatments$season_id, season_treatments$treatment)
    frame[keep, , drop = FALSE]
  }
  observations <- in_set(prediction[prediction$variable %in% variables, , drop = FALSE])
  daily <- in_set(trajectory[trajectory$variable %in% variables, , drop = FALSE])
  if (nrow(observations) == 0 || nrow(daily) == 0) {
    stop("Conditional process dynamics need prediction events and daily trajectory summaries")
  }
  observations <- attach_conditional_metadata(observations, treatment_metadata)
  daily <- attach_conditional_metadata(daily, treatment_metadata)
  variable_labels <- setNames(vapply(variables, function(variable) {
    conditional_axis_label(daily, variable)
  }, character(1)), variables)
  observations$variable_panel <- unname(variable_labels[observations$variable])
  daily$variable_panel <- unname(variable_labels[daily$variable])
  panel_levels <- unique(daily$variable_panel[match(variables, daily$variable)])
  observations$variable_panel <- factor(observations$variable_panel, levels = panel_levels)
  daily$variable_panel <- factor(daily$variable_panel, levels = panel_levels)
  treatment_levels <- conditional_treatment_levels(observations, season_treatments)
  observations$panel_label <- factor(paste0(observations$treatment_label, "\n", observations$season_id),
                                     levels = treatment_levels)
  daily$panel_label <- factor(paste0(daily$treatment_label, "\n", daily$season_id),
                              levels = treatment_levels)

  plot <- ggplot2::ggplot() +
    ggplot2::geom_ribbon(
      data = daily,
      ggplot2::aes(x = dap, ymin = sim_q025, ymax = sim_q975, fill = nitrogen_level),
      alpha = 0.28, colour = NA
    ) +
    ggplot2::geom_ribbon(
      data = daily,
      ggplot2::aes(x = dap, ymin = sim_q25, ymax = sim_q75, fill = nitrogen_level),
      alpha = 0.42, colour = NA
    ) +
    ggplot2::geom_line(
      data = daily,
      ggplot2::aes(x = dap, y = sim_median, colour = nitrogen_level),
      linewidth = line_width_mm(profile$data_linewidth_pt), lineend = "round"
    ) +
    ggplot2::geom_point(
      data = observations,
      ggplot2::aes(x = dap, y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.65, stroke = 0.42
    ) +
    ggplot2::facet_grid(variable_panel ~ panel_label, scales = "free_y", switch = "y") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Growth dynamics with conditional-ensemble uncertainty",
      subtitle = paste0("Line: conditional-ensemble median daily simulation; ribbons: ",
                        "25–75% and 95% conditional-ensemble prediction intervals; ",
                        "points: observed means"),
      x = "Days after planting", y = NULL,
      caption = paste(
        "95% conditional-ensemble prediction interval (parameter ensemble only).",
        ifelse(isTRUE(is_demo), demo_caption(TRUE), "")
      )
    ) +
    dynamics_theme(profile)
  plot <- add_conditional_observation_errorbars(plot, observations)
  list(
    plot = plot,
    observations = observations,
    daily = daily,
    height_mm = min(profile$max_height_mm, max(82, 38 * length(variables)))
  )
}

add_conditional_observation_errorbars <- function(plot, observations) {
  if (is.null(observations$observed_se)) return(plot)
  errors <- observations[is.finite(observations$observed_se) & observations$observed_se >= 0, , drop = FALSE]
  if (nrow(errors) == 0) return(plot)
  plot + ggplot2::geom_errorbar(
    data = errors,
    ggplot2::aes(x = dap, ymin = observed - observed_se, ymax = observed + observed_se),
    width = 0, linewidth = 0.35, colour = "#303030"
  )
}

build_harvest_dynamics_conditional <- function(prediction, treatment_metadata,
                                               increment_variable, cumulative_variable,
                                               season_treatments, profile, is_demo = FALSE) {
  in_set <- function(frame) {
    keep <- paste(frame$season_id, frame$treatment) %in%
      paste(season_treatments$season_id, season_treatments$treatment)
    frame[keep, , drop = FALSE]
  }
  increment <- in_set(prediction[prediction$variable == increment_variable, , drop = FALSE])
  cumulative <- in_set(prediction[prediction$variable == cumulative_variable, , drop = FALSE])
  if (nrow(increment) == 0 || nrow(cumulative) == 0) {
    stop("Conditional harvest dynamics need incremental and cumulative event summaries")
  }
  increment <- attach_conditional_metadata(increment, treatment_metadata)
  cumulative <- attach_conditional_metadata(cumulative, treatment_metadata)
  increment <- increment[order(increment$treatment, increment$dap), , drop = FALSE]
  cumulative <- cumulative[order(cumulative$treatment, cumulative$dap), , drop = FALSE]
  treatment_levels <- conditional_treatment_levels(increment, season_treatments)
  increment$panel_label <- factor(paste0(increment$treatment_label, "\n", increment$season_id),
                                  levels = treatment_levels)
  cumulative$panel_label <- factor(paste0(cumulative$treatment_label, "\n", cumulative$season_id),
                                   levels = treatment_levels)

  # Incremental harvest: paired event points of the ensemble median with vertical
  # 95% intervals; never connected into a growth curve (plan §6.1).
  p_increment <- ggplot2::ggplot(increment, ggplot2::aes(x = dap)) +
    ggplot2::geom_errorbar(
      ggplot2::aes(ymin = sim_q025, ymax = sim_q975, colour = nitrogen_level),
      width = 0, linewidth = 0.45, alpha = 0.65
    ) +
    ggplot2::geom_point(
      ggplot2::aes(y = sim_median, colour = nitrogen_level),
      shape = 1, size = 1.8, stroke = 0.65
    ) +
    ggplot2::geom_point(
      ggplot2::aes(y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.75, stroke = 0.45
    ) +
    ggplot2::facet_wrap(~panel_label, nrow = 1, scales = "fixed") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Incremental harvest by event",
      subtitle = "Points and error bars: conditional-ensemble median with 95% interval; filled points: observed means",
      x = "Days after planting",
      y = conditional_axis_label(increment, increment_variable)
    ) +
    dynamics_theme(profile)
  p_increment <- add_conditional_observation_errorbars(p_increment, increment)

  # Cumulative harvest: event-step median line + per-event ribbons; no
  # interpolation layer, metrics never use interpolated nodes.
  p_cumulative <- ggplot2::ggplot() +
    ggplot2::geom_ribbon(
      data = cumulative,
      ggplot2::aes(x = dap, ymin = sim_q025, ymax = sim_q975, fill = nitrogen_level,
                   group = treatment),
      alpha = 0.28, colour = NA
    ) +
    ggplot2::geom_ribbon(
      data = cumulative,
      ggplot2::aes(x = dap, ymin = sim_q25, ymax = sim_q75, fill = nitrogen_level,
                   group = treatment),
      alpha = 0.42, colour = NA
    ) +
    ggplot2::geom_line(
      data = cumulative,
      ggplot2::aes(x = dap, y = sim_median, colour = nitrogen_level, group = treatment),
      linewidth = line_width_mm(profile$data_linewidth_pt), lineend = "round"
    ) +
    ggplot2::geom_point(
      data = cumulative,
      ggplot2::aes(x = dap, y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.65, stroke = 0.42
    ) +
    ggplot2::facet_wrap(~panel_label, nrow = 1, scales = "fixed") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Cumulative harvest at observed events",
      subtitle = "Line: ensemble median connecting simulated values at harvest dates; ribbon: 95% interval",
      x = "Days after planting",
      y = conditional_axis_label(cumulative, cumulative_variable)
    ) +
    dynamics_theme(profile)
  p_cumulative <- add_conditional_observation_errorbars(p_cumulative, cumulative)

  p_cumulative <- p_cumulative + ggplot2::theme(legend.position = "none")
  plot <- patchwork::wrap_plots(p_increment, p_cumulative, ncol = 1, heights = c(1, 1)) +
    patchwork::plot_annotation(
      tag_levels = "a",
      caption = demo_caption(is_demo),
      theme = ggplot2::theme(plot.tag = ggplot2::element_text(face = "bold"),
                             plot.caption = ggplot2::element_text(colour = "#666666", size = 5))
    )
  list(plot = plot, increment = increment, cumulative = cumulative,
       height_mm = min(profile$max_height_mm, 145))
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
      ggplot2::aes(x = time, y = simulated, colour = nitrogen_level, group = treatment_label),
      linewidth = line_width_mm(profile$data_linewidth_pt), lineend = "round"
    ) +
    ggplot2::geom_point(
      data = observations,
      ggplot2::aes(x = time, y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.9, stroke = 0.45
    ) +
    ggplot2::facet_wrap(~treatment_label, nrow = 1, scales = "free_y") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Cumulative harvest: visual interpolation",
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
