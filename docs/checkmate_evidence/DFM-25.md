# DFM-25 翻边高度 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_MinimumFlangeHeight.html`
（注册表 `NXCheckers.json#dfms_MinimumFlangeHeight`）。

## 2. Check-Mate 判定口径

- 测量折弯根部到翻边边缘的高度 H（沿翻边面，不含弯区圆角）；
- 参数：`height_min`（固定最小值，**默认 3 mm**）与
  `height_thickness_ratio_min`（**默认 3**）——两者分别限制绝对高度与 H/T。

## 3. 我们的实现

规则 `R-DFM-25`：`meas.height < params.min_flange_height_ratio * meas.thickness + meas.radius - 1e-9`；
默认 `min_flange_height_ratio = 3.0`，另加折弯半径 R；几何层取腿面包围盒展开跨度（含弯区）。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 公式 | `H ≥ max(3 mm, 3T)`（固定 + 比例双限） | `H ≥ 3t + R` | 本项目无固定 3 mm 下限；测量含弯区 |
| 测量 | 折弯根部到边缘（不含弯区） | 包围盒跨度（含弯区，粗筛） | 粗筛近似 |

## 5. 置信度

**medium** —— 参数默认值已核对；固定下限与测量口径差异待工艺确认。
