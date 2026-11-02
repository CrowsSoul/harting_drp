# DFM-37 窄通道 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_NarrowPassages.html`
（注册表 `NXCheckers.json#dfms_NarrowPassages`）。

## 2. Check-Mate 判定口径

- 识别型腔底面与对置侧壁，测量最小间距 W 与深度 D；
- 判定（任一成立即失败）：
  1. `W < min_width_validation`（**默认 2.0 mm**）；
  2. `D/W > max_dw_ratio`（**默认 10**）；
- 参数：`milling_dir` 默认 `(0,0,-1)`。

## 3. 我们的实现

- 规则 `R-DFM-37`：`meas.width < params.min_channel_width_mm`（默认 1.0）→ P2；
- 几何：复用槽识别（对置内壁 + 共同槽底），取槽宽。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 宽度阈值 | 2.0 mm | 1.0 mm（tool_library 最小刀具直径） | 差异待工艺确认 |
| 深宽比条件 | `D/W > 10` | 未实现（DFM-28 覆盖深宽比） | DFM-28/37 分工：37 管宽度、28 管比例 |
| 测量 | 型腔最小间距 | 槽宽（粗筛） | 方向一致 |

## 5. 置信度

**medium** —— 宽度判据与公式来自官方文档；阈值与实现是项目粗筛口径。
