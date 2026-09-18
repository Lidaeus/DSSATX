all_treatment_theme <- function(profile) {
  dynamics_theme(profile) +
    ggplot2::theme(
      legend.position = "top",
      strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.3)
    )
}

build_all_treatment_process <- function(comparison, trajectory, treatment_metadata,
                                        variables, treatments, profile, is_demo = FALSE,
                                        facet_columns = 5L) {
  results <- list()
  for (variable in variables) {
    observations <- comparison[comparison$variable == variable &
                                 as.character(comparison$treatment) %in% treatments, , drop = FALSE]
    simulations <- trajectory[trajectory$variable == variable &
                                trajectory$statistic == "deterministic" &
                                as.character(trajectory$treatment) %in% treatments, , drop = FALSE]
    if (nrow(observations) == 0 || nrow(simulations) == 0) next
    counts <- stats::aggregate(time ~ treatment, simulations, length)
    if (any(counts$time < 8)) {
      stop("All-treatment process panels require at least eight daily values per treatment")
    }
    observations <- attach_treatment_metadata(observations, treatment_metadata, treatments)
    simulations <- attach_treatment_metadata(simulations, treatment_metadata, treatments)
    unit <- observations$unit[[1]]
    label <- observations$variable_label[[1]]

    plot <- ggplot2::ggplot() +
      ggplot2::geom_line(
        data = simulations,
        ggplot2::aes(x = time, y = simulated, colour = nitrogen_level, group = treatment),
        linewidth = profile$data_linewidth_pt, lineend = "round"
      ) +
      ggplot2::geom_point(
        data = observations,
        ggplot2::aes(x = time, y = observed, fill = nitrogen_level, shape = water_level),
        colour = "#202020", size = 1.55, stroke = 0.4
      ) +
      ggplot2::facet_wrap(~treatment_label, ncol = facet_columns, scales = "free_y") +
      management_scales(profile) +
      ggplot2::labs(
        title = paste0(label, " across all treatments"),
        subtitle = "Lines: daily DSSAT simulation; points: observed means",
        x = "Days after planting", y = paste0(label, " [", unit, "]"),
        caption = demo_caption(is_demo)
      ) +
      all_treatment_theme(profile)
    plot <- add_observation_errorbars(plot, observations)
    results[[variable]] <- list(plot = plot, observations = observations,
                                simulation = simulations,
                                height_mm = min(profile$max_height_mm, 108))
  }
  results
}

# ── conditional-ensemble all-treatment dynamics (plan §6.3) ────────────────
# Layout is a water x nitrogen matrix per season: 26SP is a complete 3x4
# factorial; 25SP is an incomplete factorial whose empty cells stay visibly
# empty (drop = FALSE) instead of being fabricated.  Y scales are fixed within
# a season (no free_y) so water-nitrogen response compression cannot hide.

conditional_matrix_panel_labels <- function(treatment_metadata, season) {
  part <- treatment_metadata[treatment_metadata$season_id == season, , drop = FALSE]
  data.frame(
    season_id = season,
    water_level = part$water_level,
    nitrogen_level = part$nitrogen_level,
    tn_role = paste0("TN", part$treatment, " [",
                     ifelse(part$dataset_role == "calibration", "Cal",
                            ifelse(part$dataset_role == "validation", "Val", "Diag")), "]")
  )
}

conditional_matrix_plot <- function(data, events, panel_labels, y_limits, y_label, title,
                                    profile, is_demo, ribbons = TRUE,
                                    water_levels = c("W3", "W2", "W1", "CK"),
                                    show_legend = TRUE, incremental = FALSE) {
  nitrogen <- unlist(profile$nitrogen_colors, use.names = TRUE)
  water <- unlist(profile$water_shapes, use.names = TRUE)
  nitrogen_levels <- c("N3", "N2", "N1", "N0")
  data$water_level <- factor(data$water_level, levels = water_levels)
  data$nitrogen_level <- factor(data$nitrogen_level, levels = nitrogen_levels)
  panel_labels$water_level <- factor(panel_labels$water_level, levels = water_levels)
  panel_labels$nitrogen_level <- factor(panel_labels$nitrogen_level, levels = nitrogen_levels)
  has_events <- !is.null(events) && nrow(events) > 0
  if (has_events) {
    events$water_level <- factor(events$water_level, levels = water_levels)
    events$nitrogen_level <- factor(events$nitrogen_level, levels = nitrogen_levels)
  }

  plot <- ggplot2::ggplot()
  if (ribbons && !incremental) {
    # Two-tier conditional interval: the 25-75% band sits on top of the
    # lighter 95% band so narrow DEMO ensembles remain readable at print size.
    plot <- plot +
      ggplot2::geom_ribbon(
        data = data,
        ggplot2::aes(x = dap, ymin = sim_q025, ymax = sim_q975, fill = nitrogen_level,
                     group = treatment),
        alpha = 0.28, colour = NA
      ) +
      ggplot2::geom_ribbon(
        data = data,
        ggplot2::aes(x = dap, ymin = sim_q25, ymax = sim_q75, fill = nitrogen_level,
                     group = treatment),
        alpha = 0.42, colour = NA
      )
  }
  if (incremental) {
    plot <- plot + ggplot2::geom_segment(
      data = data, ggplot2::aes(x = dap, xend = dap, y = 0, yend = sim_median,
                                colour = nitrogen_level), linewidth = 0.45)
  } else plot <- plot +
    ggplot2::geom_line(
      data = data,
      ggplot2::aes(x = dap, y = sim_median, colour = nitrogen_level, group = treatment),
      linewidth = profile$data_linewidth_pt * 0.9, lineend = "round"
    )
  if (has_events) {
    # Observed points live in the event summary, not the daily trajectory
    # table; draw them as their own layer over the median curves.
    if (!is.null(events$observed_se)) {
      errors <- events[is.finite(events$observed_se) & events$observed_se >= 0, , drop = FALSE]
      if (nrow(errors) > 0) {
        plot <- plot + ggplot2::geom_errorbar(
          data = errors,
          ggplot2::aes(x = dap, ymin = observed - observed_se, ymax = observed + observed_se),
          width = 0, linewidth = 0.35, colour = "#303030"
        )
      }
    }
    plot <- plot +
      ggplot2::geom_point(
        data = events,
        ggplot2::aes(x = dap, y = observed, fill = nitrogen_level, shape = water_level),
        colour = "#202020", size = 1.6, stroke = 0.45
      )
  }
  plot <- plot +
    ggplot2::geom_text(
      data = panel_labels,
      ggplot2::aes(x = -Inf, y = Inf, label = tn_role),
      hjust = -0.05, vjust = 1.4, size = 1.7, colour = "#555555", inherit.aes = FALSE
    ) +
    ggplot2::facet_grid(nitrogen_level ~ water_level, drop = FALSE, switch = "y") +
    ggplot2::coord_cartesian(ylim = y_limits) +
    management_scales(profile) +
    ggplot2::labs(title = title, x = "Days after planting", y = y_label,
                  caption = demo_caption(is_demo)) +
    all_treatment_theme(profile) +
    ggplot2::theme(legend.position = if (isTRUE(show_legend)) "top" else "none")
  plot
}

build_all_treatment_dynamics_conditional <- function(prediction, trajectory, treatment_metadata,
                                                     variables, profile, is_demo = FALSE) {
  results <- list()
  for (variable in variables) {
    daily <- trajectory[trajectory$variable == variable, , drop = FALSE]
    events <- prediction[prediction$variable == variable, , drop = FALSE]
    if (nrow(daily) == 0 && nrow(events) == 0) next
    if (nrow(daily) > 0) daily <- attach_conditional_metadata(daily, treatment_metadata)
    if (nrow(events) > 0) events <- attach_conditional_metadata(events, treatment_metadata)

    is_harvest <- variable %in% c("DRY_CUM", "FRESH_CUM", "CUM_HARVEST", "FRESH_HARVEST", "DRY_INC", "FRESH_INC")

    season_plots <- list()
    observations_out <- list()
    daily_out <- list()
    label_frame <- if (nrow(events) > 0) events else daily
    y_label <- conditional_axis_label(label_frame, variable)

    available_seasons <- unique(c(as.character(daily$season_id), as.character(events$season_id)))
    for (season in intersect(c("25SP", "26SP"), available_seasons)) {
      season_daily <- daily[daily$season_id == season, , drop = FALSE]
      season_events <- events[events$season_id == season, , drop = FALSE]
      labels <- conditional_matrix_panel_labels(treatment_metadata, season)

      # For cumulative harvest, use events (ordered by dap) to connect simulated harvest nodes
      # and uncertainty bands strictly between harvest dates, matching the event line style.
      if (is_harvest && nrow(season_events) > 0) {
        season_events <- season_events[order(season_events$treatment, season_events$dap), , drop = FALSE]
        source_frame <- season_events
      } else {
        source_frame <- if (nrow(season_daily) > 0) season_daily else season_events
      }

      season_values <- c()
      if (nrow(source_frame) > 0) {
        season_values <- c(season_values, source_frame$sim_q025, source_frame$sim_q975)
      }
      if (nrow(season_events) > 0) {
        season_values <- c(season_values, season_events$observed, season_events$sim_q975)
        if ("observed_se" %in% names(season_events)) {
          valid <- is.finite(season_events$observed_se) & season_events$observed_se >= 0
          season_values <- c(season_values, season_events$observed[valid] - season_events$observed_se[valid],
                             season_events$observed[valid] + season_events$observed_se[valid])
        }
      }
      season_values <- season_values[is.finite(season_values)]
      if (!length(season_values)) stop("No finite values for dynamic axis limits")
      y_limits <- c(min(0, min(season_values)), max(1e-6, max(season_values)) * 1.04)
      season_water_levels <- if (season == "26SP") c("W3", "W2", "W1") else c("W3", "W2", "W1", "CK")
      plot <- conditional_matrix_plot(
        source_frame, season_events, labels, y_limits, y_label,
        paste0(season, " | ", unique(source_frame$variable_label)[[1]], " | all treatments"),
        profile, is_demo, ribbons = nrow(source_frame) > 0,
        water_levels = season_water_levels,
        show_legend = length(season_plots) == 0,
        incremental = variable %in% c("DRY_INC", "FRESH_INC")
      )
      season_plots[[length(season_plots) + 1]] <- plot
      observations_out[[season]] <- season_events
      daily_out[[season]] <- season_daily
    }
    combined <- patchwork::wrap_plots(season_plots, ncol = 1)
    results[[variable]] <- list(
      plot = combined,
      observations = do.call(rbind, observations_out),
      daily = do.call(rbind, daily_out),
      height_mm = profile$max_height_mm
    )
  }
  results
}

build_all_treatment_harvest <- function(comparison, trajectory, treatment_metadata,
                                        increment_variable, cumulative_variable,
                                        treatments, profile, is_demo = FALSE,
                                        facet_columns = 5L) {
  increment <- comparison[comparison$variable == increment_variable &
                            as.character(comparison$treatment) %in% treatments, , drop = FALSE]
  cumulative <- comparison[comparison$variable == cumulative_variable &
                             as.character(comparison$treatment) %in% treatments, , drop = FALSE]
  daily <- trajectory[trajectory$variable == cumulative_variable &
                        trajectory$statistic == "deterministic" &
                        as.character(trajectory$treatment) %in% treatments, , drop = FALSE]
  if (nrow(increment) == 0 || nrow(cumulative) == 0 || nrow(daily) == 0) {
    stop("All-treatment harvest figures require incremental, cumulative, and daily trajectory data")
  }
  increment <- attach_treatment_metadata(increment, treatment_metadata, treatments)
  cumulative <- attach_treatment_metadata(cumulative, treatment_metadata, treatments)
  daily <- attach_treatment_metadata(daily, treatment_metadata, treatments)
  increment <- increment[order(increment$treatment, increment$time), , drop = FALSE]
  cumulative <- cumulative[order(cumulative$treatment, cumulative$time), , drop = FALSE]
  smooth_curve <- monotone_cumulative_curve(cumulative)

  p_increment <- ggplot2::ggplot(increment, ggplot2::aes(x = time)) +
    ggplot2::geom_segment(
      ggplot2::aes(xend = time, y = 0, yend = simulated, colour = nitrogen_level),
      linewidth = 0.48, alpha = 0.75
    ) +
    ggplot2::geom_point(
      ggplot2::aes(y = simulated, colour = nitrogen_level),
      shape = 1, size = 1.4, stroke = 0.5
    ) +
    ggplot2::geom_point(
      ggplot2::aes(y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.55, stroke = 0.4
    ) +
    ggplot2::facet_wrap(~treatment_label, ncol = facet_columns, scales = "free_y") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Incremental fresh harvest across all treatments",
      subtitle = "Lollipops: simulation; filled points: observed means",
      x = "Days after planting",
      y = paste0(increment$variable_label[[1]], " [", increment$unit[[1]], "]"),
      caption = demo_caption(is_demo)
    ) +
    all_treatment_theme(profile)
  p_increment <- add_observation_errorbars(p_increment, increment)

  p_event <- ggplot2::ggplot(cumulative, ggplot2::aes(x = time)) +
    ggplot2::geom_line(
      ggplot2::aes(y = simulated, colour = nitrogen_level, group = treatment_label),
      linewidth = profile$data_linewidth_pt, lineend = "round"
    ) +
    ggplot2::geom_point(
      ggplot2::aes(y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.55, stroke = 0.4
    ) +
    ggplot2::facet_wrap(~treatment_label, ncol = facet_columns, scales = "free_y") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Cumulative fresh harvest at observed events",
      subtitle = "Lines connect simulated cumulative values at harvest dates; points are observed means",
      x = "Days after planting",
      y = paste0(cumulative$variable_label[[1]], " [", cumulative$unit[[1]], "]"),
      caption = demo_caption(is_demo)
    ) +
    all_treatment_theme(profile)
  p_event <- add_observation_errorbars(p_event, cumulative)

  p_smooth <- ggplot2::ggplot() +
    ggplot2::geom_line(
      data = smooth_curve,
      ggplot2::aes(x = time, y = simulated, colour = nitrogen_level, group = treatment_label),
      linewidth = profile$data_linewidth_pt, lineend = "round"
    ) +
    ggplot2::geom_point(
      data = cumulative,
      ggplot2::aes(x = time, y = observed, fill = nitrogen_level, shape = water_level),
      colour = "#202020", size = 1.55, stroke = 0.4
    ) +
    ggplot2::facet_wrap(~treatment_label, ncol = facet_columns, scales = "free_y") +
    management_scales(profile) +
    ggplot2::labs(
      title = "Smoothed cumulative fresh harvest across all treatments",
      subtitle = "Monotone visual interpolation of simulated harvest-date values; points are observed means",
      x = "Days after planting",
      y = paste0(cumulative$variable_label[[1]], " [", cumulative$unit[[1]], "]"),
      caption = paste(
        "Visual interpolation only; metrics use original model outputs.",
        ifelse(isTRUE(is_demo), demo_caption(TRUE), "")
      )
    ) +
    all_treatment_theme(profile)
  p_smooth <- add_observation_errorbars(p_smooth, cumulative)

  list(
    increment = list(plot = p_increment, source = increment,
                     height_mm = min(profile$max_height_mm, 108)),
    cumulative_event = list(plot = p_event, source = cumulative,
                            height_mm = min(profile$max_height_mm, 108)),
    cumulative_smooth = list(plot = p_smooth, observations = cumulative,
                             daily = daily, curve = smooth_curve,
                             height_mm = min(profile$max_height_mm, 108))
  )
}
