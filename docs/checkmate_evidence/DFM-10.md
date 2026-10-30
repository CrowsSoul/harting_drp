# DFM-10 壁厚变化 — Check-Mate 取证

## 1. 出处

Check-Mate DFM Advisor **无壁厚变化率检查器**；阈值为注塑工艺基线。

## 2. 判定口径（本项目基线）

- 相邻壁厚样本（共享边或上游邻接）取 `ratio = |t_b − t_a| / max(t_a, t_b)`；
- `ratio > max_gradient_ratio` → 报；measured/threshold 以百分数展示。

## 3. 我们的实现

规则 `R-DFM-10`：`meas.ratio > params.max_gradient_ratio`，measured/threshold 各乘 100，单位 `%`，rounding 2。

## 4. 差异清单

无 Check-Mate 对照项；变化率门槛（默认 25%）为项目口径，待工艺确认。

## 5. 置信度

**low（对齐度）** —— 公式为项目基线。
