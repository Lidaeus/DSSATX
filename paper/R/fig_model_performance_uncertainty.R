# Plan §4 (1:1 observed vs conditional-ensemble prediction).  This module is
# the only renderer for the conditional model-performance figure; it consumes
# exclusively the frozen conditional bundle (conditional_prediction_summary.csv
# + two-season treatment metadata) and never reads DSSAT/PEST++ outputs.

attach_conditional_metadata <- function(data, treatment_metadata) {
  if (is.null(treatment_metadata)) {
    stop("Conditional figures require the frozen two-season treatment metadata", call. = FALSE)
  }
  data$treatment <- as.character(data$treatment)
  treatment_metadata$treatment <- as.character(treatment_metadata$treatment)
  # The two-season metadata also freezes dataset_role; when the data table
  # carries it, verify agreement and keep one column (merge() would otherwise
  # silently produce dataset_role.x/.y).
  if ("dataset_role" %in% names(data) && "dataset_role" %in% names(treatment_metadata)) {
    meta_roles <- treatment_metadata[, c("season_id", "treatment", "dataset_role")]
    check <- merge(data[, c("season_id", "treatment", "dataset_role")], meta_roles,
                   by = c("season_id", "treatment"))
    if (any(check$dataset_role.x != check$dataset_role.y)) {
      stop("dataset_role disagrees between the frozen metadata and the conditional table", call. = FALSE)
    }
    treatment_metadata <- treatment_metadata[, setdiff(names(treatment_metadata), "dataset_role"),
                                             drop = FALSE]
  }
  merged <- merge(data, treatment_metadata,
                  by = c("season_id", "treatment"), all.x = TRUE, sort = FALSE)
  missing <- merged[is.na(merged$water_level) | is.na(merged$nitrogen_level), "treatment"]
  if (length(missing) > 0) {
    stop("Missing water/nitrogen metadata for treatments: ",
         paste(unique(missing), collapse = ", "), call. = FALSE)
  }
  merged
}

conditional_metrics <- function(data, variable) {
  # Metrics are computed from the ensemble-median prediction per event and are
  # split by season x dataset_role; never pooled across variables or seasons.
  rows <- lapply(split(data, interaction(data$season_id, data$dataset_role, drop = TRUE)), function(frame) {
    observed <- frame$observed
    median_prediction <- frame$sim_median
    residual <- median_prediction - observed
    sst <- sum((observed - mean(observed))^2)
    data.frame(
      season_id = frame$season_id[[1]],
      dataset_role = frame$dataset_role[[1]],
      variable = variable,
      n_pairs = nrow(frame),
      n_treatments = length(unique(frame$treatment)),
      n_members_valid = unique(frame$n_members_valid)[[1]],
      rmse = sqrt(mean(residual^2)),
      rrmse_pct = 100 * sqrt(mean(residual^2)) / mean(observed),
      mae = mean(abs(residual)),
      bias = mean(residual),
      r2 = if (sd(observed) > 0 && sd(median_prediction) > 0) {
        stats::cor(observed, median_prediction)^2
      } else NA_real_,
      # NSE is reported for cumulative series only and is descriptive for the
      # terminal-yield acceptance, which uses RRMSE (plan §4.3).
      nse = if (sst > 0) 1 - sum(residual^2) / sst else NA_real_,
      picp95 = mean(observed >= frame$sim_q025 & observed <= frame$sim_q975),
      mpiw = mean(frame$sim_q975 - frame$sim_q025),
      rmpiw_pct = 100 * mean(frame$sim_q975 - frame$sim_q025) / mean(observed)
    )
  })
  do.call(rbind, rows)
}

build_model_performance_uncertainty <- function(prediction_summary, treatment_metadata,
                                                variable = "DRY_CUM", profile, is_demo = FALSE) {
  data <- prediction_summary[prediction_summary$variable == variable, , drop = FALSE]
  if (nrow(data) == 0) stop("No conditional predictions for variable ", variable)
  if (length(unique(data$n_members_valid)) != 1) {
    stop("Every point must use the same global complete-case member set")
  }
  data <- attach_conditional_metadata(data, treatment_metadata)
  data$is_calibration <- data$dataset_role == "calibration"
  # Calibration points: nitrogen-coloured fill; diagnostic-validation points:
  # white fill with the nitrogen colour as border (plan §4.2).
  data$fill_key <- ifelse(data$is_calibration, data$nitrogen_level, "held_out")
  fill_values <- c()
  for (level in names(profile$nitrogen_colors)) {
    fill_values[[level]] <- profile$nitrogen_colors[[level]]
  }
  fill_values[["held_out"]] <- "white"

  metrics <- conditional_metrics(data, variable)
  season_levels <- intersect(c("25SP", "26SP"), unique(data$season_id))
  data$season_id <- factor(data$season_id, levels = season_levels)
  nitrogen <- unlist(profile$nitrogen_colors, use.names = TRUE)
  water <- unlist(profile$water_shapes, use.names = TRUE)
  metric_labels <- setNames(vapply(season_levels, function(season) {
    paste0(season, "\n", gsub("Calibration", "Cal", gsub("Validation", "Val",
                                                          annotation_row(metrics, season))))
  }, character(1)), season_levels)
  data$season_panel <- factor(as.character(data$season_id), levels = season_levels,
                              labels = unname(metric_labels))

  values <- c(data$observed, data$sim_q025, data$sim_q975)
  padding <- max(diff(range(values)), 1) * 0.05
  limits <- c(max(0, min(values) - padding), max(values) + padding)
  plot <- ggplot2::ggplot(
    data, ggplot2::aes(x = observed, y = sim_median, colour = nitrogen_level,
                       fill = fill_key, shape = water_level)
  ) +
    ggplot2::geom_abline(slope = 1, intercept = 0, colour = "#8C8C8C",
                         linetype = "dashed", linewidth = 0.4) +
    ggplot2::geom_linerange(ggplot2::aes(ymin = sim_q025, ymax = sim_q975),
                            linewidth = 0.3, alpha = 0.48) +
    ggplot2::geom_linerange(ggplot2::aes(ymin = sim_q25, ymax = sim_q75),
                            linewidth = 1.05, alpha = 0.9) +
    ggplot2::geom_point(size = 1.35, stroke = 0.48) +
    ggplot2::facet_wrap(~season_panel, nrow = 1) +
    ggplot2::scale_colour_manual(name = "Nitrogen level", values = nitrogen, drop = FALSE) +
    ggplot2::scale_fill_manual(values = fill_values, drop = FALSE, guide = "none") +
    ggplot2::scale_shape_manual(name = "Water treatment", values = water, drop = FALSE) +
    ggplot2::coord_equal(xlim = limits, ylim = limits, expand = FALSE) +
    ggplot2::labs(
      title = "Cumulative dry-yield performance and parameter uncertainty",
      subtitle = paste(
        "Point = ensemble median; thin/thick bars = 95% interval/IQR.",
        "Filled = calibration; open = validation; dashed = 1:1."
      ),
      x = "Observed cumulative dry yield (kg ha\u207b\u00b9)",
      y = "Simulated ensemble median (kg ha\u207b\u00b9)",
      caption = paste(
        "Conditional-ensemble prediction interval propagates parameter uncertainty only.",
        ifelse(isTRUE(is_demo), demo_caption(TRUE), "")
      )
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      legend.position = "top",
      legend.box = "horizontal",
      strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.5,
                                         lineheight = 1.05),
      panel.spacing.x = grid::unit(4, "mm")
    )

  list(plot = plot, source = data, metrics = metrics,
       height_mm = min(profile$max_height_mm, 104))
}

annotation_row <- function(metrics, season) {
  role_names <- c(calibration = "Calibration", validation = "Validation")
  frame <- metrics[metrics$season_id == season, ]
  paste(vapply(seq_len(nrow(frame)), function(index) {
    sprintf("%s: R\u00b2 %.2f | RMSE %.0f | RRMSE %.1f%% | PICP95 %.0f%%",
            role_names[[frame$dataset_role[[index]]]], frame$r2[[index]],
            frame$rmse[[index]], frame$rrmse_pct[[index]], 100 * frame$picp95[[index]])
  }, character(1)), collapse = "\n")
}
