validate_sa_columns <- function(data, required, table_name) {
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop(table_name, " missing: ", paste(missing, collapse = ", "))
  invisible(TRUE)
}

focus_join <- function(data, focus, domain_column = "ranking_domain") {
  names_focus <- c("parameter", "primary_domain", "display_order", "process_label", "parameter_label")
  focus_part <- focus[, names_focus, drop = FALSE]
  merge(
    data, focus_part,
    by.x = c("parameter", domain_column), by.y = c("parameter", "primary_domain"),
    all = FALSE, sort = FALSE
  )
}

build_morris_main <- function(rankings, group_summary, focus, profile, is_demo = FALSE,
                            lang = SA_DEFAULT_LANG) {
  validate_sa_columns(
    rankings,
    c("season", "season_order", "season_label", "ranking_domain", "domain_label", "parameter",
      "mean_score", "consensus_rank", "domain_stable", "cross_season_mean_score"),
    "morris_season_rankings.csv"
  )
  validate_sa_columns(
    group_summary,
    c("ranking_domain", "domain_label", "response_group", "response_group_label", "parameter",
      "group_score_mean"),
    "morris_group_summary.csv"
  )
  validate_sa_columns(focus, c("parameter", "primary_domain", "display_order", "parameter_label"),
                      "morris_focus_parameters.csv")
  ranking <- focus_join(rankings, focus)
  groups <- focus_join(group_summary, focus)
  if (nrow(ranking) == 0 || nrow(groups) == 0) stop("No focus parameters match the Morris evidence")
  ranking$mean_score <- as.numeric(ranking$mean_score)
  ranking$cross_season_mean_score <- as.numeric(ranking$cross_season_mean_score)
  ranking$display_order <- as.numeric(ranking$display_order)
  ranking$stability_label <- ifelse(ranking$domain_stable, sa_t("shared.stable", lang), sa_t("shared.more_seeds", lang))
  ranking$domain_panel <- ifelse(ranking$ranking_domain == "general_genetic", sa_t("shared.panel_genetic", lang), sa_t("shared.panel_wn", lang))
  parameter_levels <- rev(focus$parameter_label[order(as.numeric(focus$display_order))])
  ranking$parameter_label <- factor(ranking$parameter_label, levels = parameter_levels)
  ranking$season_label <- factor(
    ranking$season_label,
    levels = unique(ranking$season_label[order(as.numeric(ranking$season_order))])
  )
  season_colours <- c("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00")
  used_seasons <- levels(ranking$season_label)
  season_colours <- stats::setNames(season_colours[seq_along(used_seasons)], used_seasons)
  ranges <- do.call(rbind, lapply(
    split(ranking, interaction(ranking$ranking_domain, ranking$parameter), drop = TRUE),
    function(frame) {
    data.frame(
      ranking_domain = frame$ranking_domain[[1]], domain_label = frame$domain_label[[1]],
      domain_panel = frame$domain_panel[[1]],
      parameter = frame$parameter[[1]], parameter_label = frame$parameter_label[[1]],
      min_score = min(frame$mean_score), max_score = max(frame$mean_score),
      cross_season_mean_score = frame$cross_season_mean_score[[1]]
    )
    }
  ))
  ranges$parameter_label <- factor(ranges$parameter_label, levels = parameter_levels)
  rank_plot <- ggplot2::ggplot(ranking, ggplot2::aes(mean_score, parameter_label)) +
    ggplot2::geom_segment(
      data = ranges, ggplot2::aes(x = min_score, xend = max_score,
                                  y = parameter_label, yend = parameter_label),
      inherit.aes = FALSE, colour = profile$palette$neutral, linewidth = 0.45, alpha = 0.65
    ) +
    ggplot2::geom_point(
      ggplot2::aes(colour = season_label, shape = stability_label), size = 2.1, stroke = 0.65
    ) +
    ggplot2::geom_point(
      data = ranges, ggplot2::aes(cross_season_mean_score, parameter_label),
      inherit.aes = FALSE, shape = 23, size = 2.2, stroke = 0.45, fill = "white", colour = "black"
    ) +
    ggplot2::facet_grid(rows = ggplot2::vars(domain_panel), scales = "free_y", space = "free_y") +
    ggplot2::scale_colour_manual(values = season_colours) +
    ggplot2::scale_shape_manual(values = stats::setNames(c(16, 1), c(sa_t("shared.stable", lang), sa_t("shared.more_seeds", lang)))) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(mult = c(0, 0.08))) +
    ggplot2::labs(
      title = sa_t("morris_main.rank_title", lang),
      subtitle = sa_t("morris_main.rank_subtitle", lang),
      x = sa_t("morris_main.rank_x", lang), y = NULL
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold"),
      legend.position = "bottom", legend.box = "vertical"
    )

  groups$group_score_mean <- as.numeric(groups$group_score_mean)
  groups$display_order <- as.numeric(groups$display_order)
  groups$domain_panel <- ifelse(groups$ranking_domain == "general_genetic", sa_t("shared.panel_genetic", lang), sa_t("shared.panel_wn", lang))
  parameter_code_levels <- rev(focus$parameter[order(as.numeric(focus$display_order))])
  groups$parameter <- factor(groups$parameter, levels = parameter_code_levels)
  group_order_en <- c("Phenology", "Canopy", "Biomass", "Harvest", "Water response",
                      "Nitrogen response", "Water x nitrogen")
  group_order <- vapply(group_order_en, function(g) sa_t(paste0("group.", g), lang), character(1))
  groups$response_group_label <- vapply(groups$response_group_label, function(g) sa_t(paste0("group.", g), lang), character(1))
  groups$response_group_label <- factor(groups$response_group_label, levels = group_order)

  # Keep English heatmap headers short enough to remain horizontal.  The full
  # meanings stay in the caption; Chinese labels remain explicit.
  if (!identical(lang, "zh")) {
    groups$response_group_label <- as.character(groups$response_group_label)
    groups$response_group_label[groups$response_group_label == "Water response"] <- "W resp."
    groups$response_group_label[groups$response_group_label == "Nitrogen response"] <- "N resp."
    groups$response_group_label[groups$response_group_label == "Water x nitrogen"] <- "W×N"
    group_order <- c("Phenology", "Canopy", "Biomass", "Harvest",
                    "W resp.", "N resp.", "W×N")
    groups$response_group_label <- factor(groups$response_group_label, levels = group_order)
  }
  heat_plot <- ggplot2::ggplot(
    groups, ggplot2::aes(response_group_label, parameter, fill = group_score_mean)
  ) +
    ggplot2::geom_tile(colour = "white", linewidth = 0.45) +
    ggplot2::scale_fill_gradientn(
      colours = c("#F7FBFF", "#A6CEE3", "#56B4E9", "#0072B2"),
      name = sa_t("morris_main.mean_score_legend", lang)
    ) +
    ggplot2::facet_grid(rows = ggplot2::vars(domain_panel), scales = "free", space = "free_y") +
    ggplot2::labs(
      title = sa_t("morris_main.heat_title", lang),
      x = NULL, y = NULL
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      axis.text.x = ggplot2::element_text(angle = 38, hjust = 1),
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold"),
      legend.position = "bottom"
    )

  plot <- rank_plot / heat_plot +
    patchwork::plot_layout(heights = c(1.05, 0.95), guides = "keep") +
    patchwork::plot_annotation(
      tag_levels = "a",
      title = sa_t("morris_main.title", lang),
      subtitle = if (isTRUE(is_demo)) {
        sa_t("morris_main.demo_subtitle", lang)
      } else NULL,
      caption = if (isTRUE(is_demo)) sa_t("morris_main.demo_caption", lang) else NULL,
      theme = ggplot2::theme(
        plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.subtitle = ggplot2::element_text(colour = "#4D4D4D", size = profile$font_size_pt),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 0),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)
      )
    )
  list(plot = plot, ranking_source = ranking, group_source = groups, height_mm = 145)
}

build_morris_stability <- function(seed_rankings, stability, focus, profile, is_demo = FALSE,
                                   lang = SA_DEFAULT_LANG) {
  validate_sa_columns(
    seed_rankings,
    c("season", "season_order", "season_label", "seed", "ranking_domain", "domain_label",
      "parameter", "rank", "domain_stable"),
    "morris_seed_rankings.csv"
  )
  validate_sa_columns(
    stability,
    c("season", "season_order", "season_label", "ranking_domain", "domain_label", "seed_a", "seed_b", "seed_pair",
      "spearman", "top_k_jaccard", "spearman_threshold", "jaccard_threshold", "passes"),
    "morris_pairwise_stability.csv"
  )
  ranks <- focus_join(seed_rankings, focus)
  ranks$rank <- as.numeric(ranks$rank)
  ranks$domain_panel <- ifelse(ranks$ranking_domain == "general_genetic", sa_t("shared.panel_genetic", lang), sa_t("shared.panel_wn", lang))
  seed_values <- sort(unique(as.character(ranks$seed)))
  ranks$seed_index <- factor(as.character(ranks$seed), levels = seed_values,
                             labels = seq_along(seed_values))
  ranks$parameter_label <- factor(
    ranks$parameter_label,
    levels = focus$parameter_label[order(as.numeric(focus$display_order))]
  )
  rank_plot <- ggplot2::ggplot(
    ranks, ggplot2::aes(seed_index, rank, group = parameter, colour = parameter)
  ) +
    ggplot2::geom_line(linewidth = 0.55, alpha = 0.82) +
    ggplot2::geom_point(size = 1.45) +
    ggplot2::scale_y_reverse(breaks = c(1, 5, 10, 15, 20)) +
    ggplot2::facet_grid(rows = ggplot2::vars(domain_panel), cols = ggplot2::vars(season_label),
                       scales = "free_y") +
    ggplot2::labs(
      title = sa_t("morris_stab.rank_title", lang),
      x = sa_t("morris_stab.rank_x", lang), y = sa_t("morris_stab.rank_y", lang)
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      axis.text.x = ggplot2::element_text(angle = 30, hjust = 1),
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold"),
      legend.position = "bottom"
    )

  stability$spearman <- as.numeric(stability$spearman)
  stability$top_k_jaccard <- as.numeric(stability$top_k_jaccard)
  stability$passes_label <- ifelse(as.logical(stability$passes), sa_t("shared.pass", lang), sa_t("shared.needs_more_seeds", lang))
  stability$domain_panel <- ifelse(stability$ranking_domain == "general_genetic", sa_t("shared.panel_genetic", lang), sa_t("shared.panel_wn", lang))
  stability$domain_label <- ifelse(
    stability$domain_label == "General genetic effects",
    sa_t("shared.domain_general_genetic", lang),
    sa_t("shared.domain_wn_response", lang)
  )
  stability$domain_label <- factor(
    stability$domain_label,
    levels = c(sa_t("shared.domain_general_genetic", lang), sa_t("shared.domain_wn_response", lang))
  )
  stability$season_label <- factor(
    stability$season_label,
    levels = unique(stability$season_label[order(as.numeric(stability$season_order))])
  )
  pair_values <- unique(as.character(stability$seed_pair))
  all_pair_seeds <- sort(unique(c(as.character(stability$seed_a), as.character(stability$seed_b))))
  pair_labels <- vapply(strsplit(pair_values, "-", fixed = TRUE), function(values) {
    paste(match(values[[1]], all_pair_seeds), match(values[[2]], all_pair_seeds), sep = "-")
  }, character(1))
  stability$seed_pair_index <- factor(
    as.character(stability$seed_pair), levels = pair_values,
    labels = pair_labels
  )
  # Compact evidence matrix. Shape carries pass/fail; colour stays neutral so
  # a failed numerical gate is not mistaken for a biological effect size.
  metric_long <- rbind(
    data.frame(season_label = stability$season_label, domain_panel = stability$domain_panel,
               metric = sa_t("metric.spearman_rho", lang), value = stability$spearman,
               threshold = stability$spearman_threshold,
               pass = stability$spearman >= stability$spearman_threshold),
    data.frame(season_label = stability$season_label, domain_panel = stability$domain_panel,
               metric = sa_t("metric.top15_jaccard", lang), value = stability$top_k_jaccard,
               threshold = stability$jaccard_threshold,
               pass = stability$top_k_jaccard >= stability$jaccard_threshold)
  )
  metric_long$comparison <- factor(
    paste(metric_long$season_label, metric_long$domain_panel, sep = " — "),
    levels = rev(unique(paste(stability$season_label, stability$domain_panel, sep = " — ")))
  )
  metric_long$metric <- factor(metric_long$metric, levels = c(
    sa_t("metric.spearman_rho", lang), sa_t("metric.top15_jaccard", lang)
  ))
  metric_summary <- do.call(rbind, lapply(
    split(metric_long, interaction(metric_long$season_label, metric_long$domain_panel,
                                   metric_long$metric, drop = TRUE)),
    function(part) {
      data.frame(
        season_label = part$season_label[[1]], domain_panel = part$domain_panel[[1]],
        metric = part$metric[[1]], threshold = part$threshold[[1]],
        min_value = min(part$value), max_value = max(part$value),
        mean_value = mean(part$value), pass_n = sum(part$pass), n = nrow(part)
      )
    }
  ))
  metric_summary$comparison <- factor(
    paste(metric_summary$season_label, metric_summary$domain_panel, sep = " — "),
    levels = rev(unique(paste(stability$season_label, stability$domain_panel, sep = " — ")))
  )
  metric_summary$metric <- factor(metric_summary$metric, levels = levels(metric_long$metric))
  metric_summary$pass_all <- metric_summary$pass_n == metric_summary$n
  metric_plot <- ggplot2::ggplot(metric_summary, ggplot2::aes(mean_value, comparison, shape = pass_all)) +
    ggplot2::geom_vline(ggplot2::aes(xintercept = threshold), linetype = 2,
                        linewidth = 0.45, colour = "#777777") +
    ggplot2::geom_segment(ggplot2::aes(x = min_value, xend = max_value,
                                       y = comparison, yend = comparison),
                          colour = "#777777", linewidth = 0.8) +
    ggplot2::geom_point(size = 2.2, colour = "#222222", stroke = 0.6) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.2f (%d/%d)", mean_value, pass_n, n)),
                       nudge_y = 0.18, size = 2.25, colour = "#333333") +
    ggplot2::facet_wrap(~metric, nrow = 1, scales = "free_x") +
    ggplot2::scale_shape_manual(values = c(`TRUE` = 16, `FALSE` = 1), guide = "none") +
    ggplot2::coord_cartesian(xlim = c(0.45, 1.02), clip = "off") +
    ggplot2::labs(title = sa_t("morris_stab.metric_title", lang),
                  subtitle = sa_t("morris_stab.metric_subtitle", lang),
                  x = sa_t("morris_stab.metric_x", lang), y = NULL) +
    theme_q1(profile) +
    ggplot2::theme(strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
                   strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.5),
                   axis.text.y = ggplot2::element_text(size = profile$font_size_pt - 1.0))
  plot <- rank_plot / metric_plot +
    patchwork::plot_layout(heights = c(1.15, 0.75), guides = "keep") +
    patchwork::plot_annotation(
      tag_levels = "a",
      title = sa_t("morris_stab.title", lang),
      caption = if (isTRUE(is_demo)) sa_t("morris_stab.demo_caption", lang) else NULL,
      theme = ggplot2::theme(
        plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 0),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)
      )
    )
  list(plot = plot, rank_source = ranks, stability_source = stability, height_mm = 135)
}

# ---------------------------------------------------------------------------
# W4 (plan §5.3): response-level mu*-sigma small multiples.
#
# Consumes morris_response_effects.csv (the W2 export) and renders one panel
# per fixed core response with x = mu*, y = sigma.  Strict scientific rules
# (plan §5.3):
#   * no undefined "four-quadrant threshold" lines are drawn;
#   * a large sigma is labelled "nonlinearity and/or interaction involvement",
#     never "strong interaction";
#   * colour distinguishes at most two scientific domains; the two ranking
#     domains are never merged into one panel;
#   * grey-scale readable: the top-5 parameters per panel are labelled and
#     emphasised, the rest are a low-saturation background.
# ---------------------------------------------------------------------------

build_morris_response_effects <- function(effects, focus, profile, is_demo = FALSE,
                                          top_k = 5, core_response_ids = NULL,
                                          lang = SA_DEFAULT_LANG) {
  # P0 fix: the effects table now carries OBSERVATION-level Morris statistics
  # (exact, from .mio), not a fake treatment-mean aggregate.  The figure plots
  # the legitimate observation-level mu*/sigma, with the dimensionless
  # within-family share on x for cross-treatment comparability.  The caption
  # states this honestly.  See export_morris_response_effects.py docstring.
  validate_sa_columns(
    effects,
    c("season", "seed", "ranking_domain", "response_group", "response_id",
      "response_label", "parameter", "mu_star", "sigma",
      "mu_star_share_within_family", "aggregation_level"),
    "morris_response_effects.csv"
  )
  effects$mu_star <- as.numeric(effects$mu_star)
  effects$sigma <- as.numeric(effects$sigma)
  effects$family_share <- as.numeric(effects$mu_star_share_within_family)

  # Default core responses: the four general-genetic physiology-chain anchors.
  if (is.null(core_response_ids)) {
    core_response_ids <- c("MEAN_ADAPS", "MEAN_LAI_AUC", "MEAN_AGB_END_CWAD",
                           "MEAN_FRUITD_END")
  }
  core <- effects[effects$response_id %in% core_response_ids, , drop = FALSE]
  if (nrow(core) == 0) stop("No core responses in morris_response_effects.csv")

  # Collapse the per-observation rows to one point per (response_family,
  # parameter): use the dimensionless family share (x) and the mean of the
  # observation-level sigma (y).  This is legitimate: the share is already
  # normalised, and sigma is summarised as a descriptive central tendency of
  # the observation-level spread (caption discloses this).
  agg <- stats::aggregate(
    cbind(family_share, sigma) ~ response_id + response_label + ranking_domain + parameter,
    data = core, FUN = mean, na.rm = TRUE
  )

  domain_colours <- c(
    "general_genetic" = "#0072B2",
    "water_nitrogen_response" = "#D55E00"
  )

  # Per-panel top-k by family share: emphasised + labelled; rest = background.
  agg$emphasis <- FALSE
  agg$label_text <- NA_character_
  for (rid in unique(agg$response_id)) {
    rows <- which(agg$response_id == rid)
    order_idx <- rows[order(agg$family_share[rows], decreasing = TRUE)]
    top_idx <- utils::head(order_idx, top_k)
    agg$emphasis[top_idx] <- TRUE
    agg$label_text[top_idx] <- agg$parameter[top_idx]
  }

  agg$response_label <- factor(agg$response_label, levels = unique(
    agg$response_label[match(core_response_ids, agg$response_id)]
  ))

  # Build the plot WITHOUT wrapping an already-faceted ggplot in patchwork
  # (the prior wrap_plots(list(plot)) duplicated the four panels).  A single
  # faceted ggplot is returned directly with labs() for the title.
  plot <- ggplot2::ggplot(agg) +
    ggplot2::geom_point(
      data = agg[!agg$emphasis, , drop = FALSE],
      ggplot2::aes(family_share, sigma), colour = "#D9D9D9", size = 1.1, alpha = 0.85
    ) +
    ggplot2::geom_point(
      data = agg[agg$emphasis, , drop = FALSE],
      ggplot2::aes(family_share, sigma, colour = ranking_domain), size = 1.9, stroke = 0.5
    ) +
    ggrepel_if_available(
      data = agg[agg$emphasis, , drop = FALSE],
      ggplot2::aes(family_share, sigma, label = label_text, colour = ranking_domain),
      size = 2.0, max.overlaps = 20, segment.size = 0.25, segment.alpha = 0.6,
      min.segment.length = 0, seed = 20260729
    ) +
    ggplot2::scale_colour_manual(
      values = domain_colours,
      labels = c("general_genetic" = sa_t("shared.general_genetic_label", lang),
                 "water_nitrogen_response" = sa_t("shared.water_nitrogen_label", lang)),
      name = NULL
    ) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(mult = c(0.03, 0.18))) +
    ggplot2::scale_y_continuous(expand = ggplot2::expansion(mult = c(0.04, 0.18))) +
    ggplot2::facet_wrap(~response_label, scales = "free", ncol = 2) +
    ggplot2::labs(
      title = sa_t("morris_eff.title", lang),
      subtitle = sa_tf("morris_eff.subtitle", lang, top_k),
      caption = if (isTRUE(is_demo)) {
        sa_t("morris_eff.demo_caption", lang)
      } else {
        sa_t("morris_eff.caption", lang)
      },
      x = sa_t("morris_eff.x", lang),
      y = sa_t("morris_eff.y", lang)
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
      plot.subtitle = ggplot2::element_text(colour = "#4D4D4D", size = profile$font_size_pt),
      plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1),
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.5),
      legend.position = "bottom",
      panel.spacing = ggplot2::unit(2.5, "pt")
    )

  list(plot = plot, effects_source = agg, height_mm = 130)
}

# ---------------------------------------------------------------------------
# Results-first Morris figure.
#
# The figure answers two scientific questions directly:
#   (a) which response families are sensitive to each focal parameter; and
#   (b) which focal parameters carry the largest cross-season effect magnitude.
# Seed-pair stability is deliberately kept out of this results figure.
# ---------------------------------------------------------------------------

build_morris_results <- function(group_summary, cross_season_summary, focus,
                                 profile, is_demo = FALSE,
                                 lang = SA_DEFAULT_LANG) {
  validate_sa_columns(group_summary,
                      c("ranking_domain", "response_group", "response_group_label",
                        "parameter", "group_score_mean"),
                      "morris_group_summary.csv")
  validate_sa_columns(cross_season_summary,
                      c("ranking_domain", "parameter", "cross_season_mean_score"),
                      "morris_cross_season_summary.csv")
  validate_sa_columns(focus,
                      c("parameter", "primary_domain", "display_order", "parameter_label"),
                      "morris_focus_parameters.csv")

  focus_part <- focus[, c("parameter", "primary_domain", "display_order", "parameter_label"), drop = FALSE]
  groups <- merge(group_summary, focus_part,
                  by.x = c("parameter", "ranking_domain"),
                  by.y = c("parameter", "primary_domain"),
                  all = FALSE, sort = FALSE)
  if (nrow(groups) == 0) stop("No focal parameters match Morris group results")
  groups$group_score_mean <- as.numeric(groups$group_score_mean)
  groups$domain_panel <- ifelse(groups$ranking_domain == "general_genetic",
                                sa_t("shared.panel_genetic", lang),
                                sa_t("shared.panel_wn_response", lang))
  groups$response_group_label <- vapply(groups$response_group, function(g) {
    key <- paste0("group.", switch(g, phenology = "Phenology", canopy = "Canopy",
                                   biomass = "Biomass", yield_harvest = "Harvest",
                                   water_response = "Water response",
                                   nitrogen_response = "Nitrogen response",
                                   water_nitrogen_interaction = "Water x nitrogen", g))
    sa_t(key, lang)
  }, character(1))
  # Use compact DSSAT parameter codes on the axis; full meanings are given in
  # the caption so the scientific pattern remains readable at journal width.
  groups$parameter_code <- factor(
    groups$parameter,
    levels = rev(focus$parameter[order(as.numeric(focus$display_order))])
  )
  group_order_en <- c("Phenology", "Canopy", "Biomass", "Harvest",
                      "Water response", "Nitrogen response", "Water x nitrogen")
  group_order <- vapply(group_order_en, function(g) sa_t(paste0("group.", g), lang), character(1))
  groups$response_group_label <- factor(groups$response_group_label, levels = group_order)

  # Keep English heatmap headers short enough to remain horizontal. The full
  # meanings stay in the caption; Chinese labels remain explicit.
  if (!identical(lang, "zh")) {
    groups$response_group_label <- as.character(groups$response_group_label)
    groups$response_group_label[groups$response_group_label == "Water response"] <- "W resp."
    groups$response_group_label[groups$response_group_label == "Nitrogen response"] <- "N resp."
    groups$response_group_label[groups$response_group_label == "Water x nitrogen"] <- "W×N"
    group_order <- c("Phenology", "Canopy", "Biomass", "Harvest",
                    "W resp.", "N resp.", "W×N")
    groups$response_group_label <- factor(groups$response_group_label, levels = group_order)
  }

  heat_plot <- ggplot2::ggplot(
    groups, ggplot2::aes(response_group_label, parameter_code, fill = group_score_mean)
  ) +
    ggplot2::geom_tile(colour = "white", linewidth = 0.45) +
    ggplot2::geom_text(ggplot2::aes(label = ifelse(group_score_mean > 0.001,
                                                   sprintf("%.3f", group_score_mean), "")),
                       size = 2.0, colour = "#222222") +
    ggplot2::scale_fill_gradientn(
      colours = c("#F7FBFF", "#C6DBEF", "#6BAED6", "#2171B5"),
      name = sa_t("morris_results.group_score", lang),
      guide = ggplot2::guide_colorbar(
        title.position = "top", title.hjust = 0, direction = "vertical",
        barwidth = grid::unit(4, "mm"), barheight = grid::unit(32, "mm"), ticks = TRUE
      )
    ) +
    ggplot2::facet_wrap(~domain_panel, ncol = 2, scales = "free") +
    ggplot2::labs(title = sa_t("morris_results.heat_title", lang), x = NULL, y = NULL) +
    theme_q1(profile) +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 0, hjust = 0.5),
                   strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
                   strip.text = ggplot2::element_text(face = "bold"),
                   legend.position = "right", legend.justification = "center",
                   legend.direction = "vertical",
                   legend.margin = ggplot2::margin(0, 0, 0, 2))

  focal <- merge(cross_season_summary, focus_part,
                 by.x = c("parameter", "ranking_domain"),
                 by.y = c("parameter", "primary_domain"),
                 all = FALSE, sort = FALSE)
  focal$cross_season_mean_score <- as.numeric(focal$cross_season_mean_score)
  focal$domain_panel <- ifelse(focal$ranking_domain == "general_genetic",
                               sa_t("shared.panel_genetic", lang),
                               sa_t("shared.panel_wn_response", lang))
  focal$parameter_code <- factor(
    focal$parameter,
    levels = rev(focus$parameter[order(as.numeric(focus$display_order))])
  )
  score_plot <- ggplot2::ggplot(focal,
                                ggplot2::aes(cross_season_mean_score, parameter_code)) +
    ggplot2::geom_col(fill = "#4C9BCB", width = 0.68) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.3f", cross_season_mean_score)),
                       hjust = -0.15, size = 2.15) +
    ggplot2::facet_grid(rows = ggplot2::vars(domain_panel), scales = "free_y",
                        space = "free_y") +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(mult = c(0, 0.16))) +
    ggplot2::labs(title = sa_t("morris_results.score_title", lang),
                  subtitle = sa_t("morris_results.score_subtitle", lang),
                  x = sa_t("morris_results.score_x", lang), y = NULL) +
    theme_q1(profile) +
    ggplot2::theme(strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
                   strip.text = ggplot2::element_text(face = "bold"))

  plot <- heat_plot / score_plot +
    patchwork::plot_layout(heights = c(1.2, 0.85), guides = "keep") +
    patchwork::plot_annotation(
      tag_levels = "a",
      title = sa_t("morris_results.title", lang),
      caption = if (isTRUE(is_demo)) {
        paste(sa_t("morris_results.demo_caption", lang), sa_t("morris_results.caption", lang), sep = "\n")
      } else sa_t("morris_results.caption", lang),
      theme = ggplot2::theme(
        plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 0),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)
      )
    )
  list(plot = plot, group_source = groups, score_source = focal, height_mm = 150)
}

# ggrepel is preferred for non-overlapping labels but is optional: if it is not
# installed, fall back to plain geom_text so the figure still renders.  The
# paper profile does not list ggrepel as a hard dependency (common.R checks
# only ggplot2/patchwork/jsonlite/svglite).  Returns a ggplot layer added via
# `+`, so the builder calls `plot + ggrepel_if_available(...)`.
ggrepel_if_available <- function(data, mapping, ..., max.overlaps = 20, seed = 20260729) {
  if (requireNamespace("ggrepel", quietly = TRUE)) {
    # Use the ggrepel namespace explicitly — geom_text_repel is not exported
    # by ggplot2, and the function may not be on the search path.
    layer_fun <- utils::getFromNamespace("geom_text_repel", "ggrepel")
    layer_fun(data = data, mapping = mapping, ..., max.overlaps = max.overlaps, seed = seed)
  } else {
    ggplot2::geom_text(data = data, mapping = mapping, check_overlap = FALSE, ...)
  }
}


# ---------------------------------------------------------------------------
# Task 1: Fig.S1 combined (stability + mu*-sigma in one figure).
#
# Stacks the seed-stability rank trajectories (upper) and the response-level
# mu*-sigma small multiples (lower) into a single Fig.S1, matching plan §9
# ("Fig. S1 = Morris mu*-sigma response-level small multiples + seed stability").
# ---------------------------------------------------------------------------

build_morris_s1_combined <- function(seed_rankings, stability, focus, effects,
                                     profile, is_demo = FALSE,
                                     lang = SA_DEFAULT_LANG) {
  # Build the two sub-figures via the existing builders, then extract $plot.
  stability_result <- build_morris_stability(seed_rankings, stability, focus, profile, is_demo, lang = lang)
  effects_result <- build_morris_response_effects(effects, focus, profile, is_demo, lang = lang)

  # Use wrap_plots (not the `/` operator) to compose two plots that may
  # already be patchwork objects internally — wrap_plots flattens nested
  # patchwork structures correctly, whereas `/` on two patchwork objects
  # triggers a layout wrap_dims error.
  plot <- patchwork::wrap_plots(
    list(stability_result$plot, effects_result$plot),
    ncol = 1
  ) +
    patchwork::plot_layout(heights = c(1.0, 1.1)) +
    patchwork::plot_annotation(
      tag_levels = "a",
      title = sa_t("morris_s1.title", lang),
      caption = if (isTRUE(is_demo)) {
        sa_t("morris_s1.demo_caption", lang)
      } else {
        sa_t("morris_s1.caption", lang)
      },
      theme = ggplot2::theme(
        plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1)
      )
    )

  list(
    plot = plot,
    rank_source = stability_result$rank_source,
    stability_source = stability_result$stability_source,
    effects_source = effects_result$effects_source,
    height_mm = 170
  )
}


# ---------------------------------------------------------------------------
# Task 2: Morris + Sobol summary composite figure.
#
# Three vertical panels: (a) Morris cross-season ranking, (b) process-group
# fingerprint heatmap, (c) compact Sobol S1/ST paired intervals for the
# convergence-validated season.  The Sobol evidence is read from a separate
# CSV (passed via --sobol-effects-csv) because SA and Sobol bundles are
# mutually exclusive by design.
# ---------------------------------------------------------------------------

build_sa_summary <- function(rankings, group_summary, focus, sobol_effects,
                             profile, is_demo = FALSE,
                              core_response_ids = c("anthesis_mean", "lai_auc_mean",
                                                    "agb_end_mean", "fruitd_end_mean"),
                             top_st = 3, lang = SA_DEFAULT_LANG) {
  # Panels (a) and (b): reuse build_morris_main, extract its rank_plot and
  # heat_plot by re-deriving them.  To avoid duplicating the internal logic,
  # call build_morris_main and take its combined plot, then build panel (c)
  # separately and stack all three.
  morris_result <- build_morris_main(rankings, group_summary, focus, profile, is_demo, lang = lang)

  # Panel (c): compact Sobol S1/ST for core responses, top parameters by ST.
  sobol_panel <- NULL
  if (!is.null(sobol_effects) && nrow(sobol_effects) > 0) {
    validate_sa_columns(
      sobol_effects,
      c("response_id", "response_label", "parameter", "S1", "S1_ci_low", "S1_ci_high",
        "ST", "ST_ci_low", "ST_ci_high", "interaction_supported", "display_in_figure"),
      "sobol effect decomposition"
    )
    se <- sobol_effects
    se$display_in_figure <- as.logical(se$display_in_figure)
    se <- se[se$response_id %in% core_response_ids & se$display_in_figure, , drop = FALSE]
    se$ST <- as.numeric(se$ST)
    se$S1 <- as.numeric(se$S1)
    # Top-N by ST per response
    se <- do.call(rbind, lapply(split(se, se$response_id), function(frame) {
      utils::head(frame[order(frame$ST, decreasing = TRUE), , drop = FALSE], top_st)
    }))
    se$response_label <- ifelse(
      se$response_id == "fruitd_end_mean",
      "Season-end cumulative harvested dry mass",
      se$response_label
    )
    se$parameter_key <- paste(se$response_id, se$parameter, sep = "___")
    se$parameter_key <- factor(se$parameter_key, levels = rev(unique(se$parameter_key)))
    s1_label <- sa_t("sobol.first_order_s1", lang)
    st_label <- sa_t("sobol.total_effect_st", lang)
    effect_long <- rbind(
      data.frame(se[, c("response_label", "parameter_key", "parameter")],
                 index = s1_label, estimate = se$S1,
                 ci_low = as.numeric(se$S1_ci_low), ci_high = as.numeric(se$S1_ci_high)),
      data.frame(se[, c("response_label", "parameter_key", "parameter")],
                 index = st_label, estimate = se$ST,
                 ci_low = as.numeric(se$ST_ci_low), ci_high = as.numeric(se$ST_ci_high))
    )
    effect_long$index <- factor(effect_long$index, levels = c(s1_label, st_label))
    sobol_panel <- ggplot2::ggplot() +
      ggplot2::geom_vline(xintercept = 0, linetype = 1, colour = "#BDBDBD", linewidth = 0.3) +
      ggplot2::geom_vline(xintercept = 1, linetype = 3, colour = "#BDBDBD", linewidth = 0.3) +
      ggplot2::geom_errorbar(data = effect_long,
        ggplot2::aes(x = estimate, xmin = ci_low, xmax = ci_high,
                     y = parameter_key, colour = index),
        height = 0.2, linewidth = 0.35, position = ggplot2::position_dodge(width = 0.3)) +
      ggplot2::geom_point(data = effect_long,
        ggplot2::aes(x = estimate, y = parameter_key, fill = index, shape = index),
        size = 1.8, stroke = 0.5, position = ggplot2::position_dodge(width = 0.3), colour = "#222222") +
      ggplot2::facet_wrap(~response_label, scales = "free_y", ncol = 2) +
      ggplot2::scale_colour_manual(values = stats::setNames(c("#0072B2", "#D55E00"), c(s1_label, st_label)), guide = "none") +
      ggplot2::scale_fill_manual(values = stats::setNames(c("white", "#D55E00"), c(s1_label, st_label))) +
      ggplot2::scale_shape_manual(values = stats::setNames(c(21, 21), c(s1_label, st_label))) +
      ggplot2::scale_y_discrete(labels = function(v) sub("^.*___", "", v)) +
      ggplot2::labs(
        subtitle = sa_t("sa_summary.sobol_subtitle", lang),
        x = sa_t("sa_summary.sobol_x", lang), y = NULL, fill = NULL, shape = NULL
      ) +
      theme_q1(profile) +
      ggplot2::theme(
        strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
        strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.8),
        legend.position = "bottom",
        axis.text.y = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 1.0)
      )
  }

  if (!is.null(sobol_panel)) {
    plot <- patchwork::wrap_plots(list(morris_result$plot, sobol_panel), ncol = 1) +
      patchwork::plot_layout(heights = c(1.3, 0.9)) +
      patchwork::plot_annotation(
        tag_levels = "a",
        title = sa_t("sa_summary.title", lang),
        caption = if (isTRUE(is_demo)) {
          sa_t("sa_summary.demo_caption", lang)
        } else {
          sa_t("sa_summary.caption", lang)
        },
        theme = ggplot2::theme(
          plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
          plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1)
        )
      )
    height <- 175
  } else {
    plot <- morris_result$plot
    height <- morris_result$height_mm
  }

  list(
    plot = plot,
    ranking_source = morris_result$ranking_source,
    group_source = morris_result$group_source,
    sobol_source = if (!is.null(sobol_panel)) se else NULL,
    height_mm = height
  )
}
