# DFM-03 孔对齐 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_HoleAlignment.html`
（注册表 `NXCheckers.json#dfms_HoleAlignment`）。

## 2. Check-Mate 判定口径

- 配对孔：中心沿孔轴投影距离在 `search_dist`（**默认 1 mm**）内；
- `max_distance`（**默认 0 mm**，中心投影距离上限）与 `max_angle`（孔轴夹角上限，默认 0°）；
- 超出即失败。

## 3. 我们的实现

规则 `R-DFM-03`：任一项超差即报：
`offset > axis_offset_tolerance_mm + 1e-9 or diameter_delta > diameter_tolerance_mm + 1e-9 or angle > axis_angle_tolerance_deg + 1e-9`；
默认 0.1 mm / 0.1 mm / 1.0°；几何层用 metadata 或圆柱面推断配对。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 配对搜索 | 1 mm | 2 mm + 10° 候选 | 项目放宽候选，减少漏配 |
| 容差 | 0 mm / 0° | 0.1 mm / 1° | 工程容差，待工艺确认 |
| 直径差 | 未检查 | 0.1 mm | 项目增值 |

## 5. 置信度

**medium** —— 公式结构已核对；容差为项目口径。
