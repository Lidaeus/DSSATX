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
      ggplot2::aes(y = simulated, colour = nitrogen_level, group = treatment),
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
      ggplot2::aes(x = time, y = simulated, colour = nitrogen_level, group = treatment),
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
