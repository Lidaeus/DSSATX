# Paper reconstruction prototype: explicit source graph, no raw-model reads.
build_model_framework <- function(nodes, edges, profile, is_demo = FALSE) {
  stopifnot(!anyDuplicated(nodes$id), all(edges$from %in% nodes$id), all(edges$to %in% nodes$id))
  nodes$half_width <- ifelse(nodes$section == "workflow", .205, .14)
  nodes$half_width[nodes$id == "vegetative"] <- .105
  nodes$half_height <- ifelse(nodes$id == "pre", .060, .055)
  nodes$fill <- ifelse(nodes$section == "workflow", "#EDF2F7", "#E8F1E9")
  nodes$fill[nodes$id %in% c("partition", "cohorts", "harvest")] <- "#FBEDD9"
  joined <- merge(edges, nodes[, c("id", "x", "y", "half_height")], by.x = "from", by.y = "id")
  joined <- merge(joined, nodes[, c("id", "x", "y", "half_height")], by.x = "to", by.y = "id", suffixes = c("_from", "_to"))
  joined$y_start <- joined$y_from - joined$half_height_from - .006
  joined$y_end <- joined$y_to + joined$half_height_to + .012
  p <- ggplot2::ggplot() +
    ggplot2::geom_segment(data = joined, ggplot2::aes(x = x_from, xend = x_to, y = y_start, yend = y_end),
      colour = "#687782", linewidth = line_width_mm(.65), arrow = grid::arrow(length = grid::unit(1.6, "mm"), type = "closed")) +
    ggplot2::geom_rect(data = nodes, ggplot2::aes(xmin = x - half_width, xmax = x + half_width,
      ymin = y - half_height, ymax = y + half_height, fill = fill), colour = "#65747D", linewidth = line_width_mm(.55)) +
    ggplot2::scale_fill_identity() +
    ggplot2::geom_text(data = nodes, ggplot2::aes(x = x, y = y, label = label),
      family = profile$font_family[[1]], size = 7 / ggplot2::.pt, lineheight = 1.16, colour = "#18262E") +
    ggplot2::annotate("text", x = c(.23, .75), y = .99,
      label = c("(a) 同化物分配与持续采收", "(b) 参数率定与评价流程"),
      family = profile$font_family[[1]], size = 8 / ggplot2::.pt, fontface = "bold") +
    ggplot2::annotate("text", x = .095, y = .31,
      label = "动态比例由\nXFINT、XFPHT 控制\n\n实际分配另受供给、\n库需求及水氮约束",
      family = profile$font_family[[1]], size = 6.4 / ggplot2::.pt, lineheight = 1.3, colour = "#43535C") +
    ggplot2::annotate("text", x = .75, y = .035,
      label = "固定参数及上游来源单列记录；\n参考集合与 C31 确定性候选分别报告",
      family = profile$font_family[[1]], size = 6 / ggplot2::.pt, lineheight = 1.2, colour = "#596871") +
    ggplot2::scale_x_continuous(limits = c(-.045, 1.015), expand = c(0, 0)) +
    ggplot2::scale_y_continuous(limits = c(-.025, 1.035), expand = c(0, 0)) +
    ggplot2::coord_cartesian(clip = "off") +
    ggplot2::theme_void(base_family = profile$font_family[[1]]) +
    ggplot2::theme(plot.margin = ggplot2::margin(4, 4, 4, 4, unit = "mm"), plot.background = ggplot2::element_rect(fill = "white", colour = NA)) +
    demo_watermark(is_demo)
  list(plot = p, source = nodes, edges = edges, height_mm = 124)
}
