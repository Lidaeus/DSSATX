build_spearman_structure <- function(data, profile, is_demo = FALSE) {
  required <- c("parameter_a", "parameter_b", "spearman")
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop("spearman_correlation.csv missing: ", paste(missing, collapse = ", "))
  data$spearman <- as.numeric(data$spearman)
  if (nrow(data) == 0 || any(!is.finite(data$spearman))) {
    stop("Spearman input must contain finite correlations; exclude constant parameters upstream")
  }
  if (any(abs(data$spearman) > 1 + 1e-10)) stop("Spearman correlation outside [-1, 1]")
  parameters <- unique(c(as.character(data$parameter_a), as.character(data$parameter_b)))
  n_parameters <- length(parameters)
  row_index <- match(data$parameter_a, parameters)
  column_index <- match(data$parameter_b, parameters)
  off_diagonal <- row_index != column_index
  pairs <- data.frame(
    row_index = pmin(row_index[off_diagonal], column_index[off_diagonal]),
    column_index = pmax(row_index[off_diagonal], column_index[off_diagonal]),
    spearman = data$spearman[off_diagonal]
  )
  keys <- paste(pairs$row_index, pairs$column_index, sep = ":")
  for (values in split(pairs$spearman, keys)) {
    if (diff(range(values)) > 1e-10) stop("Conflicting symmetric/duplicate Spearman entries")
  }
  pairs <- pairs[!duplicated(keys), , drop = FALSE]
  if (nrow(pairs) != n_parameters * (n_parameters - 1) / 2) {
    stop("Spearman input is missing one or more parameter pairs")
  }
  pairs <- pairs[order(pairs$row_index, pairs$column_index), , drop = FALSE]
  pairs$parameter_a <- parameters[pairs$row_index]
  pairs$parameter_b <- parameters[pairs$column_index]
  pairs$x <- pairs$column_index
  pairs$y <- n_parameters + 1 - pairs$row_index
  pairs$display_role <- "correlation"
  diagonal <- data.frame(
    row_index = seq_len(n_parameters), column_index = seq_len(n_parameters),
    spearman = 1, parameter_a = parameters, parameter_b = parameters,
    x = seq_len(n_parameters), y = n_parameters + 1 - seq_len(n_parameters),
    display_role = "parameter_label"
  )
  matrix_data <- rbind(pairs, diagonal)
  # Upper triangle only. Horizontal names end inside their diagonal cell,
  # extending into the unused lower triangle instead of rotated axis labels.
  plot <- ggplot2::ggplot(pairs, ggplot2::aes(x = x, y = y, fill = spearman)) +
    ggplot2::geom_tile(colour = "white", linewidth = 0.25) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.2f", ifelse(abs(spearman) < 0.005, 0, spearman))),
                      size = 6 / ggplot2::.pt, family = profile$font_family[[1]]) +
    ggplot2::geom_text(data = diagonal,
                      ggplot2::aes(x = x + 0.40, y = y, label = parameter_a),
                      inherit.aes = FALSE, hjust = 1, fontface = "bold",
                      size = profile$font_size_pt / ggplot2::.pt,
                      family = profile$font_family[[1]]) +
    ggplot2::scale_fill_gradient2(low = profile$palette$negative, mid = "white",
                                  high = profile$palette$positive, midpoint = 0, limits = c(-1, 1),
                                  breaks = c(-1, -0.5, 0, 0.5, 1)) +
    ggplot2::scale_x_continuous(limits = c(-0.5, n_parameters + 0.5), breaks = NULL, expand = c(0, 0)) +
    ggplot2::scale_y_continuous(limits = c(0.5, n_parameters + 0.5), breaks = NULL, expand = c(0, 0)) +
    ggplot2::coord_equal() +
    ggplot2::labs(title = "Conditional-ensemble rank-correlation structure",
                  subtitle = "Upper triangle; parameter names on the diagonal; descriptive only",
                  x = NULL, y = NULL, fill = expression(Spearman~rho), caption = demo_caption(is_demo)) +
    ggplot2::guides(fill = ggplot2::guide_colourbar(barwidth = grid::unit(45, "mm"),
                                                 barheight = grid::unit(2.5, "mm"),
                                                 title.position = "left")) +
    theme_q1(profile) +
    ggplot2::theme(axis.text = ggplot2::element_blank(), axis.ticks = ggplot2::element_blank(),
                   axis.line = ggplot2::element_blank(), legend.position = "bottom",
                   legend.justification = "center", legend.title = ggplot2::element_text(),
                   plot.margin = ggplot2::margin(4, 4, 4, 4)) +
    demo_watermark(is_demo)
  height_calc <- if (n_parameters > 10) 150 else 90
  list(plot = plot, source = matrix_data, height_mm = height_calc)
}
