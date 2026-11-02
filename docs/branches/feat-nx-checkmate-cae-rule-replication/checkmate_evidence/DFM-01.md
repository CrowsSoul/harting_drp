# DFM-01 干涉检测 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_ComponentInterference.html`
（注册表 `NXCheckers.json#dfms_ComponentInterference`）。

## 2. Check-Mate 判定口径

- 组件干涉检查：存在实体干涉即失败；
- 无体积/间隙阈值参数（只有通用的 Disabled/LogOption 等）。

## 3. 我们的实现

规则 `R-DFM-01`：`meas.volume_mm3 > params.interference_volume_mm3 + 1e-9`；
默认阈值 `0.01 mm³`（过滤数值噪声）；有上游干涉记录时用精确实体求交体积，否则包围盒重叠预筛。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 阈值 | 无（>0 即失败） | 0.01 mm³ 噪声门限 | 项目增值 |
| 几何 | 精确实体求交 | 上游记录优先，否则包围盒粗筛（标注粗筛） | 粗筛需 NX 复核 |

## 5. 置信度

**medium** —— NX 口径已核对；本项目体积阈值与粗筛路径为工程化差异。
