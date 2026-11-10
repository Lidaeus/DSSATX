build_harvest_dynamics <- function(comparison,selection,profile,is_demo=FALSE,smooth=FALSE) {
  chosen<-selection[selection$use_harvest,]
  chosen<-chosen[order(chosen$season_id,chosen$selection_order),]
  keys<-paste(chosen$season_id,chosen$treatment)
  data<-comparison[comparison$variable %in% c("FRESH_CUM","FRESH_INC") & paste(comparison$season_id,comparison$treatment) %in% keys,]
  panels<-list();curve_source<-list()
  for(variable in c("FRESH_CUM","FRESH_INC"))for(i in seq_len(nrow(chosen))) {
    trt<-chosen[i,];d<-data[data$season_id==trt$season_id & data$treatment==trt$treatment & data$variable==variable,]
    d<-d[order(d$dap),];col<-profile$nitrogen_colors[[trt$nitrogen_level]];shape<-profile$water_shapes[[trt$water_level]]
    curve<-d
    if(variable=="FRESH_CUM" && smooth) {
      if(any(diff(d$simulated)< -1e-9))stop("Cumulative nodes decrease")
      x<-sort(unique(c(d$dap,seq(min(d$dap),max(d$dap),length.out=200))))
      y<-stats::splinefun(d$dap,d$simulated,method="monoH.FC")(x)
      if(any(diff(y)< -1e-8))stop("Monotone interpolation decreased")
      curve<-data.frame(season_id=trt$season_id,treatment=trt$treatment,variable=variable,dap=x,simulated=y)
    }
    if(variable=="FRESH_CUM") {
      p<-ggplot2::ggplot()+ggplot2::geom_line(data=curve,ggplot2::aes(dap,simulated),colour=col,linewidth=line_width_mm(1))+
        ggplot2::geom_point(data=d,ggplot2::aes(dap,observed),shape=shape,fill=col,colour="#202020",size=1.7,stroke=.35)
      curve_source[[length(curve_source)+1]]<-curve[,c("season_id","treatment","variable","dap","simulated")]
      ylim<-c(0,max(data$observed[data$variable==variable],data$simulated[data$variable==variable])*1.08)
      ylabel<-"累计鲜重（t ha⁻¹）"
    } else {
      p<-ggplot2::ggplot(d,ggplot2::aes(dap))+
        ggplot2::geom_segment(ggplot2::aes(xend=dap,y=0,yend=pmax(observed,simulated)),colour="#BFC7CC",linewidth=.25)+
        ggplot2::geom_point(ggplot2::aes(y=observed),shape=shape,fill=col,colour="#202020",size=1.8,stroke=.35)+
        ggplot2::geom_point(ggplot2::aes(y=simulated),shape=shape,fill="white",colour=col,size=1.8,stroke=.55)
      ylim<-c(0,max(data$observed[data$variable==variable],data$simulated[data$variable==variable])*1.12)
      ylabel<-"单次鲜重（t ha⁻¹）"
    }
    title<-paste0("(",letters[length(panels)+1],") ",trt$season_id," ",trt$design_label)
    p<-p+ggplot2::scale_y_continuous(limits=ylim,expand=c(0,0))+
      ggplot2::scale_x_continuous(limits=c(60,125),breaks=c(70,95,120),expand=c(0,0))+
      ggplot2::labs(x="定植后天数（d）",y=if(i==1)ylabel else NULL,title=title)+theme_q1(profile)+
      ggplot2::theme(plot.title=ggplot2::element_text(size=7,face="plain"),plot.margin=ggplot2::margin(2,1,1,1,unit="mm"))
    if(!length(panels))p<-p+demo_watermark(is_demo)
    panels[[length(panels)+1]]<-p
  }
  caption<-if(smooth) "累计线为单调视觉插值，不进入指标。单次采收：实心点为实测，空心点为模拟。" else
    "累计线连接真实采收日模拟值，点为实测。单次采收：实心点为实测，空心点为模拟。"
  plot<-patchwork::wrap_plots(panels,ncol=nrow(chosen))+patchwork::plot_annotation(caption=caption,
    theme=ggplot2::theme(plot.caption=ggplot2::element_text(family=profile$font_family[[1]],size=5.7,hjust=0)))
  list(plot=plot,source=data,curves=do.call(rbind,curve_source),selection=chosen,height_mm=128)
}

build_spring_harvest <- function(comparison, selection, profile, treatment_order, status_note, smooth = FALSE) {
  key <- function(d) paste(d$season_id, d$treatment)
  data <- comparison[comparison$variable %in% c("FRESH_CUM", "FRESH_INC") &
                       key(comparison) %in% key(selection), ]
  data$management <- factor(data$management, levels = treatment_order)
  data$year <- factor(data$season_id, levels = c("26SP", "25SP"), labels = c("2026年", "2025年"))
  data <- data[order(data$year, data$management, data$variable, data$dap), ]
  cumulative <- data[data$variable == "FRESH_CUM", ]
  events <- data[data$variable == "FRESH_INC", ]
  groups <- split(cumulative, interaction(cumulative$year, cumulative$management, drop = TRUE))
  event_key <- function(d) with(d, paste(season_id, treatment, dap, harvest_number))
  if (!identical(event_key(cumulative), event_key(events))) {
    stop("Harvest dates differ between cumulative and event series")
  }
  curves <- do.call(rbind, lapply(groups, function(d) {
    if (any(diff(d$dap) <= 0) || any(diff(d$simulated) < -1e-9)) {
      stop("Cumulative series must use strictly increasing measured dates and nondecreasing yield")
    }
    x <- d$dap
    y <- d$simulated
    if (smooth) {
      x <- sort(unique(c(x, seq(min(x), max(x), length.out = 200))))
      y <- stats::splinefun(d$dap, y, method = "monoH.FC")(x)
      if (any(diff(y) < -1e-9) || any(abs(y[match(d$dap, x)] - d$simulated) > 1e-9)) {
        stop("Monotone cumulative curve changed the measured-date simulation nodes")
      }
    }
    data.frame(season_id = d$season_id[1], treatment = d$treatment[1], year = d$year[1],
      management = d$management[1], dap = x, simulated = y,
      geometry = if (smooth) "monotone_visual" else "event_step")
  }))
  mgmt <- spring_management_scales(selection, profile, treatment_order)
  cumulative_shapes <- if (smooth) setNames(rep(21, length(treatment_order)), treatment_order) else mgmt$shapes
  xlim <- range(data$dap) + c(-3, 3)
  common <- function(title, ylabel, d, show_x) {
    limit <- max(d$observed, d$simulated) * 1.12
    list(ggplot2::facet_grid(year ~ management),
      ggplot2::scale_colour_manual(values = mgmt$colors, guide = "none"),
      ggplot2::scale_fill_manual(values = mgmt$colors, guide = "none"),
      ggplot2::scale_x_continuous(breaks = scales::breaks_pretty(n = 4)),
      ggplot2::scale_y_continuous(breaks = scales::breaks_pretty(n = 3)),
      ggplot2::coord_cartesian(xlim = xlim, ylim = c(0, limit), expand = FALSE),
      ggplot2::labs(x = if (show_x) "定植后天数（d）" else NULL, y = ylabel, title = title),
      theme_q1(profile), ggplot2::theme(
        plot.title = ggplot2::element_text(size = profile$panel_label_size_pt),
        strip.background = ggplot2::element_rect(fill = "#EDF2F4", colour = NA),
        strip.text = ggplot2::element_text(size = 7),
        panel.spacing = grid::unit(2, "mm"),
        panel.grid.major = ggplot2::element_line(colour = "#E9EDF0", linewidth = .19)))
  }
  mapping <- ggplot2::aes(dap, simulated, colour = management)
  line <- if (smooth) ggplot2::geom_line(data = curves,
    ggplot2::aes(dap, simulated, colour = management, linetype = "累计模拟"), linewidth = .44) else
    ggplot2::geom_step(data = curves, mapping = mapping, direction = "hv", linewidth = .44)
  a <- ggplot2::ggplot() + line +
    ggplot2::geom_point(data = cumulative, ggplot2::aes(dap, observed, fill = management, shape = management),
      size = 1.5, colour = "#252525", stroke = .3) +
    ggplot2::scale_shape_manual(values = cumulative_shapes, guide = "none") +
    common("(a) 累计采收鲜重", "累计鲜重（t ha⁻¹）", cumulative, smooth)
  b <- ggplot2::ggplot(events, ggplot2::aes(dap)) +
    ggplot2::geom_segment(ggplot2::aes(xend = dap, y = observed, yend = simulated),
      colour = "#929CA3", linewidth = .28) +
    common("(b) 单次采收鲜重", "单次鲜重（t ha⁻¹）", events, TRUE)
  if (smooth) {
    point_data <- rbind(transform(events, yield = observed, series = "实测"),
                        transform(events, yield = simulated, series = "单次模拟"))
    a <- a + ggplot2::scale_linetype_manual(values = c("累计模拟" = "solid"), name = NULL,
      guide = ggplot2::guide_legend(override.aes = list(colour = "#505050")))
    b <- b + ggplot2::geom_point(data = point_data,
      ggplot2::aes(y = yield, colour = management, shape = series, size = series),
      stroke = .52) +
      ggplot2::scale_size_manual(values = c("实测" = 1.42, "单次模拟" = 1.92), guide = "none") +
      ggplot2::scale_shape_manual(values = c("实测" = 16, "单次模拟" = 1),
        breaks = c("实测", "单次模拟"), name = NULL,
        guide = ggplot2::guide_legend(override.aes = list(colour = "#505050", size = c(1.42, 1.92))))
  } else {
    b <- b + ggplot2::geom_point(ggplot2::aes(y = observed, fill = management, shape = management),
      size = 1.42, colour = "#252525", stroke = .32) +
      ggplot2::geom_point(ggplot2::aes(y = simulated, colour = management, shape = management),
        size = 1.92, fill = NA, stroke = .52) +
      ggplot2::scale_shape_manual(values = mgmt$shapes, guide = "none")
  }
  encoding <- if (smooth) "(a) 线为累计模拟值的单调视觉插值；点为实测。 (b) 实心为实测，空心为模拟。" else
    "(a) 阶梯为采收日累计模拟值；点为实测。 (b) 实心为实测，空心为模拟。"
  note <- paste(c(encoding, status_note), collapse = "\n")
  plot <- patchwork::wrap_plots(a, b, ncol = 1, heights = c(1, 1.06),
    guides = if (smooth) "collect" else "auto") +
    patchwork::plot_annotation(caption = note, theme = spring_caption_theme(profile))
  if (smooth) plot <- plot & ggplot2::theme(legend.position = "bottom", legend.justification = "center")
  list(plot = plot, source = data, curves = curves, selection = selection,
       height_mm = if (smooth) 169 else 163)
}
