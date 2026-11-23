"""Paired 26SP organ nitrogen atlas for the B4 refill experiment."""
import argparse
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
import numpy as np
import pandas as pd

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Output PDF")
    parser.add_argument("--font", type=Path, help="CJK font file")
    args = parser.parse_args()
    archive = Path(__file__).resolve().parent
    args.out.parent.mkdir(parents=True, exist_ok=True)
    receipt = json.loads((archive / "field_replay_receipt.json").read_text())
    data = pd.read_csv(archive / "atlas_source.csv", float_precision="round_trip")
    summ = pd.read_csv(archive / "gradient_summary.csv", float_precision="round_trip")
    if receipt["member"] != 4 or receipt["iteration"] != 4:
        raise ValueError("The atlas refers to 26SP iteration 4, member 4")
    if not all(receipt["baseline_equal_excluding_runtime_timestamp"].values()):
        raise ValueError("The field pair did not reproduce the disabled baseline")
    if data.groupby(["config","run"]).size().to_dict() != {
        (mode,run):126 for mode in ("off","on") for run in range(1,13)
    } or data.duplicated(["config","run","yrdoy"]).any():
        raise ValueError("Expected two complete 12-treatment replays")

    override = args.font or os.environ.get("DSSAT_DIAGNOSTIC_FONT")
    fonts = [Path(override)] if override else [
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ]
    font = next((path for path in fonts if path.is_file()), None)
    if font is None:
        parser.error("Provide a usable CJK font with --font")
    font_manager.fontManager.addfont(font)
    face=font_manager.FontProperties(fname=font).get_name()
    ink="#163540"; muted="#506771"; accent="#007C80"; grid="#DDE8EB"
    colors={"N0":"#687985","N1":"#1877A6","N2":"#BC711C","N3":"#B34263"}
    wat=("W1","W2","W3")
    period_end=int(data.day.max()); shade=period_end-29
    dstyles={"off":(0,(4,3)),"on":"-"}
    plt.rcParams.update({"font.family":[face,"DejaVu Sans"],"font.size":10,"pdf.fonttype":42,
                         "text.color":ink,"axes.labelcolor":ink,"axes.unicode_minus":False,
                         "axes.spines.top":False,"axes.spines.right":False,"axes.edgecolor":"#91A7AC",
                         "xtick.color":muted,"ytick.color":muted,"axes.titleweight":"bold","axes.titlesize":12})

    def layout(number,title,description):
        fig=plt.figure(figsize=(12.9,8.5),facecolor="white")
        fig.text(.074,.953,"DSSATX / 26SP 茄子 / 有机氮回补",color=accent,fontsize=10)
        fig.text(.074,.899,title,fontsize=23,fontweight="bold")
        fig.text(.074,.858,description,fontsize=11,color=muted)
        for y in (.837,.055):
            fig.add_artist(Line2D([.074,.937],[y,y],color=grid,lw=1,transform=fig.transFigure))
        fig.text(.074,.033,"80×4 最优成员 4  ·  田间管理与土壤输入相同  ·  仅切换回补容量和限速",color=muted,fontsize=8.9)
        fig.text(.937,.033,f"{number:02d} / 05",ha="right",color=muted,fontsize=8.9)
        return fig

    def style(ax,x=False):
        ax.grid(axis="both" if x else "y",color=grid,lw=.7)
        ax.set_axisbelow(True);ax.yaxis.set_major_locator(MaxNLocator(5))

    def grid_for(fig):
        return fig.add_gridspec(2,3,left=.102,right=.927,bottom=.17,top=.766,wspace=.245,hspace=.34)

    def config_handles():
        return [
            Line2D([0],[0],color=ink,ls=dstyles["off"],lw=1.45,label="关闭"),
            Line2D([0],[0],color=ink,lw=1.65,label="开启"),
        ]

    def note(fig,msg):
        fig.text(.074,.079,msg,fontsize=9.4,color=muted)

    def series(fig, basis, description):
        axes=grid_for(fig)
        handles=[Line2D([0],[0],color=c,lw=2,label=n) for n,c in colors.items()]+config_handles()
        fig.legend(handles=handles,loc="center",bbox_to_anchor=(.51,.802),ncol=6,frameon=False)
        labels={"leaf":"叶","stem":"茎"}
        for r,organ in enumerate(("leaf","stem")):
            key=f"{basis}_{organ}"
            vals=data[key]
            lo=min(vals.min(),0) if basis=="stock" else max(0,float(vals.min())*.92)
            pad=max(.02,(vals.max()-lo)*.055)
            for i,w in enumerate(wat):
                ax=fig.add_subplot(axes[r,i])
                ax.axvspan(shade,period_end,color="#EAF4F5",lw=0,zorder=0)
                for cfg in ("off","on"):
                    for n,c in colors.items():
                        q=data[data.config.eq(cfg)&data.water_level.eq(w)&data.nitrogen_level.eq(n)].sort_values("day")
                        ax.plot(q.day,q[key],ls=dstyles[cfg],color=c,lw=1.64 if cfg=="on" else 1.19,
                                alpha=1 if cfg=="on" else .62)
                if r==0: ax.set_title(w,pad=7)
                if r==1: ax.set_xlabel("移栽后天数")
                else: ax.tick_params(labelbottom=False)
                if i==0: ax.set_ylabel(labels[organ]+ ("氮库存 (kg N/ha)" if basis=="stock" else "氮浓度 (% 干重)"))
                else: ax.tick_params(labelleft=False)
                ax.set(xlim=(0,period_end),ylim=(lo,vals.max()+pad));style(ax)
        note(fig,description)

    def save(fig,pdf):
        pdf.savefig(fig)
        plt.close(fig)

    with PdfPages(args.out,metadata={"Title":"DSSATX 26SP 茎叶氮梯度诊断图册",
                                                        "Subject":"B4 organic refill paired field replay"}) as pdf:
        fig=layout(1,"有机氮的处理差距有多大","末日浓度和同水分的 N3−N1 差值。末日为 7 月 17 日。")
        ss=summ.query("basis == 'organic' and period == 'terminal'").set_index(["water_level","organ","config"])
        gs=fig.add_gridspec(1,2,left=.12,right=.908,bottom=.474,top=.770,wspace=.33)
        maximum=max(ss["N3_minus_N1"].max(),.05)*1.18
        minimum=min(ss["N3_minus_N1"].min(),0)-.009
        for j,organ in enumerate(("leaf","stem")):
            ax=fig.add_subplot(gs[0,j])
            for i,w in enumerate(wat):
                off=ss.loc[(w,organ,"off"),"N3_minus_N1"]
                on=ss.loc[(w,organ,"on"),"N3_minus_N1"]
                ax.plot([off,on],[i,i],color="#A6BCC2",lw=2,zorder=2)
                ax.scatter(off,i,s=58,edgecolor=ink,facecolor="white",zorder=4)
                ax.scatter(on,i,s=62,edgecolor=accent,facecolor=accent,marker="D",zorder=4)
            ax.set(ylim=(2.5,-.5),xlim=(minimum,maximum),
                   xlabel="N3−N1 (百分点)",title=("叶" if organ=="leaf" else "茎")+"有机氮")
            ax.axvline(0,color=muted,lw=.8);style(ax,x=True)
            ax.set_yticks(range(3), wat)
        markers=[Line2D([0],[0],marker="o",mfc="white",mec=ink,ls="",label="关闭"),
                 Line2D([0],[0],marker="D",color=accent,ls="",label="开启")]
        fig.legend(handles=markers,loc="center",bbox_to_anchor=(.5,.805),ncol=2,frameon=False)
        table_ax=fig.add_axes([.08,.171,.84,.229]);table_ax.axis("off")
        rows=[]
        for w in wat:
            leaf=ss.loc[(w,"leaf","on")];stem=ss.loc[(w,"stem","on")]
            fmt=lambda series: " / ".join(f"{series[n]:.3f}" for n in ("N1","N2","N3"))
            rows.append([w,fmt(leaf),fmt(stem),f"{leaf.N3_minus_N2:+.3f}",
                        f"{stem.N3_minus_N2:+.3f}"])
        tab=table_ax.table(cellText=rows,colLabels=["水分","开启后叶 N1 / N2 / N3","开启后茎 N1 / N2 / N3",
                                                   "叶 N3−N2","茎 N3−N2"],cellLoc="center",bbox=[0,0,1,1],
                           colWidths=[.10,.28,.28,.17,.17])
        tab.auto_set_font_size(False);tab.set_fontsize(10.4)
        for (row,col),cell in tab.get_celld().items():
            cell.set_edgecolor("white")
            cell.set_facecolor("#DFEBEE" if row==0 else ("#F2F7F8" if row%2 else "white"))
            if row==0: cell.get_text().set_fontweight("bold")
        fig.text(.08,.135,"浓度采用 % 干重；差值采用百分点。回补开启值为叶、茎容量 0.015、0.010 g N/g DM，时标 4 d。",
                 fontsize=9.5,color=muted)
        note(fig,"根吸倍率、硝态库容、物候与其他最优参数保持冻结值。")
        save(fig,pdf)

        fig=layout(2,"叶、茎有机氮浓度轨迹","实线为开启，虚线为关闭；每一器官的三个水分面板共用同一纵轴。")
        series(fig,"organic","背景阴影标记季末 30 天。两组曲线均取相同处理、相同模拟日。")
        save(fig,pdf)

        fig=layout(3,"相邻施氮量的同日差值","正值表示较高施氮处理浓度更高；零线便于识别差距收窄或排序反转。")
        handles=[Line2D([0],[0],color=colors["N2"],lw=2,label="N2−N1"),
                 Line2D([0],[0],color=colors["N3"],lw=2,label="N3−N2")]+config_handles()
        fig.legend(handles=handles,loc="center",bbox_to_anchor=(.52,.802),ncol=4,frameon=False)
        axes=grid_for(fig)
        for r,organ in enumerate(("leaf","stem")):
            key="organic_"+organ
            pivot=data.pivot(index=["water_level","config","day"],columns="nitrogen_level",values=key)
            pivot["mid"]=pivot.N2-pivot.N1;pivot["high"]=pivot.N3-pivot.N2
            low=min(0,float(pivot[["mid","high"]].min().min()))
            high=max(0,float(pivot[["mid","high"]].max().max()))
            pad=max(.012,(high-low)*.08)
            for i,w in enumerate(wat):
                ax=fig.add_subplot(axes[r,i]);ax.axvspan(shade,period_end,color="#EAF4F5",lw=0)
                ax.axhline(0,color="#879A9F",lw=.8)
                for cfg in ("off","on"):
                    p=pivot.loc[w,cfg]
                    for name,n in [("mid","N2"),("high","N3")]:
                        ax.plot(p.index,p[name],color=colors[n],ls=dstyles[cfg],lw=1.55 if cfg=="on" else 1.15,
                                alpha=1 if cfg=="on" else .64)
                if i==0: ax.set_ylabel(("叶" if r==0 else "茎")+"有机氮差 (百分点)")
                else: ax.tick_params(labelleft=False)
                if r==0: ax.set_title(w);ax.tick_params(labelbottom=False)
                else: ax.set_xlabel("移栽后天数")
                ax.set(xlim=(0,period_end),ylim=(low-pad,high+pad));style(ax)
        note(fig,"每日先在同一水分内按施氮水平配对，再计算浓度之差。")
        save(fig,pdf)

        fig=layout(4,"站存叶、茎有机氮库存","库存同时反映氮浓度和器官生物量，单位为每公顷 kg N。")
        series(fig,"stock","库存来自器官有机氮账本，不包含无机库、根、果实和已脱落组织。")
        save(fig,pdf)

        fig=layout(5,"含无机氮的总浓度端点","在模拟有机氮之上加回模型分摊的硝态、铵态氮，假定两形态均完全回收。")
        series(fig,"total","本页是观测口径敏感性端点。组织实际消煮回收率仍待独立测定。")
        save(fig,pdf)


if __name__ == "__main__":
    main()
