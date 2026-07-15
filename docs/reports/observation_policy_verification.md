# Observation Policy 与处理均值 sigma 验证记录

> 日期：2026-07-15
> 分支：`codex/p0-research-credibility`
> 范围：显式 log 双侧变换、处理均值 sigma、组倍率与 pwtadj1 延后

## 1. 已实现口径

- FileA/FileT 与 DSSAT 常规输出保持实际物理尺度；
- `.pst` 中观测和 PEST tagged 输出中的模拟使用同一 `ln((y+offset)/reference)`；
- `y + offset <= 0`、缺少 log 组原尺度 sigma、同一模拟 token 配置冲突均直接失败；
- 处理均值 sigma 支持 `sqrt(SD²/n_eff + sigma_model² + sigma_floor²)`；
- 权重审计同时输出原值/变换值、原 sigma/变换 sigma、来源、组倍率和最终权重；
- 生产入口拒绝 pwtadj1；未来若重新审批，内部回归定义已改为平衡总组 Phi。

## 2. 自动测试

```text
python -m pytest tests/ -q
48 passed
```

覆盖手算 Phi、`w=1/sigma`、均值 sigma、非法重复数、log 非正值、观测—模拟同变换、缺 sigma、tagged 输出替换及总组 Phi 定义。

## 3. 真实 DSSAT/PEST++ 冒烟

使用 `eggplant_pheno`、10 个 ADAPM 观测、自然对数策略执行 DSSAT 和 PEST++ `noptmax=0`：

- 原始 `Evaluate.OUT` 模拟 ADAPS 为 `36`；
- PEST `PestEval.OUT` 中对应模拟为 `ln(36)=3.58351893846`；
- `.pst` 观测为 `ln(45)=3.80666248977`；
- 原尺度 sigma 为 `25`，传播后 `sigma_log=0.518642400349`；
- FileA/FileT 运行副本与 `data/raw/experiments` 原文件 SHA-256 完全一致；
- PEST++ 完成 1/1 forward run，失败 0，报告总 `Phi=1.85111`。

手算回归：

```text
10 × [(ln(45) - ln(36)) / sqrt(ln(1 + (25/45)²))]²
= 1.85111
```

PEST 报告与手算一致。

## 4. 尚未解决的科学输入

代码能力通过不代表正式试验 sigma 已确定。正式率定前仍需整理原始重复或为每个变量审批 pooled/assumed sigma、`n_eff`、模型误差、sigma 下限及是否启用 log。当前示例配置不自动用于正式运行，正式 frozen bounds 也未变更。
