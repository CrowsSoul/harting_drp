# DFM-16 圆角半径 — Check-Mate 取证

## 1. 出处

| 通道 | 位置（本机安装，不入库） |
|---|---|
| 官方文档（参考） | `DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_StandardCornerRadius.html` |

## 2. Check-Mate 判定口径（参考）

- `dfms_StandardCornerRadius`：识别轴线平行铣削方向的凹圆柱面，半径不在
  `standard_corner_radii`（默认 `1.0/1.5/2.0/3.0/5.0/10.0 mm`）内 → 失败；
- 这是"标准刀具半径"口径，**不是注塑内/外圆角倍率**；Check-Mate DFM Advisor
  没有注塑圆角倍率检查器。

## 3. 我们的实现

规则 `R-DFM-16`：
- 内圆角阈值 = 名义壁厚 × `inner_radius_ratio`（默认 0.25）；
- 外圆角阈值 = 名义壁厚 × `outer_radius_ratio`（默认 0.5）；
- expression 用 `if(meas.is_outer == 1, 外倍率, 内倍率) * meas.nominal_wall_mm` 选倍率；
- 角上缺圆角（`has_radius == 0`）另起一个 case，measured 记 0。

## 4. 差异清单（口径级差异）

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 半径是否属于标准系列 | 半径 ≥ 壁厚 × 内/外倍率 | 不同取向；本项目为注塑设计口径 |
| 系列/倍率 | 固定 6 项标准半径 | 倍率可配 | 保留项目口径，待工艺确认 |

## 5. 置信度

**low（对齐度）** —— NX 口径为铣削标准半径；注塑倍率无对照。
