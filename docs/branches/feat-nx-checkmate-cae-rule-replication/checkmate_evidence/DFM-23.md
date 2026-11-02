# DFM-23 槽的最小宽度 — Check-Mate 取证

## 1. 出处

- `DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_MinimumHoleDiameter.html`
  （孔最小直径：`D/T < 1` 失败）；
- `DESIGN_TOOLS\checkmate\dfa\checker\sheet_metal\mqc_dfm_check_cutout_size.dfa`
  （截口尺寸范围检查，默认 min/max 尺寸可配）。

## 2. Check-Mate 判定口径

- 孔：`D/T < 1`；
- 截口：按 `cutout_size` 的 min/max 范围判定（`.dfa` 参数）；
- **没有**单独的"槽宽/t"检查器。

## 3. 我们的实现

规则 `R-DFM-23`：`meas.width < params.min_slot_width_ratio * meas.thickness - 1e-9`；
默认 `min_slot_width_ratio = 1.2`；几何层识别对置内壁 + 共同槽底的直槽。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 判据 | 孔最小直径或截口尺寸范围 | 槽宽 ≥ 1.2t | 近似借用孔的口径；阈值项目化 |
| 对象 | 孔 / 截口 | 直槽（粗筛） | 方向一致 |

## 5. 置信度

**medium** —— 相关口径已核对；槽宽专项规则需工艺确认。
