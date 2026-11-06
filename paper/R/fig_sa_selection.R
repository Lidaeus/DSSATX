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

build_single_seed_selection <- function(rankings, summary, profile, is_demo=TRUE) {
  d <- rankings[order(rankings$rank), , drop=FALSE]
  k <- summary$elbow_rank; k95 <- summary$k95
  blue <- "#0072B2"; orange <- "#D55E00"; grey <- "#B7BDC4"
  p1 <- ggplot2::ggplot(d, ggplot2::aes(rank, score)) +
    ggplot2::geom_line(colour="#A4ADB5", linewidth=0.45) +
    ggplot2::geom_point(ggplot2::aes(colour=elbow_core),size=1.5) +
    ggplot2::scale_colour_manual(values=c("TRUE"=blue,"FALSE"=grey),guide="none") +
    ggplot2::geom_vline(xintercept=k,colour=blue,linetype="dashed",linewidth=0.35) +
    ggplot2::annotate("text",x=k+5,y=max(d$score)*.80,hjust=0,size=2.5,colour=blue,
      label=sprintf("Elbow: %d parameters\n%.1f%% relative influence",k,100*summary$elbow_coverage)) +
    ggplot2::scale_y_continuous(labels=scales::label_percent(accuracy=1),expand=ggplot2::expansion(mult=c(0,.12))) +
    ggplot2::scale_x_continuous(breaks=c(1,k,20,40,60,86),expand=ggplot2::expansion(mult=c(.02,.03))) +
    ggplot2::labs(title="a  Ranked influence",x="Parameter rank",y="Balanced relative influence") +
    theme_q1(profile) + ggplot2::theme(axis.text=ggplot2::element_text(size=7),plot.title=ggplot2::element_text(size=8,face="bold"))
  p2 <- ggplot2::ggplot(d,ggplot2::aes(rank,cumulative)) +
    ggplot2::geom_line(colour=blue,linewidth=.65) +
    ggplot2::geom_hline(yintercept=.95,colour=orange,linetype="dotted",linewidth=.35) +
    ggplot2::geom_vline(xintercept=k95,colour=orange,linetype="dotted",linewidth=.35) +
    ggplot2::geom_point(data=d[d$rank %in% c(k,k95),],size=2,colour=orange) +
    ggplot2::annotate("text",x=k95+4,y=.84,hjust=0,size=2.5,colour=orange,
                      label=sprintf("90%%: %d parameters\n95%%: %d parameters",summary$k90,k95)) +
    ggplot2::scale_y_continuous(labels=scales::label_percent(accuracy=1),limits=c(0,1.03),breaks=c(0,.25,.5,.75,.95,1),expand=c(0,0)) +
    ggplot2::scale_x_continuous(breaks=c(1,k,k95,60,86),expand=ggplot2::expansion(mult=c(.02,.03))) +
    ggplot2::labs(title="b  Cumulative influence",x="Parameter rank",y="Cumulative relative influence") +
    theme_q1(profile) + ggplot2::theme(axis.text=ggplot2::element_text(size=7),plot.title=ggplot2::element_text(size=8,face="bold"))
  plot <- p1+p2+patchwork::plot_layout(ncol=2)+patchwork::plot_annotation(
    title="Morris screening: phenology, LAI and harvested dry mass",
    subtitle="2025 spring observed conditions | 30 trajectories | one seed (20261030)",
    caption=paste0("Equal weight for three response-normalized influence shares; not variance explained. Elbow is a screening heuristic.\n",
                   if(is_demo) "DEMO - current-run review; science_pending. Full original response contract did not pass." else ""),
    theme=ggplot2::theme(plot.title=ggplot2::element_text(size=9,face="bold"),plot.subtitle=ggplot2::element_text(size=7),
                        plot.caption=ggplot2::element_text(size=6,hjust=0)))
  list(plot=plot,source=d,height_mm=93)
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
