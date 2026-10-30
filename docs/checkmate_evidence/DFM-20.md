# DFM-20 孔到边缘距离 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_PunchedHoleToPartEdge.html`
（注册表 `NXCheckers.json#dfms_PunchedHoleToPartEdge`）。

## 2. Check-Mate 判定口径

- 测量冲孔（含根部圆角）到板边的最短距离 C；
- 以板厚标准值 T 为基准：`C/T < dist_thickness_ratio_min`（**默认 3**）→ 失败。

## 3. 我们的实现

规则 `R-DFM-20`：`meas.gap < params.min_edge_distance_ratio * meas.thickness - 1e-9`；
默认 `min_edge_distance_ratio = 1.5`；几何层用包围盒估板边、中心距减孔半径。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 公式 | `C < 3T` | `gap < 1.5t` | 同构，阈值更松（1.5 vs 3），待工艺确认 |
| 测量 | 孔特征含根部圆角到板边最短距离 | 包围盒板边 - 孔半径（粗筛） | 粗筛近似 |

## 5. 置信度

**medium** —— 公式与默认值来自官方文档；阈值差异与近似测量已列明。
