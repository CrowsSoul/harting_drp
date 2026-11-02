# DFM-09 均匀壁厚 — Check-Mate 取证

## 1. 出处

Check-Mate DFM Advisor **无均匀壁厚检查器**；本项目阈值为注塑工艺基线
（`source_standard` 已注明「名义壁厚 ±倍率 + 面积占比」）。

## 2. 判定口径（本项目基线）

- 名义壁厚：上游值 / 显式参数 / 面积样本中位数；
- 逐样本 `ratio = thickness / nominal`，`ratio < low` 或 `> high` 记为偏离；
- 偏离样本面积占比 `area_ratio > max_area_ratio` → 报；
- measured/threshold 以百分数展示（`area_ratio × 100`）。

## 3. 我们的实现

规则 `R-DFM-09`：`meas.area_ratio > params.max_area_ratio`，measured/threshold 各乘 100，单位 `%`，rounding 2。

## 4. 差异清单

无 Check-Mate 对照项；倍率区间与面积占比门槛为项目口径，待工艺确认。

## 5. 置信度

**low（对齐度）** —— 公式为项目基线。
