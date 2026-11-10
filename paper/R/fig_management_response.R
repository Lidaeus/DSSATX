build_management_response <- function(terminal,metadata,profile,is_demo=FALSE) {
  d<-merge(terminal,metadata[,c("season_id","treatment","water_level","nitrogen_level")],by=c("season_id","treatment"))
  d<-d[d$water_level!="CK",]
  d$n_position<-match(d$nitrogen_level,c("N0","N1","N2","N3"))
  d$season_id<-factor(d$season_id,levels=c("25SP","26SP"))
  d$water_level<-factor(d$water_level,levels=c("W1","W2","W3"))
  pieces<-split(d,list(d$season_id,d$water_level),drop=TRUE)
  d<-do.call(rbind,lapply(pieces,function(part) {
    part<-part[order(part$n_position),]
    part$segment<-cumsum(c(1,diff(part$n_position)!=1));part
  }))
  group_size<-ave(d$treatment,interaction(d$season_id,d$water_level,d$segment),FUN=length)
  lines<-d[group_size>1,]
  p<-ggplot2::ggplot(d,ggplot2::aes(n_position))+
    ggplot2::geom_segment(ggplot2::aes(xend=n_position,y=observed,yend=simulated),colour="#C7CED3",linewidth=.25)+
    ggplot2::geom_line(data=lines,ggplot2::aes(y=observed,group=segment),colour="#202020",linewidth=line_width_mm(.9))+
    ggplot2::geom_line(data=lines,ggplot2::aes(y=simulated,group=segment),colour="#858D94",linewidth=line_width_mm(.9))+
    ggplot2::geom_point(ggplot2::aes(y=observed,fill=nitrogen_level,shape=water_level),colour="#202020",size=2.1,stroke=.5)+
    ggplot2::geom_point(ggplot2::aes(y=simulated,colour=nitrogen_level,shape=water_level),fill="white",size=2.1,stroke=.65)+
    ggplot2::facet_grid(season_id~water_level,scales="free_y")+
    ggplot2::scale_x_continuous(breaks=1:4,labels=c("N0","N1","N2","N3"),limits=c(.7,4.3),expand=c(0,0))+
    ggplot2::scale_y_continuous(expand=ggplot2::expansion(mult=c(.14,.15)))+
    ggplot2::scale_shape_manual(values=unlist(profile$water_shapes),guide="none")+
    ggplot2::scale_fill_manual(values=unlist(profile$nitrogen_colors),guide="none")+
    ggplot2::scale_colour_manual(values=unlist(profile$nitrogen_colors),guide="none")+
    ggplot2::labs(x="施氮水平",y="季末鲜果产量（t ha⁻¹）",
      caption="实心点/黑线为实测，空心点/灰线为模拟；同处理竖直配对。缺失氮水平断线，同季共用纵轴。")+
    theme_q1(profile)+ggplot2::theme(strip.background=ggplot2::element_rect(fill="#EEF1F3",colour=NA),
      strip.text=ggplot2::element_text(face="plain"),panel.spacing=grid::unit(3,"mm"),
      plot.caption=ggplot2::element_text(size=5.7,hjust=0))+
    demo_watermark(is_demo)
  list(plot=p,source=d,height_mm=115)
}

build_management_contrasts <- function(contrasts,summary,profile,is_demo=FALSE) {
  panels<-list()
  for(kind in c("nitrogen","water")) {
    d<-contrasts[contrasts$kind==kind,]
    d<-d[order(d$season_id,d$level,d$contrast),]
    d$label<-paste(d$season_id,d$level,d$contrast)
    d$y<-rev(seq_len(nrow(d)))
    p<-ggplot2::ggplot(d,ggplot2::aes(y=y))+
      ggplot2::geom_vline(xintercept=0,colour="#8B959D",linetype="dotted",linewidth=.3)+
      ggplot2::geom_segment(ggplot2::aes(x=observed,xend=simulated,yend=y),colour="#B7C0C6",linewidth=.4)+
      ggplot2::geom_point(ggplot2::aes(x=observed),shape=21,fill="#252525",colour="#252525",size=1.8)+
      ggplot2::geom_point(ggplot2::aes(x=simulated),shape=21,fill="white",colour="#252525",size=1.8,stroke=.6)+
      ggplot2::scale_y_continuous(breaks=d$y,labels=d$label,limits=c(.4,nrow(d)+.6))+
      ggplot2::labs(x="鲜果产量差（t ha⁻¹）",y=NULL,title=if(kind=="nitrogen") "(a) 施氮端点增产" else "(b) 同氮水平的灌溉增产")+
      theme_q1(profile)+ggplot2::theme(plot.title=ggplot2::element_text(face="plain"))
    if(kind=="nitrogen")p<-p+demo_watermark(is_demo)
    panels[[length(panels)+1]]<-p
  }
  plot<-patchwork::wrap_plots(panels,ncol=2,widths=c(1,1.2))+patchwork::plot_annotation(
    caption="实心点为实测差值，空心点为模拟差值；仅比较实际存在的处理组合；不以边际分位数相减构造区间。",
    theme=ggplot2::theme(plot.caption=ggplot2::element_text(family=profile$font_family[[1]],size=5.7,hjust=0)))
  list(plot=plot,source=contrasts,summary=summary,height_mm=148)
}
