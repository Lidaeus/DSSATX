# ---------------------------------------------------------------------------
# Task 3a: Morris mu*-sigma interaction scatter.
#
# Consumes morris_interaction_summary.csv (one row per parameter, aggregated
# from observation-level effects by the Python tool).  Each point is one
# parameter; x = median mu*, y = median sigma, colour = dominant process
# group, size = sigma/mu* ratio (interaction/nonlinearity hint).  Top
# parameters by mu* and by sigma-ratio are labelled.
#
# Scientific note (P0): mu*/sigma are observation-level medians aggregated
# across observations/seasons/seeds — a descriptive overview, NOT a
# treatment-mean statistic.  The caption states this.
# ---------------------------------------------------------------------------

validate_interaction_columns <- function(data, required, table_name) {
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop(table_name, " missing: ", paste(missing, collapse = ", "))
  invisible(TRUE)
}

build_morris_interaction <- function(summary_data, profile, is_demo = FALSE,
                                     top_n = 30, label_top_mu = 5, label_top_ratio = 5,
                                     lang = SA_DEFAULT_LANG) {
  validate_interaction_columns(
    summary_data,
    c("parameter", "mu_star_median", "sigma_median", "sigma_ratio",
      "response_group_label"),
    "morris_interaction_summary.csv"
  )
  d <- summary_data
  d$mu_star <- as.numeric(d$mu_star_median)
  d$sigma <- as.numeric(d$sigma_median)
  d$ratio <- as.numeric(d$sigma_ratio)
  d$ratio[!is.finite(d$ratio) | d$mu_star <= 0] <- 0

  # Show top_n by mu* (the most important parameters); the rest are context.
  d <- d[order(d$mu_star, decreasing = TRUE), , drop = FALSE]
  plot_df <- utils::head(d, top_n)

  # Labels: union of top by mu* and top by ratio (within the shown set).
  top_mu <- utils::head(plot_df[order(plot_df$mu_star, decreasing = TRUE), ], label_top_mu)$parameter
  top_ratio <- utils::head(plot_df[order(plot_df$ratio, decreasing = TRUE), ], label_top_ratio)$parameter
  label_pars <- unique(c(top_mu, top_ratio))
  plot_df$label_text <- ifelse(plot_df$parameter %in% label_pars, plot_df$parameter, NA_character_)

  # Process-group colour palette (grey-scale readable, max 7 groups).
  # Compute used_groups from the ORIGINAL (English) labels before translating.
  group_palette <- c(
    "Phenology" = "#0072B2", "Canopy" = "#009E73", "Biomass" = "#D55E00",
    "Harvest" = "#CC79A7", "Water response" = "#56B4E9",
    "Nitrogen response" = "#E69F00", "Water x nitrogen" = "#999999", "Other" = "#B0B0B0"
  )
  used_groups <- unique(plot_df$response_group_label)
  group_palette <- group_palette[intersect(names(group_palette), used_groups)]
  # Translate both the data values and the palette names to the target language
  # so the colour scale names match the data's colour values.
  plot_df$response_group_label <- vapply(
    plot_df$response_group_label,
    function(g) sa_t(paste0("group.", g), lang),
    character(1)
  )
  group_colours <- stats::setNames(
    group_palette,
    vapply(names(group_palette), function(g) sa_t(paste0("group.", g), lang), character(1))
  )

  plot <- ggplot2::ggplot(plot_df, ggplot2::aes(mu_star, sigma)) +
    ggplot2::geom_point(ggplot2::aes(colour = response_group_label, size = ratio), alpha = 0.75) +
    ggrepel_if_available(
      data = plot_df[!is.na(plot_df$label_text), , drop = FALSE],
      ggplot2::aes(label = label_text),
      size = 2.2, fontface = "italic", box.padding = 0.4, point.padding = 0.25,
      max.overlaps = 25, segment.color = "grey50", segment.size = 0.2, min.segment.length = 0
    ) +
    ggplot2::scale_colour_manual(values = group_colours, name = sa_t("interaction.process_group", lang)) +
    ggplot2::scale_size_continuous(
      range = c(1.5, 6), name = expression(sigma / mu^"*")
    ) +
    ggplot2::scale_x_continuous(
      trans = scales::pseudo_log_trans(sigma = 0.1, base = 10),
      breaks = c(0, 0.01, 0.1, 1, 5, 10),
      labels = c("0", "0.01", "0.1", "1", "5", "10")
    ) +
    ggplot2::scale_y_continuous(
      trans = scales::pseudo_log_trans(sigma = 0.1, base = 10),
      breaks = c(0, 0.01, 0.1, 1, 5, 10),
      labels = c("0", "0.01", "0.1", "1", "5", "10")
    ) +
    ggplot2::labs(
      title = sa_t("interaction.title", lang),
      subtitle = sa_tf("interaction.subtitle", lang, top_n),
      x = sa_t("interaction.x", lang),
      y = sa_t("interaction.y", lang)
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      legend.position = "right",
      legend.box = "vertical",
      plot.subtitle = ggplot2::element_text(colour = "#4D4D4D", size = profile$font_size_pt - 0.5)
    )

  list(plot = plot, interaction_source = plot_df, height_mm = 120)
}
