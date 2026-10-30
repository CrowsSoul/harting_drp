# DFM-31 特征尺寸与刀具标准 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_StandardHoleSizes.html`
（注册表 `NXCheckers.json#dfms_StandardHoleSizes`）。

## 2. Check-Mate 判定口径

- 测量孔的**最小直径**（不含钻尖）；
- 判定：孔径与标准直径列表任一值不匹配 → 失败；
- 参数：`std_diameters`（float list，mm），**默认 0.75 / 1.6 / 2.5 / 3.3 / 4.2**（英制钻头换算系列）；
- 无容差参数。

## 3. 我们的实现

- 规则 `R-DFM-31`：
  `abs(meas.diameter - nearest(params.standard_diameters, meas.diameter)) > params.tolerance_mm` → 报；
  threshold 取 `nearest(...)` 最近标准值。
- 参数：公制常用钻头系列 + `tolerance_mm = 0.05`（甲方刀具库可覆盖）。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 标准系列 | 0.75/1.6/2.5/3.3/4.2（英制换算） | 23 项公制系列 | 保留公制（甲方现场刀具为公制），系列可配 |
| 匹配容差 | 无（精确匹配） | ±0.05 mm | 项目增值，避免浮点/取整误报 |
| 测量对象 | 最小直径 | 圆柱面直径（粗筛） | 后续用孔组最小直径替换 |

## 5. 置信度

**medium** —— 公式（"到标准系列最近元"的隶属判定）来自官方文档；系列与容差是项目差异，需工艺确认。
