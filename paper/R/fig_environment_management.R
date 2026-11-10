build_environment_management <- function(weather, events, dates, profile, is_demo=FALSE) {
  seasons <- c("25SP","26SP")
  x_range <- range(c(0,events$dap,dates$final_dap))
  panels <- list()
  for (row in 1:4) for (column in 1:2) {
    season <- seasons[column]
    w <- weather[weather$season_id==season & weather$in_crop_period,]
    e <- events[events$season_id==season,]
    title <- paste0("(",letters[(row-1)*2+column],") ",season,"  ",
      c("最高与最低气温","太阳辐射","灌溉事件","施氮事件")[row])
    if(row==1) {
      p <- ggplot2::ggplot(w,ggplot2::aes(dap))+
        ggplot2::geom_line(ggplot2::aes(y=TMAX),colour="#B44035",linewidth=line_width_mm(.8))+
        ggplot2::geom_line(ggplot2::aes(y=TMIN),colour="#236B99",linewidth=line_width_mm(.8))+
        ggplot2::scale_y_continuous(limits=range(c(weather$TMAX[weather$in_crop_period],weather$TMIN[weather$in_crop_period])))+
        ggplot2::labs(y="气温（°C）")
    } else if(row==2) {
      p <- ggplot2::ggplot(w,ggplot2::aes(dap,SRAD))+
        ggplot2::geom_line(colour="#9A7A24",linewidth=line_width_mm(.8))+
        ggplot2::scale_y_continuous(limits=c(0,max(weather$SRAD[weather$in_crop_period])*1.04))+
        ggplot2::labs(y="辐射（MJ m⁻² d⁻¹）")
    } else if(row==3) {
      e <- e[e$kind=="irrigation",]
      p <- ggplot2::ggplot(e,ggplot2::aes(dap,amount))+
        ggplot2::geom_segment(ggplot2::aes(xend=dap,y=0,yend=amount),colour="#A7AFB5",linewidth=.2)+
        ggplot2::geom_point(ggplot2::aes(shape=level),size=1.4,stroke=.4,colour="#273C48",fill="white")+
        ggplot2::scale_shape_manual(values=unlist(profile$water_shapes),limits=c("W3","W2","W1","CK"),drop=FALSE,name=NULL)+
        ggplot2::scale_y_continuous(limits=c(0,max(events$amount[events$kind=="irrigation"])*1.08),expand=c(0,0))+
        ggplot2::labs(y="灌水量（mm）")
    } else {
      e <- e[e$kind=="nitrogen" & e$amount>0,]
      p <- ggplot2::ggplot(e,ggplot2::aes(dap,amount,colour=level))+
        ggplot2::geom_segment(ggplot2::aes(xend=dap,y=0,yend=amount),linewidth=.25,alpha=.7)+
        ggplot2::geom_point(size=1.2)+
        ggplot2::scale_colour_manual(values=unlist(profile$nitrogen_colors),name=NULL)+
        ggplot2::scale_y_continuous(limits=c(0,max(events$amount[events$kind=="nitrogen"])*1.08),expand=c(0,0))+
        ggplot2::labs(y="施氮量（kg N ha⁻¹）")
    }
    p <- p+ggplot2::scale_x_continuous(limits=x_range,breaks=seq(0,120,30),expand=ggplot2::expansion(mult=.02))+
      ggplot2::labs(title=title,x=if(row==4) "定植后天数（d）" else NULL)+theme_q1(profile)+
      ggplot2::theme(legend.position="bottom",plot.title=ggplot2::element_text(size=7,face="plain"),
        plot.margin=ggplot2::margin(2,2,1,1,unit="mm"))
    if(row==1 && column==1) p <- p+demo_watermark(is_demo)
    # One shared irrigation legend; 26SP has no CK observations.
    if(row==3 && column==2) p <- p+ggplot2::guides(shape="none")
    panels[[length(panels)+1]] <- p
  }
  plot <- patchwork::wrap_plots(panels,ncol=2,guides="collect") & ggplot2::theme(legend.position="bottom")
  plot <- plot+patchwork::plot_annotation(caption="红/蓝线为最高/最低气温；管理量来自实际FileX输入；N0无施氮；CK单列。",
    theme=ggplot2::theme(plot.caption=ggplot2::element_text(family=profile$font_family[[1]],size=5.8,hjust=0)))
  list(plot=plot,source=weather,events=events,season_dates=dates,height_mm=168)
}

build_weather_reference_comparison <- function(stripes,differences,dates,profile,is_demo=FALSE) {
  palettes <- list(TMAX=c("#FEF9BC","#F3D162","#CD524B","#71372E"),
    TMIN=c("#1E1D70","#4B89A6","#F0EBD8","#D35400"),SRAD=c("#002456","#686A71","#C9B968","#FCE748"))
  variables <- c("TMAX","TMIN","SRAD")
  units <- c("最高气温（°C）","最低气温（°C）","太阳辐射（MJ m⁻² d⁻¹）")
  upper<-lower<-list()
  boundaries<-dates
  boundaries$start_doy<-as.integer(format(as.Date(boundaries$planting_date),"%j"))
  boundaries$end_doy<-as.integer(format(as.Date(boundaries$final_observed_harvest),"%j"))
  boundaries$y<-match(boundaries$season_id,c("25SP","26SP"))
  for(i in seq_along(variables)) {
    v<-variables[i];d<-stripes[stripes$variable==v,];d$y<-match(d$season_id,c("25SP","26SP"))
    upper[[i]]<-ggplot2::ggplot(d,ggplot2::aes(doy,y))+
      ggplot2::geom_tile(fill="#D7DADC",width=1,height=.82)+
      ggplot2::geom_tile(data=d[d$in_crop_period,],ggplot2::aes(fill=value),width=1,height=.82)+
      ggplot2::geom_segment(data=boundaries,ggplot2::aes(x=start_doy,xend=start_doy,y=y-.44,yend=y+.44),
        inherit.aes=FALSE,colour="#B44035",linetype="dashed",linewidth=.35)+
      ggplot2::geom_segment(data=boundaries,ggplot2::aes(x=end_doy,xend=end_doy,y=y-.44,yend=y+.44),
        inherit.aes=FALSE,colour="#B44035",linetype="dashed",linewidth=.35)+
      ggplot2::scale_fill_gradientn(colours=palettes[[v]],name=NULL)+
      ggplot2::scale_x_continuous(limits=c(.5,212.5),breaks=c(16,46,75,106,136,167,197),labels=paste0(1:7,"月"),expand=c(0,0))+
      ggplot2::scale_y_continuous(breaks=1:2,labels=c("25SP","26SP"),limits=c(.5,2.5),expand=c(0,0))+
      ggplot2::guides(fill=ggplot2::guide_colourbar(barwidth=grid::unit(32,"mm"),barheight=grid::unit(2,"mm")))+
      ggplot2::labs(x=NULL,y=NULL,title=paste0("(",letters[i],") ",units[i]))+theme_q1(profile)+
      ggplot2::theme(legend.position="top",plot.title=ggplot2::element_text(size=7,face="plain"),
        axis.line=ggplot2::element_blank(),axis.ticks.y=ggplot2::element_blank())
    dd<-differences[differences$variable==v,]
    lower[[i]]<-ggplot2::ggplot(dd,ggplot2::aes(dap,difference))+
      ggplot2::geom_hline(yintercept=0,colour="#7B858B",linewidth=.25)+
      ggplot2::geom_col(fill=c("#E4A18B","#8FAED2","#D8C482")[i],alpha=.65,width=.85)+
      ggplot2::geom_line(ggplot2::aes(y=rolling7),colour=c("#B94C2F","#236B99","#A18120")[i],linewidth=.45,na.rm=TRUE)+
      ggplot2::geom_hline(yintercept=dd$mean_difference_common_dap[1],colour="#9A4444",linetype="dotted",linewidth=.3)+
      ggplot2::labs(title=paste0("(",letters[i+3],") 两春差值（26SP−25SP）"),x="定植后天数（d）",
        y=if(i<3) "气温差（°C）" else "辐射差（MJ m⁻² d⁻¹）")+theme_q1(profile)+
      ggplot2::theme(plot.title=ggplot2::element_text(size=7,face="plain"))
  }
  upper[[1]]<-upper[[1]]+demo_watermark(is_demo)
  plot<-patchwork::wrap_plots(c(upper,lower),ncol=3)+patchwork::plot_annotation(
    caption="灰色为作物期外数据；空白为无数据；实线为完整7日滑动平均，点线为共同DAP窗口均值。",
    theme=ggplot2::theme(plot.caption=ggplot2::element_text(family=profile$font_family[[1]],size=5.8,hjust=0)))
  list(plot=plot,source=stripes,differences=differences,season_dates=dates,height_mm=125)
}
