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
