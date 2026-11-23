"""Render the reviewed 26SP joint IES replay as a standalone diagnostic atlas."""
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
    parser.add_argument("--out", type=Path, required=True, help="Destination PDF")
    parser.add_argument("--font", type=Path, help="Path to a CJK font file")
    args = parser.parse_args()
    archive = Path(__file__).resolve().parent
    path = args.out
    path.parent.mkdir(parents=True, exist_ok=True)

    fig_size = (13.0, 8.8)
    ink, mute, teal, grid = "#173442", "#506873", "#087F81", "#DBE5EA"
    blue, orange, red, grey = "#1475A5", "#C27822", "#B64B63", "#6A7881"
    colors = dict(zip(["N0","N1","N2","N3"], [grey,blue,orange,red]))
    water = ["W1","W2","W3"]
    levels = list(colors)
    family_order = ["lai","shoot_dm","leaf_n","fresh"]
    family_label = {"lai":"叶面积指数","shoot_dm":"叶茎干重","leaf_n":"叶氮浓度","fresh":"累计鲜果"}
    units = {"lai":"m²/m²","shoot_dm":"kg DM/ha","leaf_n":"百分点","fresh":"t/ha"}
    role_style = {"fit":("o",blue), "holdout":("s",teal), "n3":("^",red), "diagnostic":("D",grey)}
    role_label = {"fit":"参与拟合","holdout":"保留 N1","n3":"保留 N3","diagnostic":"零权重观测"}
    font_override = args.font or os.environ.get("DSSAT_DIAGNOSTIC_FONT")
    fonts = [Path(font_override)] if font_override else [
        Path("/System/Library/Fonts/STHeiti Medium.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ]
    font = next((f for f in fonts if f.is_file()), None)
    if font is None:
        parser.error("Provide a usable CJK font with --font")
    font_manager.fontManager.addfont(font)
    face = font_manager.FontProperties(fname=font).get_name()
    plt.rcParams.update({
        "font.family": [face, "DejaVu Sans"], "font.size": 10, "axes.unicode_minus": False,
        "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#9DB0BA", "axes.labelcolor": ink, "xtick.color": mute,
        "ytick.color": mute, "text.color": ink, "axes.titlesize": 12, "axes.titleweight": "bold",
    })
    d = pd.read_csv(archive / "atlas_daily.csv", float_precision="round_trip")
    obs = pd.read_csv(archive / "matched_observations.csv")
    stats = pd.read_csv(archive / "fit_metrics.csv")
    end = pd.read_csv(archive / "terminal_yield_pairs.csv")
    history = pd.read_csv(archive / "ies_phi_history.csv")
    receipt = json.loads((archive / "replay_receipt.json").read_text())
    audit = json.loads((archive / "balance_audit.json").read_text())
    bounds = pd.read_csv(archive / "bounds.csv").set_index("name")
    p = pd.read_csv(archive / "best_parameters.csv", index_col=0).value
    parameter_pos = (p - bounds.lower) / (bounds.upper - bounds.lower)
    meta = d[["run","treatment","water_level","nitrogen_level"]].drop_duplicates()
    assert len(meta) == 12 and set(d.groupby("treatment").size()) == {126}
    assert receipt["iteration"] == 4 and receipt["member"] == "4"

    for var in ("maintenance","fruit_growth"):
        d[var + "_kg"] = 10 * d[var]
    layer = pd.read_csv(archive / "atlas_layer_settlement.csv", float_precision="round_trip")

    def page(number, title, subtitle):
        fig = plt.figure(figsize=fig_size, facecolor="white")
        fig.text(.075,.951,"DSSATX  /  26SP 茄子", fontsize=9.5, color=teal, fontweight="bold")
        fig.text(.075,.901,title, fontsize=23, fontweight="bold")
        fig.text(.075,.862,subtitle, fontsize=10.5,color=mute)
        fig.add_artist(Line2D([.075,.935],[.84,.84],color=grid,lw=1,transform=fig.transFigure))
        fig.add_artist(Line2D([.075,.935],[.057,.057],color=grid,lw=1,transform=fig.transFigure))
        fig.text(.075,.034,"61 参数 IES  ·  80 成员 / 4 轮  ·  最终成员 4  ·  独立复跑",fontsize=8.5,color=mute)
        fig.text(.935,.034,f"{number:02d} / 09",ha="right",fontsize=8.5,color=mute)
        return fig

    def finish(pdf, fig):
        pdf.savefig(fig)
        plt.close(fig)

    def style(ax, x=False):
        ax.grid(axis="both" if x else "y", color=grid, lw=.65)
        ax.set_axisbelow(True)
        ax.yaxis.set_major_locator(MaxNLocator(5))

    def legend(fig, with_obs=False, at=.813):
        handles = [Line2D([0],[0],color=colors[n],lw=2,label=n) for n in levels]
        if with_obs:
            for role in ("fit","holdout","n3"):
                marker,_ = role_style[role]
                handles.append(Line2D([0],[0],marker=marker,ls="",mec=ink,mfc=ink if role=="fit" else "white",
                                      color=ink,label=role_label[role],ms=5.5))
        fig.legend(handles=handles,loc="center",bbox_to_anchor=(.5,at),ncol=len(handles),frameon=False,
                   fontsize=9.4,handletextpad=.6,columnspacing=1.6)

    def panels(fig, nrows, ncols=3, *, wspace=.27, hspace=.42, top=.771, bottom=.166):
        return fig.add_gridspec(nrows,ncols,left=.102,right=.924,bottom=bottom,top=top,wspace=wspace,hspace=hspace)

    def overlay(ax, treatment, code, color):
        if code is None:
            return
        q = obs.loc[obs.treatment.eq(treatment)&obs.column.eq(code)]
        for role, g in q.groupby("role"):
            marker,_ = role_style[role]
            v = g.observed / (1000 if code == "CHFPW" else 1)
            ax.scatter(g.dap, v, s=22, marker=marker, facecolors=color if role=="fit" else "white",
                       edgecolors=color, lw=.95, zorder=4)

    def trajectories(fig, specs, note, *, with_obs=False):
        legend(fig, with_obs)
        g = panels(fig,len(specs),hspace=.34)
        for r,(var,label,code) in enumerate(specs):
            vals=list(d[var].dropna())
            if code:
                vals.extend(obs.loc[obs.column.eq(code),"observed"]/(1000 if code=="CHFPW" else 1))
            low=min(0,min(vals))
            high=max(vals)
            for c,w in enumerate(water):
                ax=fig.add_subplot(g[r,c])
                for n in levels:
                    q=d[d.water_level.eq(w)&d.nitrogen_level.eq(n)].sort_values("dap")
                    line=ax.step if var=="yield_cumulative" else ax.plot
                    kwargs={"where":"post"} if var=="yield_cumulative" else {}
                    line(q.dap,q[var],color=colors[n],lw=1.5,**kwargs)
                    overlay(ax,int(q.treatment.iloc[0]),code,colors[n])
                if r==0: ax.set_title(w)
                ax.set_ylim(low,high*1.045 if high>0 else 1)
                ax.set_xlim(d.dap.min(),d.dap.max()+2)
                style(ax)
                if c==0: ax.set_ylabel(label)
                else: ax.tick_params(labelleft=False)
                if r==len(specs)-1: ax.set_xlabel("移栽后天数")
                else: ax.tick_params(labelbottom=False)
        fig.text(.075,.075,note,fontsize=9,color=mute)

    with PdfPages(path, metadata={"Title":"DSSATX 26SP 61 参数联合率定诊断图册",
                                "Author":"DSSATX research","Subject":"Final IES iteration 4, member 4"}) as pdf:
        fig=page(1,"率定总览","第 4 轮成员 4 的目标族拟合与 IES 收敛轨迹")
        top = fig.add_gridspec(1,2,left=.09,right=.92,bottom=.46,top=.779,wspace=.37)
        ax=fig.add_subplot(top[0,0]); style(ax)
        ax.plot(history.iteration,history["mean"],"o-",color=grey,lw=1.8,label="集合均值")
        ax.plot(history.iteration,history["min"],"o-",color=teal,lw=2.2,label="集合最小值")
        ax.set(xlabel="IES 轮次",ylabel="加权目标函数 Φ",xticks=range(5)); ax.legend(frameon=False)
        ax=fig.add_subplot(top[0,1]); style(ax,x=True)
        fit=stats[(stats.role=="fit")&(stats.scale=="family")].set_index("key").loc[family_order]
        ax.barh([family_label[k] for k in family_order],fit.phi,color=[blue,teal,grey,orange],height=.58)
        ax.invert_yaxis(); ax.set_xlabel("成员 4 的 Φ 贡献"); ax.set_xlim(0,fit.phi.max()*1.23)
        for i,v in enumerate(fit.phi): ax.text(v+.17,i,f"{v:.2f}",va="center",color=ink,fontsize=9)
        cols=["目标族","观测数","RMSE","MAE","偏差","R²"]
        cells=[[family_label[k]+"  ("+units[k]+")",str(int(v.n)),f"{v.rmse:.3f}",f"{v.mae:.3f}",
                f"{v.bias:+.3f}",f"{v.r2:.3f}"] for k,v in fit.iterrows()]
        ax=fig.add_axes([.085,.153,.83,.24]); ax.axis("off")
        table=ax.table(cellText=cells,colLabels=cols,cellLoc="center",colLoc="center",bbox=[0,0,1,1],
                       colWidths=[.32,.10,.15,.15,.15,.13])
        table.auto_set_font_size(False); table.set_fontsize(10.5)
        for (r,c),cell in table.get_celld().items():
            cell.set_edgecolor("white"); cell.set_facecolor("#DFEBEE" if r==0 else ("#F1F6F8" if r%2 else "white"))
            if r==0: cell.get_text().set_fontweight("bold")
            if c==0: cell.get_text().set_ha("left"); cell.PAD=.045
        fig.text(.085,.103,f"独立复跑 Φ = {receipt['phi_replayed']:.6f}  ·  131 项正权重观测  ·  偏差 = 模拟 − 实测",
                 color=mute,fontsize=9)
        fig.text(.085,.08,"R² = 1 − SSE/SST。干重合并叶和茎；叶氮误差单位为干重百分点。",color=mute,fontsize=9)
        finish(pdf,fig)

        fig=page(2,"各目标的实测与模拟","对角线表示一对一吻合；保留处理与零权重叶氮点分别标注")
        handles=[Line2D([0],[0],marker=m,mec=c,mfc=c if role=="fit" else "white",ls="",label=role_label[role],ms=6)
                 for role,(m,c) in role_style.items()]
        fig.legend(handles=handles,loc="center",bbox_to_anchor=(.5,.809),ncol=4,frameon=False)
        gs=panels(fig,2,hspace=.50,top=.756,bottom=.167)
        labels=[("LAID","叶面积指数","m²/m²"),("LWAD","叶干重","kg DM/ha"),("SWAD","茎干重","kg DM/ha"),
                ("LN%D","叶氮浓度","% DM"),("CHFPW","累计鲜果","t/ha")]
        for i,(code,label,unit) in enumerate(labels):
            ax=fig.add_subplot(gs[i//3,i%3]); q=obs[obs.column.eq(code)]
            div=1000 if code=="CHFPW" else 1
            vals=np.r_[q.observed.to_numpy()/div,q.simulated.to_numpy()/div]
            lo=0 if code!="LN%D" else vals.min()*.9; hi=vals.max()*1.05
            ax.plot([lo,hi],[lo,hi],color="#8C9FA7",lw=1,ls="--",zorder=1)
            for role,z in q.groupby("role"):
                m,c=role_style[role]
                ax.scatter(z.observed/div,z.simulated/div,marker=m,s=26,edgecolor=c,
                           facecolor=c if role=="fit" else "white",alpha=.87,lw=.8,zorder=3)
            ax.set(xlim=(lo,hi),ylim=(lo,hi),xlabel="实测  "+unit,ylabel="模拟  "+unit,title=label); style(ax,x=True)
            ax.xaxis.set_major_locator(MaxNLocator(5))
        ax=fig.add_subplot(gs[1,2]); z=obs[obs.role.eq("fit")].copy()
        z["resid"]=(z.simulated-z.observed)*z.weight
        ax.boxplot([z.loc[z.group.eq(k),"resid"] for k in family_order],orientation="horizontal",
                   tick_labels=["LAI","干重","叶氮","鲜果"],widths=.50,
                   medianprops={"color":teal},boxprops={"color":grey},flierprops={"markersize":3,"alpha":.45})
        ax.axvline(0,color="#9DB0BA",lw=1); ax.set(title="加权残差",xlabel="权重 ×（模拟 − 实测）"); style(ax,x=True)
        ax.set_yticks(range(1,5), ["LAI","干重","叶氮","鲜果"])
        fig.text(.075,.083,"鲜果单位为 t/ha。验算与绘图均使用观测原日期。",color=mute,fontsize=9)
        finish(pdf,fig)

        fig=page(3,"冠层与器官生长","同一行的三种水分处理共用纵轴，实测点区分拟合与留出")
        trajectories(fig,[("lai","LAI\n(m²/m²)","LAID"),("leaf_DM","叶干重\n(kg DM/ha)","LWAD"),
                          ("stem_DM","茎干重\n(kg DM/ha)","SWAD")],
                     "LAI 曲线来自精细面积账本，观测误差指标采用 DSSAT 原生输出的打印值。",with_obs=True)
        finish(pdf,fig)

        fig=page(4,"累计鲜果与终期氮梯度","每日累计用采收阶梯表示，终期比较取各处理最后一个实测采收日期")
        legend(fig, True)
        pane=panels(fig,2,hspace=.46)
        ymax=max(obs.loc[obs.column.eq("CHFPW"),"observed"].max()/1000,d.yield_cumulative.max())*1.10
        for i,w in enumerate(water):
            ax=fig.add_subplot(pane[0,i])
            for n in levels:
                g=d[d.water_level.eq(w)&d.nitrogen_level.eq(n)].sort_values("dap")
                ax.step(g.dap,g.yield_cumulative,where="post",color=colors[n],lw=1.5)
                overlay(ax,int(g.treatment.iloc[0]),"CHFPW",colors[n])
            ax.set(title=w,ylim=(0,ymax),xlabel="移栽后天数"); style(ax)
            if i==0: ax.set_ylabel("累计鲜果 (t/ha)")
            a=fig.add_subplot(pane[1,i])
            p_end=end[end.water_level.eq(w)].set_index("nitrogen_level").loc[levels]
            a.plot(levels,p_end.observed/1000,"o--",color=grey,lw=1.45,label="实测",mfc="white")
            a.plot(levels,p_end.simulated/1000,"o-",color=teal,lw=1.65,label="模拟")
            a.set(ylim=(47,80),xlabel="施氮水平"); style(a)
            if i==0: a.set_ylabel("末次实测日期 (t/ha)"); a.legend(frameon=False,fontsize=9)
        fig.text(.075,.075,"W1、W2、W3 的模拟 N2 终期鲜果均低于 N1，实测方向均为增加。",fontsize=9,color=mute)
        finish(pdf,fig)

        fig=page(5,"根吸收、无机库与同化","根系实际吸收、库内存量与同化通量按单位分别显示")
        trajectories(fig,[("U_cumulative","累计实吸\n(kg N/ha)",None),("Q_NO3","硝态氮库存\n(kg N/ha)",None),
                          ("Q_NH4","铵态氮库存\n(kg N/ha)",None),("A_daily","日同化量\n(kg N/ha/d)",None)],
                     "Q 是植株等效无机氮库存；土壤端实际扣账由逐层账本独立核对。")
        finish(pdf,fig)

        fig=page(6,"器官氮状态与冠层光合","临界氮状态、叶表功能氮及冠层碳输入使用各自口径")
        trajectories(fig,[("NNI_raw_leaf","叶经典 NNI\n(比值)",None),
                          ("leaf_N_functional_area","低端参照以上叶氮\n(g N/m² 叶)",None),
                          ("photo_N_mean","日均光合氮因子\n(0-1)",None),
                          ("PG_daily","冠层日光合输入\n(kg CH₂O/ha/d)",None)],
                     "面积功能氮为账本中的低端参照以上叶氮。实际光合氮因子来自日内叶片调用的等权均值。")
        finish(pdf,fig)

        fig=page(7,"碳消耗与叶面积周转","同水分下检查营养和果实碳流、新增叶面积与叶面积损失")
        trajectories(fig,[("maintenance_kg","维持呼吸\n(kg CH₂O/ha/d)",None),
                          ("fruit_growth_kg","果实生长用碳\n(kg CH₂O/ha/d)",None),
                          ("LAI_new","新增 LAI\n(m²/m²/d)",None),("LAI_lost","损失 LAI\n(m²/m²/d)",None)],
                     "本批次的奢侈氮分配选项关闭。碳通量和面积变化均取自独立复跑的日账本。")
        finish(pdf,fig)

        fig=page(8,"逐层吸氮与高氮处理差值","层累计取最终结算量，包含季末尚待土壤记账部分")
        legend(fig)
        pane=panels(fig,2,hspace=.45)
        layered=layer.set_index(["water_level","nitrogen_level","layer"]).settled_n.sort_index()
        max_n=layered.max()*1.10
        deltas=[]
        for w in water:
            q=d[d.water_level.eq(w)].pivot(index="dap",columns="nitrogen_level",values="U_cumulative")
            deltas.append(pd.DataFrame({"N2−N1":q["N2"]-q["N1"],"N3−N2":q["N3"]-q["N2"]}))
        max_d=max(float(np.abs(q.to_numpy()).max()) for q in deltas)
        for i,w in enumerate(water):
            ax=fig.add_subplot(pane[0,i])
            for j,n in enumerate(levels):
                q=layered.loc[w,n]
                ax.barh(q.index+(j-1.5)*.18,q,height=.16,color=colors[n])
            ax.invert_yaxis(); ax.set(title=w,xlim=(0,max_n),xlabel="最终结算量 (kg N/ha)")
            if i==0: ax.set_ylabel("土层索引")
            ax.yaxis.set_major_locator(MaxNLocator(6,integer=True)); style(ax,x=True)
            a=fig.add_subplot(pane[1,i]); q=deltas[i]
            a.plot(q.index,q["N2−N1"],color=orange,label="N2−N1",lw=1.55)
            a.plot(q.index,q["N3−N2"],color=red,label="N3−N2",lw=1.55,ls="--")
            a.axhline(0,color=grey,lw=.8);a.set(ylim=(-max_d*1.12,max_d*1.12),xlabel="移栽后天数")
            if i==0: a.set_ylabel("累计实吸差 (kg N/ha)"); a.legend(frameon=False,fontsize=9)
            style(a)
        fig.text(.075,.075,"逐层账本共 39,312 行。质量流、扩散与候选量没有计入这张实际结算图。",fontsize=9,color=mute)
        finish(pdf,fig)

        fig=page(9,"留出表现、边界与守恒","独立复跑对照留出误差、参数最邻近边界和碳氮账")
        ax=fig.add_axes([.08,.49,.42,.28]); ax.axis("off")
        group=(stats[(stats.scale=="family") & stats.role.isin(["holdout","n3"])]
               .pivot(index="key",columns="role",values="rmse").loc[family_order])
        table=ax.table(cellText=[[family_label[k],units[k],f"{v.holdout:.3f}",f"{v.n3:.3f}"] for k,v in group.iterrows()],
                       colLabels=["目标族","误差单位","N1 RMSE","N3 RMSE"],cellLoc="center",bbox=[0,0,1,1])
        table.auto_set_font_size(False); table.set_fontsize(9.4)
        for (r,c),cell in table.get_celld().items():
            cell.set_edgecolor("white"); cell.set_facecolor("#DFEBEE" if r==0 else ("#F1F6F8" if r%2 else "white"))
            if r==0: cell.get_text().set_fontweight("bold")
        ax=fig.add_axes([.62,.48,.29,.29])
        near=pd.concat([parameter_pos,1-parameter_pos],axis=1).min(axis=1).nsmallest(7)
        z=parameter_pos.loc[near.index]
        ax.scatter(z,np.arange(len(z)),color=[red if v<.01 or v>.99 else teal for v in z],s=35,zorder=3)
        ax.set(xlim=(-.045,1.045),xticks=[0,.25,.5,.75,1],yticks=np.arange(len(z)),yticklabels=z.index,
               xlabel="参数在区间内的位置 (下界 0 / 上界 1)",title="最靠近边界的 7 项")
        ax.invert_yaxis(); ax.axvline(0,color=grey,lw=.8); ax.axvline(1,color=grey,lw=.8); style(ax,x=True)
        ax.set_yticks(np.arange(len(z)), z.index)
        fig.text(.08,.386,"最大守恒残差",fontsize=14,fontweight="bold")
        metrics=[("植株季节氮账",audit["max_season_plant_N_residual_gN_m2"],"g N/m²"),
                 ("每日实际碳账",audit["max_daily_cash_residual_gCH2O_m2"],"g CH₂O/m²"),
                 ("每日无机氮账",audit["max_daily_inorganic_residual_gN_m2"],"g N/m²")]
        for i,(title,value,u) in enumerate(metrics):
            x=.08+i*.29
            fig.text(x,.344,title,fontsize=10,color=mute)
            fig.text(x,.301,f"{value:.2e}",fontsize=18,color=teal,fontweight="bold")
            fig.text(x,.274,u,fontsize=9,color=mute)
        fig.text(.08,.201,"保留 N1 包括 W1–N1 和 W3–N1；保留 N3 包括三种水分处理。",fontsize=10)
        fig.text(.08,.161,"最优成员的 RWDTH、TRIFL 精确触边；XFINT、YSWBAR(3) 离边界不足区间宽度 1%。",fontsize=10)
        fig.text(.08,.120,"三种水分下 N1 到 N2 的鲜果排序仍需检验。本图册记录该参数点的模拟与观测。",fontsize=10,color=mute)
        finish(pdf,fig)

    print(path)


if __name__ == "__main__":
    main()
