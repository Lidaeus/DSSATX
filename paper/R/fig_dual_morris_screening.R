read_dual_morris_screening <- function(input_dir, allow_demo = FALSE) {
  manifest <- jsonlite::fromJSON(file.path(input_dir, "paper_data_manifest.json"),
                                 simplifyVector = FALSE)
  if (!identical(manifest$bundle_type, "dual_spring_morris_screening")) {
    stop("Fig3 Morris requires a frozen dual-spring screening bundle")
  }
  is_demo <- !identical(manifest$data_status, "science_validated")
  if (is_demo && !isTRUE(allow_demo)) {
    stop("Morris data are not science_validated; use --allow-unvalidated-demo for review")
  }
  files <- c(scores = "morris_process_scores.csv", ranking = "screening_126_parameters.csv",
             active = "proposed_active_parameters.csv")
  listed <- vapply(manifest$artifacts, function(a) a$path, character(1))
  if (anyDuplicated(listed) || !setequal(listed, unname(files))) {
    stop("Unexpected or missing dual-spring Morris artifacts")
  }
  tables <- lapply(files, function(name) {
    path <- file.path(input_dir, name)
    if (!identical(sha256_file(path), manifest$artifacts[[match(name, listed)]]$sha256)) {
      stop("Morris artifact hash mismatch: ", name)
    }
    utils::read.csv(path, fileEncoding = "UTF-8", check.names = FALSE)
  })
  c(list(manifest = manifest, is_demo = is_demo), tables)
}

build_dual_morris_screening <- function(bundle, profile, is_demo) {
  groups <- c("phenology", "canopy", "biomass", "yield_harvest",
              "water_response", "nitrogen_response", "water_nitrogen_interaction")
  seasons <- c("25SP", "26SP")
  scores <- bundle$scores[, c("season_id", "response_group", "parameter", "group_score")]
  rank <- bundle$ranking[, c("parameter", "core_rank", "core_score", "core_cumulative", "selection")]
  rank <- rank[order(rank$core_rank), ]
  threshold <- bundle$manifest$threshold
  n <- bundle$manifest$n_parameters
  equal_numeric <- function(a, b) length(a) == length(b) &&
    all(is.finite(a) & is.finite(b) & abs(a - b) < 1e-12)
  if (nrow(rank) != n || !identical(as.integer(rank$core_rank), seq_len(n)) ||
      anyDuplicated(rank$parameter) || !setequal(scores$parameter, rank$parameter) ||
      !setequal(scores$season_id, seasons) || !setequal(scores$response_group, groups) ||
      nrow(scores) != n * length(seasons) * length(groups) ||
      anyDuplicated(scores[c("season_id", "response_group", "parameter")]) ||
      any(!is.finite(scores$group_score) | scores$group_score < 0)) {
    stop("Incomplete Morris ranking or season-by-process score matrix")
  }
  totals <- tapply(scores$group_score, scores[c("season_id", "response_group")], sum)
  core_scores <- with(scores[scores$response_group %in% groups[1:4], ],
                      tapply(group_score, parameter, mean))
  if (!equal_numeric(as.vector(totals), rep(1, length(totals))) ||
      !equal_numeric(rank$core_score, core_scores[rank$parameter]) ||
      !equal_numeric(rank$core_cumulative, cumsum(rank$core_score)) ||
      any(diff(rank$core_score) > 0) || !equal_numeric(tail(rank$core_cumulative, 1), 1)) {
    stop("Morris core scores or cumulative ranking do not match the process scores")
  }
  crossing <- which(rank$core_cumulative >= threshold)[1]
  core <- rank[rank$selection == "core_98", ]
  extra <- rank[rank$selection == "process_supplement", ]
  active <- bundle$active[order(bundle$active$core_rank), ]
  if (is.na(crossing) || !identical(core$core_rank, seq_len(crossing)) ||
      !identical(core$parameter, unlist(bundle$manifest$core_parameters)) ||
      !identical(extra$parameter, unlist(bundle$manifest$supplement_parameters)) ||
      !identical(active$parameter, c(core$parameter, extra$parameter)) ||
      !identical(active$selection, c(core$selection, extra$selection)) ||
      !all(rank$selection %in% c("core_98", "process_supplement", "fixed_candidate"))) {
    stop("Morris selection does not match the cutoff and frozen proposal")
  }

  top <- head(core$parameter, 15)
  a_data <- scores[scores$parameter %in% top, ]
  a_data$core_rank <- match(a_data$parameter, top)
  a_data <- a_data[order(match(a_data$season_id, seasons), a_data$core_rank,
                         match(a_data$response_group, groups)), ]
  a_data$score_pct <- 100 * a_data$group_score
  a_data$parameter <- factor(a_data$parameter, levels = rev(top))
  a_data$group <- factor(a_data$response_group, levels = groups,
    labels = c("物候", "冠层", "生物量", "产量", "灌溉响应", "施氮响应", "水氮交互"))
  a_data$season_id <- factor(a_data$season_id, levels = seasons)
  ceiling_pct <- ceiling(max(a_data$score_pct) / 5) * 5
  panel_title <- ggplot2::element_text(size = profile$panel_label_size_pt, face = "bold",
                                       margin = ggplot2::margin(b = 6))
  a <- ggplot2::ggplot(a_data, ggplot2::aes(group, parameter, fill = score_pct)) +
    ggplot2::geom_tile(colour = "white", linewidth = .16) +
    ggplot2::facet_grid(~season_id) +
    ggplot2::scale_x_discrete(expand = c(0, 0)) +
    ggplot2::scale_y_discrete(expand = c(0, 0)) +
    ggplot2::scale_fill_gradient(low = "#F4F7F8", high = "#175979",
      limits = c(0, ceiling_pct), name = "组内敏感性得分占比（%）") +
    ggplot2::guides(fill = ggplot2::guide_colourbar(title.position = "top",
      barwidth = grid::unit(41, "mm"), barheight = grid::unit(2, "mm"))) +
    ggplot2::labs(x = NULL, y = NULL, title = "(a)") +
    theme_q1(profile) +
    ggplot2::theme(plot.title = panel_title, legend.position = "bottom",
      legend.justification = "left", legend.box.spacing = grid::unit(1, "mm"),
      legend.title = ggplot2::element_text(size = 7),
      axis.line = ggplot2::element_blank(), axis.ticks = ggplot2::element_blank(),
      axis.text.x = ggplot2::element_text(angle = 90, hjust = 1, vjust = .5),
      strip.background = ggplot2::element_rect(fill = "#EDF2F4", colour = NA),
      strip.text = ggplot2::element_text(size = 7),
      panel.spacing.x = grid::unit(1.6, "mm"))

  rank$cumulative_pct <- 100 * rank$core_cumulative
  palette <- c(core_98 = "#175979", process_supplement = "#AC4B16", fixed_candidate = "#ABB3BA")
  extra$cumulative_pct <- 100 * extra$core_cumulative
  # Stagger text to the left of the crowded cutoff, preserving rank order.
  # Point coordinates always come directly from the frozen screening table.
  extra$label_rank <- seq(min(extra$core_rank) - 9, max(extra$core_rank) + 11, length.out = nrow(extra))
  extra$label_x <- 82
  b <- ggplot2::ggplot(rank, ggplot2::aes(cumulative_pct, core_rank)) +
    ggplot2::geom_vline(xintercept = 100 * threshold, linetype = "dashed",
      colour = "#657681", linewidth = .26) +
    ggplot2::geom_path(colour = palette[["fixed_candidate"]], linewidth = .46) +
    ggplot2::geom_path(data = rank[seq_len(crossing), ], colour = palette[["core_98"]],
      linewidth = .54) +
    ggplot2::geom_point(data = rank[rank$selection != "process_supplement", ],
      ggplot2::aes(colour = selection), size = .88) +
    ggplot2::geom_segment(data = extra,
      ggplot2::aes(x = label_x + 1.5, y = label_rank, xend = cumulative_pct, yend = core_rank),
      linewidth = .25, colour = palette[["process_supplement"]]) +
    ggplot2::geom_point(data = extra, ggplot2::aes(colour = selection), size = 1.2, stroke = 0) +
    ggplot2::geom_text(data = extra, ggplot2::aes(x = label_x, y = label_rank, label = parameter),
      hjust = 1, size = 7 / ggplot2::.pt, family = profile$font_family[[1]],
      colour = palette[["process_supplement"]]) +
    ggplot2::annotate("text", x = 100 * threshold - 1, y = n - 4,
      label = paste0(100 * threshold, "%"), hjust = 1, colour = "#53636E",
      size = 7 / ggplot2::.pt, family = profile$font_family[[1]]) +
    ggplot2::scale_colour_manual(values = palette, breaks = names(palette),
      labels = c(paste0("核心入选（", nrow(core), "）"), paste0("补充入选（", nrow(extra), "）"),
                 paste0("未入选（", n - nrow(core) - nrow(extra), "）"))) +
    ggplot2::scale_x_continuous(limits = c(0, 102), breaks = seq(0, 100, 25),
      expand = c(0, 0)) +
    ggplot2::scale_y_reverse(breaks = c(1, 20, 40, 60, 80, 100, n), limits = c(n + 2, -1),
      expand = c(0, 0)) +
    ggplot2::labs(title = "(b)", x = "累计敏感性得分占比（%）", y = "参数排名") +
    theme_q1(profile) +
    ggplot2::theme(plot.title = panel_title, legend.position = "inside",
      legend.position.inside = c(.035, .045), legend.justification.inside = c(0, 0),
      legend.background = ggplot2::element_rect(fill = "white", colour = "#D3D9DD", linewidth = .22),
      legend.margin = ggplot2::margin(3, 9, 3, 3),
      legend.key.width = grid::unit(3.2, "mm"), legend.key.height = grid::unit(3.6, "mm"),
      legend.text = ggplot2::element_text(size = 6.4),
      panel.grid.major = ggplot2::element_line(colour = "#E9EDF0", linewidth = .18)) +
    ggplot2::guides(colour = ggplot2::guide_legend(ncol = 1, override.aes = list(size = 1.7)))
  caption <- if (is_demo) "DEMO · 科学审查待完成" else NULL
  plot <- patchwork::wrap_plots(a, b, widths = c(1.04, .75)) +
    patchwork::plot_annotation(caption = caption, theme = ggplot2::theme(
      plot.caption = ggplot2::element_text(family = profile$font_family[[1]], size = 6,
                                           colour = "#687078", hjust = 0)))
  list(plot = plot, heatmap = a_data, ranking = rank, supplement_labels = extra,
       summary = data.frame(n_parameters = n, paired_trajectories = bundle$manifest$paired_trajectories,
         cutoff = threshold, cutoff_rank = crossing, cutoff_parameter = core$parameter[crossing],
         core_score_share = core$core_cumulative[crossing],
         selected_score_share = sum(rank$core_score[rank$parameter %in% active$parameter])),
       # Remove a quarter of the previous panel (b) plot-area width from the page.
       width_mm = profile$double_column_width_mm - 19.5, height_mm = 125)
}
