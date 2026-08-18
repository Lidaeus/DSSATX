# ---------------------------------------------------------------------------
# Task 3b: Parameter selection rationality funnel (55 -> 23).
#
# Shows how the 55-parameter Morris space is reduced to the 23 Sobol screening
# candidates, via two stacked panels:
#   (a) Elbow plot: rank vs cross-season mean Morris score, selected params
#       highlighted; the "elbow" visually justifies where the cut is drawn.
#   (b) Cumulative coverage: rank vs cumulative sensitivity fraction, with the
#       95% information threshold marked.
#
# Data: morris_cross_season_summary.csv (general_genetic domain, 55 params) +
# the 23 Sobol candidate list + Table S1 parameter definitions for labels.
# ---------------------------------------------------------------------------

validate_selection_columns <- function(data, required, table_name) {
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop(table_name, " missing: ", paste(missing, collapse = ", "))
  invisible(TRUE)
}

build_selection_rationality <- function(cross_season_summary, sobol_candidates,
                                        param_labels, profile, is_demo = FALSE,
                                        domain = "general_genetic",
                                        lang = SA_DEFAULT_LANG) {
  validate_selection_columns(
    cross_season_summary,
    c("parameter", "ranking_domain", "cross_season_mean_score", "cross_season_rank"),
    "morris_cross_season_summary.csv"
  )
  d <- cross_season_summary[cross_season_summary$ranking_domain == domain, , drop = FALSE]
  if (nrow(d) == 0) stop("No parameters in ranking_domain '", domain, "'")
  d$score <- as.numeric(d$cross_season_mean_score)
  d <- d[order(d$score, decreasing = TRUE), , drop = FALSE]
  d$rank <- seq_len(nrow(d))
  total_score <- sum(d$score)
  d$cum_frac <- cumsum(d$score) / total_score

  selected <- toupper(trimws(sobol_candidates$parameter))
  d$is_selected <- toupper(d$parameter) %in% selected
  n_selected <- sum(d$is_selected)
  n_total <- nrow(d)

  # Join parameter labels (definition) if available.
  if (!is.null(param_labels) && nrow(param_labels) > 0) {
    labels <- stats::setNames(param_labels$definition, toupper(param_labels$parameter))
    d$definition <- labels[toupper(d$parameter)]
  } else {
    d$definition <- d$parameter
  }

  k95 <- min(which(d$cum_frac >= 0.95), nrow(d))

  # (a) Elbow plot
  elbow <- ggplot2::ggplot(d, ggplot2::aes(rank, score)) +
    ggplot2::geom_line(colour = "grey75") +
    ggplot2::geom_point(ggplot2::aes(colour = is_selected), size = 1.6, alpha = 0.85) +
    ggplot2::scale_colour_manual(
      values = c("TRUE" = "#D55E00", "FALSE" = "grey80"),
      labels = c("TRUE" = sa_tf("selection.selected_label", lang, n_selected),
                 "FALSE" = sa_tf("selection.screened_label", lang, n_total - n_selected)),
      name = NULL
    ) +
    ggplot2::labs(
      subtitle = sa_t("selection.elbow_subtitle", lang),
      x = sa_t("selection.elbow_x", lang), y = sa_t("selection.elbow_y", lang)
    ) +
    theme_q1(profile) +
    ggplot2::theme(legend.position = "bottom", plot.subtitle = ggplot2::element_text(face = "bold"))

  # (b) Cumulative coverage
  cumulative <- ggplot2::ggplot(d, ggplot2::aes(rank, cum_frac)) +
    ggplot2::geom_area(fill = "#56B4E9", alpha = 0.2) +
    ggplot2::geom_line(colour = "#0072B2", linewidth = 0.8) +
    ggplot2::geom_hline(yintercept = 0.95, linetype = "dotted", colour = "#D55E00") +
    ggplot2::annotate("text", x = 1, y = 0.965, label = sa_t("selection.threshold_label", lang),
                      colour = "#D55E00", size = 2.5, hjust = 0) +
    ggplot2::labs(
      subtitle = sa_t("selection.cum_subtitle", lang),
      x = sa_t("selection.cum_x", lang), y = sa_t("selection.cum_y", lang)
    ) +
    theme_q1(profile) +
    ggplot2::theme(plot.subtitle = ggplot2::element_text(face = "bold"))

  plot <- elbow / cumulative +
    patchwork::plot_layout(heights = c(1, 1)) +
    patchwork::plot_annotation(
      title = sa_t("selection.title", lang),
      caption = if (isTRUE(is_demo)) {
        sa_t("selection.demo_caption", lang)
      } else {
        sa_t("selection.caption", lang)
      },
      theme = ggplot2::theme(
        plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1)
      )
    )

  list(plot = plot, selection_source = d, height_mm = 140)
}
