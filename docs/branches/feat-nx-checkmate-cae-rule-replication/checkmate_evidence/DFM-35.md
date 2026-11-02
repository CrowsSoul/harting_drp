# DFM-35 深圆角转角 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_DeepRadiusCorners.html`
（注册表 `NXCheckers.json#dfms_DeepRadiusCorners`）。

## 2. Check-Mate 判定口径

- 测量每个转角采样点的**铣削深度 L** 与**转角半径 R**；未倒圆角按 R=0 计；
- 判定：`L/R > lr_ratio_max`（**默认 10**）或 R=0 → 失败；
- 参数：`milling_dir` 默认 `(0,0,-1)`。

## 3. 我们的实现

- 规则 `R-DFM-35`：`meas.radius < params.min_corner_radius_mm`（默认 0.5）→ P2；
- 几何：内部回转圆角面、两侧平面互垂；未评估型腔深度（二期粗筛）。

## 4. 差异清单（口径级差异）

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 深径比 `L/R > 10` 或 R=0 | 绝对半径 `R < 0.5` | **不同公式**；我方缺转角深度测量 |
| 深度 | 逐采样点测量 | 未测 | W2 保持粗筛；升级需在 journals 里取型腔深度 |

## 5. 置信度

**medium** —— NX 公式已核实（`L/R ≤ lr_ratio_max`），但与我方粗筛不同；对齐需先补深度测量。
