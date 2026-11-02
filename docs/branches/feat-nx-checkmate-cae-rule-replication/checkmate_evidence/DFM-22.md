# DFM-22 孔径与料厚比 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_MinimumHoleDiameter.html`
（注册表 `NXCheckers.json#dfms_MinimumHoleDiameter`）。

## 2. Check-Mate 判定口径

- 测量孔的最小直径 D（沿孔轴）与板厚标准值 T；
- `D/T < diam_thickness_ratio_min`（**默认 1**）→ 失败。

## 3. 我们的实现

规则 `R-DFM-22`：`meas.diameter < params.min_hole_diameter_ratio * meas.thickness - 1e-9`；
默认 `min_hole_diameter_ratio = 1.0`，与 Check-Mate 默认一致。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 公式与默认值 | `D < 1×T` | `d < 1×t` | **一致** |
| 测量 | 孔特征最小直径 | 同轴孔组最小直径（粗筛） | 近似 |

## 5. 置信度

**high（口径）** —— 公式与默认阈值一致；测量为粗筛近似。
