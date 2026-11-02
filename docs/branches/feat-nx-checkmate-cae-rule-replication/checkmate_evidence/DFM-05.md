# DFM-05 紧固件可达性 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_FastenerAccess.html`
（注册表 `NXCheckers.json#dfms_FastenerAccess`）。

## 2. Check-Mate 判定口径

- 头部区域径向最小间隙 `min_head_clearance`（**默认 2 mm**）；
- 轴向插入空间：可用空间 ≥ 杆长 + `min_insertion_clearance`（**默认 2 mm**）；
- 不满足即失败。

## 3. 我们的实现

规则 `R-DFM-05` 三个 case：
1. `meas.accessible_flag == 1`（上游明确标注不可达）；
2. `meas.diameter_mm < params.tool_envelope_diameter_mm`（默认 10 mm）；
3. `meas.height_mm < params.tool_envelope_height_mm`（默认 40 mm）。
measured/threshold 用 `if()` 按"直径优先、否则高度"选择。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 头部径向 2 mm + 轴向杆长+2 mm | 工具包络 Φ10×40 mm | 不同度量：NX 更贴近螺栓安装，本项目更贴近工具空间 |
| 数据 | 几何自动测量 | 上游紧固件测量记录 | 粗筛：无记录即跳过 |

## 5. 置信度

**low（对齐度）** —— 语义相近但度量不同；需工艺确认采用哪套口径。
