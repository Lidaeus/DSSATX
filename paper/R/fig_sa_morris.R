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
        "Current evidence: water-nitrogen rankings in XXQL2502 and XXQL2601 require additional seeds"
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
