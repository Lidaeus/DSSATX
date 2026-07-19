build_spearman_structure <- function(data, profile, is_demo = FALSE) {
  required <- c("parameter_a", "parameter_b", "spearman")
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) stop("spearman_correlation.csv missing: ", paste(missing, collapse = ", "))
  data$spearman <- as.numeric(data$spearman)
  data <- data[is.finite(data$spearman), required, drop = FALSE]
  if (nrow(data) == 0) stop("Spearman table has no finite rows")
  parameters <- sort(unique(c(as.character(data$parameter_a), as.character(data$parameter_b))))
  mirrored <- rbind(data, data.frame(parameter_a = data$parameter_b, parameter_b = data$parameter_a,
                                     spearman = data$spearman))
  diagonal <- data.frame(parameter_a = parameters, parameter_b = parameters, spearman = 1)
  matrix_data <- rbind(mirrored, diagonal)
  matrix_data$parameter_a <- factor(matrix_data$parameter_a, levels = rev(parameters))
  matrix_data$parameter_b <- factor(matrix_data$parameter_b, levels = parameters)
  plot <- ggplot2::ggplot(matrix_data, ggplot2::aes(x = parameter_b, y = parameter_a, fill = spearman)) +
    ggplot2::geom_tile(colour = "white", linewidth = 0.35) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.2f", spearman)), size = 2.2) +
    ggplot2::scale_fill_gradient2(low = profile$palette$negative, mid = "white",
                                  high = profile$palette$positive, midpoint = 0, limits = c(-1, 1)) +
    ggplot2::coord_equal() +
    ggplot2::labs(title = "Conditional-ensemble rank-correlation structure",
                  subtitle = "Spearman correlation among active parameters; descriptive only",
                  x = NULL, y = NULL, fill = "Spearman r", caption = demo_caption(is_demo)) +
    theme_q1(profile) +
    ggplot2::theme(axis.text.x = ggplot2::element_text(angle = 45, hjust = 1), legend.position = "right") +
    demo_watermark(is_demo)
  list(plot = plot, source = matrix_data, height_mm = 80)
}
