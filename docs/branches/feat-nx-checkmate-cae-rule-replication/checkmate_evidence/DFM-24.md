# DFM-24 折弯与切口距离 — Check-Mate 取证

## 1. 出处

- `DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_PunchedHoleToBend.html`
  （冲孔到折弯起点最短距离）；
- `DESIGN_TOOLS\checkmate\dfa\checker\sheet_metal\mqc_dfm_check_cutout_bending_distance.dfa`
  （截口到折弯距离）。

## 2. Check-Mate 判定口径

- `dfms_PunchedHoleToBend`：`C/T < dist_thickness_ratio_min`（**默认 3**）→ 失败，
  **不含**折弯半径附加项；
- `.dfa` 检查器按截口到折弯距离的范围判定。

## 3. 我们的实现

规则 `R-DFM-24`：`meas.clear < params.bend_clearance_ratio * meas.thickness + meas.radius - 1e-9`；
默认 `bend_clearance_ratio = 3.0`，另加折弯半径 R；几何层用孔轴到折弯轴公垂线距离。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 公式 | `C < 3T` | `clear < 3t + R` | 本项目多计入弯区（R），更保守 |
| 测量 | 孔边到折弯起点 | 轴线公垂线 - 孔半径（粗筛） | 粗筛近似 |

## 5. 置信度

**medium** —— 默认系数一致（3）；+R 项与测量方式为项目口径。
