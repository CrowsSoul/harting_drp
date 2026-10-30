# DFM-06 紧固件间隙 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_FastenerClearance.html`
（注册表 `NXCheckers.json#dfms_FastenerClearance`）。

## 2. Check-Mate 判定口径

- 轴向：紧固件与盲孔底的最小端部间隙 `min_tip_clearance`（**默认 1 mm**）；
- 径向：紧固件与通孔的最小径向间隙 `min_through_hole_clearance`（**默认 0.1 mm**）。

## 3. 我们的实现

规则 `R-DFM-06` 两个 case（按 `meas.direction` 区分）：
1. `direction == 1`（径向）且 `clearance < params.radial_clearance_mm - 1e-9`（默认 0.5）；
2. `direction == 2`（轴向）且 `clearance < params.axial_clearance_mm - 1e-9`（默认 0.5）。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 径向 | 0.1 mm | 0.5 mm | 本项目更严，待工艺确认 |
| 轴向 | 1.0 mm（端部间隙） | 0.5 mm（轴向间隙） | 度量对象不同 |
| 数据 | 几何自动测量 | 上游紧固件测量记录 | 粗筛 |

## 5. 置信度

**medium** —— 公式结构一致；阈值与度量对象存在项目差异。
