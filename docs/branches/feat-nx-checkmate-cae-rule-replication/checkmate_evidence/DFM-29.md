# DFM-29 平底盲孔 — Check-Mate 取证

## 1. 出处

`DESIGN_TOOLS\checkmate\dfmadvisor\localization\dfms_FlatBottomHoles.html`
（注册表 `NXCheckers.json#dfms_FlatBottomHoles`）。

## 2. Check-Mate 判定口径

- 识别盲孔，取孔底端面；
- **孔底为平面 → 失败**（平底需额外立铣清底，增加成本）；
- 无阈值参数（只有 `Disabled` / `SaveInPart` / `LogOption` / `LogMessage` 通用项）。

## 3. 我们的实现

- 规则 `R-DFM-29`：`meas.flat_bottom_count > 0` → P2；measured 取孔深，无阈值（与旧路径一致）。
- 几何：孔组端部位于零件内部的相邻面；平面底判平底，圆锥底（钻尖）不报，曲面底暂不判定。

## 4. 差异清单

| 项 | Check-Mate | 本项目 | 处理 |
|---|---|---|---|
| 口径 | 孔底是平面即失败 | 同 | 一致 |
| 阶梯孔 | 按一条计 | 同轴孔组按一条 | 一致 |
| 曲面/球面底 | 未说明 | 暂不判定（缺法向） | 缺数据跳过，符合"不猜"约定 |

## 5. 置信度

**high（口径）** —— 官方文档明确"flat bottom → failed"，判定完全一致；黑盒样本待 W2 试验件补齐。
