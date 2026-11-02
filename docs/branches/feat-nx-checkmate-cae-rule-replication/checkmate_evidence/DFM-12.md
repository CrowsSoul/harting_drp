# DFM-12 模具壁厚 — Check-Mate 取证

## 1. 出处

Check-Mate DFM Advisor **无模具钢净厚检查器**；阈值为注塑工艺基线。

## 2. 判定口径（本项目基线）

- 同一零件内两个可比较特征（筋/凸台）中心距（垂直于开模方向）减去两特征外包半宽；
- `steel < min_mold_steel_thickness_mm` → 报。

## 3. 我们的实现

规则 `R-DFM-12`：`meas.steel_mm < params.min_mold_steel_thickness_mm`，unit mm，rounding 2。

## 4. 差异清单

无 Check-Mate 对照项；中心距近似为包围盒/轴线点，属粗筛。

## 5. 置信度

**low（对齐度）** —— 公式为项目基线。
