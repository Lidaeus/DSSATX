build_selected_dynamics <- function(comparison, variables, treatments, profile, is_demo = FALSE) {
  data <- comparison[comparison$variable %in% variables &
                       as.character(comparison$treatment) %in% treatments, , drop = FALSE]
  if (nrow(data) == 0) stop("No requested dynamics variable-treatment combinations are available")
  keys <- expand.grid(variable = variables, treatment = treatments, stringsAsFactors = FALSE)
  panels <- list()
  for (index in seq_len(nrow(keys))) {
    frame <- data[data$variable == keys$variable[[index]] &
                    as.character(data$treatment) == keys$treatment[[index]], , drop = FALSE]
    if (nrow(frame) == 0) next
    frame <- frame[order(frame$time), , drop = FALSE]
    unit <- frame$unit[[1]]
    subtitle <- paste0("Treatment ", keys$treatment[[index]], if (nzchar(unit)) paste0("; ", unit) else "")
    panels[[length(panels) + 1L]] <- ggplot2::ggplot(frame, ggplot2::aes(time)) +
      ggplot2::geom_line(ggplot2::aes(y = simulated, linetype = "Simulated"),
                         colour = profile$palette$simulated, linewidth = profile$data_linewidth_pt) +
      ggplot2::geom_point(ggplot2::aes(y = observed, shape = "Observed"),
                          colour = profile$palette$observed, fill = "white", size = 1.7, stroke = 0.55) +
      ggplot2::scale_linetype_manual(values = c(Simulated = "solid")) +
      ggplot2::scale_shape_manual(values = c(Observed = 21)) +
      ggplot2::labs(title = frame$variable_label[[1]], subtitle = subtitle,
                    x = frame$time_label[[1]], y = NULL) +
      theme_q1(profile)
  }
  columns <- max(1L, min(length(treatments), 2L))
  plot <- patchwork::wrap_plots(panels, ncol = columns, guides = "collect") +
    patchwork::plot_annotation(tag_levels = "a", caption = demo_caption(is_demo),
      theme = ggplot2::theme(plot.tag = ggplot2::element_text(face = "bold"),
                             plot.caption = ggplot2::element_text(colour = "#666666", size = 5))) &
    ggplot2::theme(legend.position = "top")
  list(plot = plot, source = data,
       height_mm = min(profile$max_height_mm, max(75, 62 * ceiling(length(panels) / columns))))
}
