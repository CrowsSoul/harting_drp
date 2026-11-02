# DFM-18 尖角 — Check-Mate 取证

## 1. 出处

| 通道 | 位置（本机安装，不入库） |
|---|---|
| 规则文件 | `DESIGN_TOOLS\checkmate\dfa\checker\pdq\mqc_pdq_sharp_edge_angle.dfa`（PDQ 设计质量检查） |
| 同类 | `mqc_pdq_sharp_face_angle.dfa`、`vda_face_sharp_corner.dfa` |

## 2. Check-Mate 判定口径（参考）

- 在成环的边上检查尖角：二面角小于 `angle_tolerance`（**默认 0.5°**）即报；
- 另有 `distance`（0.1）、`tangent_angle`（30°）、`curvature`（2）等拓扑采样参数；
- 属于 PDQ（设计质量）类，不是 DFM Advisor 的注塑检查。

## 3. 我们的实现

规则 `R-DFM-18`：`meas.angle_deg < params.sharp_angle_deg - params.angle_tolerance_deg`；
默认 `sharp_angle_deg = 60°`、`angle_tolerance_deg = 1e-6`；豁免边在几何层过滤。

## 4. 差异清单（口径级差异）

| 项 | Check-Mate PDQ | 本项目 | 处理 |
|---|---|---|---|
| 阈值 | 二面角 < 0.5° | 二面角 < 60° | 阈值差异大：本项目按注塑尖角工艺门槛，需工艺确认 |
| 对象 | 边环上的尖角 | 相邻平面二面角 | 粗筛近似 |

## 5. 置信度

**medium** —— 规则文件与参数已核对；阈值口径需工艺确认。
