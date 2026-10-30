# DFM-19 最小弯曲半径 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfa\checker\sheet_metal\mqc_dfm_check_bending_break_radius.dfa`
（KF 规则：折弯断裂半径检查）。

## 2. Check-Mate 判定口径

- 参数：`standard_multiple_factor` 默认 **0.1**、`deviation_multiple_factor` 默认 **1.1**；
- 语义：折弯半径应为板材厚度的标准倍数（0.1t 系列），偏差超过 1.1 倍即报；
- 是"半径标准化"检查，不是"最小 R/t"检查。

## 3. 我们的实现

规则 `R-DFM-19`：`meas.radius < params.min_bend_radius_ratio * meas.thickness - 1e-9`；
默认 `min_bend_radius_ratio = 0.5`；几何层用折弯候选圆柱面内半径、料厚取规则值或推断值。

## 4. 差异清单（口径级差异）

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 半径是否属于 0.1t 标准倍数（±10%） | 内半径 ≥ 0.5t | **不同公式**；本项目关注开裂下限 |
| 参数 | 倍数/偏差因子 | R/t 下限 | 待工艺确认是否叠加标准化判据 |

## 5. 置信度

**medium** —— 规则文件参数已核对；口径差异明确。
