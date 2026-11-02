# DFM-04 孔/槽对齐 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_SlotToHoleAlignment.html`
（注册表 `NXCheckers.json#dfms_SlotToHoleAlignment`）。

## 2. Check-Mate 判定口径

- 孔轴与槽轴对齐：`dist_max`（**默认 0.01 mm**）与 `ang_max`（**默认 0.1°**）；
- 超出即失败。

## 3. 我们的实现

规则 `R-DFM-04`：
`meas.offset_mm > params.center_offset_tolerance_mm + 1e-9 or meas.angle_deg > params.axis_angle_tolerance_deg + 1e-9`；
默认 0.2 mm / 1.0°；几何层用孔/槽 metadata 或槽识别结果配对。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 距离容差 | 0.01 mm | 0.2 mm | 本项目明显更松（粗筛容差），待工艺确认 |
| 角度容差 | 0.1° | 1.0° | 同上 |

## 5. 置信度

**medium** —— 公式一致，容差为项目口径。
