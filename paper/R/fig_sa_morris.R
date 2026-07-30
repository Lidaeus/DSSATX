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

build_morris_main <- function(rankings, group_summary, focus, profile, is_demo = FALSE) {
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
  ranking$stability_label <- ifelse(ranking$domain_stable, "Stable", "More seeds required")
  ranking$domain_panel <- ifelse(ranking$ranking_domain == "general_genetic", "Genetic", "W-N")
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
    ggplot2::scale_shape_manual(values = c("Stable" = 16, "More seeds required" = 1)) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(mult = c(0, 0.08))) +
    ggplot2::labs(
      title = "Cross-season sensitivity ranking",
      subtitle = "Points: seasons; diamond: equal-season mean; line: seasonal range",
      x = "Hierarchy-normalised Morris score", y = NULL
    ) +
    theme_q1(profile) +
    ggplot2::theme(
      strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
      strip.text = ggplot2::element_text(face = "bold"),
      legend.position = "bottom", legend.box = "vertical"
    )

  groups$group_score_mean <- as.numeric(groups$group_score_mean)
  groups$display_order <- as.numeric(groups$display_order)
  groups$domain_panel <- ifelse(groups$ranking_domain == "general_genetic", "Genetic", "W-N")
  parameter_code_levels <- rev(focus$parameter[order(as.numeric(focus$display_order))])
  groups$parameter <- factor(groups$parameter, levels = parameter_code_levels)
  group_order <- c("Phenology", "Canopy", "Biomass", "Harvest", "Water response",
                   "Nitrogen response", "Water x nitrogen")
  groups$response_group_label <- factor(groups$response_group_label, levels = group_order)
  heat_plot <- ggplot2::ggplot(
    groups, ggplot2::aes(response_group_label, parameter, fill = group_score_mean)
  ) +
    ggplot2::geom_tile(colour = "white", linewidth = 0.45) +
    ggplot2::scale_fill_gradientn(
      colours = c("#F7FBFF", "#A6CEE3", "#56B4E9", "#0072B2"),
      name = "Mean score"
    ) +
    ggplot2::facet_grid(rows = ggplot2::vars(domain_panel), scales = "free", space = "free_y") +
    ggplot2::labs(
      title = "Process-specific sensitivity fingerprint",
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
      title = "Multi-season Morris screening identifies dominant process controls",
      subtitle = if (isTRUE(is_demo)) {
        "Current evidence: the XXQL2502 water-nitrogen Top-15 boundary remains seed-sensitive"
      } else NULL,
      caption = if (isTRUE(is_demo)) "DEMO - science pending; current Morris evidence is not yet citable" else NULL,
      theme = ggplot2::theme(
        plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.subtitle = ggplot2::element_text(colour = "#4D4D4D", size = profile$font_size_pt),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)
      )
    )
  list(plot = plot, ranking_source = ranking, group_source = groups, height_mm = 145)
}

build_morris_stability <- function(seed_rankings, stability, focus, profile, is_demo = FALSE) {
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
  ranks$domain_panel <- ifelse(ranks$ranking_domain == "general_genetic", "Genetic", "W-N")
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
      title = "Per-seed rank trajectories of the cross-season focus parameters",
      x = "Prespecified seed index", y = "Rank (1 = most sensitive)"
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
  stability$passes_label <- ifelse(as.logical(stability$passes), "Pass", "Needs more seeds")
  stability$domain_panel <- ifelse(stability$ranking_domain == "general_genetic", "Genetic", "W-N")
  stability$domain_label <- factor(
    stability$domain_label,
    levels = c("General genetic effects", "Water-nitrogen response")
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
  metric_panel <- function(value, threshold, title, y_label) {
    ggplot2::ggplot(stability, ggplot2::aes(seed_pair_index, .data[[value]])) +
      ggplot2::geom_hline(
        yintercept = unique(stability[[threshold]])[[1]], linetype = 2,
        linewidth = 0.55, colour = profile$palette$neutral
      ) +
      ggplot2::geom_point(
        ggplot2::aes(shape = passes_label, colour = passes_label), size = 2.0, stroke = 0.7
      ) +
      ggplot2::scale_colour_manual(values = c("Pass" = profile$palette$positive,
                                               "Needs more seeds" = profile$palette$negative)) +
      ggplot2::scale_shape_manual(values = c("Pass" = 16, "Needs more seeds" = 4)) +
      ggplot2::facet_grid(rows = ggplot2::vars(domain_panel), cols = ggplot2::vars(season_label)) +
      ggplot2::coord_cartesian(ylim = c(0.5, 1.01)) +
      ggplot2::labs(title = title, subtitle = paste0("Dashed threshold = ", unique(stability[[threshold]])[[1]]),
                    x = "Seed pair index", y = y_label) +
      theme_q1(profile) +
      ggplot2::theme(
        strip.background = ggplot2::element_rect(fill = "#F2F2F2", colour = NA),
        strip.text = ggplot2::element_text(face = "bold", size = profile$font_size_pt - 0.5),
        legend.position = "bottom"
      )
  }
  spearman_plot <- metric_panel("spearman", "spearman_threshold", "Whole-ranking agreement", "Spearman rho")
  jaccard_plot <- metric_panel("top_k_jaccard", "jaccard_threshold", "Top-15 membership agreement", "Jaccard index")
  plot <- rank_plot / (spearman_plot + jaccard_plot) +
    patchwork::plot_layout(heights = c(1.05, 1.0), guides = "keep") +
    patchwork::plot_annotation(
      tag_levels = "a",
      title = "Morris ranking stability across independent seeds",
      caption = if (isTRUE(is_demo)) "DEMO - science pending; current Morris evidence is not yet citable" else NULL,
      theme = ggplot2::theme(
        plot.title = ggplot2::element_text(face = "bold", size = profile$font_size_pt + 1),
        plot.caption = ggplot2::element_text(colour = "#666666", size = 5, hjust = 1),
        plot.tag = ggplot2::element_text(face = "bold", size = profile$panel_label_size_pt)
      )
    )
  list(plot = plot, rank_source = ranks, stability_source = stability, height_mm = 155)
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
                                          top_k = 5, core_response_ids = NULL) {
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
      labels = c("general_genetic" = "General genetic",
                 "water_nitrogen_response" = "Water-nitrogen"),
      name = NULL
    ) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(mult = c(0.03, 0.18))) +
    ggplot2::scale_y_continuous(expand = ggplot2::expansion(mult = c(0.04, 0.18))) +
    ggplot2::facet_wrap(~response_label, scales = "free", ncol = 2) +
    ggplot2::labs(
      title = "Morris effects across core response families",
      subtitle = paste0("Top-", top_k,
                        " parameters per response are labelled; grey points show the remainder."),
      caption = if (isTRUE(is_demo)) {
        paste(
          "DEMO - science pending. Points summarize exact observation-level statistics from .mio across treatments and seasons.",
          "High sigma indicates nonlinearity and/or interaction involvement, not a specific parameter pair.",
          "Importance is conditional on the sampled ranges and scenarios.",
          sep = "\n"
        )
      } else {
        paste(
          "Points summarize exact observation-level statistics from .mio across treatments and seasons.",
          "High sigma indicates nonlinearity and/or interaction involvement, not a specific parameter pair.",
          "Importance is conditional on the sampled ranges and scenarios.",
          sep = "\n"
        )
      },
      x = "Mean within-observation mu* share",
      y = "Mean observation-level sigma"
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
