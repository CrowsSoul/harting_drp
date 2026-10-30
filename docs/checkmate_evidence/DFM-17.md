# DFM-17 多抽芯方向 — Check-Mate 取证

## 1. 出处

- Check-Mate DFM Advisor **无抽芯方向聚类检查器**；
- 相邻概念：`dfms_UndercutDetection.html` 的 `draft_dirs`（默认 `(0,0,1)`、`(0,0,-1)`），
  只判断倒扣在给方向上是否可见，不统计方向簇数量。

## 2. 判定口径（本项目基线）

- 收集未豁免倒扣的方向向量，按夹角聚类（`direction_cluster_angle_deg`，默认 15°）；
- 方向簇数 `direction_count > 1` → 报（需要多个滑块/斜顶方向）。

## 3. 我们的实现

规则 `R-DFM-17`：`meas.direction_count > 1`，measured=簇数，threshold=1，unit「方向」。
几何层负责聚类（方向相似度是特征分组，不是判定）。

## 4. 差异清单

无 Check-Mate 对照项；聚类容差（15°）为项目口径，待工艺确认。

## 5. 置信度

**low（对齐度）** —— 公式为项目基线。
