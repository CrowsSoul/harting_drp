# DFM-15 凸台设计 — Check-Mate 取证

## 1. 出处

Check-Mate DFM Advisor **无凸台壁厚/根部圆角检查器**；阈值为注塑工艺基线。

## 2. 判定口径（本项目基线）

四类候选问题，取"实测/阈值"比值最小（最不利）的一项报告：

1. 凸台壁厚 < `min_boss_wall_thickness_mm`；
2. 凸台顶厚 < `min_top_thickness_mm`；
3. 根部圆角 < 凸台壁厚 × `min_root_fillet_to_wall_ratio`；
4. 凸台到侧壁距离 < `min_side_wall_clearance_mm`。

## 3. 我们的实现

问题选择（哪一项最不利）留在 checker；**判定** `meas.worst_measured < meas.worst_threshold`
写在规则 `R-DFM-15` 里，measured/threshold 由 checker 传入。

## 4. 差异清单

无 Check-Mate 对照项；阈值均为项目基线。

## 5. 置信度

**low（对齐度）** —— 公式为项目基线。
