# DFM-34 内部倒角 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_InternalChamfers.html`
（注册表 `NXCheckers.json#dfms_InternalChamfers`）。

## 2. Check-Mate 判定口径

- 识别型腔底部的内部倒角：底面（垂直铣削方向的平面）相邻面与铣削方向成 45°；
- **型腔底部存在内部倒角 → 失败**（建议改用圆角，球头刀更易加工）；
- 参数只有 `milling_dir`（默认 `(0,0,-1)`）。

## 3. 我们的实现

- 规则 `R-DFM-34` 两个 case（首个命中生效，与旧路径"角度不合格则不再看尺寸"一致）：
  1. 倒角角度到标准角度系列（默认 30/45/60°）的偏差 > `angle_tolerance_deg`(5°) → 报；
  2. 倒角尺寸 > 0 且到标准尺寸系列（默认 0.2/0.3/0.5/1.0/1.5/2.0）的偏差 > `size_tolerance_mm`(0.1) → 报。
- 表达式：`abs(meas.angle_deg - nearest(meas.standard_angles_deg, meas.angle_deg)) > params.angle_tolerance_deg`。

## 4. 差异清单（口径级差异）

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 型腔底部有内倒角即失败 | 内倒角角度/尺寸不在标准系列才报 | **不同取向**；本项目认为标准 C 角可用，非标才增本 |
| 角度/尺寸系列 | 无 | 工具库系列（可配） | 保留 |

## 5. 置信度

**low（对齐度）** —— 文档证清了 NX 的取向，与我方判据不同；一致率不适用本条，需工艺确认。
