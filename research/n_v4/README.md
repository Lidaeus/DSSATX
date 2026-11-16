# V4 P0/P1：固定基线下分离机制，再进入共同接受与储备

> Historical workflow. Its original scripts are preserved at `archive/pre-standalone-root-n`. Use the [current suite](../../RESEARCH.md) for new runs.

## 当前LAI优先入口（2026-11-03）

本工作树从7c981878建立独立分支`codex/n-v4-lai-20261103`，按用户要求显著压低
健康组织N日动员率，并增加单一的叶氮状态—可用C/N—新叶组装路径。
见[lai_spec.md](lai_spec.md)。旧P1/P2段落均为交付时快照。

`lai_workflow.py`进行隔离编译、原生驱动、固定12处理、输入拒绝和兼容回归；
`controlled_lai.py`运行5类合成整株机制试验；`analyze_lai.py`和
`analyze_controlled_lai.py`独立复核同612项目标、原生输入和器官／C/N／面积日账。
输出固定为`D:/Tomato_Cal/subprojects/critical_n/reports/n_v4_lai_20261103`。
所有新开关默认关闭，未覆盖现用执行体，也未启动参数率定。

## 当前P2入口（2026-11-03）

本工作树已实现可关闭的P2共同接受与叶茎有机R子库存，见
[p2_spec.md](p2_spec.md)。历史P1说明保留在下文，其“尚未实现”状态描述的是P1交付。

`p2_workflow.py`负责隔离构建交付、原生测试、固定参数对照、非法配置检查；
`analyze_p2.py r5`复核612目标、真实源库预算、库存与实际光合调用。
输出为`D:/Tomato_Cal/subprojects/critical_n/reports/n_v4_p2_20261103`。
P2默认关闭；不能只换exe就认为已启用。完整启用需实际工作目录的NML包含
`common_acceptance=1,reserve_mode=1`及显式容量、填充时标和保护设置。
本阶段是工程交付，不自动推广为最佳拟合/管理模型，不自动重新率定。

用户于2026-11-03要求开始实施前一份审查报告，并在未来批判性吸收四区间设计。
基线为67620982上的官方4.8.6.4+C4 r2，工作分支为
`codex/n-v4-p0-p1-20261103`。旧工作树、输入、率定批次和执行体均不覆盖。

本阶段交付的是默认保持兼容、支持独立机制检验的研究引擎。没有将Phi最低的
曲线组合升级为正式模型：它重新产生了W2的N0/N3产量倒挂。

## 新配置与语义

新增字段仅在完整C4 stage5/A/叶耦合路径上允许启用。

| 字段 | 默认 | 含义 |
|---|---:|---|
| leaf_min_ratio / stem_min_ratio | -1 | -1继承原min_ratio；显式值必须在(0,1)，仅移动对应软低端参考 |
| leaf_inf / stem_inf | 0 | 正值启用`cinf+(a-cinf)*max(W0,W)^(-b)`；0精确走旧核函数 |
| photo_reference_mode | 0 | 0保持旧面积氮参照；1使用独立固定功能SLN参考 |
| photo_sln_ref | -1 | mode1必须显式给出正值，单位g N/m²叶；与SLW的cm²基准换算一次 |
| leaf_expansion_mode | 0 | 0保留旧额外浓度限制；1省略该政策因子，保留原生新组织N/C预算、共享状态及根冠分配 |
| v4_diagnostics | 0 | 1输出PlantNV4.csv，逐日记录实际叶门控、接受前后生长与叶→茎储碳转移 |

Nmin仍是器官软参考，未增加实际浓度投影。新生组织最低组成仍由原生VEGGR的
实际可用N预算控制；mode1不是无N生长，也不是最终共同接受算法。

固定面积氮目前仍使用Norg相对软低端参考的功能代理，并对高于临界部分封顶；
独立有机储备R尚未实现，不能把此代理称为真正的Rubisco或显式储备扣除。
本阶段接口不应不加验证地整体加入PEST活动参数。旧率定默认只识别旧字段，
本阶段只扩展隔离回放与独立预算审计，没有修改主PEST注册或现有冻结边界。

## 复现入口

```
python -X utf8 research/n_v4/p1_workflow.py prepare
# 以本独立工作树的CMake/Ninja/gfortran构建build/bin/dscsm048.exe后：
python -X utf8 research/n_v4/p1_workflow.py deliver
python -X utf8 research/n_v4/p1_workflow.py units
python -X utf8 research/n_v4/p1_workflow.py cases
python -X utf8 research/n_v4/p1_workflow.py guards
python -X utf8 research/n_v4/p1_workflow.py trace-checks
python -X utf8 research/n_v4/analyze_p1.py
```

输出固定到`D:/Tomato_Cal/subprojects/critical_n/reports/n_v4_p0_p1_20261103`，
已完成批次拒绝覆盖。新批次须先明确改为独立输出根目录。
prepare冻结原C4最佳实际输入、配置、612目标及受保护执行体哈希；所有机制试验
只改变独立NML，不重新率定。曲线形状试验保持原建立期平台及W0，不能称为
完整复现V15曲线或移植V15最佳参数。

原生五组驱动包含核心/预算/C1—C4/P1核函数；实跑覆盖默认精确回归、官方
模式回归、11组全12处理固定参数试验、3组开启追踪的精确复验、6种非法配置
拒绝，以及实际叶级光合调用重建。全化学元素C闭合不在本阶段声称范围内。

## 下一阶段已授权方向，尚未实现

1. 一次性C/N共同接受，区分实际资源限制和可选扩展政策；原生最低新叶组成
   与软Nmin分开定义。P1表明不能只删除额外叶门控。
2. 叶、茎R作为Norg的真实可动员子库存，有限填充、保护、释放、衰老／移除损失。
   R不额外创建N、DM或叶面积，不把有机N逆向变成硝态N。
3. 在同一预算下重新检查功能N→光合、花源／坐果与果实生长接受、根吸收受体反馈。
   保持原生果实N组成与同日商品成熟果观测定义。
4. 将四区间设计落实为连续状态，不硬切换：高N时优先修复功能并按接受能力补库；
   低C时先限制同化承诺、让未同化N留在Q。以后若确需富N促长，只用一个有界
   营养体需求权重，在C/N共同接受前作用，默认增幅0；不同时无依据提高SLA和DM。
5. 轻度缺N可先影响面积而维持SLN；严重持续功能亏缺才应产生更明显能力／衰老反馈。
   不把`1-exp(-3Z)`与充足区直接拼接，不承诺软Nmin是整株不可跨越的死亡线。

以上不恢复V15质流+主动吸收直接相加、旧0.5平台或总NRUS直接杀面积；
不引入强制产量排序、日期护栏、品质替代目标或25秋前置验收。
