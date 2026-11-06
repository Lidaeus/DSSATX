# Controlled forward comparison; theoretical potential curve is separate from model states.
build_partition_forward_compact <- function(function_data,metrics,profile,is_demo=FALSE) {
  colours<-c(baseline="#0072B2",disabled="#D55E00")
  scale_variant<-function()ggplot2::scale_colour_manual(values=colours,
    breaks=c("baseline","disabled"),labels=c("动态分配开启","动态分配关闭"),name=NULL)
  a<-ggplot2::ggplot(function_data,ggplot2::aes(photothermal_age,relative_potential_fraction,colour=variant))+
    ggplot2::geom_line(linewidth=line_width_mm(1))+scale_variant()+
    ggplot2::scale_y_continuous(limits=c(0,1.07),breaks=c(0,.25,.5,.75,1),expand=c(0,0))+
    ggplot2::labs(x="开花后累计光温时间（光温日）",y="相对潜在分配基准",title="(a) 潜在分配基准函数")+
    theme_q1(profile)+demo_watermark(is_demo)
  variables<-c("TERMINAL_FRESH","FRESH_CUM","FRESH_INC","SWAD","LWAD","LAID")
  labels<-c("季末鲜果产量","累计采收鲜重","单次采收鲜重","茎干重","叶干重","LAI")
  m<-metrics[metrics$dataset_role=="all" & metrics$date_offset_days==0 &
    metrics$season_id %in% c("25SP","26SP") & metrics$variable %in% variables,]
  m$y<-match(m$variable,variables)+ifelse(m$season_id=="25SP",-.13,.13)
  links<-merge(m[m$variant=="baseline",c("season_id","variable","nrmse_pct","y")],
    m[m$variant=="disabled",c("season_id","variable","nrmse_pct")],by=c("season_id","variable"),suffixes=c("_baseline","_disabled"))
  d<-ggplot2::ggplot(m,ggplot2::aes(nrmse_pct,y,colour=variant,shape=season_id))+
    ggplot2::geom_segment(data=links,ggplot2::aes(x=nrmse_pct_baseline,xend=nrmse_pct_disabled,y=y,yend=y),
      inherit.aes=FALSE,colour="#BDC6CC",linewidth=.4)+
    ggplot2::geom_point(size=1.9)+scale_variant()+
    ggplot2::scale_shape_manual(values=c("25SP"=16,"26SP"=17),name=NULL)+
    ggplot2::scale_y_continuous(breaks=seq_along(variables),labels=labels,limits=c(.5,6.5))+
    ggplot2::scale_x_continuous(limits=c(0,NA),expand=ggplot2::expansion(mult=c(0,.05)))+
    ggplot2::labs(x="nRMSE（%）",y=NULL,title="(d) 固定参数前向对照")+
    theme_q1(profile)+ggplot2::guides(colour="none")
  plot<-patchwork::wrap_plots(a,d,widths=c(1,1.2),guides="collect") & ggplot2::theme(legend.position="bottom",plot.title=ggplot2::element_text(face="plain"))
  plot<-plot+patchwork::plot_annotation(caption="未重新率定：由C31直接设XFINT=1；正式重新率定消融待开展。\n26SP的LAI指标含12个SLA推算值，与原C31口径一致。",
    theme=ggplot2::theme(plot.caption=ggplot2::element_text(family=profile$font_family[[1]],size=5.7,hjust=0)))
  list(plot=plot,source=function_data,metrics=m,height_mm=92)
}

build_partition_ablation <- function(events, function_data, metrics, profile, is_demo = FALSE, smooth = FALSE) {
  colours <- c(baseline = "#0072B2", disabled = "#D55E00")
  labels <- c(baseline = "动态分配开启", disabled = "动态分配关闭")
  scale_variant <- function() ggplot2::scale_colour_manual(values = colours, breaks = names(colours), labels = labels, name = NULL)
  p_a <- ggplot2::ggplot(function_data, ggplot2::aes(x = photothermal_age, y = relative_potential_fraction, colour = variant)) +
    ggplot2::geom_line(linewidth = line_width_mm(1)) + scale_variant() +
    ggplot2::scale_y_continuous(limits = c(0, 1.06), breaks = c(0, .25, .5, .75, 1), expand = c(0, 0)) +
    ggplot2::labs(x = "开花后累计光温时间（光温日）", y = "相对潜在分配基准", title = "(a) 潜在分配上限的参数化函数") +
    theme_q1(profile) + ggplot2::theme(legend.position = "bottom") + demo_watermark(is_demo)
  source <- events
  if (smooth) {
    groups <- split(events, list(events$season_id, events$variant), drop = TRUE)
    source <- do.call(rbind, lapply(groups, function(d) {
      d <- d[order(d$dap), ]
      if (any(diff(d$simulated) < -1e-9)) stop("Cumulative ablation nodes decrease")
      x <- sort(unique(c(d$dap, seq(min(d$dap), max(d$dap), length.out = 240))))
      y <- stats::splinefun(d$dap, d$simulated, method = "monoH.FC")(x)
      if (any(diff(y) < -1e-8)) stop("Monotone visual interpolation decreased")
      data.frame(season_id = d$season_id[1], variant = d$variant[1], dap = x, simulated = y)
    }))
  }
  event_panel <- function(season, title) {
    d <- source[source$season_id == season, ]
    obs <- events[events$season_id == season & events$variant == "baseline", ]
    ggplot2::ggplot(d, ggplot2::aes(x = dap, y = simulated, colour = variant)) +
      ggplot2::geom_line(linewidth = line_width_mm(1)) +
      ggplot2::geom_point(data = obs, ggplot2::aes(x = dap, y = observed), inherit.aes = FALSE,
        colour = "#202020", fill = "white", shape = 21, size = 1.8, stroke = .5) +
      scale_variant() +
      ggplot2::scale_y_continuous(limits = c(0, NA), expand = ggplot2::expansion(mult = c(0, .08))) +
      ggplot2::labs(x = "定植后天数（d）", y = expression("累计采收鲜重（t " * ha^{-1} * "）"), title = title) +
      theme_q1(profile) + ggplot2::theme(legend.position = "bottom")
  }
  p_b <- event_panel("25SP", "(b) 2025年春 W3N3")
  p_c <- event_panel("26SP", "(c) 2026年春 W3N3")
  variables <- c("TERMINAL_FRESH", "FRESH_CUM", "FRESH_INC", "SWAD", "LWAD", "LAID")
  variable_labels <- c("季末鲜果产量", "累计采收鲜重", "单次采收鲜重", "茎干重", "叶干重", "LAI")
  m <- metrics[metrics$dataset_role == "all" & metrics$date_offset_days == 0 &
    metrics$season_id %in% c("25SP", "26SP") & metrics$variable %in% variables, ]
  m$y <- match(m$variable, variables) + ifelse(m$season_id == "25SP", -.14, .14)
  lo <- m[m$variant == "baseline", c("season_id", "variable", "nrmse_pct", "y")]
  hi <- m[m$variant == "disabled", c("season_id", "variable", "nrmse_pct")]
  links <- merge(lo, hi, by = c("season_id", "variable"), suffixes = c("_baseline", "_disabled"))
  p_d <- ggplot2::ggplot(m, ggplot2::aes(x = nrmse_pct, y = y, colour = variant, shape = season_id)) +
    ggplot2::geom_segment(data = links, ggplot2::aes(x = nrmse_pct_baseline, xend = nrmse_pct_disabled, y = y, yend = y),
      inherit.aes = FALSE, colour = "#B9C3C9", linewidth = line_width_mm(.8)) +
    ggplot2::geom_point(size = 1.8, stroke = .5) + scale_variant() +
    ggplot2::scale_shape_manual(values = c("25SP" = 16, "26SP" = 17), labels = c("2025年春", "2026年春"), name = NULL) +
    ggplot2::scale_y_continuous(breaks = seq_along(variables), labels = variable_labels, limits = c(.5, 6.5)) +
    ggplot2::scale_x_continuous(limits = c(0, NA), expand = ggplot2::expansion(mult = c(0, .05))) +
    ggplot2::labs(x = "nRMSE（%）", y = NULL, title = "(d) 全处理误差及变量间权衡") +
    theme_q1(profile) + ggplot2::theme(legend.position = "bottom", legend.box = "vertical") +
    ggplot2::guides(colour = "none")
  combined <- patchwork::wrap_plots(p_a, p_b, p_c, p_d, ncol = 2, guides = "collect") &
    ggplot2::theme(legend.position = "bottom", plot.title = ggplot2::element_text(size = 7, face = "bold"))
  combined <- combined + patchwork::plot_annotation(caption = if (smooth)
    "样板｜累计线为单调视觉插值，不进入指标；固定参数前向对照，未重新率定。" else
    "样板｜黑边点为观测；累计线连接真实采收节点；同日工作口径，固定参数前向对照。",
    theme = ggplot2::theme(plot.caption = ggplot2::element_text(family = profile$font_family[[1]], size = 5.7, hjust = 0)))
  list(plot = combined, source = source, metrics = m, function_source = function_data, height_mm = 160)
}
