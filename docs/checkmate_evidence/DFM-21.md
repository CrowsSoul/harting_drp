# DFM-21 孔间距 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_PunchedHoleSpacing.html`
（注册表 `NXCheckers.json#dfms_PunchedHoleSpacing`）。

## 2. Check-Mate 判定口径

- 测量相邻冲孔（含根部圆角）最短距离 S；
- `S/T < dist_thickness_ratio_min`（**默认 3**）→ 失败。

## 3. 我们的实现

规则 `R-DFM-21`：`meas.clear < params.min_hole_spacing_ratio * meas.thickness - 1e-9`；
默认 `min_hole_spacing_ratio = 2.0`；几何层取平行孔组中心距减两孔半径。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 公式 | `S < 3T` | `clear < 2t` | 同构，阈值更松（2 vs 3），待工艺确认 |
| 对象 | 冲孔（含圆角） | 同轴孔组（粗筛外接圆） | 方向一致 |

## 5. 置信度

**medium** —— 公式与默认值来自官方文档。
